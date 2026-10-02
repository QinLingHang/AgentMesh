package model

import "time"

// DurableTaskStreamSnapshot is the authoritative execution attempt visible to
// an owner-scoped durable task event subscription. The execution identity and
// fence are used only to suppress stale live deltas after worker failover.
type DurableTaskStreamSnapshot struct {
	TaskID      int64
	Status      string
	JobStatus   string
	ExecutionID string
	FenceEpoch  int64
}

// DurableLiveDelta is an ephemeral, replayable projection of model output for
// the current durable attempt. It is never written to MySQL and contains only
// answer text plus the minimum fencing metadata needed to reject stale workers.
type DurableLiveDelta struct {
	StreamID    string    `json:"streamId"`
	TaskID      int64     `json:"taskId"`
	ExecutionID string    `json:"executionId"`
	FenceEpoch  int64     `json:"fenceEpoch"`
	Ordinal     int64     `json:"ordinal"`
	Delta       string    `json:"delta"`
	CreatedAt   time.Time `json:"createdAt"`
}
