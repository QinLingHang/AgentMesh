package model

import "time"

// =========================================================
// User
// =========================================================

type User struct {
	ID int64 `json:"id"`

	Email string `json:"email"`

	PasswordHash string `json:"-"`

	DisplayName string `json:"displayName"`

	Status string `json:"status"`

	CreatedAt time.Time `json:"createdAt"`

	UpdatedAt time.Time `json:"updatedAt"`
}

// =========================================================
// Conversation
// =========================================================

type Conversation struct {
	ID int64 `json:"id"`

	UserID int64 `json:"userId"`

	Title string `json:"title"`

	LastMessageAt *time.Time `json:"lastMessageAt"`

	CreatedAt time.Time `json:"createdAt"`

	UpdatedAt time.Time `json:"updatedAt"`
}

// =========================================================
// Message
// =========================================================

type Message struct {
	ID int64 `json:"id"`

	ConversationID int64 `json:"conversationId"`

	Role string `json:"role"`

	Content string `json:"content"`

	Status string `json:"status"`

	RequestID *string `json:"requestId"`

	Metadata map[string]any `json:"metadata,omitempty"`

	CreatedAt time.Time `json:"createdAt"`
}

// =========================================================
// Task Attachment
//
// Ephemeral per-conversation input attached to a user message.
// It is intentionally separate from KnowledgeBase ingestion.
// =========================================================

type TaskAttachment struct {
	ID             string    `json:"id"`
	UserID         int64     `json:"-"`
	ConversationID int64     `json:"conversationId"`
	OriginalName   string    `json:"name"`
	MediaType      string    `json:"mediaType"`
	Extension      string    `json:"extension"`
	SizeBytes      int64     `json:"sizeBytes"`
	ChecksumSHA256 string    `json:"checksumSha256"`
	StorageKey     string    `json:"-"`
	Kind           string    `json:"kind"`
	CreatedAt      time.Time `json:"createdAt"`
}

// =========================================================
// Agent Capability Profile
// =========================================================

type AgentCapabilityProfile struct {
	Capability string `json:"capability"`

	QualityScore float64 `json:"qualityScore"`

	AvgLatencyMS int64 `json:"avgLatencyMs"`

	AvgCost float64 `json:"avgCost"`

	SuccessRate float64 `json:"successRate"`

	FailureRate float64 `json:"failureRate"`

	SampleCount int64 `json:"sampleCount"`
}

// =========================================================
// Agent
// =========================================================

type Agent struct {
	ID int64 `json:"id"`

	UserID int64 `json:"userId"`

	Name string `json:"name"`

	Description string `json:"description"`

	Endpoint string `json:"endpoint"`

	Protocol string `json:"protocol"`

	Capabilities []string `json:"capabilities"`

	Provider string `json:"provider"`

	ModelName string `json:"modelName"`

	QualityScore float64 `json:"qualityScore"`

	AvgLatencyMS int64 `json:"avgLatencyMs"`

	AvgCost float64 `json:"avgCost"`

	SuccessRate float64 `json:"successRate"`

	FailureRate float64 `json:"failureRate"`

	CurrentLoad float64 `json:"currentLoad"`

	Status string `json:"status"`

	CreatedAt time.Time `json:"createdAt"`

	UpdatedAt time.Time `json:"updatedAt"`

	CapabilityProfiles []AgentCapabilityProfile `json:"capabilityProfiles"`
}

// =========================================================
// Tool
// =========================================================

type Tool struct {
	ID int64 `json:"id"`

	UserID int64 `json:"userId"`

	Name string `json:"name"`

	Description string `json:"description"`

	Protocol string `json:"protocol"`

	Endpoint string `json:"endpoint,omitempty"`

	InputSchema map[string]any `json:"inputSchema"`

	RiskLevel string `json:"riskLevel"`

	RequiresConfirmation bool `json:"requiresConfirmation"`

	Enabled bool `json:"enabled"`

	CreatedAt time.Time `json:"createdAt"`

	UpdatedAt time.Time `json:"updatedAt"`
}

// =========================================================
// MCP Server
// =========================================================

type MCPServer struct {
	ID int64 `json:"id"`

	UserID int64 `json:"userId"`

	Name string `json:"name"`

	Transport string `json:"transport"`

	Endpoint string `json:"endpoint"`

	Enabled bool `json:"enabled"`

	ConnectTimeoutMS int64 `json:"connectTimeoutMs"`

	CallTimeoutMS int64 `json:"callTimeoutMs"`

	CreatedAt time.Time `json:"createdAt"`

	UpdatedAt time.Time `json:"updatedAt"`
}

// =========================================================
// Agent Feedback
//
// Python Runtime
//       ↓
// Go Control Plane
//       ↓
// MySQL Capability Profile
// =========================================================

type AgentFeedback struct {
	AgentID int64 `json:"agentId"`

	Capability string `json:"capability"`

	Success bool `json:"success"`

	LatencyMS int64 `json:"latencyMs"`

	Cost float64 `json:"cost"`

	QualityScore *float64 `json:"qualityScore"`

	ErrorType string `json:"errorType"`
}

// =========================================================
// Task Constraints
// =========================================================

type TaskConstraints struct {
	MaxLatencyMS int64 `json:"maxLatencyMs"`

	MaxCost float64 `json:"maxCost"`

	MinQuality float64 `json:"minQuality"`

	// RetryOnWorkerLoss is opt-in because replay after a worker accepted an
	// execution is safe only for idempotent/read-only workloads. V3 uses this
	// flag to reassign a task after the worker execution lease expires.
	RetryOnWorkerLoss bool `json:"retryOnWorkerLoss,omitempty"`
}

// =========================================================
// Persisted Runtime Continuation
//
// 这是 Go Control Plane 持久化的 Runtime Resume 凭证。
//
// 它来源于 Python Runtime:
//
// {
//     protocol,
//     agentId,
//     capability,
//     taskId,
//     contextId,
//     state
// }
//
// 浏览器恢复任务时只提交：
//
// POST /api/tasks/:id/resume
//
// {
//     "task": "用户补充的信息"
// }
//
// React 不直接提交下面这些字段。
// Go 从 MySQL continuation_json 中读取 authoritative state。
// =========================================================

type TaskContinuation struct {
	Protocol string `json:"protocol"`

	AgentID int64 `json:"agentId"`

	Capability string `json:"capability"`

	TaskID string `json:"taskId"`

	ContextID string `json:"contextId"`

	State string `json:"state"`

	Kind string `json:"kind,omitempty"`

	ApprovalID string `json:"approvalId,omitempty"`

	ToolName string `json:"toolName,omitempty"`

	ToolProtocol string `json:"toolProtocol,omitempty"`

	RiskLevel string `json:"riskLevel,omitempty"`

	RequiresConfirmation bool `json:"requiresConfirmation,omitempty"`

	Arguments map[string]any `json:"arguments,omitempty"`

	Fingerprint string `json:"fingerprint,omitempty"`

	Summary string `json:"summary,omitempty"`
}

// TaskApproval is the browser-safe projection of a persisted tool approval.
// The authoritative arguments stay server-side inside continuation_json.
type TaskApproval struct {
	ApprovalID           string         `json:"approvalId"`
	ToolName             string         `json:"toolName"`
	ToolProtocol         string         `json:"toolProtocol"`
	RiskLevel            string         `json:"riskLevel"`
	RequiresConfirmation bool           `json:"requiresConfirmation"`
	Summary              string         `json:"summary"`
	ArgumentsPreview     map[string]any `json:"argumentsPreview,omitempty"`
}

// =========================================================
// Task
//
// Long-lived Agent Runtime Task
//
// 生命周期：
//
// RUNNING
//    ↓
// INPUT_REQUIRED / AUTH_REQUIRED
//    ↓
// RUNNING
//    ↓
// COMPLETED
//
// 或：
//
// RUNNING
//    ↓
// ERROR
//
// 同一个逻辑 Agent Task 始终复用同一个 Go Task ID。
// =========================================================

type Task struct {
	// Durable submission identity and fingerprint are repository-internal;
	// the worker must never receive these values through the Task JSON.
	ClientRequestID            string         `json:"-"`
	RequestFingerprint         string         `json:"-"`
	PendingUserMessageMetadata map[string]any `json:"-"`
	ID                         int64          `json:"id"`

	UserID int64 `json:"userId"`

	ConversationID *int64 `json:"conversationId"`

	// -----------------------------------------------------
	// requestId
	//
	// 一个 Go Long-lived Task 的逻辑 Request ID。
	//
	// Resume 时不会重新创建一个 Task，
	// 因此仍然沿用这个 RequestID。
	// -----------------------------------------------------

	RequestID string `json:"requestId"`

	// -----------------------------------------------------
	// Initial Task Text
	//
	// 保存最初提交给 AgentMesh 的原始任务。
	//
	// Resume 时用户后续补充内容通过 Message History 保存，
	// 不覆盖这里的 TaskText。
	// -----------------------------------------------------

	TaskText string `json:"taskText"`

	// -----------------------------------------------------
	// Runtime Policy Snapshot
	//
	// 创建 Task 时冻结。
	//
	// Resume 时 Go 从 Task 中恢复这些策略，
	// 不再依赖浏览器重新提交。
	// -----------------------------------------------------

	Scheduler string `json:"scheduler"`

	Planner string `json:"planner"`

	ExecutionMode string `json:"executionMode"`

	SynthesisMode string `json:"synthesisMode"`

	ModelSelection ModelSelection `json:"modelSelection"`

	RagPolicy RagPolicy `json:"ragPolicy"`

	EffectiveRagPolicy EffectiveRagPolicy `json:"effectiveRagPolicy"`

	// direct keeps the historical synchronous request path. durable is Durable Runtime's
	// queued/leased worker path and is persisted with the task.
	DeliveryMode string `json:"deliveryMode"`

	Constraints TaskConstraints `json:"constraints"`

	// -----------------------------------------------------
	// Lifecycle State
	//
	// RUNNING
	// INPUT_REQUIRED
	// AUTH_REQUIRED
	// COMPLETED
	// ERROR
	// CANCELED
	// -----------------------------------------------------

	Status string `json:"status"`

	// -----------------------------------------------------
	// Runtime Result
	//
	// INPUT_REQUIRED 时：
	// 保存 Agent 提示用户补充的信息。
	//
	// COMPLETED 时：
	// 保存最终答案。
	// -----------------------------------------------------

	ResultText *string `json:"resultText"`

	SelectedAgents []string `json:"selectedAgents,omitempty"`

	Trace []map[string]any `json:"trace,omitempty"`

	DAG map[string]any `json:"dag,omitempty"`

	LatencyMS *int64 `json:"latencyMs"`

	EstimatedCost *float64 `json:"estimatedCost"`

	ErrorMessage *string `json:"errorMessage"`

	Approval *TaskApproval `json:"approval,omitempty"`

	// -----------------------------------------------------
	// Runtime Continuation
	//
	// 只存在于：
	//
	// INPUT_REQUIRED
	// AUTH_REQUIRED
	//
	// COMPLETED / ERROR 后会被清空。
	//
	// json:"-" 非常重要：
	//
	// 普通 Task API 不把：
	//
	// remote taskId
	// contextId
	// agentId
	//
	// 直接返回给浏览器。
	//
	// Resume 时由 Go 服务端从数据库自己读取。
	// -----------------------------------------------------

	Continuation *TaskContinuation `json:"-"`

	CreatedAt time.Time `json:"createdAt"`

	UpdatedAt time.Time `json:"updatedAt"`
}
