package eventbus

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"example.com/agentmesh-control-plane/internal/service"

	"github.com/segmentio/kafka-go"
)

const runtimeResultEventType = "runtime.execution.result"

type RuntimeEventEnvelope struct {
	EventID        string          `json:"eventId"`
	EventType      string          `json:"eventType"`
	EventVersion   int             `json:"eventVersion"`
	OccurredAt     time.Time       `json:"occurredAt"`
	Source         string          `json:"source"`
	PartitionKey   string          `json:"partitionKey"`
	UserID         *int64          `json:"userId,omitempty"`
	ConversationID *int64          `json:"conversationId,omitempty"`
	ExecutionID    string          `json:"executionId"`
	Payload        json.RawMessage `json:"payload"`
}

type RuntimeResultPayload struct {
	JobID    int64                            `json:"jobId"`
	Callback service.DurableExecutionCallback `json:"callback"`
}

type RuntimeEventConsumerConfig struct {
	Enabled            bool
	Brokers            []string
	Topic              string
	DLQTopic           string
	GroupID            string
	ClientID           string
	ProcessMaxAttempts int
	DedupeRetention    time.Duration
}

type RuntimeEventConsumer struct {
	db      *sql.DB
	service *service.DurableRuntimeService
	cfg     RuntimeEventConsumerConfig
	reader  *kafka.Reader
	dlq     *kafka.Writer

	cancel context.CancelFunc
	wg     sync.WaitGroup

	fetched            atomic.Int64
	processed          atomic.Int64
	duplicates         atomic.Int64
	retries            atomic.Int64
	dlqCount           atomic.Int64
	processingFailures atomic.Int64
	dlqPublishFailures atomic.Int64
	staleFenceRejects  atomic.Int64
	callbackNoops      atomic.Int64
	callbackRecoveries atomic.Int64
}

func NewRuntimeEventConsumer(db *sql.DB, runtimeService *service.DurableRuntimeService, cfg RuntimeEventConsumerConfig) *RuntimeEventConsumer {
	if cfg.ProcessMaxAttempts < 1 {
		cfg.ProcessMaxAttempts = 10
	}
	if cfg.DedupeRetention <= 0 {
		cfg.DedupeRetention = 30 * 24 * time.Hour
	}
	return &RuntimeEventConsumer{db: db, service: runtimeService, cfg: cfg}
}

func (c *RuntimeEventConsumer) Start(parent context.Context) {
	if c == nil || !c.cfg.Enabled || c.cancel != nil {
		return
	}
	if len(c.cfg.Brokers) == 0 || strings.TrimSpace(c.cfg.Topic) == "" || strings.TrimSpace(c.cfg.GroupID) == "" {
		log.Printf("kafka consumer disabled: incomplete configuration")
		return
	}

	dialer := &kafka.Dialer{Timeout: 10 * time.Second, ClientID: c.cfg.ClientID}
	c.reader = kafka.NewReader(kafka.ReaderConfig{
		Brokers:        c.cfg.Brokers,
		Dialer:         dialer,
		GroupID:        c.cfg.GroupID,
		Topic:          c.cfg.Topic,
		MinBytes:       1,
		MaxBytes:       10e6,
		MaxWait:        500 * time.Millisecond,
		CommitInterval: 0, // explicit commit only after business success / DLQ
		StartOffset:    kafka.FirstOffset,
	})
	c.dlq = &kafka.Writer{
		Addr:         kafka.TCP(c.cfg.Brokers...),
		Transport:    &kafka.Transport{ClientID: c.cfg.ClientID},
		Topic:        c.cfg.DLQTopic,
		Balancer:     &kafka.Hash{},
		RequiredAcks: kafka.RequireAll,
		Async:        false,
	}

	ctx, cancel := context.WithCancel(parent)
	c.cancel = cancel
	c.wg.Add(1)
	go func() {
		defer c.wg.Done()
		c.loop(ctx)
	}()
}

func (c *RuntimeEventConsumer) Stop() {
	if c == nil || c.cancel == nil {
		return
	}
	c.cancel()
	c.wg.Wait()
	if c.reader != nil {
		_ = c.reader.Close()
	}
	if c.dlq != nil {
		_ = c.dlq.Close()
	}
	c.cancel = nil
}

func (c *RuntimeEventConsumer) loop(ctx context.Context) {
	nextCleanup := time.Now().UTC()
	for {
		message, err := c.reader.FetchMessage(ctx)
		if err != nil {
			if ctx.Err() != nil {
				return
			}
			log.Printf("kafka fetch failed")
			if !sleepContext(ctx, 500*time.Millisecond) {
				return
			}
			continue
		}

		c.fetched.Add(1)
		if time.Now().UTC().After(nextCleanup) {
			if _, cleanupErr := c.db.ExecContext(ctx,
				`DELETE FROM processed_runtime_events WHERE processed_at < ?`,
				time.Now().UTC().Add(-c.cfg.DedupeRetention),
			); cleanupErr != nil {
				log.Printf("event dedupe cleanup failed")
			}
			nextCleanup = time.Now().UTC().Add(10 * time.Minute)
		}

		// Event Delivery FIX: fully resolve this exact fetched record before asking the reader
		// for a later offset. FetchMessage advances the reader's in-memory cursor;
		// fetching a later record after a transient failure could otherwise allow a
		// higher CommitMessages call to commit past the failed offset.
		if !c.processFetchedMessage(ctx, message) {
			return
		}
		if commitErr := c.reader.CommitMessages(ctx, message); commitErr != nil && ctx.Err() == nil {
			// Business effect (or privacy-safe DLQ handoff) is already durable. A
			// later higher commit may subsume this offset; replay remains safe because
			// event_id dedupe and callback recovery are idempotent.
			log.Printf("kafka commit failed topic=%s partition=%d offset=%d", message.Topic, message.Partition, message.Offset)
		}
	}
}

func (c *RuntimeEventConsumer) processFetchedMessage(ctx context.Context, message kafka.Message) bool {
	position := fmt.Sprintf("%s:%d:%d", message.Topic, message.Partition, message.Offset)
	for attempt := 1; ; attempt++ {
		err := c.handleMessage(ctx, message)
		if err == nil {
			c.processed.Add(1)
			return true
		}
		c.processingFailures.Add(1)

		var permanent permanentError
		isPermanent := errors.As(err, &permanent)
		if !isPermanent && attempt < c.cfg.ProcessMaxAttempts {
			c.retries.Add(1)
			log.Printf("runtime event retry position=%s attempt=%d", position, attempt)
			if !sleepContext(ctx, time.Duration(minInt(attempt, 5))*250*time.Millisecond) {
				return false
			}
			continue
		}

		// Once a message is classified as permanent, or transient handling has
		// exhausted its bounded attempts, keep ownership of this exact message
		// until the DLQ write succeeds. Never fetch/commit a later offset first.
		for {
			if ctx.Err() != nil {
				return false
			}
			if dlqErr := c.writeDLQ(ctx, message, err); dlqErr == nil {
				c.dlqCount.Add(1)
				return true
			}
			c.dlqPublishFailures.Add(1)
			log.Printf("runtime event DLQ publish failed position=%s", position)
			if !sleepContext(ctx, time.Second) {
				return false
			}
		}
	}
}

func (c *RuntimeEventConsumer) handleMessage(ctx context.Context, message kafka.Message) error {
	var event RuntimeEventEnvelope
	if err := json.Unmarshal(message.Value, &event); err != nil {
		return permanentError{fmt.Errorf("invalid event JSON: %w", err)}
	}
	if strings.TrimSpace(event.EventID) == "" || strings.TrimSpace(event.EventType) == "" || event.EventVersion < 1 {
		return permanentError{errors.New("invalid event envelope")}
	}

	processed, err := c.isProcessed(ctx, event.EventID)
	if err != nil {
		return err
	}
	if processed {
		c.duplicates.Add(1)
		return nil
	}

	if event.EventType != runtimeResultEventType || event.EventVersion != 1 {
		return permanentError{fmt.Errorf("unsupported event %s v%d", event.EventType, event.EventVersion)}
	}

	var payload RuntimeResultPayload
	if err := json.Unmarshal(event.Payload, &payload); err != nil {
		return permanentError{fmt.Errorf("invalid runtime result payload: %w", err)}
	}
	if payload.JobID <= 0 || strings.TrimSpace(payload.Callback.ExecutionID) == "" {
		return permanentError{errors.New("runtime result missing job/execution identity")}
	}
	if event.ExecutionID != "" && event.ExecutionID != payload.Callback.ExecutionID {
		return permanentError{errors.New("event/callback execution identity mismatch")}
	}

	outcome, err := c.service.CallbackWithOutcome(ctx, payload.JobID, payload.Callback)
	if err != nil {
		return err
	}
	switch outcome {
	case service.DurableCallbackStaleFence:
		c.staleFenceRejects.Add(1)
	case service.DurableCallbackDuplicate, service.DurableCallbackTerminal:
		c.callbackNoops.Add(1)
	case service.DurableCallbackRecovered:
		c.callbackRecoveries.Add(1)
	}
	return c.markProcessed(ctx, event, message)
}

func (c *RuntimeEventConsumer) isProcessed(ctx context.Context, eventID string) (bool, error) {
	var value string
	err := c.db.QueryRowContext(ctx, `SELECT event_id FROM processed_runtime_events WHERE event_id = ? LIMIT 1`, eventID).Scan(&value)
	if errors.Is(err, sql.ErrNoRows) {
		return false, nil
	}
	return err == nil, err
}

func (c *RuntimeEventConsumer) markProcessed(ctx context.Context, event RuntimeEventEnvelope, message kafka.Message) error {
	_, err := c.db.ExecContext(ctx, `
		INSERT IGNORE INTO processed_runtime_events(
			event_id, event_type, event_version, execution_id,
			topic_name, partition_id, offset_value
		) VALUES(?, ?, ?, ?, ?, ?, ?)
	`, event.EventID, event.EventType, event.EventVersion, nullableString(event.ExecutionID),
		message.Topic, message.Partition, message.Offset)
	return err
}

func (c *RuntimeEventConsumer) writeDLQ(ctx context.Context, message kafka.Message, cause error) error {
	if c.dlq == nil || strings.TrimSpace(c.cfg.DLQTopic) == "" {
		return errors.New("DLQ is not configured")
	}
	dlqMessage, err := buildPrivacySafeDLQMessage(message, cause)
	if err != nil {
		return err
	}
	return c.dlq.WriteMessages(ctx, dlqMessage)
}

// buildPrivacySafeDLQMessage deliberately never copies the source key or source
// value. Base64 is reversible and therefore is not redaction. Operators get a
// SHA-256 fingerprint, byte count and Kafka coordinates for correlation while
// prompts, credentials, provider payloads and arbitrary malformed bytes remain
// unrecoverable from the DLQ record itself.
func buildPrivacySafeDLQMessage(message kafka.Message, cause error) (kafka.Message, error) {
	category := "processing_failed"
	var permanent permanentError
	if errors.As(cause, &permanent) {
		category = "invalid_event"
	}
	payloadHash := sha256Hex(message.Value)
	keyHash := sha256Hex(message.Key)
	wrapper := map[string]any{
		"failedAt":        time.Now().UTC(),
		"failureType":     category,
		"sourceTopic":     message.Topic,
		"sourcePartition": message.Partition,
		"sourceOffset":    message.Offset,
		"payloadSha256":   payloadHash,
		"payloadBytes":    len(message.Value),
		"keySha256":       keyHash,
	}
	encoded, err := json.Marshal(wrapper)
	if err != nil {
		return kafka.Message{}, err
	}
	// A deterministic non-sensitive key keeps repeated poison records co-located
	// without forwarding the possibly attacker-controlled original Kafka key.
	return kafka.Message{Key: []byte(payloadHash), Value: encoded}, nil
}

func sha256Hex(value []byte) string {
	sum := sha256.Sum256(value)
	return hex.EncodeToString(sum[:])
}

func (c *RuntimeEventConsumer) Snapshot() map[string]any {
	if c == nil {
		return map[string]any{"enabled": false}
	}
	processingFailures := c.processingFailures.Load()
	dlqPublishFailures := c.dlqPublishFailures.Load()
	return map[string]any{
		"enabled":            c.cfg.Enabled,
		"topic":              c.cfg.Topic,
		"groupId":            c.cfg.GroupID,
		"fetched":            c.fetched.Load(),
		"processed":          c.processed.Load(),
		"duplicates":         c.duplicates.Load(),
		"retries":            c.retries.Load(),
		"dlq":                c.dlqCount.Load(),
		"processingFailures": processingFailures,
		"dlqPublishFailures": dlqPublishFailures,
		"failures":           processingFailures + dlqPublishFailures,
		"staleFenceRejects":  c.staleFenceRejects.Load(),
		"callbackNoops":      c.callbackNoops.Load(),
		"callbackRecoveries": c.callbackRecoveries.Load(),
	}
}

type permanentError struct{ error }

func nullableString(value string) any {
	if strings.TrimSpace(value) == "" {
		return nil
	}
	return value
}

func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func sleepContext(ctx context.Context, duration time.Duration) bool {
	timer := time.NewTimer(duration)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return false
	case <-timer.C:
		return true
	}
}
