package service

import (
	"context"
	"errors"
	"strings"

	"github.com/google/uuid"

	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/repository"
)

const clarificationTaskKind = "clarification"

// PersistRoutingClarification records the user turn and the clarification prompt as
// one idempotent, suspended logical task. It creates no Runtime job and invokes
// no Tool/Agent/Knowledge capability.
func (s *TaskService) PersistRoutingClarification(
	ctx context.Context,
	uid int64,
	in RunTaskInput,
	decision *ExecutionRouteDecision,
) (*RunTaskResult, error) {
	if decision == nil || decision.RuntimePath != "NONE" || len(decision.UnresolvedRequirements) == 0 {
		return nil, ErrInvalidInput
	}
	// Trim exactly as the existing direct entry points do, then fingerprint
	// the original client request before filling execution defaults.
	in.Task = strings.TrimSpace(in.Task)
	clientKey, fingerprint, err := directRequestIdentity(in)
	if err != nil {
		return nil, err
	}
	if replay, replayErr := s.findDirectReplay(ctx, uid, clientKey, fingerprint); replayErr != nil || replay != nil {
		return replay, replayErr
	}
	in.Task = strings.TrimSpace(in.Task)
	if in.Task == "" {
		return nil, ErrInvalidInput
	}
	if in.Scheduler == "" {
		in.Scheduler = "adaptive"
	}
	if in.Planner == "" {
		in.Planner = "multi_objective"
	}
	if in.ExecutionMode == "" {
		in.ExecutionMode = "auto"
	}
	if in.SynthesisMode == "" {
		in.SynthesisMode = "auto"
	}
	var project *model.ProjectRuntimeContext
	if s.projectRuntime != nil && in.ConversationID != nil {
		project, err = s.resolveProjectRuntimeForRouting(ctx, uid, *in.ConversationID)
		if err != nil {
			return nil, err
		}
		applyProjectRuntimePolicy(&in, project)
	}
	normalizedRag, effectiveRag, _, err := s.resolveEffectiveRagPolicy(ctx, uid, in.ConversationID, in.RagPolicy)
	if err != nil {
		return nil, err
	}
	in.RagPolicy = normalizedRag
	in.ExecutionRoute = decision.Strategy
	in.RoutingReasonCodes = append([]string(nil), decision.ReasonCodes...)
	in.RoutingAnalysisSource = decision.AnalysisSource
	in.RoutingAnalysisLatencyMS = decision.AnalysisLatencyMS
	in.RoutingModelCalls = decision.PreflightModelCalls
	in.RoutingModelTokens = decision.PreflightModelTokens
	in.RoutingModelEstimatedCost = decision.PreflightModelEstimatedCost
	in.RoutingModelCostKnown = decision.PreflightModelCostKnown
	requestID := uuid.NewString()
	task, replayed, err := s.insertDirectTask(ctx, model.Task{
		UserID: uid, ConversationID: in.ConversationID, RequestID: requestID, TaskText: in.Task,
		Scheduler: in.Scheduler, Planner: in.Planner, ExecutionMode: in.ExecutionMode, SynthesisMode: in.SynthesisMode,
		ModelSelection: in.ModelSelection, RagPolicy: in.RagPolicy, EffectiveRagPolicy: effectiveRag,
		ClientRequestID: clientKey, RequestFingerprint: fingerprint,
		PendingUserMessageMetadata: executionRoutingMetadata(in, map[string]any{
			"runtimePhase": "clarification", "status": "INPUT_REQUIRED",
		}),
	}, in.Constraints)
	if err != nil {
		return nil, err
	}
	if replayed {
		return replayDirectTask(task), nil
	}
	message := decision.UnresolvedRequirements[0]
	continuation := &model.TaskContinuation{
		Protocol: clarificationTaskKind, AgentID: 0, Capability: "clarification",
		TaskID: "clarification", ContextID: executionRoutingVersion,
		State: "INPUT_REQUIRED", Kind: clarificationTaskKind, Summary: message,
	}
	var assistant *repository.AssistantMessageWrite
	if in.ConversationID != nil {
		assistant = &repository.AssistantMessageWrite{
			UserID: uid, ConversationID: *in.ConversationID, Content: message,
			Status: "INPUT_REQUIRED", RequestID: requestID,
			Metadata: map[string]any{
				"taskId": task.ID, "runtimePhase": "clarification",
				"status": "INPUT_REQUIRED", "routingClarification": true,
			},
		}
	}
	trace := executionRoutingTrace(in, "direct")
	if err = s.suspendTaskWithAssistant(ctx, repository.TaskSuspensionWrite{
		UserID: uid, TaskID: task.ID, ConversationID: conversationIDValue(in.ConversationID),
		Status: "INPUT_REQUIRED", Result: message, Continuation: continuation,
		Selected: []string{}, Trace: trace, DAG: map[string]any{}, LatencyMS: 0, EstimatedCost: 0,
	}, assistant); err != nil {
		_ = s.tasks.FailTask(ctx, uid, task.ID, "failed to persist clarification state", 0)
		if errors.Is(err, repository.ErrInvalidTaskState) {
			return nil, ErrConflict
		}
		return nil, err
	}
	fresh, err := s.tasks.TaskByID(ctx, uid, task.ID)
	if err != nil {
		return nil, err
	}
	return replayDirectTask(fresh), nil
}

// ResolveRoutingClarification marks a consumed clarification wait as completed. It
// has no external side effects; failure leaves a harmless stale wait that the
// continuation resolver ignores once a newer execution exists.
func (s *TaskService) ResolveRoutingClarification(ctx context.Context, uid, taskID int64) error {
	if taskID <= 0 {
		return nil
	}
	task, err := s.tasks.TaskByID(ctx, uid, taskID)
	if err != nil || task == nil {
		return err
	}
	if task.Status != "INPUT_REQUIRED" || task.Continuation == nil || task.Continuation.Kind != clarificationTaskKind {
		return nil
	}
	started, err := s.tasks.BeginTaskResume(ctx, uid, task.ID)
	if err != nil || !started {
		return err
	}
	return s.tasks.CompleteTask(ctx, uid, task.ID, "clarification resolved", task.SelectedAgents, task.Trace, task.DAG, 0, 0)
}

// Supersede prior clarification waits only AFTER a newer task was durably
// accepted or finished. Failure to clean up must never retry business work.
// Only older, same-conversation, user-owned clarification tasks are touched.
func (s *TaskService) SupersedeRoutingClarifications(ctx context.Context, uid int64, completed *model.Task) error {
	if completed == nil || completed.ConversationID == nil || s.tasks == nil {
		return nil
	}
	items, err := s.tasks.ListTasks(ctx, uid, 50)
	if err != nil {
		return err
	}
	for _, item := range items {
		if item.ID >= completed.ID || item.ConversationID == nil ||
			*item.ConversationID != *completed.ConversationID || item.Status != "INPUT_REQUIRED" ||
			item.Continuation == nil || item.Continuation.Kind != clarificationTaskKind {
			continue
		}
		if err := s.ResolveRoutingClarification(ctx, uid, item.ID); err != nil {
			return err
		}
	}
	return nil
}
