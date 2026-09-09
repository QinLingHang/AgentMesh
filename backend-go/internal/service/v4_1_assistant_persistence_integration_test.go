package service

import (
	"context"
	"database/sql"
	"fmt"
	"math"
	"testing"
	"time"

	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/repository"
)

type v41PersistenceFixture struct {
	database       *sql.DB
	repo           *repository.MySQL
	uid            int64
	conversationID int64
	task           *model.Task
}

func newV41PersistenceFixture(t *testing.T) v41PersistenceFixture {
	t.Helper()
	database, _ := p2Database(t)
	repo := repository.NewMySQL(database)
	ctx := context.Background()

	stamp := time.Now().UnixNano()
	userResult, err := database.Exec(
		"INSERT INTO users(email,password_hash,display_name) VALUES(?,?,?)",
		fmt.Sprintf("v41-persistence-%d@example.test", stamp),
		"fixture",
		"V4.1 Persistence",
	)
	if err != nil {
		t.Fatal(err)
	}
	uid, err := userResult.LastInsertId()
	if err != nil {
		t.Fatal(err)
	}

	conversationResult, err := database.Exec(
		"INSERT INTO conversations(user_id,title) VALUES(?,'V4.1 persistence')",
		uid,
	)
	if err != nil {
		t.Fatal(err)
	}
	conversationID, err := conversationResult.LastInsertId()
	if err != nil {
		t.Fatal(err)
	}

	task, err := repo.CreateTask(ctx, model.Task{
		UserID:         uid,
		ConversationID: &conversationID,
		RequestID:      fmt.Sprintf("v41-persistence-%d", stamp),
		TaskText:       "verify atomic assistant persistence",
		Scheduler:      "adaptive",
		Planner:        "multi_objective",
		ExecutionMode:  "auto",
		SynthesisMode:  "auto",
	}, model.TaskConstraints{MaxLatencyMS: 5000, MaxCost: 0.2, MinQuality: 0.5})
	if err != nil {
		t.Fatal(err)
	}

	return v41PersistenceFixture{
		database:       database,
		repo:           repo,
		uid:            uid,
		conversationID: conversationID,
		task:           task,
	}
}

func v41CompletionWrite(f v41PersistenceFixture, answer string) repository.TaskCompletionWrite {
	return repository.TaskCompletionWrite{
		UserID:         f.uid,
		TaskID:         f.task.ID,
		ConversationID: f.conversationID,
		Result:         answer,
		Selected:       []string{"GeneralAgent"},
		Trace:          []map[string]any{{"kind": "model", "status": "completed"}},
		DAG:            map[string]any{"nodes": []any{}, "edges": []any{}},
		LatencyMS:      12,
		EstimatedCost:  0.01,
	}
}

func v41AssistantWrite(f v41PersistenceFixture, answer string) repository.AssistantMessageWrite {
	return repository.AssistantMessageWrite{
		UserID:         f.uid,
		ConversationID: f.conversationID,
		Content:        answer,
		Status:         "COMPLETED",
		RequestID:      f.task.RequestID,
		Metadata:       map[string]any{"taskId": f.task.ID, "runtimePhase": "v4_1_atomic_test"},
	}
}

func TestV41CompleteTaskAndAssistantHistoryCommitAtomically(t *testing.T) {
	f := newV41PersistenceFixture(t)
	ctx := context.Background()
	answer := "V41_ATOMIC_ASSISTANT"

	message, err := f.repo.CompleteTaskWithAssistantMessage(ctx, v41CompletionWrite(f, answer), v41AssistantWrite(f, answer))
	if err != nil {
		t.Fatal(err)
	}
	if message == nil || message.Role != "assistant" || message.Content != answer {
		t.Fatalf("unexpected assistant message: %+v", message)
	}

	refreshed, err := f.repo.TaskByID(ctx, f.uid, f.task.ID)
	if err != nil {
		t.Fatal(err)
	}
	if refreshed == nil || refreshed.Status != "COMPLETED" || refreshed.ResultText == nil || *refreshed.ResultText != answer {
		t.Fatalf("task not atomically completed: %+v", refreshed)
	}

	messages, err := f.repo.ListMessages(ctx, f.uid, f.conversationID, 20)
	if err != nil {
		t.Fatal(err)
	}
	found := false
	for _, item := range messages {
		if item.Role == "assistant" && item.RequestID != nil && *item.RequestID == f.task.RequestID && item.Content == answer {
			found = true
		}
	}
	if !found {
		t.Fatalf("authoritative assistant history missing: %+v", messages)
	}
}

func TestV41SuspendTaskAndAssistantHistoryCommitAtomically(t *testing.T) {
	f := newV41PersistenceFixture(t)
	ctx := context.Background()
	answer := "V41_ATOMIC_SUSPENSION"
	continuation := &model.TaskContinuation{
		Protocol: "internal", AgentID: 1, Capability: "general",
		TaskID: "v41-suspend-task", ContextID: "v41-suspend-context",
		State: "INPUT_REQUIRED", Kind: "agent",
	}

	message, err := f.repo.SuspendTaskWithAssistantMessage(ctx, repository.TaskSuspensionWrite{
		UserID: f.uid, TaskID: f.task.ID, ConversationID: f.conversationID,
		Status: "INPUT_REQUIRED", Result: answer, Continuation: continuation,
		Selected:  []string{"GeneralAgent"},
		Trace:     []map[string]any{{"kind": "agent", "status": "input_required"}},
		DAG:       map[string]any{"nodes": []any{}, "edges": []any{}},
		LatencyMS: 9, EstimatedCost: 0.01,
	}, repository.AssistantMessageWrite{
		UserID: f.uid, ConversationID: f.conversationID, Content: answer,
		Status: "INPUT_REQUIRED", RequestID: f.task.RequestID,
		Metadata: map[string]any{"taskId": f.task.ID, "runtimePhase": "v4_1_atomic_suspend_test"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if message == nil || message.Role != "assistant" || message.Status != "INPUT_REQUIRED" || message.Content != answer {
		t.Fatalf("unexpected suspended assistant message: %+v", message)
	}

	refreshed, err := f.repo.TaskByID(ctx, f.uid, f.task.ID)
	if err != nil {
		t.Fatal(err)
	}
	if refreshed == nil || refreshed.Status != "INPUT_REQUIRED" || refreshed.Continuation == nil {
		t.Fatalf("task not atomically suspended: %+v", refreshed)
	}

	messages, err := f.repo.ListMessages(ctx, f.uid, f.conversationID, 20)
	if err != nil {
		t.Fatal(err)
	}
	found := false
	for _, item := range messages {
		if item.Role == "assistant" && item.Status == "INPUT_REQUIRED" && item.Content == answer {
			found = true
		}
	}
	if !found {
		t.Fatalf("authoritative suspended assistant history missing: %+v", messages)
	}
}

func TestV41CompleteTaskRollsBackWhenAssistantHistoryCannotPersist(t *testing.T) {
	f := newV41PersistenceFixture(t)
	ctx := context.Background()

	// json.Marshal rejects NaN. The task UPDATE occurs first inside the same
	// transaction; metadata encoding then fails while preparing the assistant
	// insert. The transaction must roll the task back to RUNNING.
	badMessage := v41AssistantWrite(f, "MUST_NOT_COMMIT")
	badMessage.Metadata["invalidNumber"] = math.NaN()

	_, err := f.repo.CompleteTaskWithAssistantMessage(ctx, v41CompletionWrite(f, "MUST_ROLL_BACK"), badMessage)
	if err == nil {
		t.Fatal("expected assistant persistence failure")
	}

	refreshed, loadErr := f.repo.TaskByID(ctx, f.uid, f.task.ID)
	if loadErr != nil {
		t.Fatal(loadErr)
	}
	if refreshed == nil || refreshed.Status != "RUNNING" || refreshed.ResultText != nil {
		t.Fatalf("task transition leaked across rollback: %+v", refreshed)
	}

	messages, listErr := f.repo.ListMessages(ctx, f.uid, f.conversationID, 20)
	if listErr != nil {
		t.Fatal(listErr)
	}
	for _, item := range messages {
		if item.Role == "assistant" {
			t.Fatalf("assistant row leaked across rollback: %+v", item)
		}
	}
}

func TestV41TaskFinalizationSurvivesCanceledRequestContext(t *testing.T) {
	f := newV41PersistenceFixture(t)
	service := NewTaskService(f.repo, f.repo, f.repo, nil, f.repo, f.repo)

	requestCtx, cancel := context.WithCancel(context.Background())
	cancel()
	answer := "V41_DETACHED_FINALIZATION"

	if err := service.completeTaskWithAssistant(requestCtx, v41CompletionWrite(f, answer), func() *repository.AssistantMessageWrite {
		write := v41AssistantWrite(f, answer)
		return &write
	}()); err != nil {
		t.Fatalf("finalization must survive request cancellation after runtime completion: %v", err)
	}

	messages, err := f.repo.ListMessages(context.Background(), f.uid, f.conversationID, 20)
	if err != nil {
		t.Fatal(err)
	}
	found := false
	for _, item := range messages {
		if item.Role == "assistant" && item.Content == answer {
			found = true
		}
	}
	if !found {
		t.Fatalf("assistant history missing after detached finalization: %+v", messages)
	}
}
