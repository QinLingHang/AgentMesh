package service

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
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
	DispatcherID            string
	DispatcherLeaseDuration time.Duration
	PollInterval            time.Duration
	LeaseDuration           time.Duration
	ExecutionLeaseDuration  time.Duration
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

	cancel          context.CancelFunc
	wg              sync.WaitGroup
	startedAt       time.Time
	nextReconcileAt time.Time
}

type DurableExecutionCallback struct {
	WorkerID        string                         `json:"workerId"`
	ExecutionID     string                         `json:"executionId"`
	LeaseToken      string                         `json:"leaseToken"`
	FenceEpoch      int64                          `json:"fenceEpoch"`
	DispatcherEpoch int64                          `json:"dispatcherEpoch"`
	Status          string                         `json:"status"`
	Response        *runtimeclient.ExecuteResponse `json:"response,omitempty"`
	ErrorCategory   string                         `json:"errorCategory,omitempty"`
}

// DurableWorkerPhase is deliberately metadata-only. The handler ignores extra
// JSON fields; only these enumerated fields are ever forwarded or persisted.
type DurableWorkerPhase struct {
	WorkerID    string `json:"workerId"`
	ExecutionID string `json:"executionId"`
	LeaseToken  string `json:"leaseToken"`
	FenceEpoch  int64  `json:"fenceEpoch"`
	Ordinal     int64  `json:"ordinal"`
	Phase       string `json:"phase"`
	Status      string `json:"status"`
}

var allowedWorkerPhases = map[string]bool{
	"task": true, "planner": true, "scheduler": true,
	"agent": true, "tool": true, "mcp": true, "rag": true,
	"knowledge": true, "memory": true, "model": true,
}

// WorkerPhase is best-effort observability: failure to publish a phase never
// changes the business result. An admitted phase is durable and SSE-replayable.
func (s *DurableRuntimeService) WorkerPhase(ctx context.Context, jobID int64, phase DurableWorkerPhase) (bool, error) {
	phase.WorkerID = strings.TrimSpace(phase.WorkerID)
	phase.ExecutionID = strings.TrimSpace(phase.ExecutionID)
	phase.LeaseToken = strings.TrimSpace(phase.LeaseToken)
	phase.Phase = strings.ToLower(strings.TrimSpace(phase.Phase))
	phase.Status = strings.ToLower(strings.TrimSpace(phase.Status))
	if jobID <= 0 || phase.WorkerID == "" || phase.ExecutionID == "" || phase.LeaseToken == "" ||
		phase.FenceEpoch <= 0 || phase.Ordinal <= 0 || phase.Ordinal > 256 ||
		!allowedWorkerPhases[phase.Phase] ||
		(phase.Status != "running" && phase.Status != "completed" && phase.Status != "error" && phase.Status != "skipped") {
		return false, ErrInvalidInput
	}
	writer, ok := s.repo.(interface {
		AppendDurableWorkerPhase(context.Context, int64, string, string, string, int64, int64, string, string) (bool, error)
	})
	if !ok {
		return false, errors.New("durable phase storage unavailable")
	}
	return writer.AppendDurableWorkerPhase(ctx, jobID, phase.ExecutionID, phase.WorkerID,
		phase.LeaseToken, phase.FenceEpoch, phase.Ordinal, phase.Phase, phase.Status)
}

func NewDurableRuntimeService(
	repo repository.DurableRuntimeRepository,
	taskService *TaskService,
	runtime *runtimeclient.Client,
	cfg DurableRuntimeConfig,
) *DurableRuntimeService {
	if strings.TrimSpace(cfg.DispatcherID) == "" {
		cfg.DispatcherID = "dispatcher-local-1"
	}
	if cfg.DispatcherLeaseDuration <= 0 {
		cfg.DispatcherLeaseDuration = 5 * time.Second
	}
	if cfg.PollInterval <= 0 {
		cfg.PollInterval = 300 * time.Millisecond
	}
	if cfg.LeaseDuration <= 0 {
		cfg.LeaseDuration = 15 * time.Second
	}
	if cfg.ExecutionLeaseDuration <= 0 {
		cfg.ExecutionLeaseDuration = 20 * time.Second
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
	s.startedAt = time.Now().UTC()
	s.wg.Add(1)
	go func() {
		defer s.wg.Done()
		ticker := time.NewTicker(s.cfg.PollInterval)
		defer ticker.Stop()
		s.dispatchTick(ctx)
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
	releaseCtx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	_ = s.repo.ReleaseRuntimeDispatcherLease(releaseCtx, s.cfg.DispatcherID)
	cancel()
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

// validClientRequestID bounds the identifier used in the MySQL composite key.
// It must never be used as a bearer secret or as an authorization substitute.
func validClientRequestID(value string) bool {
	if value == "" {
		return true
	} // backwards compatibility
	if len(value) < 8 || len(value) > 64 {
		return false
	}
	for _, char := range value {
		if !((char >= 'a' && char <= 'z') || (char >= 'A' && char <= 'Z') ||
			(char >= '0' && char <= '9') || char == '-' || char == '_') {
			return false
		}
	}
	return true
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
	// Only a stable client-supplied identity participates in deduplication.
	// Legacy clients without the field keep the original submission semantics.
	in.ClientRequestID = strings.TrimSpace(in.ClientRequestID)
	if !validClientRequestID(in.ClientRequestID) {
		return nil, ErrInvalidInput
	}
	fingerprintInput := in
	fingerprintInput.ClientRequestID = ""
	fingerprintJSON, err := json.Marshal(fingerprintInput)
	if err != nil {
		return nil, err
	}
	digest := sha256.Sum256(fingerprintJSON)
	requestFingerprint := hex.EncodeToString(digest[:])

	if in.ClientRequestID != "" {
		existing, existingFingerprint, lookupErr := s.repo.LookupDurableSubmission(ctx, uid, in.ClientRequestID)
		if errors.Is(lookupErr, repository.ErrSubmissionConflict) {
			return nil, ErrIdempotencyConflict
		}
		if lookupErr != nil {
			return nil, lookupErr
		}
		if existing != nil {
			if existingFingerprint != requestFingerprint || existing.DeliveryMode != "durable" {
				return nil, ErrIdempotencyConflict
			}
			return durableSubmissionResult(existing), nil
		}
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
		_, _, normalizedSelection, modelErr := s.taskService.resolveRequestModelRuntimePool(ctx, uid, projectRuntimeContext, in.ModelSelection)
		if modelErr != nil {
			return nil, modelErr
		}
		in.ModelSelection = normalizedSelection
	}

	normalizedRagPolicy, effectiveRagPolicy, knowledgeCatalog, err := s.taskService.resolveEffectiveRagPolicy(
		ctx, uid, in.ConversationID, in.RagPolicy,
	)
	if err != nil {
		return nil, err
	}
	in.RagPolicy = normalizedRagPolicy

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

	// Store only the policy/task envelope. Agent/Tool/MCP pools are intentionally
	// refreshed immediately before dispatch so revoked Project bindings cannot be
	// resurrected by a queued payload.
	req := runtimeclient.ExecuteRequest{
		UserID: uid, RequestID: requestID, ConversationID: in.ConversationID,
		ExecutionRoute: in.ExecutionRoute, Task: in.Task, Scheduler: in.Scheduler, Planner: in.Planner,
		ExecutionMode: in.ExecutionMode, SynthesisMode: in.SynthesisMode,
		ModelSelection:     runtimeclient.ModelSelection{Mode: in.ModelSelection.Mode, ServiceID: in.ModelSelection.ServiceID},
		RagPolicy:          in.RagPolicy,
		EffectiveRagPolicy: effectiveRagPolicy,
		KnowledgeCatalog:   knowledgeCatalog,
		Constraints:        in.Constraints, AttachmentIDs: append([]int64(nil), in.AttachmentIDs...),
	}
	requestJSON, err := json.Marshal(req)
	if err != nil {
		return nil, err
	}

	task, _, err := s.repo.CreateQueuedTaskAndRuntimeJob(ctx, model.Task{
		ClientRequestID: in.ClientRequestID, RequestFingerprint: requestFingerprint,
		PendingUserMessageMetadata: executionRoutingMetadata(in, map[string]any{
			"runtimePhase": "durable_queued", "deliveryMode": "durable", "attachments": attachmentMeta,
		}),
		UserID: uid, ConversationID: in.ConversationID, RequestID: requestID,
		TaskText: in.Task, Scheduler: in.Scheduler, Planner: in.Planner,
		ExecutionMode: in.ExecutionMode, SynthesisMode: in.SynthesisMode,
		ModelSelection:     in.ModelSelection,
		RagPolicy:          in.RagPolicy,
		EffectiveRagPolicy: effectiveRagPolicy,
		DeliveryMode:       "durable",
	}, in.Constraints, requestJSON, uuid.NewString(), time.Now().UTC().Add(s.cfg.JobDeadline), s.cfg.MaxAttempts)
	if errors.Is(err, repository.ErrSubmissionConflict) {
		return nil, ErrIdempotencyConflict
	}
	if errors.Is(err, repository.ErrNotOwned) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	return durableSubmissionResult(task), nil
}

// The replay response is a projection of the ORIGINAL authoritative task,
// never the newly generated temporary request ID or a second execution.
func durableSubmissionResult(task *model.Task) *RunTaskResult {
	status := task.Status
	answer := "任务已进入可靠队列，Runtime Worker 将异步执行。"
	if task.ResultText != nil {
		answer = *task.ResultText
	}
	if task.ErrorMessage != nil && status == "ERROR" {
		answer = *task.ErrorMessage
	}

	return &RunTaskResult{
		Task:           task,
		Status:         status,
		Answer:         answer,
		Citations:      []runtimeclient.RuntimeCitation{},
		Scheduler:      task.Scheduler,
		Planner:        task.Planner,
		ExecutionMode:  task.ExecutionMode,
		SynthesisMode:  task.SynthesisMode,
		TaskProfile:    map[string]any{},
		SelectedAgents: task.SelectedAgents,
		Trace:          task.Trace,
		DAG:            task.DAG,
		AgentFeedback:  []model.AgentFeedback{},
		Observability:  runtimeclient.ObservabilitySummary{},
	}
}

func (s *DurableRuntimeService) dispatchTick(ctx context.Context) {
	if !s.cfg.Enabled {
		return
	}

	lease, leader, err := s.repo.AcquireRuntimeDispatcherLease(
		ctx, s.cfg.DispatcherID, s.cfg.DispatcherLeaseDuration,
	)
	if err != nil {
		log.Printf("v3 acquire dispatcher lease: %v", err)
		return
	}
	if !leader {
		return
	}

	now := time.Now().UTC()
	staleBefore := now.Add(-s.cfg.WorkerStaleAfter)
	if workers, nodes, topologyErr := s.repo.MarkStaleRuntimeTopology(ctx, staleBefore); topologyErr != nil {
		log.Printf("v3 mark stale runtime topology: %v", topologyErr)
	} else if workers > 0 || nodes > 0 {
		log.Printf("v3 topology offline workers=%d nodes=%d", workers, nodes)
	}
	if _, err := s.repo.RecoverExpiredRuntimeLeases(ctx, now); err != nil {
		log.Printf("v3 recover pre-accept runtime leases: %v", err)
	}
	// After a control-plane restart, give workers time to reconnect/renew
	// before recovering old ACCEPTED leases. Otherwise the dispatcher can race
	// an already-published Kafka result and irreversibly fail its task.
	if s.startedAt.IsZero() || !now.Before(s.startedAt.Add(2*s.cfg.WorkerStaleAfter)) {
		if requeued, failed, recoverErr := s.repo.RecoverLostAcceptedRuntimeJobs(
			ctx, now, s.cfg.RetryBackoff, 50,
		); recoverErr != nil {
			log.Printf("v3 recover accepted runtime executions: %v", recoverErr)
		} else if requeued > 0 || failed > 0 {
			log.Printf("v3 accepted execution recovery requeued=%d failed=%d", requeued, failed)
		}
	}
	// COMPLETING must never be failed based on a 30s wall-clock timeout: its
	// task/history transaction may already be committed. Prefer Kafka replay;
	// reconcile committed task terminals only after a generous replay window.
	if !now.Before(s.nextReconcileAt) {
		s.nextReconcileAt = now.Add(time.Minute)
		if reconciled, reconcileErr := s.repo.ReconcileCommittedCompletingJobs(ctx, now.Add(-10*time.Minute)); reconcileErr != nil {
			log.Printf("event delivery reconcile committed callbacks failed: %v", reconcileErr)
		} else if reconciled > 0 {
			log.Printf("event delivery reconciled committed callbacks count=%d", reconciled)
		}
	}

	expired, err := s.repo.ListExpiredAcceptedRuntimeJobs(ctx, now, 50)
	if err == nil {
		for _, job := range expired {
			_ = s.repo.FailRuntimeJob(ctx, job.ID, "runtime execution deadline exceeded; outcome treated as ambiguous")
		}
	}

	workers, err := s.repo.ListAvailableRuntimeWorkers(ctx, staleBefore, 64)
	if err != nil {
		log.Printf("v3 list workers: %v", err)
		return
	}
	dispatcherEpoch := int64(0)
	if lease != nil {
		dispatcherEpoch = lease.Epoch
	}
	for _, worker := range workers {
		slots := worker.Capacity - worker.AuthoritativeActive
		if slots < 1 {
			continue
		}
		for i := 0; i < slots; i++ {
			leaseToken := uuid.NewString()
			job, requestJSON, err := s.repo.ClaimNextRuntimeJob(ctx, worker.WorkerID, leaseToken, s.cfg.LeaseDuration)
			if err != nil {
				log.Printf("v3 claim job: %v", err)
				break
			}
			if job == nil {
				// Capacity may have changed after the worker list snapshot. Do not
				// stop the whole dispatcher; another node may still have capacity.
				break
			}
			s.dispatchOne(ctx, worker, job, leaseToken, dispatcherEpoch, requestJSON)
		}
	}
}

func (s *DurableRuntimeService) dispatchOne(
	ctx context.Context,
	worker model.RuntimeWorker,
	job *model.RuntimeJob,
	leaseToken string,
	dispatcherEpoch int64,
	requestJSON []byte,
) {
	var req runtimeclient.ExecuteRequest
	if err := json.Unmarshal(requestJSON, &req); err != nil {
		_ = s.repo.FailRuntimeJob(ctx, job.ID, "invalid durable runtime payload")
		return
	}

	// Rehydrate recent conversation context at dispatch time instead of
	// persisting it inside the durable queue payload.  The queued user message
	// has already been stored in MySQL, so exclude that current request from
	// history to avoid duplicating req.Task.
	if req.ConversationID != nil {
		recent, historyErr := s.taskService.messages.ListMessages(
			ctx, job.UserID, *req.ConversationID, 12,
		)
		if historyErr != nil {
			_ = s.repo.FailRuntimeJob(ctx, job.ID, "conversation history unavailable")
			return
		}
		filtered := recent[:0]
		for _, message := range recent {
			isCurrent := message.RequestID != nil &&
				*message.RequestID == req.RequestID &&
				strings.EqualFold(strings.TrimSpace(message.Role), "user")
			if isCurrent {
				continue
			}
			filtered = append(filtered, message)
		}
		req.History = boundedInteractiveHistory(filtered)
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
	_, liveEffectiveRagPolicy, liveKnowledgeCatalog, ragErr := s.taskService.resolveEffectiveRagPolicy(
		ctx, job.UserID, req.ConversationID, req.RagPolicy,
	)
	if ragErr != nil {
		_ = s.repo.FailRuntimeJob(ctx, job.ID, "knowledge authorization unavailable")
		return
	}
	req.EffectiveRagPolicy, req.KnowledgeCatalog = constrainEffectiveRagPolicyToSnapshot(
		req.EffectiveRagPolicy, liveEffectiveRagPolicy, liveKnowledgeCatalog,
	)

	agents, tools, mcps, err := s.taskService.loadRuntimeResources(ctx, projectRuntimeResourceUserID(job.UserID, projectContext))
	if err != nil {
		_ = s.repo.FailRuntimeJob(ctx, job.ID, "runtime resources unavailable")
		return
	}
	agents, tools, mcps = filterProjectRuntimeResources(projectContext, agents, tools, mcps)
	if s.taskService.governance != nil {
		selection := model.ModelSelection{Mode: req.ModelSelection.Mode, ServiceID: req.ModelSelection.ServiceID}
		modelPool, projectModel, normalizedSelection, modelErr := s.taskService.resolveRequestModelRuntimePool(ctx, job.UserID, projectContext, selection)
		if modelErr != nil {
			_ = s.repo.FailRuntimeJob(ctx, job.ID, "model provider unavailable")
			return
		}
		req.ProjectModel = projectModel
		req.ModelPool = modelPool
		req.ModelSelection = runtimeclient.ModelSelection{Mode: normalizedSelection.Mode, ServiceID: normalizedSelection.ServiceID}
	}
	if len(agents) == 0 && !(req.ExecutionRoute == "RUNTIME" && req.EffectiveRagPolicy.Mode != model.RagModeOff && len(req.EffectiveRagPolicy.AllowedKnowledgeBaseIDs) > 0) {
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
		FenceEpoch: job.FenceEpoch, DispatcherEpoch: dispatcherEpoch,
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
	// The result-pending heartbeat or callback can race the 202 acknowledgement
	// and advance DISPATCHING before this step. marked=false is valid.
	if marked {
		_ = s.repo.RecordRuntimeWorkerDispatchSuccess(ctx, worker.WorkerID)
	}
}

func (s *DurableRuntimeService) Heartbeat(
	ctx context.Context,
	worker model.RuntimeWorker,
	leases []model.RuntimeExecutionLeaseRef,
) ([]string, error) {
	if strings.TrimSpace(worker.WorkerID) == "" || strings.TrimSpace(worker.Endpoint) == "" {
		return nil, ErrInvalidInput
	}
	worker.WorkerID = strings.TrimSpace(worker.WorkerID)
	worker.NodeID = strings.TrimSpace(worker.NodeID)
	if worker.NodeID == "" {
		worker.NodeID = worker.WorkerID
	}
	if err := s.repo.HeartbeatRuntimeWorker(ctx, worker); err != nil {
		return nil, err
	}
	for _, lease := range leases {
		if !lease.ResultPending || lease.JobID <= 0 || lease.ExecutionID == "" || lease.LeaseToken == "" {
			continue
		}
		if _, err := s.repo.MarkRuntimeJobResultPending(
			ctx, lease.JobID, lease.ExecutionID, worker.WorkerID,
			lease.LeaseToken, lease.FenceEpoch,
		); err != nil {
			return nil, err
		}
	}
	_, err := s.repo.RenewRuntimeExecutionLeases(
		ctx, worker.WorkerID, leases, s.cfg.ExecutionLeaseDuration,
	)
	if err != nil {
		return nil, err
	}
	terminal := make([]string, 0)
	for _, lease := range leases {
		if !lease.ResultPending {
			continue
		}
		job, err := s.repo.RuntimeJobByID(ctx, lease.JobID)
		if err != nil {
			return nil, err
		}
		if job == nil || job.ExecutionID != lease.ExecutionID || job.WorkerID == nil ||
			*job.WorkerID != worker.WorkerID || job.FenceEpoch != lease.FenceEpoch {
			continue
		}
		if job.Status == "COMPLETED" || job.Status == "FAILED" || job.Status == "CANCELED" {
			terminal = append(terminal, lease.ExecutionID)
		}
	}
	return terminal, nil
}

type DurableCallbackOutcome string

const (
	DurableCallbackApplied    DurableCallbackOutcome = "applied"
	DurableCallbackRecovered  DurableCallbackOutcome = "recovered"
	DurableCallbackDuplicate  DurableCallbackOutcome = "duplicate"
	DurableCallbackStaleFence DurableCallbackOutcome = "stale_fence"
	DurableCallbackTerminal   DurableCallbackOutcome = "terminal"
)

func (s *DurableRuntimeService) Callback(ctx context.Context, jobID int64, callback DurableExecutionCallback) error {
	_, err := s.CallbackWithOutcome(ctx, jobID, callback)
	return err
}

// CallbackWithOutcome preserves the Durable Runtime/HTTP callback contract while exposing
// the no-op reason needed by the Event Delivery Kafka consumer for observability. It is also
// restart-safe for callbacks that were fenced into COMPLETING before a consumer
// process crashed: the same execution/worker/lease may resume finalization, while
// stale workers remain fenced out.
func (s *DurableRuntimeService) CallbackWithOutcome(ctx context.Context, jobID int64, callback DurableExecutionCallback) (DurableCallbackOutcome, error) {
	job, err := s.repo.RuntimeJobByID(ctx, jobID)
	if err != nil {
		return "", err
	}
	if job == nil {
		return "", ErrNotFound
	}
	if job.Status == "COMPLETED" || job.Status == "CANCELED" || job.Status == "FAILED" {
		return DurableCallbackTerminal, nil
	}

	// V3 adds a monotonic fence epoch on top of the random lease token. Older
	// legacy workers omit it (zero) and remain compatible; V3 workers must match the
	// current assignment so callbacks from a recovered stale node are ignored.
	if callback.FenceEpoch != 0 && callback.FenceEpoch != job.FenceEpoch {
		return DurableCallbackStaleFence, nil
	}

	resuming := job.Status == "COMPLETING"
	if resuming {
		owned, ownershipErr := s.repo.RuntimeJobCallbackOwned(
			ctx, jobID, callback.ExecutionID, callback.WorkerID, callback.LeaseToken,
		)
		if ownershipErr != nil {
			return "", ownershipErr
		}
		if !owned {
			return DurableCallbackDuplicate, nil
		}
	} else {
		begun, beginErr := s.repo.BeginRuntimeJobCallback(ctx, jobID, callback.ExecutionID, callback.WorkerID, callback.LeaseToken)
		if beginErr != nil {
			return "", beginErr
		}
		if !begun {
			// A duplicate callback may observe a state that no longer accepts this
			// lease. It must never execute the side effects twice.
			return DurableCallbackDuplicate, nil
		}
	}

	status := strings.ToLower(strings.TrimSpace(callback.Status))
	if status == "canceled" {
		if err := s.repo.FailRuntimeJob(ctx, jobID, "runtime execution canceled"); err != nil {
			return "", err
		}
		return DurableCallbackApplied, nil
	}
	if status == "failed" || callback.Response == nil {
		category := strings.TrimSpace(callback.ErrorCategory)
		if category == "" {
			category = "runtime_execution_failed"
		}
		if err := s.repo.FailRuntimeJob(ctx, jobID, category); err != nil {
			return "", err
		}
		return DurableCallbackApplied, nil
	}

	task, err := s.taskService.tasks.TaskByID(ctx, job.UserID, job.TaskID)
	if err != nil {
		_ = s.repo.FailRuntimeJob(ctx, jobID, "task persistence unavailable")
		return "", err
	}
	if task == nil {
		_ = s.repo.FailRuntimeJob(ctx, jobID, "task missing")
		return "", ErrNotFound
	}
	response := callback.Response
	runtimeStatus := normalizeRuntimeStatus(response.Status)

	// A crash can happen after the authoritative task/history transaction commits
	// but before runtime_jobs moves from COMPLETING to COMPLETED. On replay, finish
	// only the runtime-job marker instead of trying to write the user result twice.
	if resuming {
		alreadyFinalized := runtimeStatus == "COMPLETED" && task.Status == "COMPLETED"
		alreadySuspended := (runtimeStatus == "INPUT_REQUIRED" || runtimeStatus == "AUTH_REQUIRED") && task.Status == runtimeStatus
		if alreadyFinalized || alreadySuspended {
			if err := s.repo.MarkRuntimeJobCompleted(ctx, jobID); err != nil {
				return "", err
			}
			return DurableCallbackRecovered, nil
		}
	}

	response.Trace = append([]map[string]any{durableReliabilityTrace(
		job, callback.WorkerID, callback.DispatcherEpoch, "completed",
	)}, response.Trace...)

	var projectID *int64
	if s.taskService.projectRuntime != nil && task.ConversationID != nil {
		if projectCtx, resolveErr := s.taskService.projectRuntime.ResolveForConversation(ctx, job.UserID, *task.ConversationID); resolveErr == nil && projectCtx != nil {
			id := projectCtx.ProjectID
			projectID = &id
			if s.taskService.governance != nil {
				s.taskService.governance.RecordUsage(ctx, projectCtx.ProjectID, int64(response.Observability.ModelTotalTokens), response.EstimatedCost, int64(response.Observability.ToolCalls))
			}
		}
	}
	s.taskService.recordRunCost(ctx, job.UserID, job.TaskID, projectID, response.Observability, response.EstimatedCost)

	if runtimeStatus == "INPUT_REQUIRED" || runtimeStatus == "AUTH_REQUIRED" {
		if response.Continuation == nil {
			_ = s.repo.FailRuntimeJob(ctx, jobID, "runtime suspended without continuation")
			return "", errors.New("runtime suspended without continuation")
		}
		continuation := runtimeContinuationToModel(response.Continuation)
		var assistantMessage *repository.AssistantMessageWrite
		if task.ConversationID != nil {
			assistantMessage = &repository.AssistantMessageWrite{
				UserID: job.UserID, ConversationID: conversationIDValue(task.ConversationID), Content: response.Answer, Status: runtimeStatus, RequestID: task.RequestID,
				Metadata: map[string]any{
					"taskId": job.TaskID, "runtimePhase": "durable_suspended", "deliveryMode": "durable",
					"trace": response.Trace, "dag": response.DAG, "selectedAgents": response.SelectedAgents,
					"taskProfile": response.TaskProfile, "observability": response.Observability,
					"scorecard": response.Scorecard, "agentFeedback": response.AgentFeedback,
					"citations": normalizeRuntimeCitations(response.Citations),
				},
			}
		}
		if err := s.taskService.suspendTaskWithAssistant(ctx, repository.TaskSuspensionWrite{
			UserID: job.UserID, TaskID: job.TaskID, ConversationID: conversationIDValue(task.ConversationID), Status: runtimeStatus, Result: response.Answer, Continuation: continuation,
			Selected: response.SelectedAgents, Trace: response.Trace, DAG: response.DAG,
			LatencyMS: response.ElapsedMS, EstimatedCost: response.EstimatedCost,
		}, assistantMessage); err != nil {
			_ = s.repo.FailRuntimeJob(ctx, jobID, "failed to persist runtime suspension and assistant history")
			return "", err
		}
		if err := s.repo.MarkRuntimeJobCompleted(ctx, jobID); err != nil {
			return "", err
		}
		return DurableCallbackApplied, nil
	}

	if runtimeStatus != "COMPLETED" {
		if err := s.repo.FailRuntimeJob(ctx, jobID, "unsupported runtime status"); err != nil {
			return "", err
		}
		return DurableCallbackApplied, nil
	}
	var assistantMessage *repository.AssistantMessageWrite
	if task.ConversationID != nil {
		assistantMessage = &repository.AssistantMessageWrite{
			UserID: job.UserID, ConversationID: conversationIDValue(task.ConversationID), Content: response.Answer, Status: "COMPLETED", RequestID: task.RequestID,
			Metadata: map[string]any{
				"taskId": task.ID, "runtimePhase": "durable_completed", "deliveryMode": "durable",
				"trace": response.Trace, "dag": response.DAG, "selectedAgents": response.SelectedAgents,
				"taskProfile": response.TaskProfile, "scheduler": task.Scheduler, "planner": task.Planner,
				"executionMode": task.ExecutionMode, "synthesisMode": task.SynthesisMode,
				"observability": response.Observability, "scorecard": response.Scorecard,
				"agentFeedback": response.AgentFeedback, "citations": normalizeRuntimeCitations(response.Citations),
			},
		}
	}
	if err := s.taskService.completeTaskWithAssistant(ctx, repository.TaskCompletionWrite{
		UserID: job.UserID, TaskID: job.TaskID, ConversationID: conversationIDValue(task.ConversationID), Result: response.Answer, Selected: response.SelectedAgents,
		Trace: response.Trace, DAG: response.DAG, LatencyMS: response.ElapsedMS, EstimatedCost: response.EstimatedCost,
	}, assistantMessage); err != nil {
		_ = s.repo.FailRuntimeJob(ctx, jobID, "failed to persist runtime completion and assistant history")
		return "", err
	}
	if err := s.taskService.agents.RecordAgentFeedback(ctx, job.UserID, task.RequestID, response.AgentFeedback); err != nil {
		// Evaluation feedback persistence is important but cannot turn an already
		// completed user task into an execution replay.
		log.Printf("durable-runtime agent feedback persistence failed: %v", err)
	}
	if err := s.repo.MarkRuntimeJobCompleted(ctx, jobID); err != nil {
		return "", err
	}
	return DurableCallbackApplied, nil
}

func durableReliabilityTrace(job *model.RuntimeJob, workerID string, dispatcherEpoch int64, status string) map[string]any {
	detail := map[string]any{
		"deliveryMode":      "durable",
		"jobId":             job.ID,
		"executionId":       job.ExecutionID,
		"workerId":          workerID,
		"fenceEpoch":        job.FenceEpoch,
		"dispatcherEpoch":   dispatcherEpoch,
		"attempt":           job.AttemptCount,
		"maxAttempts":       job.MaxAttempts,
		"failoverRetrySafe": job.FailoverRetrySafe,
		"dispatchStatus":    status,
	}
	if job.NodeID != nil {
		detail["nodeId"] = *job.NodeID
	}
	encoded, _ := json.Marshal(detail)
	return map[string]any{
		"kind": "reliability", "title": "Durable Runtime Dispatch", "status": "completed",
		"detail": string(encoded), "elapsedMs": 0,
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
	snapshot, err := s.repo.RuntimeReliabilitySnapshot(ctx, time.Now().UTC().Add(-s.cfg.WorkerStaleAfter))
	if err != nil {
		return nil, err
	}
	if lease, leaseErr := s.repo.RuntimeDispatcherLease(ctx); leaseErr == nil && lease != nil {
		snapshot.DispatcherLeader = lease.HolderID == s.cfg.DispatcherID && lease.LeaseUntil.After(time.Now().UTC())
	}
	return snapshot, nil
}

func (s *DurableRuntimeService) Topology(ctx context.Context) (*model.RuntimeTopologySnapshot, error) {
	if !s.cfg.Enabled {
		return &model.RuntimeTopologySnapshot{
			Reliability: model.RuntimeReliabilitySnapshot{Enabled: false},
			Nodes:       []model.RuntimeNode{}, Workers: []model.RuntimeWorker{},
		}, nil
	}
	topology, err := s.repo.RuntimeTopologySnapshot(ctx, time.Now().UTC().Add(-s.cfg.WorkerStaleAfter))
	if err != nil {
		return nil, err
	}
	if lease, leaseErr := s.repo.RuntimeDispatcherLease(ctx); leaseErr == nil && lease != nil {
		topology.Reliability.DispatcherLeader = lease.HolderID == s.cfg.DispatcherID && lease.LeaseUntil.After(time.Now().UTC())
	}
	return topology, nil
}

// TaskEvents reads an owner-scoped, metadata-only durable state journal. The
// repository validates ownership on every poll, including after reconnect.
func (s *DurableRuntimeService) TaskEvents(ctx context.Context, uid, taskID, after int64) ([]model.DurableTaskEvent, string, error) {
	reader, ok := s.repo.(interface {
		SyncAndListDurableTaskEvents(context.Context, int64, int64, int64, int) ([]model.DurableTaskEvent, string, error)
	})
	if !ok {
		return nil, "", errors.New("durable event storage unavailable")
	}
	events, status, err := reader.SyncAndListDurableTaskEvents(ctx, uid, taskID, after, 100)
	if errors.Is(err, repository.ErrNotOwned) {
		return nil, "", ErrNotFound
	}
	return events, status, err
}
