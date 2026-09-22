package model

import "time"

// DurableTaskEvent is a metadata-only projection of a persisted task/job state
// or an admitted worker phase. No prompts, arguments, raw tool results, titles,
// model deltas or internal endpoints are stored in this journal.
// Sequence is the database cursor used for replay across gateway restarts.
type DurableTaskEvent struct {
	Sequence    int64     `json:"sequence"`
	TaskID      int64     `json:"taskId"`
	Status      string    `json:"status"`
	JobStatus   string    `json:"jobStatus"`
	FenceEpoch  int64     `json:"fenceEpoch"`
	EventType   string    `json:"eventType"`
	Phase       string    `json:"phase,omitempty"`
	PhaseStatus string    `json:"phaseStatus,omitempty"`
	CreatedAt   time.Time `json:"createdAt"`
}
