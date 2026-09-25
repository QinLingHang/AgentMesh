package service

import (
	"context"
	"errors"
	"sync"
	"testing"

	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/repository"
)

// Integration test uses p2Database's isolated database; it never touches
// the user's active development, production or coworker's schema.
func TestKnowledgeRuntimeDirectConcurrentSubmissionCreatesOneTaskAndMessage(t *testing.T) {
	database, _ := p2Database(t)
	repo := repository.NewMySQL(database)
	ctx := context.Background()
	res, err := database.ExecContext(ctx, `INSERT INTO users(email,password_hash,display_name) VALUES('knowledge-runtime-direct@example.test','fixture','Direct')`)
	if err != nil {
		t.Fatal(err)
	}
	uid, err := res.LastInsertId()
	if err != nil {
		t.Fatal(err)
	}
	res, err = database.ExecContext(ctx, `INSERT INTO conversations(user_id,title) VALUES(?,'Direct retry')`, uid)
	if err != nil {
		t.Fatal(err)
	}
	conversationID, err := res.LastInsertId()
	if err != nil {
		t.Fatal(err)
	}
	input := RunTaskInput{ClientRequestID: "knowledge-runtime-direct-concurrent-123", ConversationID: &conversationID,
		Task: "检查订单状态", Scheduler: "adaptive", Planner: "multi_objective", ExecutionMode: "auto", SynthesisMode: "auto"}
	key, fingerprint, err := directRequestIdentity(input)
	if err != nil {
		t.Fatal(err)
	}
	create := func() (*model.Task, bool, error) {
		return repo.CreateDirectSubmission(ctx, model.Task{
			UserID: uid, ConversationID: &conversationID, RequestID: "direct-test-req",
			TaskText: input.Task, Scheduler: input.Scheduler, Planner: input.Planner,
			ExecutionMode: input.ExecutionMode, SynthesisMode: input.SynthesisMode,
			ClientRequestID: key, RequestFingerprint: fingerprint,
			PendingUserMessageMetadata: map[string]any{"runtimePhase": "initial"},
		}, model.TaskConstraints{})
	}
	const workers = 5
	type outcome struct {
		task   *model.Task
		replay bool
		err    error
	}
	results := make([]outcome, workers)
	var wg sync.WaitGroup
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func(index int) {
			defer wg.Done()
			results[index].task, results[index].replay, results[index].err = create()
		}(i)
	}
	wg.Wait()
	var originalID int64
	creations := 0
	for i, result := range results {
		if result.err != nil || result.task == nil {
			t.Fatalf("worker %d failed: %v", i, result.err)
		}
		if originalID == 0 {
			originalID = result.task.ID
		}
		if result.task.ID != originalID {
			t.Fatalf("duplicate created different task IDs %d / %d", originalID, result.task.ID)
		}
		if !result.replay {
			creations++
		}
	}
	if creations != 1 {
		t.Fatalf("number of original creations=%d, want 1", creations)
	}
	var tasks, messages, ledger int
	if err = database.QueryRowContext(ctx, `SELECT COUNT(*) FROM tasks WHERE user_id=?`, uid).Scan(&tasks); err != nil {
		t.Fatal(err)
	}
	if err = database.QueryRowContext(ctx, `SELECT COUNT(*) FROM messages WHERE conversation_id=? AND role='user'`, conversationID).Scan(&messages); err != nil {
		t.Fatal(err)
	}
	if err = database.QueryRowContext(ctx, `SELECT COUNT(*) FROM task_submission_keys WHERE user_id=?`, uid).Scan(&ledger); err != nil {
		t.Fatal(err)
	}
	if tasks != 1 || messages != 1 || ledger != 1 {
		t.Fatalf("duplicate state tasks=%d messages=%d ledger=%d", tasks, messages, ledger)
	}

	// A task request_id collision is NOT proof that a different client key
	// belongs to the original request. It must never replay another key or
	// expose the raw MySQL duplicate-key error to the API consumer.
	_, _, err = repo.CreateDirectSubmission(ctx, model.Task{
		UserID: uid, ConversationID: &conversationID, RequestID: "direct-test-req",
		TaskText: input.Task, ClientRequestID: "another-direct-key-123",
		RequestFingerprint: fingerprint,
	}, model.TaskConstraints{})
	if !errors.Is(err, repository.ErrSubmissionConflict) {
		t.Fatalf("different key with same request ID must fail closed: %v", err)
	}
	if err = database.QueryRowContext(ctx, `SELECT COUNT(*) FROM tasks WHERE user_id=?`, uid).Scan(&tasks); err != nil {
		t.Fatal(err)
	}
	if err = database.QueryRowContext(ctx, `SELECT COUNT(*) FROM task_submission_keys WHERE user_id=?`, uid).Scan(&ledger); err != nil {
		t.Fatal(err)
	}
	if tasks != 1 || ledger != 1 {
		t.Fatalf("request ID conflict changed durable state tasks=%d ledger=%d", tasks, ledger)
	}

	// A retry can carry a freshly generated server request ID while retaining
	// the client's idempotency key. This must exercise the ledger's unique key
	// (rather than tasks.uk_task_request), and still replay the first task.
	ledgerReplay, replayed, err := repo.CreateDirectSubmission(ctx, model.Task{
		UserID: uid, ConversationID: &conversationID, RequestID: "new-server-request-id",
		TaskText: input.Task, ClientRequestID: key, RequestFingerprint: fingerprint,
	}, model.TaskConstraints{})
	if err != nil || !replayed || ledgerReplay == nil || ledgerReplay.ID != originalID {
		t.Fatalf("ledger collision did not replay original: task=%+v replay=%t err=%v", ledgerReplay, replayed, err)
	}

	// Same key + changed payload must fail closed, without a second task.
	wrong := input
	wrong.Task = "删除订单"
	_, otherFingerprint, err := directRequestIdentity(wrong)
	if err != nil {
		t.Fatal(err)
	}
	_, _, err = repo.CreateDirectSubmission(ctx, model.Task{
		UserID: uid, ConversationID: &conversationID, RequestID: "changed-req", TaskText: wrong.Task,
		ClientRequestID: key, RequestFingerprint: otherFingerprint,
	}, model.TaskConstraints{})
	if !errors.Is(err, repository.ErrSubmissionConflict) {
		t.Fatalf("changed payload conflict=%v", err)
	}
}
