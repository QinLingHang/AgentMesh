package eventbus

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/segmentio/kafka-go"
)

func TestBuildPrivacySafeDLQMessageDoesNotRetainSourcePayloadOrKey(t *testing.T) {
	secret := "P21-QA-SYNTHETIC-SECRET-DO-NOT-RETAIN"
	message := kafka.Message{
		Topic:     "agentmesh.runtime.events",
		Partition: 7,
		Offset:    19,
		Key:       []byte("key-" + secret),
		Value:     []byte(`{"eventId":"broken","payload":"` + secret + `"`),
	}

	dlq, err := buildPrivacySafeDLQMessage(message, permanentError{errInvalidFixture{}})
	if err != nil {
		t.Fatalf("build DLQ: %v", err)
	}
	if strings.Contains(string(dlq.Key), secret) || strings.Contains(string(dlq.Value), secret) {
		t.Fatalf("privacy-safe DLQ retained source secret: key=%q value=%s", string(dlq.Key), string(dlq.Value))
	}
	if string(dlq.Key) == string(message.Key) {
		t.Fatalf("DLQ forwarded the original Kafka key")
	}
	if strings.Contains(string(dlq.Value), "payloadBase64") {
		t.Fatalf("DLQ must not contain reversible payloadBase64")
	}

	var payload map[string]any
	if err := json.Unmarshal(dlq.Value, &payload); err != nil {
		t.Fatalf("decode DLQ wrapper: %v", err)
	}
	if payload["payloadSha256"] == "" || payload["keySha256"] == "" {
		t.Fatalf("DLQ fingerprint metadata missing: %#v", payload)
	}
	if got := int(payload["payloadBytes"].(float64)); got != len(message.Value) {
		t.Fatalf("payloadBytes=%d want=%d", got, len(message.Value))
	}
}

type errInvalidFixture struct{}

func (errInvalidFixture) Error() string { return "fixture invalid" }
