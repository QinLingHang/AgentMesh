package model

import "time"

// RuntimeExecutionLeaseRef is emitted by a live Runtime worker in its heartbeat.
// The control plane renews only an exact worker/execution/lease/fence tuple,
// preventing a recovered stale process from extending a newer assignment.
type RuntimeExecutionLeaseRef struct {
	JobID         int64  `json:"jobId"`
	ExecutionID   string `json:"executionId"`
	LeaseToken    string `json:"-"`
	FenceEpoch    int64  `json:"fenceEpoch"`
	ResultPending bool   `json:"resultPending,omitempty"`
}

// RuntimeWorker is a trusted control-plane view of one Python Runtime worker.
// Endpoint and lease credentials are never serialized to browser APIs.
type RuntimeWorker struct {
	WorkerID            string     `json:"workerId"`
	NodeID              string     `json:"nodeId"`
	Zone                string     `json:"zone,omitempty"`
	Version             string     `json:"version,omitempty"`
	Endpoint            string     `json:"-"`
	Capacity            int        `json:"capacity"`
	ActiveExecutions    int        `json:"activeExecutions"`
	AuthoritativeActive int        `json:"authoritativeActive"`
	NodeCapacity        int        `json:"nodeCapacity"`
	NodeActive          int        `json:"nodeActiveExecutions"`
	SchedulingScore     float64    `json:"schedulingScore"`
	Draining            bool       `json:"draining"`
	Status              string     `json:"status"`
	ConsecutiveFailures int        `json:"consecutiveFailures"`
	CircuitOpenUntil    *time.Time `json:"circuitOpenUntil,omitempty"`
	StartedAt           *time.Time `json:"startedAt,omitempty"`
	LastAssignmentAt    *time.Time `json:"lastAssignmentAt,omitempty"`
	LastHeartbeatAt     time.Time  `json:"lastHeartbeatAt"`
	CreatedAt           time.Time  `json:"createdAt"`
	UpdatedAt           time.Time  `json:"updatedAt"`
}

// RuntimeNode is a sanitized node-level aggregation. It deliberately contains
// no internal network endpoint or secret material.
type RuntimeNode struct {
	NodeID           string    `json:"nodeId"`
	Zone             string    `json:"zone,omitempty"`
	Version          string    `json:"version,omitempty"`
	Capacity         int       `json:"capacity"`
	ActiveExecutions int       `json:"activeExecutions"`
	WorkerCount      int       `json:"workerCount"`
	Draining         bool      `json:"draining"`
	Status           string    `json:"status"`
	LastHeartbeatAt  time.Time `json:"lastHeartbeatAt"`
}

// RuntimeDispatcherLease is the database-backed HA ownership record used by
// control-plane replicas. Epoch is monotonic and becomes part of dispatch
// observability so a standby can take over after the previous lease expires.
type RuntimeDispatcherLease struct {
	LeaseName       string    `json:"leaseName"`
	HolderID        string    `json:"holderId"`
	Epoch           int64     `json:"epoch"`
	LeaseUntil      time.Time `json:"leaseUntil"`
	LastHeartbeatAt time.Time `json:"lastHeartbeatAt"`
}

// RuntimeJob is the durable dispatch unit that bridges a Go Task to a Python
// worker execution. RequestJSON and lease credentials remain repository-only.
type RuntimeJob struct {
	ID                int64      `json:"id"`
	TaskID            int64      `json:"taskId"`
	UserID            int64      `json:"userId"`
	RequestID         string     `json:"requestId"`
	ExecutionID       string     `json:"executionId"`
	Status            string     `json:"status"`
	WorkerID          *string    `json:"workerId,omitempty"`
	NodeID            *string    `json:"nodeId,omitempty"`
	FenceEpoch        int64      `json:"fenceEpoch"`
	AttemptCount      int        `json:"attemptCount"`
	MaxAttempts       int        `json:"maxAttempts"`
	FailoverRetrySafe bool       `json:"failoverRetrySafe"`
	DeadlineAt        time.Time  `json:"deadlineAt"`
	LeaseExpiresAt    *time.Time `json:"leaseExpiresAt,omitempty"`
	AcceptedAt        *time.Time `json:"acceptedAt,omitempty"`
	LastError         *string    `json:"lastError,omitempty"`
	CreatedAt         time.Time  `json:"createdAt"`
	UpdatedAt         time.Time  `json:"updatedAt"`
}

// RuntimeReliabilitySnapshot is intentionally metadata-only. It gives the UI
// queue/node/worker health without exposing internal worker endpoints or payloads.
type RuntimeReliabilitySnapshot struct {
	Enabled               bool    `json:"enabled"`
	QueueDepth            int     `json:"queueDepth"`
	Leased                int     `json:"leased"`
	Accepted              int     `json:"accepted"`
	Failed                int     `json:"failed"`
	Canceled              int     `json:"canceled"`
	Workers               int     `json:"workers"`
	AvailableWorkers      int     `json:"availableWorkers"`
	DrainingWorkers       int     `json:"drainingWorkers"`
	CircuitOpenWorkers    int     `json:"circuitOpenWorkers"`
	Nodes                 int     `json:"nodes"`
	AvailableNodes        int     `json:"availableNodes"`
	StaleNodes            int     `json:"staleNodes"`
	TotalCapacity         int     `json:"totalCapacity"`
	ActiveExecutions      int     `json:"activeExecutions"`
	UtilizationPercent    float64 `json:"utilizationPercent"`
	DispatcherLeader      bool    `json:"dispatcherLeader"`
	DispatcherEpoch       int64   `json:"dispatcherEpoch"`
	DispatcherLeaseRemain int64   `json:"dispatcherLeaseRemainingMs"`
	OldestQueuedMS        int64   `json:"oldestQueuedMs"`
}

// RuntimeTopologySnapshot powers the V3 operations dashboard. Worker endpoints,
// internal tokens and lease tokens are deliberately absent.
type RuntimeTopologySnapshot struct {
	Reliability RuntimeReliabilitySnapshot `json:"reliability"`
	Nodes       []RuntimeNode              `json:"nodes"`
	Workers     []RuntimeWorker            `json:"workers"`
}
