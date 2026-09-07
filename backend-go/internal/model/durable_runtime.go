package model

import "time"

// RuntimeWorker is a trusted control-plane view of one Python Runtime worker.
// Endpoint is never serialized to browser APIs.
type RuntimeWorker struct {
	WorkerID            string     `json:"workerId"`
	Endpoint            string     `json:"-"`
	Capacity            int        `json:"capacity"`
	ActiveExecutions    int        `json:"activeExecutions"`
	Draining            bool       `json:"draining"`
	Status              string     `json:"status"`
	ConsecutiveFailures int        `json:"consecutiveFailures"`
	CircuitOpenUntil    *time.Time `json:"circuitOpenUntil,omitempty"`
	LastHeartbeatAt     time.Time  `json:"lastHeartbeatAt"`
	CreatedAt           time.Time  `json:"createdAt"`
	UpdatedAt           time.Time  `json:"updatedAt"`
}

// RuntimeJob is the durable dispatch unit that bridges a Go Task to a Python
// worker execution. RequestJSON and lease credentials remain repository-only.
type RuntimeJob struct {
	ID             int64      `json:"id"`
	TaskID         int64      `json:"taskId"`
	UserID         int64      `json:"userId"`
	RequestID      string     `json:"requestId"`
	ExecutionID    string     `json:"executionId"`
	Status         string     `json:"status"`
	WorkerID       *string    `json:"workerId,omitempty"`
	AttemptCount   int        `json:"attemptCount"`
	MaxAttempts    int        `json:"maxAttempts"`
	DeadlineAt     time.Time  `json:"deadlineAt"`
	LeaseExpiresAt *time.Time `json:"leaseExpiresAt,omitempty"`
	AcceptedAt     *time.Time `json:"acceptedAt,omitempty"`
	LastError      *string    `json:"lastError,omitempty"`
	CreatedAt      time.Time  `json:"createdAt"`
	UpdatedAt      time.Time  `json:"updatedAt"`
}

// RuntimeReliabilitySnapshot is intentionally metadata-only. It gives the UI
// queue/worker health without exposing internal worker endpoints or payloads.
type RuntimeReliabilitySnapshot struct {
	Enabled            bool  `json:"enabled"`
	QueueDepth         int   `json:"queueDepth"`
	Leased             int   `json:"leased"`
	Accepted           int   `json:"accepted"`
	Failed             int   `json:"failed"`
	Canceled           int   `json:"canceled"`
	Workers            int   `json:"workers"`
	AvailableWorkers   int   `json:"availableWorkers"`
	DrainingWorkers    int   `json:"drainingWorkers"`
	CircuitOpenWorkers int   `json:"circuitOpenWorkers"`
	OldestQueuedMS     int64 `json:"oldestQueuedMs"`
}
