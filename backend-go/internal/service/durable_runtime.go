package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"strings"
	"sync"
	"time"

	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/repository"
	runtimeclient "example.com/agentmesh-control-plane/internal/runtime"

	"github.com/google/uuid"
)

type DurableRuntimeConfig struct {
	Enabled                 bool
	ControlPlaneBaseURL     string
	PollInterval            time.Duration
	LeaseDuration           time.Duration
	WorkerStaleAfter        time.Duration
	AcceptanceTimeout       time.Duration
	RetryBackoff            time.Duration
	JobDeadline             time.Duration
	MaxAttempts             int
	MaxQueueDepth           int
	CircuitFailureThreshold int
	CircuitOpenFor          time.Duration
}

type DurableRuntimeService struct {
	repo        repository.DurableRuntimeRepository
	taskService *TaskService
	runtime     *runtimeclient.Client
	cfg         DurableRuntimeConfig

	cancel context.CancelFunc
	wg     sync.WaitGroup
}

type DurableExecutionCallback struct {
	WorkerID      string                         `json:"workerId"`
	ExecutionID   string                         `json:"executionId"`
	LeaseToken    string                         `json:"leaseToken"`
	Status        string                         `json:"status"`
	Response      *runtimeclient.ExecuteResponse `json:"response,omitempty"`
	ErrorCategory string                         `json:"errorCategory,omitempty"`
}

func NewDurableRuntimeService(
	repo repository.DurableRuntimeRepository,
	taskService *TaskService,
	runtime *runtimeclient.Client,
	cfg DurableRuntimeConfig,
) *DurableRuntimeService {
	if cfg.PollInterval <= 0 {
		cfg.PollInterval = 300 * time.Millisecond
	}
	if cfg.LeaseDuration <= 0 {
		cfg.LeaseDuration = 15 * time.Second
	}
	if cfg.WorkerStaleAfter <= 0 {
		cfg.WorkerStaleAfter = 20 * time.Second
	}
	if cfg.AcceptanceTimeout <= 0 {
		cfg.AcceptanceTimeout = 5 * time.Second
	}
	if cfg.RetryBackoff <= 0 {
		cfg.RetryBackoff = 500 * time.Millisecond
	}
	if cfg.JobDeadline <= 0 {
		cfg.JobDeadline = 2 * time.Minute
	}
	if cfg.MaxAttempts < 1 {
		cfg.MaxAttempts = 3
	}
	if cfg.MaxQueueDepth < 1 {
		cfg.MaxQueueDepth = 500
	}
	if cfg.CircuitFailureThreshold < 1 {
		cfg.CircuitFailureThreshold = 3
	}
	if cfg.CircuitOpenFor <= 0 {
		cfg.CircuitOpenFor = 20 * time.Second
	}
	return &DurableRuntimeService{repo: repo, taskService: taskService, runtime: runtime, cfg: cfg}
}

func (s *DurableRuntimeService) Start(parent context.Context) {
	if s == nil || !s.cfg.Enabled || s.cancel != nil {
		return
	}
	ctx, cancel := context.WithCancel(parent)
	s.cancel = cancel
	s.wg.Add(1)
	go func() {
		defer s.wg.Done()
		ticker := time.NewTicker(s.cfg.PollInterval)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				s.dispatchTick(ctx)
			}
		}
	}()
}

func (s *DurableRuntimeService) Stop() {
	if s == nil || s.cancel == nil {
		return
	}
	s.cancel()
	s.wg.Wait()
	s.cancel = nil
}

func normalizeDurableRunInput(in RunTaskInput) (RunTaskInput, error) {
	in.Task = strings.TrimSpace(in.Task)
	if in.Task == "" {
		return in, ErrInvalidInput
	}
	in.Scheduler = strings.ToLower(strings.TrimSpace(in.Scheduler))
	in.Planner = strings.ToLower(strings.TrimSpace(in.Planner))
	in.ExecutionMode = strings.ToLower(strings.TrimSpace(in.ExecutionMode))
	in.SynthesisMode = strings.ToLower(strings.TrimSpace(in.SynthesisMode))
	if in.Scheduler == "" {
		in.Scheduler = "greedy"
	}
	if in.Planner == "" {
		in.Planner = "heuristic"
	}
	if in.ExecutionMode == "" {
		in.ExecutionMode = "auto"
	}
	if in.SynthesisMode == "" {
		in.SynthesisMode = "auto"
	}
	switch in.Scheduler {
	case "fixed", "capability", "greedy", "adaptive":
	default:
		return in, ErrInvalidInput
	}
	switch in.Planner {
	case "heuristic", "multi_objective":
	default:
		return in, ErrInvalidInput
	}
	switch in.ExecutionMode {
	case "auto", "parallel", "sequential":
	default:
		return in, ErrInvalidInput
	}
	switch in.SynthesisMode {
	case "auto", "always", "never":
	default:
		return in, ErrInvalidInput
	}
	if in.Constraints.MaxLatencyMS <= 0 {
		in.Constraints.MaxLatencyMS = 8000
	}
	if in.Constraints.MaxCost <= 0 {
		in.Constraints.MaxCost = 0.15
	}
	if in.Constraints.MinQuality <= 0 {
		in.Constraints.MinQuality = 0.8
	}
	return in, nil
}

func (s *DurableRuntimeService) Run(ctx context.Context, uid int64, in RunTaskInput) (*RunTaskResult, error) {
	if !s.cfg.Enabled {
		return nil, errors.New("durable runtime is disabled")
	}
	var err error
	in, err = normalizeDurableRunInput(in)
	if err != nil {
		return nil, err
	}

	var projectRuntimeContext *model.ProjectRuntimeContext
	if s.taskService.projectRuntime != nil && in.ConversationID != nil {
		projectRuntimeContext, err = s.taskService.projectRuntime.ResolveForConversation(ctx, uid, *in.ConversationID)
		if err != nil {
			return nil, err
		}
		if s.taskService.governance != nil && projectRuntimeContext != nil {
			if quotaErr := s.taskService.governance.CheckQuota(ctx, uid, projectRuntimeContext.ProjectID); quotaErr != nil {
				return nil, quotaErr
			}
		}
		applyProjectRuntimePolicy(&in, projectRuntimeContext)
	}

	if s.taskService.governance != nil {
		if _, modelErr := s.taskService.resolveRequestModelRuntime(ctx, uid, projectRuntimeContext); modelErr != nil {
			return nil, modelErr
		}
	}

	snapshot, err := s.repo.RuntimeReliabilitySnapshot(ctx, time.Now().UTC().Add(-s.cfg.WorkerStaleAfter))
	if err != nil {
		return nil, err
	}
	active := snapshot.QueueDepth + snapshot.Leased + snapshot.Accepted
	if active >= s.cfg.MaxQueueDepth {
		return nil, errors.New("runtime queue is full")
	}

	requestID := uuid.NewString()

	var attachmentMeta []map[string]any
	if len(in.AttachmentIDs) > 0 {
		if in.ConversationID == nil || s.taskService.attachments == nil {
			return nil, ErrInvalidInput
		}
		_, resolvedMeta, attachmentErr := s.taskService.attachments.ResolveForRuntime(
			ctx, uid, *in.ConversationID, in.AttachmentIDs,
		)
		if attachmentErr != nil {
			return nil, attachmentErr
		}
		attachmentMeta = resolvedMeta
	}

	if in.ConversationID != nil {
		_, err = s.taskService.messages.CreateMessage(ctx, uid, *in.ConversationID, "user", in.Task, "COMPLETED", requestID, map[string]any{
			"runtimePhase": "durable_queued",
			"deliveryMode": "durable",
			"attachments":  attachmentMeta,
		})
		if errors.Is(err, repository.ErrNotOwned) {
			return nil, ErrNotFound
		}
		if err != nil {
			return nil, err
		}
	}

	// Store only the policy/task envelope. Agent/Tool/MCP pools are intentionally
	// refreshed immediately before dispatch so revoked Project bindings cannot be
	// resurrected by a queued payload.
	req := runtimeclient.ExecuteRequest{
		UserID: uid, RequestID: requestID, ConversationID: in.ConversationID,
		Task: in.Task, Scheduler: in.Scheduler, Planner: in.Planner,
		ExecutionMode: in.ExecutionMode, SynthesisMode: in.SynthesisMode,
		Constraints: in.Constraints, AttachmentIDs: append([]int64(nil), in.AttachmentIDs...),
	}
	requestJSON, err := json.Marshal(req)
	if err != nil {
		return nil, err
	}

	task, _, err := s.repo.CreateQueuedTaskAndRuntimeJob(ctx, model.Task{
		UserID: uid, ConversationID: in.ConversationID, RequestID: requestID,
		TaskText: in.Task, Scheduler: in.Scheduler, Planner: in.Planner,
		ExecutionMode: in.ExecutionMode, SynthesisMode: in.SynthesisMode,
		DeliveryMode: "durable",
	}, in.Constraints, requestJSON, uuid.NewString(), time.Now().UTC().Add(s.cfg.JobDeadline), s.cfg.MaxAttempts)
	if err != nil {
		return nil, err
	}

	return &RunTaskResult{
		Task:           task,
		Status:         "QUEUED",
		Answer:         "任务已进入可靠队列，Runtime Worker 将异步执行。",
		Citations:      []runtimeclient.RuntimeCitation{},
		Scheduler:      in.Scheduler,
		Planner:        in.Planner,
		ExecutionMode:  in.ExecutionMode,
		SynthesisMode:  in.SynthesisMode,
		TaskProfile:    map[string]any{},
		SelectedAgents: []string{},
		Trace:          []map[string]any{},
		DAG:            map[string]any{},
		AgentFeedback:  []model.AgentFeedback{},
		Observability:  runtimeclient.ObservabilitySummary{},
	}, nil
}

func (s *DurableRuntimeService) dispatchTick(ctx context.Context) {
	if !s.cfg.Enabled {
		return
	}
	now := time.Now().UTC()
	if _, err := s.repo.RecoverExpiredRuntimeLeases(ctx, now); err != nil {
		log.Printf("p8 recover runtime leases: %v", err)
	}
	expired, err := s.repo.ListExpiredAcceptedRuntimeJobs(ctx, now, 50)
	if err == nil {
		for _, job := range expired {
			_ = s.repo.FailRuntimeJob(ctx, job.ID, "runtime execution deadline exceeded; outcome treated as ambiguous")
		}
	}

	workers, err := s.repo.ListAvailableRuntimeWorkers(ctx, now.Add(-s.cfg.WorkerStaleAfter), 32)
	if err != nil {
		log.Printf("p8 list workers: %v", err)
		return
	}
	for _, worker := range workers {
		slots := worker.Capacity - worker.ActiveExecutions
		if slots < 1 {
			continue
		}
		for i := 0; i < slots; i++ {
			leaseToken := uuid.NewString()
			job, requestJSON, err := s.repo.ClaimNextRuntimeJob(ctx, worker.WorkerID, leaseToken, s.cfg.LeaseDuration)
			if err != nil {
				log.Printf("p8 claim job: %v", err)
				break
			}
			if job == nil {
				return
			}
			s.dispatchOne(ctx, worker, job, leaseToken, requestJSON)
		}
	}
}

func (s *DurableRuntimeService) dispatchOne(ctx context.Context, worker model.RuntimeWorker, job *model.RuntimeJob, leaseToken string, requestJSON []byte) {
	var req runtimeclient.ExecuteRequest
	if err := json.Unmarshal(requestJSON, &req); err != nil {
		_ = s.repo.FailRuntimeJob(ctx, job.ID, "invalid durable runtime payload")
		return
	}

	if len(req.AttachmentIDs) > 0 {
		if req.ConversationID == nil || s.taskService.attachments == nil {
			_ = s.repo.FailRuntimeJob(ctx, job.ID, "runtime attachments unavailable")
			return
		}
		resolved, _, attachmentErr := s.taskService.attachments.ResolveForRuntime(
			ctx, job.UserID, *req.ConversationID, req.AttachmentIDs,
		)
		if attachmentErr != nil {
			_ = s.repo.FailRuntimeJob(ctx, job.ID, "runtime attachments unavailable")
			return
		}
		req.Attachments = resolved
		req.AttachmentIDs = nil
	}

	// Re-read current Project membership/configuration and resource bindings at
	// dispatch time. The actor stays job.UserID, while a shared Project executes
	// against the Project owner's configured Agent/Tool/MCP registry.
	var projectContext *model.ProjectRuntimeContext
	var err error
	if s.taskService.projectRuntime != nil && req.ConversationID != nil {
		projectContext, err = s.taskService.projectRuntime.ResolveForConversation(ctx, job.UserID, *req.ConversationID)
		if err != nil {
			_ = s.repo.FailRuntimeJob(ctx, job.ID, "project runtime unavailable")
			return
		}
	}
	agents, tools, mcps, err := s.taskService.loadRuntimeResources(ctx, projectRuntimeResourceUserID(job.UserID, projectContext))
	if err != nil {
		_ = s.repo.FailRuntimeJob(ctx, job.ID, "runtime resources unavailable")
		return
	}
	agents, tools, mcps = filterProjectRuntimeResources(projectContext, agents, tools, mcps)
	if s.taskService.governance != nil {
		projectModel, modelErr := s.taskService.resolveRequestModelRuntime(ctx, job.UserID, projectContext)
		if modelErr != nil {
			_ = s.repo.FailRuntimeJob(ctx, job.ID, "model provider unavailable")
			return
		}
		req.ProjectModel = projectModel
	}
	if len(agents) == 0 {
		_ = s.repo.FailRuntimeJob(ctx, job.ID, "project runtime has no enabled agents")
		return
	}
	req.Agents, req.Tools, req.MCPServers = agents, tools, mcps

	dispatching, err := s.repo.MarkRuntimeJobDispatching(ctx, job.ID, worker.WorkerID, leaseToken)
	if err != nil || !dispatching {
		_ = s.repo.FailRuntimeJob(ctx, job.ID, "unable to establish durable dispatch fence")
		return
	}

	callbackURL := strings.TrimRight(s.cfg.ControlPlaneBaseURL, "/") + fmt.Sprintf("/internal/v1/runtime/jobs/%d/result", job.ID)
	acceptCtx, cancel := runtimeclient.AcceptanceTimeout(ctx, s.cfg.AcceptanceTimeout)
	accepted, dispatchErr := s.runtime.SubmitDurableExecution(acceptCtx, worker.Endpoint, runtimeclient.DurableExecutionEnvelope{
		JobID: job.ID, ExecutionID: job.ExecutionID, LeaseToken: leaseToken,
		CallbackURL: callbackURL, Request: req,
	})
	cancel()
	if dispatchErr != nil {
		var typed *runtimeclient.WorkerDispatchError
		if errors.As(dispatchErr, &typed) && typed.SafeToRetry && job.AttemptCount < job.MaxAttempts && time.Now().UTC().Before(job.DeadlineAt) {
			_ = s.repo.RecordRuntimeWorkerDispatchFailure(ctx, worker.WorkerID, s.cfg.CircuitFailureThreshold, s.cfg.CircuitOpenFor)
			delay := s.cfg.RetryBackoff * time.Duration(job.AttemptCount)
			if delay <= 0 {
				delay = s.cfg.RetryBackoff
			}
			_ = s.repo.RequeueRuntimeJob(ctx, job.ID, delay, "worker unavailable before acceptance")
			return
		}
		// Once the dispatch boundary is ambiguous, never replay automatically.
		_ = s.repo.RecordRuntimeWorkerDispatchFailure(ctx, worker.WorkerID, s.cfg.CircuitFailureThreshold, s.cfg.CircuitOpenFor)
		_ = s.repo.FailRuntimeJob(ctx, job.ID, "runtime execution outcome is ambiguous; automatic replay disabled")
		return
	}
	if accepted == nil || !accepted.Accepted {
		_ = s.repo.FailRuntimeJob(ctx, job.ID, "runtime worker did not acknowledge execution")
		return
	}
	marked, err := s.repo.MarkRuntimeJobAccepted(ctx, job.ID, worker.WorkerID, leaseToken)
	if err != nil {
		// A worker already accepted this execution. Database uncertainty must fail
		// closed rather than turn into a replayable LEASED job.
		_ = s.repo.FailRuntimeJob(ctx, job.ID, "worker accepted execution but control-plane acknowledgement failed")
		return
	}
	// The callback can race the 202 acknowledgement and move DISPATCHING directly
	// to COMPLETING. In that case marked=false is valid and still safe.
	if marked {
		_ = s.repo.RecordRuntimeWorkerDispatchSuccess(ctx, worker.WorkerID)
	}
}

func (s *DurableRuntimeService) Heartbeat(ctx context.Context, worker model.RuntimeWorker) error {
	if strings.TrimSpace(worker.WorkerID) == "" || strings.TrimSpace(worker.Endpoint) == "" {
		return ErrInvalidInput
	}
	return s.repo.HeartbeatRuntimeWorker(ctx, worker)
}

func (s *DurableRuntimeService) Callback(ctx context.Context, jobID int64, callback DurableExecutionCallback) error {
	job, err := s.repo.RuntimeJobByID(ctx, jobID)
	if err != nil {
		return err
	}
	if job == nil {
		return ErrNotFound
	}
	if job.Status == "COMPLETED" || job.Status == "CANCELED" || job.Status == "FAILED" {
		return nil
	}

	begun, err := s.repo.BeginRuntimeJobCallback(ctx, jobID, callback.ExecutionID, callback.WorkerID, callback.LeaseToken)
	if err != nil {
		return err
	}
	if !begun {
		// A duplicate callback may observe COMPLETING after the first callback won
		// the CAS. It must never execute the side effects twice.
		return nil
	}

	status := strings.ToLower(strings.TrimSpace(callback.Status))
	if status == "canceled" {
		return s.repo.FailRuntimeJob(ctx, jobID, "runtime execution canceled")
	}
	if status == "failed" || callback.Response == nil {
		category := strings.TrimSpace(callback.ErrorCategory)
		if category == "" {
			category = "runtime_execution_failed"
		}
		return s.repo.FailRuntimeJob(ctx, jobID, category)
	}

	task, err := s.taskService.tasks.TaskByID(ctx, job.UserID, job.TaskID)
	if err != nil {
		_ = s.repo.FailRuntimeJob(ctx, jobID, "task persistence unavailable")
		return err
	}
	if task == nil {
		_ = s.repo.FailRuntimeJob(ctx, jobID, "task missing")
		return ErrNotFound
	}
	response := callback.Response
	response.Trace = append([]map[string]any{durableReliabilityTrace(job, callback.WorkerID, "completed")}, response.Trace...)
	if s.taskService.governance != nil && s.taskService.projectRuntime != nil && task.ConversationID != nil {
		if projectCtx, resolveErr := s.taskService.projectRuntime.ResolveForConversation(ctx, job.UserID, *task.ConversationID); resolveErr == nil && projectCtx != nil {
			s.taskService.governance.RecordUsage(ctx, projectCtx.ProjectID, int64(response.Observability.ModelTotalTokens), response.EstimatedCost, int64(response.Observability.ToolCalls))
		}
	}
	runtimeStatus := normalizeRuntimeStatus(response.Status)

	if runtimeStatus == "INPUT_REQUIRED" || runtimeStatus == "AUTH_REQUIRED" {
		if response.Continuation == nil {
			_ = s.repo.FailRuntimeJob(ctx, jobID, "runtime suspended without continuation")
			return errors.New("runtime suspended without continuation")
		}
		continuation := runtimeContinuationToModel(response.Continuation)
		if err := s.taskService.tasks.SuspendTask(ctx, job.UserID, job.TaskID, runtimeStatus, response.Answer, continuation,
			response.SelectedAgents, response.Trace, response.DAG, response.ElapsedMS, response.EstimatedCost); err != nil {
			_ = s.repo.FailRuntimeJob(ctx, jobID, "failed to persist runtime suspension")
			return err
		}
		if task.ConversationID != nil {
			_, _ = s.taskService.messages.CreateMessage(ctx, job.UserID, *task.ConversationID, "assistant", response.Answer,
				runtimeStatus, task.RequestID, map[string]any{
					"taskId": task.ID, "runtimePhase": "durable_suspended", "deliveryMode": "durable",
					"trace": response.Trace, "dag": response.DAG, "selectedAgents": response.SelectedAgents,
					"taskProfile": response.TaskProfile, "observability": response.Observability,
					"scorecard": response.Scorecard, "agentFeedback": response.AgentFeedback,
					"citations": normalizeRuntimeCitations(response.Citations),
				})
		}
		return s.repo.MarkRuntimeJobCompleted(ctx, jobID)
	}

	if runtimeStatus != "COMPLETED" {
		return s.repo.FailRuntimeJob(ctx, jobID, "unsupported runtime status")
	}
	if err := s.taskService.tasks.CompleteTask(ctx, job.UserID, job.TaskID, response.Answer, response.SelectedAgents,
		response.Trace, response.DAG, response.ElapsedMS, response.EstimatedCost); err != nil {
		_ = s.repo.FailRuntimeJob(ctx, jobID, "failed to persist runtime completion")
		return err
	}
	if err := s.taskService.agents.RecordAgentFeedback(ctx, job.UserID, task.RequestID, response.AgentFeedback); err != nil {
		// Evaluation feedback persistence is important but cannot turn an already
		// completed user task into an execution replay.
		log.Printf("p8 agent feedback persistence failed: %v", err)
	}
	if task.ConversationID != nil {
		_, _ = s.taskService.messages.CreateMessage(ctx, job.UserID, *task.ConversationID, "assistant", response.Answer,
			"COMPLETED", task.RequestID, map[string]any{
				"taskId": task.ID, "runtimePhase": "durable_completed", "deliveryMode": "durable",
				"trace": response.Trace, "dag": response.DAG, "selectedAgents": response.SelectedAgents,
				"taskProfile": response.TaskProfile, "scheduler": task.Scheduler, "planner": task.Planner,
				"executionMode": task.ExecutionMode, "synthesisMode": task.SynthesisMode,
				"observability": response.Observability, "scorecard": response.Scorecard,
				"agentFeedback": response.AgentFeedback, "citations": normalizeRuntimeCitations(response.Citations),
			})
	}
	return s.repo.MarkRuntimeJobCompleted(ctx, jobID)
}

func durableReliabilityTrace(job *model.RuntimeJob, workerID, status string) map[string]any {
	detail, _ := json.Marshal(map[string]any{
		"deliveryMode":   "durable",
		"jobId":          job.ID,
		"executionId":    job.ExecutionID,
		"workerId":       workerID,
		"attempt":        job.AttemptCount,
		"maxAttempts":    job.MaxAttempts,
		"dispatchStatus": status,
	})
	return map[string]any{
		"kind": "reliability", "title": "Durable Runtime Dispatch", "status": "completed",
		"detail": string(detail), "elapsedMs": 0,
	}
}

func (s *DurableRuntimeService) Cancel(ctx context.Context, uid, taskID int64) (*model.Task, error) {
	job, err := s.repo.CancelRuntimeTask(ctx, uid, taskID)
	if errors.Is(err, repository.ErrNotOwned) {
		return nil, ErrNotFound
	}
	if errors.Is(err, repository.ErrInvalidTaskState) {
		return nil, ErrConflict
	}
	if err != nil {
		return nil, err
	}
	if job != nil && job.WorkerID != nil {
		if worker, lookupErr := s.repo.RuntimeWorkerByID(ctx, *job.WorkerID); lookupErr == nil && worker != nil {
			cancelCtx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
			_ = s.runtime.CancelDurableExecution(cancelCtx, worker.Endpoint, job.ExecutionID)
			cancel()
		}
	}
	return s.taskService.tasks.TaskByID(ctx, uid, taskID)
}

func (s *DurableRuntimeService) Reliability(ctx context.Context) (*model.RuntimeReliabilitySnapshot, error) {
	if !s.cfg.Enabled {
		return &model.RuntimeReliabilitySnapshot{Enabled: false}, nil
	}
	return s.repo.RuntimeReliabilitySnapshot(ctx, time.Now().UTC().Add(-s.cfg.WorkerStaleAfter))
}
