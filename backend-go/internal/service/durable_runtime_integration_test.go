package service

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/repository"
	runtimeclient "example.com/agentmesh-control-plane/internal/runtime"
)

func p8Fixture(t *testing.T) (*DurableRuntimeService, *repository.MySQL, int64) {
	t.Helper()
	database, _ := p2Database(t)
	ctx := context.Background()
	repo := repository.NewMySQL(database)

	result, err := database.Exec(`INSERT INTO users(email,password_hash,display_name) VALUES('durable-runtime@example.test','fixture','Durable Runtime')`)
	if err != nil {
		t.Fatal(err)
	}
	uid, _ := result.LastInsertId()
	if _, err = database.Exec(`
		INSERT INTO agents(user_id,name,endpoint,protocol,capabilities_json,status)
		VALUES(?,'Durable Runtime General','internal://success','internal','["general"]','ACTIVE')
	`, uid); err != nil {
		t.Fatal(err)
	}

	runtime := runtimeclient.NewClient("http://127.0.0.1:1", "internal-test-token", time.Second)
	taskService := NewTaskService(repo, repo, repo, runtime, repo, repo)
	service := NewDurableRuntimeService(repo, taskService, runtime, DurableRuntimeConfig{
		Enabled: true, ControlPlaneBaseURL: "http://control-plane.invalid",
		LeaseDuration: time.Second, JobDeadline: time.Minute, MaxAttempts: 3,
		MaxQueueDepth: 50, CircuitFailureThreshold: 2, CircuitOpenFor: time.Minute,
	})
	_ = ctx
	return service, repo, uid
}

func p8Run(t *testing.T, s *DurableRuntimeService, uid int64, text string) *RunTaskResult {
	t.Helper()
	result, err := s.Run(context.Background(), uid, RunTaskInput{
		Task: text, Scheduler: "adaptive", Planner: "multi_objective",
		ExecutionMode: "auto", SynthesisMode: "auto",
		Constraints: model.TaskConstraints{MaxLatencyMS: 8000, MaxCost: .15, MinQuality: .8},
	})
	if err != nil {
		t.Fatal(err)
	}
	if result.Status != "QUEUED" || result.Task == nil || result.Task.Status != "QUEUED" || result.Task.DeliveryMode != "durable" {
		t.Fatalf("unexpected durable run result: %#v", result)
	}
	return result
}

func TestDurableRuntimeQueueLeaseFencingAndCallbackPersistence(t *testing.T) {
	s, repo, uid := p8Fixture(t)
	ctx := context.Background()
	result := p8Run(t, s, uid, "durable completion")

	job, raw, err := repo.ClaimNextRuntimeJob(ctx, "worker-durable", "lease-durable", time.Second)
	if err != nil || job != nil || raw != nil {
		t.Fatalf("unregistered worker must not claim; job=%#v err=%v", job, err)
	}

	if err = repo.HeartbeatRuntimeWorker(ctx, model.RuntimeWorker{
		WorkerID: "worker-durable", Endpoint: "http://runtime.invalid:9572", Capacity: 1,
	}); err != nil {
		t.Fatal(err)
	}
	job, raw, err = repo.ClaimNextRuntimeJob(ctx, "worker-durable", "lease-durable", time.Second)
	if err != nil || job == nil {
		t.Fatalf("claim failed: job=%#v err=%v", job, err)
	}
	if job.TaskID != result.Task.ID || job.Status != "LEASED" || job.AttemptCount != 1 {
		t.Fatalf("unexpected lease: %#v", job)
	}

	var stored runtimeclient.ExecuteRequest
	if err := json.Unmarshal(raw, &stored); err != nil {
		t.Fatal(err)
	}
	if len(stored.Agents) != 0 || len(stored.Tools) != 0 || len(stored.MCPServers) != 0 {
		t.Fatalf("queued payload must not freeze resource pools: %#v", stored)
	}

	ok, err := repo.MarkRuntimeJobDispatching(ctx, job.ID, "worker-durable", "lease-durable")
	if err != nil || !ok {
		t.Fatalf("dispatch fence: ok=%v err=%v", ok, err)
	}
	ok, err = repo.MarkRuntimeJobAccepted(ctx, job.ID, "worker-durable", "lease-durable")
	if err != nil || !ok {
		t.Fatalf("accept fence: ok=%v err=%v", ok, err)
	}

	callback := DurableExecutionCallback{
		WorkerID: "worker-durable", ExecutionID: job.ExecutionID, LeaseToken: "lease-durable", Status: "completed",
		Response: &runtimeclient.ExecuteResponse{
			RequestID: result.Task.RequestID, Status: "COMPLETED", Answer: "durable answer",
			Scheduler: "adaptive", TaskProfile: map[string]any{"complexity": "medium"},
			SelectedAgents: []string{"Durable Runtime General"}, Trace: []map[string]any{}, DAG: map[string]any{},
		},
	}
	if err := s.Callback(ctx, job.ID, callback); err != nil {
		t.Fatal(err)
	}
	// Duplicate callbacks are idempotent and must not replay completion side effects.
	if err := s.Callback(ctx, job.ID, callback); err != nil {
		t.Fatal(err)
	}

	persisted, err := repo.TaskByID(ctx, uid, result.Task.ID)
	if err != nil {
		t.Fatal(err)
	}
	if persisted == nil || persisted.Status != "COMPLETED" || persisted.ResultText == nil || *persisted.ResultText != "durable answer" {
		t.Fatalf("completion not persisted: %#v", persisted)
	}
	finalJob, err := repo.RuntimeJobByID(ctx, job.ID)
	if err != nil || finalJob == nil || finalJob.Status != "COMPLETED" {
		t.Fatalf("runtime job not completed: %#v err=%v", finalJob, err)
	}
}

func TestDurableRuntimeLeaseRecoveryCapacityCancelAndCircuitBreaker(t *testing.T) {
	s, repo, uid := p8Fixture(t)
	ctx := context.Background()
	if err := repo.HeartbeatRuntimeWorker(ctx, model.RuntimeWorker{
		WorkerID: "worker-capacity", Endpoint: "http://runtime.invalid:9572", Capacity: 1,
	}); err != nil {
		t.Fatal(err)
	}

	first := p8Run(t, s, uid, "first")
	_ = first
	p8Run(t, s, uid, "second")
	job, _, err := repo.ClaimNextRuntimeJob(ctx, "worker-capacity", "lease-one", -time.Second)
	if err != nil || job == nil {
		t.Fatalf("first claim: %#v %v", job, err)
	}
	// Authoritative durable states enforce capacity even if heartbeat telemetry says zero.
	blocked, _, err := repo.ClaimNextRuntimeJob(ctx, "worker-capacity", "lease-two", time.Second)
	if err != nil || blocked != nil {
		t.Fatalf("capacity must block second claim: %#v %v", blocked, err)
	}

	recovered, err := repo.RecoverExpiredRuntimeLeases(ctx, time.Now().UTC())
	if err != nil || recovered != 1 {
		t.Fatalf("lease recovery: recovered=%d err=%v", recovered, err)
	}
	job, _, err = repo.ClaimNextRuntimeJob(ctx, "worker-capacity", "lease-three", -time.Second)
	if err != nil || job == nil {
		t.Fatalf("reclaim: %#v %v", job, err)
	}
	ok, err := repo.MarkRuntimeJobDispatching(ctx, job.ID, "worker-capacity", "lease-three")
	if err != nil || !ok {
		t.Fatalf("dispatching fence: %v %v", ok, err)
	}
	// DISPATCHING crossed the ambiguous boundary and must never be lease-replayed.
	recovered, err = repo.RecoverExpiredRuntimeLeases(ctx, time.Now().UTC().Add(time.Minute))
	if err != nil || recovered != 0 {
		t.Fatalf("ambiguous dispatch was incorrectly replayed: recovered=%d err=%v", recovered, err)
	}

	// Finish ambiguous fixture so capacity becomes available, then cancel a fresh queued task.
	if err := repo.FailRuntimeJob(ctx, job.ID, "ambiguous fixture closed"); err != nil {
		t.Fatal(err)
	}
	cancelTarget := p8Run(t, s, uid, "cancel me")
	cancelled, err := s.Cancel(ctx, uid, cancelTarget.Task.ID)
	if err != nil || cancelled == nil || cancelled.Status != "CANCELED" {
		t.Fatalf("cancel failed: %#v err=%v", cancelled, err)
	}

	if err := repo.RecordRuntimeWorkerDispatchFailure(ctx, "worker-capacity", 2, time.Minute); err != nil {
		t.Fatal(err)
	}
	if err := repo.RecordRuntimeWorkerDispatchFailure(ctx, "worker-capacity", 2, time.Minute); err != nil {
		t.Fatal(err)
	}
	workers, err := repo.ListAvailableRuntimeWorkers(ctx, time.Now().UTC().Add(-time.Minute), 10)
	if err != nil {
		t.Fatal(err)
	}
	for _, worker := range workers {
		if worker.WorkerID == "worker-capacity" {
			t.Fatal("circuit-open worker must not be dispatchable")
		}
	}
}

func TestDurableRuntimeReliabilitySnapshotNeverExposesWorkerEndpoint(t *testing.T) {
	s, repo, uid := p8Fixture(t)
	ctx := context.Background()
	_ = uid
	if err := repo.HeartbeatRuntimeWorker(ctx, model.RuntimeWorker{
		WorkerID: "privacy-worker", Endpoint: "http://10.0.0.7:9572/private", Capacity: 2,
	}); err != nil {
		t.Fatal(err)
	}
	snapshot, err := s.Reliability(ctx)
	if err != nil {
		t.Fatal(err)
	}
	data, err := json.Marshal(snapshot)
	if err != nil {
		t.Fatal(err)
	}
	if string(data) == "" || string(data) == "null" {
		t.Fatal("reliability snapshot missing")
	}
	if contains := string(data); len(contains) > 0 && (json.Valid(data) == false) {
		t.Fatal("invalid reliability json")
	}
	if string(data) != "" && (containsString(string(data), "10.0.0.7") || containsString(string(data), "private")) {
		t.Fatalf("worker endpoint leaked: %s", data)
	}
}

func containsString(value, needle string) bool {
	for i := 0; i+len(needle) <= len(value); i++ {
		if value[i:i+len(needle)] == needle {
			return true
		}
	}
	return false
}
