package service

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"testing"
	"time"

	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/repository"
)

// p2Database creates/drops a randomly named isolated schema; no development
// database or Redis instance is ever reset by this test.
func TestP22DurableConcurrentSubmissionCreatesOneTaskJobAndMessage(t *testing.T) {
	database, _ := p2Database(t)
	repo := repository.NewMySQL(database)
	ctx := context.Background()
	res, err := database.ExecContext(ctx, `INSERT INTO users(email,password_hash,display_name) VALUES('p22-durable-race@example.test','fixture','Durable race')`)
	if err != nil {
		t.Fatal(err)
	}
	uid, err := res.LastInsertId()
	if err != nil {
		t.Fatal(err)
	}
	res, err = database.ExecContext(ctx, `INSERT INTO conversations(user_id,title) VALUES(?,'Durable race')`, uid)
	if err != nil {
		t.Fatal(err)
	}
	conversationID, err := res.LastInsertId()
	if err != nil {
		t.Fatal(err)
	}
	const key = "p22-durable-race-client-key"
	const fingerprint = "012345678901234567890123456789012345678901234567890123456789abcd"
	const requestID = "p22-durable-race-server-request"
	create := func(clientKey, serverRequestID, digest, executionID string) (*model.Task, *model.RuntimeJob, error) {
		return repo.CreateQueuedTaskAndRuntimeJob(ctx, model.Task{
			UserID: uid, ConversationID: &conversationID, RequestID: serverRequestID,
			ClientRequestID: clientKey, RequestFingerprint: digest,
			TaskText: "durable concurrently submitted task", Scheduler: "adaptive", Planner: "multi_objective",
			ExecutionMode: "auto", SynthesisMode: "auto", DeliveryMode: "durable",
		}, model.TaskConstraints{}, []byte(`{}`), executionID, time.Now().UTC().Add(time.Minute), 3)
	}
	const workers = 5
	type outcome struct {
		task *model.Task
		job  *model.RuntimeJob
		err  error
	}
	results := make([]outcome, workers)
	var wg sync.WaitGroup
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func(index int) {
			defer wg.Done()
			results[index].task, results[index].job, results[index].err = create(key, requestID, fingerprint, fmt.Sprintf("durable-execution-%d", index))
		}(i)
	}
	wg.Wait()
	var originalTaskID, originalJobID int64
	for i, result := range results {
		if result.err != nil || result.task == nil || result.job == nil {
			t.Fatalf("worker %d: task=%+v job=%+v err=%v", i, result.task, result.job, result.err)
		}
		if i == 0 {
			originalTaskID, originalJobID = result.task.ID, result.job.ID
		}
		if result.task.ID != originalTaskID || result.job.ID != originalJobID {
			t.Fatalf("worker %d returned different task/job: %d/%d want %d/%d", i, result.task.ID, result.job.ID, originalTaskID, originalJobID)
		}
	}
	// Exercise the second 1062 site: the same client key with a fresh server
	// request ID must roll back its temporary task/job/event and replay.
	replayedTask, replayedJob, err := create(key, "fresh-server-request", fingerprint, "fresh-execution")
	if err != nil || replayedTask == nil || replayedJob == nil || replayedTask.ID != originalTaskID || replayedJob.ID != originalJobID {
		t.Fatalf("ledger replay: task=%+v job=%+v err=%v", replayedTask, replayedJob, err)
	}
	if _, _, err := create("different-client-key", requestID, fingerprint, "different-execution"); !errors.Is(err, repository.ErrSubmissionConflict) {
		t.Fatalf("same server ID but another client key must conflict, got %v", err)
	}
	if _, _, err := create(key, "changed-server-request", "different-fingerprint", "changed-execution"); !errors.Is(err, repository.ErrSubmissionConflict) {
		t.Fatalf("same key with changed payload must conflict, got %v", err)
	}
	for _, item := range []struct {
		name  string
		query string
	}{
		{"task", `SELECT COUNT(*) FROM tasks WHERE user_id=?`},
		{"job", `SELECT COUNT(*) FROM runtime_jobs WHERE user_id=?`},
		{"ledger", `SELECT COUNT(*) FROM task_submission_keys WHERE user_id=?`},
	} {
		var count int
		if err := database.QueryRowContext(ctx, item.query, uid).Scan(&count); err != nil {
			t.Fatal(err)
		}
		if count != 1 {
			t.Errorf("%s count=%d, want exactly one", item.name, count)
		}
	}
	var messages, events int
	if err := database.QueryRowContext(ctx, `SELECT COUNT(*) FROM messages WHERE conversation_id=? AND role='user'`, conversationID).Scan(&messages); err != nil {
		t.Fatal(err)
	}
	if err := database.QueryRowContext(ctx, `SELECT COUNT(*) FROM durable_task_events WHERE task_id=?`, originalTaskID).Scan(&events); err != nil {
		t.Fatal(err)
	}
	if messages != 1 || events != 1 {
		t.Fatalf("messages=%d events=%d, both must equal one", messages, events)
	}
}
