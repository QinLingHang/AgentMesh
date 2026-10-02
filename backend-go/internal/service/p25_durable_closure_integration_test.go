package service

import (
	"context"
	"fmt"
	"os"
	"sort"
	"strconv"
	"testing"
	"time"

	"example.com/agentmesh-control-plane/internal/cache"
	"example.com/agentmesh-control-plane/internal/model"
	runtimeclient "example.com/agentmesh-control-plane/internal/runtime"
	"github.com/redis/go-redis/v9"
)

func p25Redis(t *testing.T) (*redis.Client, *cache.DurableStreamStore) {
	t.Helper()
	addr := os.Getenv("P25_QA_REDIS_ADDR")
	if addr == "" {
		t.Skip("set P25_QA_REDIS_ADDR to run isolated P25 Redis closure tests")
	}
	db := 0
	if raw := os.Getenv("P25_QA_REDIS_DB"); raw != "" {
		parsed, err := strconv.Atoi(raw)
		if err != nil || parsed < 0 {
			t.Fatalf("invalid P25_QA_REDIS_DB")
		}
		db = parsed
	}
	client := redis.NewClient(&redis.Options{Addr: addr, DB: db})
	if err := client.Ping(context.Background()).Err(); err != nil {
		client.Close()
		t.Fatalf("P25 QA Redis unavailable: %v", err)
	}
	t.Cleanup(func() { _ = client.Close() })
	return client, cache.NewDurableStreamStore(client, 64, 5*time.Minute)
}

func p25AcceptJob(t *testing.T, repo interface {
	HeartbeatRuntimeWorker(context.Context, model.RuntimeWorker) error
	ClaimNextRuntimeJob(context.Context, string, string, time.Duration) (*model.RuntimeJob, []byte, error)
	MarkRuntimeJobDispatching(context.Context, int64, string, string) (bool, error)
	MarkRuntimeJobAccepted(context.Context, int64, string, string) (bool, error)
}, worker, lease string, duration time.Duration) *model.RuntimeJob {
	t.Helper()
	ctx := context.Background()
	if err := repo.HeartbeatRuntimeWorker(ctx, model.RuntimeWorker{WorkerID: worker, Endpoint: "http://runtime.invalid:9572", Capacity: 1}); err != nil {
		t.Fatal(err)
	}
	job, _, err := repo.ClaimNextRuntimeJob(ctx, worker, lease, duration)
	if err != nil || job == nil {
		t.Fatalf("claim %s: job=%+v err=%v", worker, job, err)
	}
	if ok, err := repo.MarkRuntimeJobDispatching(ctx, job.ID, worker, lease); err != nil || !ok {
		t.Fatalf("dispatch %s: ok=%v err=%v", worker, ok, err)
	}
	if ok, err := repo.MarkRuntimeJobAccepted(ctx, job.ID, worker, lease); err != nil || !ok {
		t.Fatalf("accept %s: ok=%v err=%v", worker, ok, err)
	}
	return job
}

func p25Complete(t *testing.T, s *DurableRuntimeService, job *model.RuntimeJob, worker, lease, answer string) DurableCallbackOutcome {
	t.Helper()
	outcome, err := s.CallbackWithOutcome(context.Background(), job.ID, DurableExecutionCallback{
		WorkerID: worker, ExecutionID: job.ExecutionID, LeaseToken: lease, FenceEpoch: job.FenceEpoch,
		Status: "completed", Response: &runtimeclient.ExecuteResponse{
			RequestID: job.RequestID, Status: "COMPLETED", Answer: answer,
			Scheduler: "adaptive", TaskProfile: map[string]any{}, Trace: []map[string]any{}, DAG: map[string]any{},
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	return outcome
}

func p25Run(t *testing.T, s *DurableRuntimeService, repo interface {
	CreateConversation(context.Context, int64, string) (*model.Conversation, error)
}, uid int64, text string, retryOnWorkerLoss bool) *RunTaskResult {
	t.Helper()
	conversation, err := repo.CreateConversation(context.Background(), uid, text)
	if err != nil {
		t.Fatal(err)
	}
	result, err := s.Run(context.Background(), uid, RunTaskInput{
		ConversationID: &conversation.ID,
		Task:           text, Scheduler: "adaptive", Planner: "multi_objective", ExecutionMode: "auto", SynthesisMode: "auto",
		Constraints: model.TaskConstraints{MaxLatencyMS: 8000, MaxCost: .15, MinQuality: .8, RetryOnWorkerLoss: retryOnWorkerLoss},
	})
	if err != nil {
		t.Fatal(err)
	}
	return result
}

func p25AssertSingleAssistant(t *testing.T, s *DurableRuntimeService, uid, taskID int64, answer string) {
	t.Helper()
	task, err := s.taskService.tasks.TaskByID(context.Background(), uid, taskID)
	if err != nil || task == nil || task.Status != "COMPLETED" || task.ResultText == nil || *task.ResultText != answer || task.ConversationID == nil {
		t.Fatalf("authoritative task mismatch: task=%+v err=%v", task, err)
	}
	messages, err := s.taskService.messages.ListMessages(context.Background(), uid, *task.ConversationID, 100)
	if err != nil {
		t.Fatal(err)
	}
	count := 0
	for _, message := range messages {
		if message.Role == "assistant" && message.Content == answer {
			count++
		}
	}
	if count != 1 {
		t.Fatalf("assistant message count=%d, want 1", count)
	}
}

func TestP25DisconnectReplayUsesSameTaskAndCompositeDeltaCursor(t *testing.T) {
	ctx := context.Background()
	s, repo, uid := p8Fixture(t)
	client, store := p25Redis(t)
	s.SetLiveStreamStore(store)
	result := p25Run(t, s, repo, uid, "P25 disconnect replay", false)
	key := fmt.Sprintf("agentmesh:durable:task:%d:live", result.Task.ID)
	t.Cleanup(func() { _ = client.Del(ctx, key).Err() })
	job := p25AcceptJob(t, repo, "p25-replay-worker", "p25-replay-lease", 5*time.Second)

	for ordinal, delta := range []string{"one ", "two ", "three ", "four"} {
		accepted, err := s.WorkerDelta(ctx, job.ID, DurableWorkerDelta{
			WorkerID: "p25-replay-worker", ExecutionID: job.ExecutionID, LeaseToken: "p25-replay-lease",
			FenceEpoch: job.FenceEpoch, Ordinal: int64(ordinal + 1), Type: "delta", Delta: delta,
		})
		if err != nil || !accepted {
			t.Fatalf("delta %d rejected: accepted=%v err=%v", ordinal+1, accepted, err)
		}
	}
	first, err := s.TaskLiveDeltas(ctx, result.Task.ID, fmt.Sprintf("%d-0", job.FenceEpoch))
	if err != nil || len(first) != 4 {
		t.Fatalf("initial replay: events=%+v err=%v", first, err)
	}
	disconnectCursor := first[1].StreamID
	resumed, err := s.TaskLiveDeltas(ctx, result.Task.ID, disconnectCursor)
	if err != nil || len(resumed) != 2 {
		t.Fatalf("resume from %s: events=%+v err=%v", disconnectCursor, resumed, err)
	}
	ordinals := []int64{first[0].Ordinal, first[1].Ordinal, resumed[0].Ordinal, resumed[1].Ordinal}
	if !sort.SliceIsSorted(ordinals, func(i, j int) bool { return ordinals[i] < ordinals[j] }) || fmt.Sprint(ordinals) != "[1 2 3 4]" {
		t.Fatalf("duplicate or missing replay ordinals: %v", ordinals)
	}
	if outcome := p25Complete(t, s, job, "p25-replay-worker", "p25-replay-lease", "one two three four"); outcome != DurableCallbackApplied {
		t.Fatalf("completion outcome=%s", outcome)
	}
	p25AssertSingleAssistant(t, s, uid, result.Task.ID, "one two three four")
	t.Logf("taskId=%d disconnectCursor=%s reconnectCursor=%s executionId=%s fenceEpoch=%d receivedOrdinals=%v duplicateCount=0 missingCount=0 assistantMessageCount=1 terminalStatus=COMPLETED", result.Task.ID, disconnectCursor, resumed[len(resumed)-1].StreamID, job.ExecutionID, job.FenceEpoch, ordinals)
}

func TestP25HigherFenceRejectsLateAttemptAndPersistsOnlyAuthoritativeResult(t *testing.T) {
	ctx := context.Background()
	s, repo, uid := p8Fixture(t)
	capture := &captureDurableLiveStream{}
	s.SetLiveStreamStore(capture)
	result := p25Run(t, s, repo, uid, "P25 higher fence", true)
	a := p25AcceptJob(t, repo, "p25-worker-a", "p25-lease-a", time.Second)
	if accepted, err := s.WorkerDelta(ctx, a.ID, DurableWorkerDelta{WorkerID: "p25-worker-a", ExecutionID: a.ExecutionID, LeaseToken: "p25-lease-a", FenceEpoch: a.FenceEpoch, Ordinal: 1, Type: "delta", Delta: "old partial"}); err != nil || !accepted {
		t.Fatalf("attempt A delta: accepted=%v err=%v", accepted, err)
	}
	time.Sleep(1100 * time.Millisecond)
	if requeued, failed, err := repo.RecoverLostAcceptedRuntimeJobs(ctx, time.Now().UTC(), 0, 10); err != nil || requeued != 1 || failed != 0 {
		t.Fatalf("controlled lease recovery: requeued=%d failed=%d err=%v", requeued, failed, err)
	}
	b := p25AcceptJob(t, repo, "p25-worker-b", "p25-lease-b", 5*time.Second)
	if b.ID != a.ID || b.ExecutionID == a.ExecutionID || b.FenceEpoch <= a.FenceEpoch {
		t.Fatalf("authoritative transition A=%+v B=%+v", a, b)
	}
	if accepted, err := s.WorkerDelta(ctx, a.ID, DurableWorkerDelta{WorkerID: "p25-worker-a", ExecutionID: a.ExecutionID, LeaseToken: "p25-lease-a", FenceEpoch: a.FenceEpoch, Ordinal: 2, Type: "delta", Delta: "late old"}); err != nil || accepted {
		t.Fatalf("late A delta accepted=%v err=%v", accepted, err)
	}
	if accepted, err := s.WorkerDelta(ctx, b.ID, DurableWorkerDelta{WorkerID: "p25-worker-b", ExecutionID: b.ExecutionID, LeaseToken: "p25-lease-b", FenceEpoch: b.FenceEpoch, Ordinal: 1, Type: "delta", Delta: "new answer"}); err != nil || !accepted {
		t.Fatalf("attempt B delta: accepted=%v err=%v", accepted, err)
	}
	lateOutcome, err := s.CallbackWithOutcome(ctx, a.ID, DurableExecutionCallback{WorkerID: "p25-worker-a", ExecutionID: a.ExecutionID, LeaseToken: "p25-lease-a", FenceEpoch: a.FenceEpoch, Status: "completed", Response: &runtimeclient.ExecuteResponse{RequestID: a.RequestID, Status: "COMPLETED", Answer: "late old"}})
	if err != nil || (lateOutcome != DurableCallbackStaleFence && lateOutcome != DurableCallbackDuplicate) {
		t.Fatalf("late A result outcome=%s err=%v", lateOutcome, err)
	}
	if outcome := p25Complete(t, s, b, "p25-worker-b", "p25-lease-b", "new answer"); outcome != DurableCallbackApplied {
		t.Fatalf("B completion outcome=%s", outcome)
	}
	p25AssertSingleAssistant(t, s, uid, result.Task.ID, "new answer")
	_, snapshot, err := s.TaskEventBatch(ctx, uid, result.Task.ID, 0)
	if err != nil || snapshot.ExecutionID != b.ExecutionID || snapshot.FenceEpoch != b.FenceEpoch {
		t.Fatalf("authoritative snapshot=%+v err=%v", snapshot, err)
	}
	t.Logf("taskId=%d executionA=%s fenceA=%d executionB=%s fenceB=%d lateDeltaAccepted=false lateResultOutcome=%s assistantMessageCount=1 terminalStatus=COMPLETED", result.Task.ID, a.ExecutionID, a.FenceEpoch, b.ExecutionID, b.FenceEpoch, lateOutcome)
}

func TestP25RedisLiveBufferLossPreservesDurableTerminalResult(t *testing.T) {
	ctx := context.Background()
	s, repo, uid := p8Fixture(t)
	client, store := p25Redis(t)
	s.SetLiveStreamStore(store)
	result := p25Run(t, s, repo, uid, "P25 Redis live buffer loss", false)
	key := fmt.Sprintf("agentmesh:durable:task:%d:live", result.Task.ID)
	t.Cleanup(func() { _ = client.Del(ctx, key).Err() })
	job := p25AcceptJob(t, repo, "p25-redis-worker", "p25-redis-lease", 5*time.Second)
	for ordinal, delta := range []string{"live ", "answer"} {
		accepted, err := s.WorkerDelta(ctx, job.ID, DurableWorkerDelta{WorkerID: "p25-redis-worker", ExecutionID: job.ExecutionID, LeaseToken: "p25-redis-lease", FenceEpoch: job.FenceEpoch, Ordinal: int64(ordinal + 1), Type: "delta", Delta: delta})
		if err != nil || !accepted {
			t.Fatalf("delta %d: accepted=%v err=%v", ordinal+1, accepted, err)
		}
	}
	if size, err := client.XLen(ctx, key).Result(); err != nil || size != 2 {
		t.Fatalf("isolated live buffer size=%d err=%v", size, err)
	}
	if deleted, err := client.Del(ctx, key).Result(); err != nil || deleted != 1 {
		t.Fatalf("delete exact task buffer: deleted=%d err=%v", deleted, err)
	}
	if outcome := p25Complete(t, s, job, "p25-redis-worker", "p25-redis-lease", "live answer"); outcome != DurableCallbackApplied {
		t.Fatalf("completion outcome=%s", outcome)
	}
	if deltas, err := s.TaskLiveDeltas(ctx, result.Task.ID, "0-0"); err != nil || len(deltas) != 0 {
		t.Fatalf("lost buffer unexpectedly restored: deltas=%+v err=%v", deltas, err)
	}
	p25AssertSingleAssistant(t, s, uid, result.Task.ID, "live answer")
	t.Logf("taskId=%d executionId=%s fenceEpoch=%d deletedRedisKeyForTaskOnly=true assistantMessageCount=1 terminalStatus=COMPLETED finalAnswerRecovered=true", result.Task.ID, job.ExecutionID, job.FenceEpoch)
}
