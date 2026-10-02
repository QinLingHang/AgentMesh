package cache

import (
	"testing"
	"time"

	"example.com/agentmesh-control-plane/internal/model"

	"github.com/redis/go-redis/v9"
)

func TestDurableDeltaIDUsesFenceThenOrdinal(t *testing.T) {
	if got := durableDeltaID(7, 19); got != "7-19" {
		t.Fatalf("unexpected stream id: %s", got)
	}
	if got := durableDeltaID(8, 1); got != "8-1" {
		t.Fatalf("unexpected next-fence stream id: %s", got)
	}
}

func TestDecodeDurableDeltaRoundTripFields(t *testing.T) {
	created := time.Date(2026, 10, 1, 12, 0, 0, 123, time.UTC)
	row := redis.XMessage{ID: "4-2", Values: map[string]any{
		"taskId": int64(99), "executionId": "exec-1", "fenceEpoch": int64(4),
		"ordinal": int64(2), "delta": "你好", "createdAt": created.Format(time.RFC3339Nano),
	}}
	got, ok := decodeDurableDelta(row)
	if !ok {
		t.Fatal("valid redis row rejected")
	}
	want := model.DurableLiveDelta{
		StreamID: "4-2", TaskID: 99, ExecutionID: "exec-1", FenceEpoch: 4,
		Ordinal: 2, Delta: "你好", CreatedAt: created,
	}
	if got.StreamID != want.StreamID || got.TaskID != want.TaskID || got.ExecutionID != want.ExecutionID ||
		got.FenceEpoch != want.FenceEpoch || got.Ordinal != want.Ordinal || got.Delta != want.Delta || !got.CreatedAt.Equal(want.CreatedAt) {
		t.Fatalf("decode mismatch: got=%+v want=%+v", got, want)
	}
}

func TestDecodeDurableDeltaRejectsMissingExecutionIdentity(t *testing.T) {
	row := redis.XMessage{ID: "1-1", Values: map[string]any{
		"taskId": 1, "fenceEpoch": 1, "ordinal": 1, "delta": "x",
		"createdAt": time.Now().UTC().Format(time.RFC3339Nano),
	}}
	if _, ok := decodeDurableDelta(row); ok {
		t.Fatal("missing execution id must be rejected")
	}
}
