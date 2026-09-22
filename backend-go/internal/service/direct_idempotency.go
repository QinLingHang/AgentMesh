package service

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"strings"

	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/repository"
	runtimeclient "example.com/agentmesh-control-plane/internal/runtime"
)

// Keep a request's identity stable across model selection, policy resolution
// and Go/Python processing. A request key identifies one exact user action.
func directRequestIdentity(in RunTaskInput) (string, string, error) {
	key := strings.TrimSpace(in.ClientRequestID)
	if !validClientRequestID(key) {
		return "", "", ErrInvalidInput
	}
	if key == "" {
		return "", "", nil
	}
	in.ClientRequestID = ""
	raw, err := json.Marshal(in)
	if err != nil {
		return "", "", err
	}
	digest := sha256.Sum256(raw)
	return key, hex.EncodeToString(digest[:]), nil
}

func replayDirectTask(task *model.Task) *RunTaskResult {
	answer := "该请求已经被接收，正在执行；请通过任务列表查询原任务状态。"
	if task.ResultText != nil {
		answer = *task.ResultText
	}
	if task.Status == "ERROR" && task.ErrorMessage != nil {
		answer = *task.ErrorMessage
	}
	elapsed := int64(0)
	if task.LatencyMS != nil {
		elapsed = *task.LatencyMS
	}
	cost := float64(0)
	if task.EstimatedCost != nil {
		cost = *task.EstimatedCost
	}
	return &RunTaskResult{Task: task, Status: task.Status, Answer: answer,
		Citations: []runtimeclient.RuntimeCitation{}, Scheduler: task.Scheduler, Planner: task.Planner,
		ExecutionMode: task.ExecutionMode, SynthesisMode: task.SynthesisMode,
		TaskProfile: map[string]any{"idempotentReplay": true}, SelectedAgents: task.SelectedAgents,
		EstimatedCost: cost, ElapsedMS: elapsed, Trace: task.Trace, DAG: task.DAG,
		AgentFeedback: []model.AgentFeedback{}, Observability: runtimeclient.ObservabilitySummary{}}
}

// Replays completed/pending requests without creating messages, tasks or tool
// side effects. The SQL ledger is shared with Durable and scoped per user.
func (s *TaskService) findDirectReplay(ctx context.Context, uid int64, key, fingerprint string) (*RunTaskResult, error) {
	if key == "" {
		return nil, nil
	}
	store, ok := s.tasks.(repository.DirectSubmissionRepository)
	if !ok {
		return nil, errors.New("direct idempotency repository is unavailable")
	}
	task, existingFingerprint, err := store.LookupDurableSubmission(ctx, uid, key)
	if errors.Is(err, repository.ErrSubmissionConflict) {
		return nil, ErrIdempotencyConflict
	}
	if err != nil {
		return nil, err
	}
	if task == nil {
		return nil, nil
	}
	if existingFingerprint != fingerprint || task.DeliveryMode != "direct" {
		return nil, ErrIdempotencyConflict
	}
	// A matching idempotency key proves this is the same submission, NOT that
	// historical project/conversation access remains granted. Revalidate the
	// current project binding before replaying a stored private answer.
	if s.projectRuntime != nil && task.ConversationID != nil {
		if _, err := s.projectRuntime.ResolveForConversation(ctx, uid, *task.ConversationID); err != nil {
			return nil, err
		}
	}
	return replayDirectTask(task), nil
}

func (s *TaskService) insertDirectTask(ctx context.Context, task model.Task, constraints model.TaskConstraints) (*model.Task, bool, error) {
	if task.ClientRequestID == "" { // Legacy API keeps its historical contract.
		if task.ConversationID != nil {
			_, err := s.messages.CreateMessage(ctx, task.UserID, *task.ConversationID, "user", task.TaskText, "COMPLETED", task.RequestID, task.PendingUserMessageMetadata)
			if errors.Is(err, repository.ErrNotOwned) {
				return nil, false, ErrNotFound
			}
			if err != nil {
				return nil, false, err
			}
		}
		created, err := s.tasks.CreateTask(ctx, task, constraints)
		return created, false, err
	}
	store, ok := s.tasks.(repository.DirectSubmissionRepository)
	if !ok {
		return nil, false, errors.New("direct idempotency repository is unavailable")
	}
	created, replayed, err := store.CreateDirectSubmission(ctx, task, constraints)
	if errors.Is(err, repository.ErrSubmissionConflict) {
		return nil, false, ErrIdempotencyConflict
	}
	if errors.Is(err, repository.ErrNotOwned) {
		return nil, false, ErrNotFound
	}
	return created, replayed, err
}
