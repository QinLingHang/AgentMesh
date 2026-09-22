package repository

import (
	"context"
	"errors"
	"time"

	"example.com/agentmesh-control-plane/internal/model"
)

// =========================================================
// Repository Errors
// =========================================================

var ErrEmailExists = errors.New(
	"email exists",
)

var ErrInvalidRefreshToken = errors.New(
	"invalid refresh token",
)

// ErrSubmissionConflict means a client reused its idempotency key for a
// different request payload. Never enqueue another task in this case.
var ErrSubmissionConflict = errors.New("client request id conflicts with a different payload")

var ErrNotOwned = errors.New(
	"not owned",
)

var ErrProjectAlreadyBound = errors.New(
	"project already bound to another organization",
)

// =========================================================
// Task State Conflict
//
// 例如：
//
// INPUT_REQUIRED
//      ↓
// Resume A 成功
//      ↓
// RUNNING
//
// 此时 Resume B 再执行，
// affectedRows = 0。
//
// Repository 返回 ErrInvalidTaskState，
// Service 再映射成 ErrConflict。
// =========================================================

var ErrInvalidTaskState = errors.New(
	"invalid task state",
)

// =========================================================
// User Repository
// =========================================================

type UserRepository interface {
	CreateUser(
		context.Context,
		string,
		string,
		string,
	) (*model.User, error)

	UserByEmail(
		context.Context,
		string,
	) (*model.User, error)

	UserByID(
		context.Context,
		int64,
	) (*model.User, error)
}

// =========================================================
// Refresh Token Repository
// =========================================================

type RefreshRepository interface {
	CreateRefresh(
		context.Context,
		int64,
		string,
		time.Time,
	) error

	RotateRefresh(
		context.Context,
		string,
		string,
		time.Time,
	) (int64, error)

	RevokeRefresh(
		context.Context,
		string,
	) error
}

// =========================================================
// Conversation Repository
// =========================================================

type ConversationRepository interface {
	CreateConversation(
		context.Context,
		int64,
		string,
	) (*model.Conversation, error)

	ListConversations(
		context.Context,
		int64,
		int,
	) ([]model.Conversation, error)

	ConversationByID(
		context.Context,
		int64,
		int64,
	) (*model.Conversation, error)

	DeleteConversation(
		context.Context,
		int64,
		int64,
	) (bool, error)
}

// =========================================================
// Message Repository
// =========================================================

type MessageRepository interface {
	CreateMessage(
		context.Context,
		int64,
		int64,
		string,
		string,
		string,
		string,
		map[string]any,
	) (*model.Message, error)

	ListMessages(
		context.Context,
		int64,
		int64,
		int,
	) ([]model.Message, error)

	// ListMessagesBefore returns one cursor page from the durable MySQL
	// conversation log. beforeID=0 means the newest page. hasMore reports
	// whether older rows still exist. This is a UI/history contract only; model
	// context budgeting is handled separately by the Runtime.
	ListMessagesBefore(
		context.Context,
		int64,
		int64,
		int64,
		int,
	) ([]model.Message, bool, error)
}

// ConversationMemoryRepository is an optional stronger MySQL contract used by
// Runtime conversation-memory compaction. Keeping it separate from
// MessageRepository avoids widening every test double while preserving one Go
// ownership boundary around durable conversation state.
type ConversationMemoryRepository interface {
	ListConversationMemoryCapsules(
		context.Context,
		int64,
		int64,
		int,
	) ([]model.ConversationMemoryCapsule, error)

	UpsertConversationMemoryCapsule(
		context.Context,
		int64,
		int64,
		model.ConversationMemoryCapsuleWrite,
	) (*model.ConversationMemoryCapsule, error)

	ConversationCompactionWindow(
		context.Context,
		int64,
		int64,
		int64,
		int,
		int,
		int,
	) ([]model.Message, error)
}

// TaskCompletionWrite and TaskSuspensionWrite describe authoritative task-state
// transitions that may be finalized atomically with an assistant message.
// They intentionally live in the repository package so MySQL can commit both
// records in one transaction without coupling the repository to service types.
type TaskCompletionWrite struct {
	UserID         int64
	TaskID         int64
	ConversationID int64
	Result         string
	Selected       []string
	Trace          []map[string]any
	DAG            map[string]any
	LatencyMS      int64
	EstimatedCost  float64
}

type TaskSuspensionWrite struct {
	UserID         int64
	TaskID         int64
	ConversationID int64
	Status         string
	Result         string
	Continuation   *model.TaskContinuation
	Selected       []string
	Trace          []map[string]any
	DAG            map[string]any
	LatencyMS      int64
	EstimatedCost  float64
}

type AssistantMessageWrite struct {
	UserID         int64
	ConversationID int64
	Content        string
	Status         string
	RequestID      string
	Metadata       map[string]any
}

// TaskMessageFinalizer is an optional stronger repository contract used by
// production MySQL. Implementations commit the task transition and assistant
// history together so callers cannot observe COMPLETED/SUSPENDED without the
// corresponding authoritative assistant message.
type TaskMessageFinalizer interface {
	CompleteTaskWithAssistantMessage(
		context.Context,
		TaskCompletionWrite,
		AssistantMessageWrite,
	) (*model.Message, error)

	SuspendTaskWithAssistantMessage(
		context.Context,
		TaskSuspensionWrite,
		AssistantMessageWrite,
	) (*model.Message, error)
}

// =========================================================
// Conversation Attachment Repository
// =========================================================

type AttachmentRepository interface {
	CreateConversationAttachment(context.Context, model.ConversationAttachment) (*model.ConversationAttachment, error)
	ConversationAttachmentByID(context.Context, int64, int64, int64) (*model.ConversationAttachment, error)
	ListConversationAttachments(context.Context, int64, int64) ([]model.ConversationAttachment, error)
	DeleteConversationAttachment(context.Context, int64, int64, int64) (bool, error)
}

// =========================================================
// Agent Repository
// =========================================================

type AgentRepository interface {
	CreateAgent(
		context.Context,
		int64,
		model.Agent,
	) (*model.Agent, error)

	ListAgents(
		context.Context,
		int64,
	) ([]model.Agent, error)

	DeleteAgent(
		context.Context,
		int64,
		int64,
	) (bool, error)

	RecordAgentFeedback(
		context.Context,
		int64,
		string,
		[]model.AgentFeedback,
	) error
}

// =========================================================
// Tool Repository
// =========================================================

type ToolRepository interface {
	CreateTool(
		context.Context,
		int64,
		model.Tool,
	) (*model.Tool, error)

	ListTools(
		context.Context,
		int64,
		bool,
	) ([]model.Tool, error)

	ToolByID(
		context.Context,
		int64,
		int64,
	) (*model.Tool, error)

	UpdateTool(
		context.Context,
		int64,
		int64,
		model.Tool,
	) (*model.Tool, error)

	DeleteTool(
		context.Context,
		int64,
		int64,
	) (bool, error)
}

// =========================================================
// MCP Server Repository
// =========================================================

type MCPServerRepository interface {
	CreateMCPServer(
		context.Context,
		int64,
		model.MCPServer,
	) (*model.MCPServer, error)

	ListMCPServers(
		context.Context,
		int64,
		bool,
	) ([]model.MCPServer, error)

	MCPServerByID(
		context.Context,
		int64,
		int64,
	) (*model.MCPServer, error)

	UpdateMCPServer(
		context.Context,
		int64,
		int64,
		model.MCPServer,
	) (*model.MCPServer, error)

	DeleteMCPServer(
		context.Context,
		int64,
		int64,
	) (bool, error)
}

// =========================================================
// User-global Memory Repository
//
// Ownership is always user_id. There is intentionally no project scope here.
// =========================================================

type MemoryRepository interface {
	CreateMemory(
		context.Context,
		int64,
		model.UserMemory,
	) (*model.UserMemory, error)

	MemoryByID(
		context.Context,
		int64,
		int64,
	) (*model.UserMemory, error)

	MemoryByKey(
		context.Context,
		int64,
		string,
	) (*model.UserMemory, error)

	ListMemories(
		context.Context,
		int64,
		model.MemoryFilter,
	) ([]model.UserMemory, error)

	ListActiveMemories(
		context.Context,
		int64,
		int,
	) ([]model.UserMemory, error)

	UpdateMemory(
		context.Context,
		int64,
		int64,
		model.UserMemory,
	) (*model.UserMemory, error)

	DeleteMemory(
		context.Context,
		int64,
		int64,
	) (bool, error)

	TouchMemoryAccess(
		context.Context,
		int64,
		int64,
	) error
}

// =========================================================
// Task Repository
//
// v1.9.5B Long-lived Task State Machine
//
// CreateTask
//
//      ↓
//
// RUNNING
//
//      ↓
//
// SuspendTask
//
//      ↓
//
// INPUT_REQUIRED / AUTH_REQUIRED
//
//      ↓
//
// BeginTaskResume
//
//      ↓
//
// RUNNING
//
//      ↓
//
// CompleteTask
//
//      ↓
//
// COMPLETED
//
// Resume 不创建新的 Task。
// =========================================================

type TaskRepository interface {
	// -----------------------------------------------------
	// Create a brand new logical AgentMesh Task.
	// -----------------------------------------------------

	CreateTask(
		context.Context,
		model.Task,
		model.TaskConstraints,
	) (*model.Task, error)

	// -----------------------------------------------------
	// Read one task with tenant ownership protection.
	//
	// WHERE id=? AND user_id=?
	// -----------------------------------------------------

	TaskByID(
		context.Context,
		int64,
		int64,
	) (*model.Task, error)

	// -----------------------------------------------------
	// RUNNING
	//    ↓
	// INPUT_REQUIRED / AUTH_REQUIRED
	//
	// continuation 与状态一起持久化。
	// -----------------------------------------------------

	SuspendTask(
		context.Context,
		int64,
		int64,
		string,
		string,
		*model.TaskContinuation,
		[]string,
		[]map[string]any,
		map[string]any,
		int64,
		float64,
	) error

	// -----------------------------------------------------
	// INPUT_REQUIRED / AUTH_REQUIRED
	//             ↓
	//          RUNNING
	//
	// 数据库 CAS。
	//
	// 返回：
	//
	// true  = 本次 Resume 成功抢到执行权
	// false = 状态已经被其他请求改变
	// -----------------------------------------------------

	BeginTaskResume(
		context.Context,
		int64,
		int64,
	) (bool, error)

	// -----------------------------------------------------
	// RUNNING
	//    ↓
	// COMPLETED
	// -----------------------------------------------------

	CompleteTask(
		context.Context,
		int64,
		int64,
		string,
		[]string,
		[]map[string]any,
		map[string]any,
		int64,
		float64,
	) error

	// -----------------------------------------------------
	// RUNNING
	//    ↓
	// ERROR
	// -----------------------------------------------------

	FailTask(
		context.Context,
		int64,
		int64,
		string,
		int64,
	) error

	// -----------------------------------------------------
	// Task History
	// -----------------------------------------------------

	ListTasks(
		context.Context,
		int64,
		int,
	) ([]model.Task, error)
}

// =========================================================
// P8 Durable Runtime Repository
// =========================================================

type DurableRuntimeRepository interface {
	LookupDurableSubmission(context.Context, int64, string) (*model.Task, string, error)

	CreateQueuedTaskAndRuntimeJob(
		context.Context,
		model.Task,
		model.TaskConstraints,
		[]byte,
		string,
		time.Time,
		int,
	) (*model.Task, *model.RuntimeJob, error)

	HeartbeatRuntimeWorker(
		context.Context,
		model.RuntimeWorker,
	) error

	RenewRuntimeExecutionLeases(
		context.Context,
		string,
		[]model.RuntimeExecutionLeaseRef,
		time.Duration,
	) (int64, error)

	MarkRuntimeJobResultPending(context.Context, int64, string, string, string, int64) (bool, error)
	ReconcileCommittedCompletingJobs(context.Context, time.Time) (int64, error)

	RuntimeWorkerByID(
		context.Context,
		string,
	) (*model.RuntimeWorker, error)

	ListAvailableRuntimeWorkers(
		context.Context,
		time.Time,
		int,
	) ([]model.RuntimeWorker, error)

	ClaimNextRuntimeJob(
		context.Context,
		string,
		string,
		time.Duration,
	) (*model.RuntimeJob, []byte, error)

	MarkRuntimeJobDispatching(
		context.Context,
		int64,
		string,
		string,
	) (bool, error)

	MarkRuntimeJobAccepted(
		context.Context,
		int64,
		string,
		string,
	) (bool, error)

	RuntimeJobByID(
		context.Context,
		int64,
	) (*model.RuntimeJob, error)

	BeginRuntimeJobCallback(
		context.Context,
		int64,
		string,
		string,
		string,
	) (bool, error)

	RuntimeJobCallbackOwned(
		context.Context,
		int64,
		string,
		string,
		string,
	) (bool, error)

	MarkRuntimeJobCompleted(
		context.Context,
		int64,
	) error

	RequeueRuntimeJob(
		context.Context,
		int64,
		time.Duration,
		string,
	) error

	FailRuntimeJob(
		context.Context,
		int64,
		string,
	) error

	CancelRuntimeTask(
		context.Context,
		int64,
		int64,
	) (*model.RuntimeJob, error)

	RecoverExpiredRuntimeLeases(
		context.Context,
		time.Time,
	) (int64, error)

	RecoverLostAcceptedRuntimeJobs(
		context.Context,
		time.Time,
		time.Duration,
		int,
	) (int64, int64, error)

	MarkStaleRuntimeTopology(
		context.Context,
		time.Time,
	) (int64, int64, error)

	ListExpiredAcceptedRuntimeJobs(
		context.Context,
		time.Time,
		int,
	) ([]model.RuntimeJob, error)

	RecordRuntimeWorkerDispatchSuccess(
		context.Context,
		string,
	) error

	RecordRuntimeWorkerDispatchFailure(
		context.Context,
		string,
		int,
		time.Duration,
	) error

	RuntimeReliabilitySnapshot(
		context.Context,
		time.Time,
	) (*model.RuntimeReliabilitySnapshot, error)

	RuntimeTopologySnapshot(
		context.Context,
		time.Time,
	) (*model.RuntimeTopologySnapshot, error)

	AcquireRuntimeDispatcherLease(
		context.Context,
		string,
		time.Duration,
	) (*model.RuntimeDispatcherLease, bool, error)

	ReleaseRuntimeDispatcherLease(
		context.Context,
		string,
	) error

	RuntimeDispatcherLease(
		context.Context,
	) (*model.RuntimeDispatcherLease, error)
}
