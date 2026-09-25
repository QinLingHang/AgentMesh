package service

import (
	"context"
	"errors"
	"testing"
	"time"

	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/repository"
	runtimeclient "example.com/agentmesh-control-plane/internal/runtime"
)

// Requires the project's existing MySQL integration test environment.
// Duplicate requests must not insert a second task, runtime job or user message.
func TestKnowledgeRuntimeDurableSubmissionIdempotency(t *testing.T) {
	database, _ := p2Database(t)
	repo := repository.NewMySQL(database)
	ctx := context.Background()
	createdUser, err := database.ExecContext(ctx, `INSERT INTO users(email,password_hash,display_name) VALUES('knowledge-runtime-idempotency@example.test','fixture','Knowledge Runtime')`)
	if err != nil {
		t.Fatal(err)
	}
	uid, err := createdUser.LastInsertId()
	if err != nil {
		t.Fatal(err)
	}
	runtime := runtimeclient.NewClient("http://127.0.0.1:1", "internal-test-token", time.Second)
	taskService := NewTaskService(repo, repo, repo, runtime, repo, repo)
	s := NewDurableRuntimeService(repo, taskService, runtime, DurableRuntimeConfig{
		Enabled: true, MaxQueueDepth: 5, JobDeadline: time.Minute, MaxAttempts: 3,
	})
	created, err := database.ExecContext(ctx, `INSERT INTO conversations(user_id, title) VALUES (?, 'idempotency')`, uid)
	if err != nil {
		t.Fatal(err)
	}
	conversationID, err := created.LastInsertId()
	if err != nil {
		t.Fatal(err)
	}

	key := "knowledge-runtime-same-request-000001"
	input := RunTaskInput{
		ClientRequestID: key, ConversationID: &conversationID,
		Task: "idempotent durable task", Scheduler: "adaptive", Planner: "multi_objective",
		ExecutionMode: "auto", SynthesisMode: "auto",
		Constraints: model.TaskConstraints{MaxLatencyMS: 8000, MaxCost: 0.15, MinQuality: 0.8},
	}
	first, err := s.Run(ctx, uid, input)
	if err != nil {
		t.Fatal(err)
	}
	// Replays must succeed even when the first submission itself fills the queue.
	s.cfg.MaxQueueDepth = 1
	replay, err := s.Run(ctx, uid, input)
	if err != nil {
		t.Fatal(err)
	}
	if first.Task.ID != replay.Task.ID || first.Task.RequestID != replay.Task.RequestID {
		t.Fatalf("replay created a new task: first=%d replay=%d", first.Task.ID, replay.Task.ID)
	}

	var count int
	if err := database.QueryRowContext(ctx, `SELECT COUNT(*) FROM runtime_jobs WHERE task_id = ?`, first.Task.ID).Scan(&count); err != nil {
		t.Fatal(err)
	}
	if count != 1 {
		t.Fatalf("runtime jobs = %d, want 1", count)
	}
	if err := database.QueryRowContext(ctx, `SELECT COUNT(*) FROM messages WHERE conversation_id = ? AND role = 'user' AND request_id = ?`, conversationID, first.Task.RequestID).Scan(&count); err != nil {
		t.Fatal(err)
	}
	if count != 1 {
		t.Fatalf("user messages = %d, want 1", count)
	}

	input.Task = "same key different work"
	if _, err := s.Run(ctx, uid, input); !errors.Is(err, ErrIdempotencyConflict) {
		t.Fatalf("changed payload must conflict, got %v", err)
	}
}
