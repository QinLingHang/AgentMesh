package cache

import (
	"context"
	"errors"
	"fmt"
	"strconv"
	"strings"
	"time"

	"example.com/agentmesh-control-plane/internal/model"

	"github.com/redis/go-redis/v9"
)

const (
	defaultDurableStreamMaxLen = int64(2048)
	defaultDurableStreamTTL    = 30 * time.Minute
)

// DurableStreamStore keeps short-lived model deltas for durable executions.
// Authoritative task/job state and the final assistant message remain in MySQL;
// this Redis stream exists only to preserve live UX and bounded reconnect replay.
type DurableStreamStore struct {
	client *redis.Client
	maxLen int64
	ttl    time.Duration
}

func NewDurableStreamStore(client *redis.Client, maxLen int64, ttl time.Duration) *DurableStreamStore {
	if maxLen <= 0 {
		maxLen = defaultDurableStreamMaxLen
	}
	if ttl <= 0 {
		ttl = defaultDurableStreamTTL
	}
	return &DurableStreamStore{client: client, maxLen: maxLen, ttl: ttl}
}

func durableStreamKey(taskID int64) string {
	return fmt.Sprintf("agentmesh:durable:task:%d:live", taskID)
}

func durableDeltaID(fenceEpoch, ordinal int64) string {
	return fmt.Sprintf("%d-%d", fenceEpoch, ordinal)
}

func (s *DurableStreamStore) AppendDelta(ctx context.Context, event model.DurableLiveDelta) (string, bool, error) {
	if s == nil || s.client == nil {
		return "", false, errors.New("durable live stream unavailable")
	}
	if event.TaskID <= 0 || event.FenceEpoch <= 0 || event.Ordinal <= 0 || strings.TrimSpace(event.ExecutionID) == "" || event.Delta == "" {
		return "", false, errors.New("invalid durable live delta")
	}

	key := durableStreamKey(event.TaskID)
	id := durableDeltaID(event.FenceEpoch, event.Ordinal)
	if existing, ok, err := s.exact(ctx, key, id); err != nil {
		return "", false, err
	} else if ok {
		if sameDurableDelta(existing, event) {
			return id, false, nil
		}
		return "", false, errors.New("durable live delta ordinal conflict")
	}

	createdAt := event.CreatedAt.UTC()
	if createdAt.IsZero() {
		createdAt = time.Now().UTC()
	}
	_, err := s.client.TxPipelined(ctx, func(pipe redis.Pipeliner) error {
		pipe.XAdd(ctx, &redis.XAddArgs{
			Stream: key,
			ID:     id,
			MaxLen: s.maxLen,
			Approx: true,
			Values: map[string]any{
				"taskId":      event.TaskID,
				"executionId": event.ExecutionID,
				"fenceEpoch":  event.FenceEpoch,
				"ordinal":     event.Ordinal,
				"delta":       event.Delta,
				"createdAt":   createdAt.Format(time.RFC3339Nano),
			},
		})
		pipe.Expire(ctx, key, s.ttl)
		return nil
	})
	if err != nil {
		// XADD and EXPIRE are committed together. If the network loses the EXEC
		// response, re-read the deterministic ID: an exact match means the entire
		// transaction (including the TTL) already committed.
		if existing, ok, readErr := s.exact(ctx, key, id); readErr == nil && ok {
			if sameDurableDelta(existing, event) {
				return id, false, nil
			}
			return "", false, errors.New("durable live delta ordinal conflict")
		}
		return "", false, err
	}
	return id, true, nil
}

func (s *DurableStreamStore) ReadDeltas(ctx context.Context, taskID int64, after string, limit int64) ([]model.DurableLiveDelta, error) {
	if s == nil || s.client == nil || taskID <= 0 {
		return nil, nil
	}
	if limit <= 0 || limit > 512 {
		limit = 256
	}
	start := "-"
	if strings.TrimSpace(after) != "" && after != "0-0" {
		start = "(" + strings.TrimSpace(after)
	}
	rows, err := s.client.XRangeN(ctx, durableStreamKey(taskID), start, "+", limit).Result()
	if err == redis.Nil {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	result := make([]model.DurableLiveDelta, 0, len(rows))
	for _, row := range rows {
		event, ok := decodeDurableDelta(row)
		if ok {
			result = append(result, event)
		}
	}
	return result, nil
}

func (s *DurableStreamStore) exact(ctx context.Context, key, id string) (model.DurableLiveDelta, bool, error) {
	rows, err := s.client.XRangeN(ctx, key, id, id, 1).Result()
	if err == redis.Nil || (err == nil && len(rows) == 0) {
		return model.DurableLiveDelta{}, false, nil
	}
	if err != nil {
		return model.DurableLiveDelta{}, false, err
	}
	event, ok := decodeDurableDelta(rows[0])
	if !ok {
		return model.DurableLiveDelta{}, false, errors.New("invalid durable live delta in redis")
	}
	return event, true, nil
}

func decodeDurableDelta(row redis.XMessage) (model.DurableLiveDelta, bool) {
	taskID, okTask := parseRedisInt64(row.Values["taskId"])
	fence, okFence := parseRedisInt64(row.Values["fenceEpoch"])
	ordinal, okOrdinal := parseRedisInt64(row.Values["ordinal"])
	executionID := redisString(row.Values["executionId"])
	delta := redisString(row.Values["delta"])
	createdAt, err := time.Parse(time.RFC3339Nano, redisString(row.Values["createdAt"]))
	if !okTask || !okFence || !okOrdinal || taskID <= 0 || fence <= 0 || ordinal <= 0 || executionID == "" || delta == "" || err != nil {
		return model.DurableLiveDelta{}, false
	}
	return model.DurableLiveDelta{
		StreamID: row.ID, TaskID: taskID, ExecutionID: executionID,
		FenceEpoch: fence, Ordinal: ordinal, Delta: delta, CreatedAt: createdAt.UTC(),
	}, true
}

func sameDurableDelta(existing, incoming model.DurableLiveDelta) bool {
	return existing.TaskID == incoming.TaskID &&
		existing.ExecutionID == incoming.ExecutionID &&
		existing.FenceEpoch == incoming.FenceEpoch &&
		existing.Ordinal == incoming.Ordinal &&
		existing.Delta == incoming.Delta
}

func redisString(value any) string {
	switch typed := value.(type) {
	case string:
		return typed
	case []byte:
		return string(typed)
	case fmt.Stringer:
		return typed.String()
	case nil:
		return ""
	default:
		return fmt.Sprint(typed)
	}
}

func parseRedisInt64(value any) (int64, bool) {
	parsed, err := strconv.ParseInt(strings.TrimSpace(redisString(value)), 10, 64)
	return parsed, err == nil
}
