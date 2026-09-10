package service

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"strconv"
	"testing"
	"time"

	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/repository"
	runtimeclient "example.com/agentmesh-control-plane/internal/runtime"
)

func v3Heartbeat(t *testing.T, repo interface {
	HeartbeatRuntimeWorker(context.Context, model.RuntimeWorker) error
}, workerID, nodeID string, capacity int) {
	t.Helper()
	if err := repo.HeartbeatRuntimeWorker(context.Background(), model.RuntimeWorker{
		WorkerID:         workerID,
		NodeID:           nodeID,
		Zone:             "zone-test",
		Version:          "3.0.0-dev",
		Endpoint:         "http://" + workerID + ".invalid:9572",
		Capacity:         capacity,
		NodeCapacity:     capacity,
		ActiveExecutions: 0,
	}); err != nil {
		t.Fatal(err)
	}
}

func newV3RuntimeClient() *runtimeclient.Client {
	return runtimeclient.NewClient("http://127.0.0.1:1", "internal-test-token", time.Second)
}

func TestV3NodeRegistrationCapacityAwareSchedulingAndTopologyPrivacy(t *testing.T) {
	s, repo, uid := p8Fixture(t)
	ctx := context.Background()
	v3Heartbeat(t, repo, "worker-a", "node-a", 4)
	v3Heartbeat(t, repo, "worker-b", "node-b", 2)

	p8Run(t, s, uid, "capacity-aware job one")
	job, _, err := repo.ClaimNextRuntimeJob(ctx, "worker-a", "lease-a", time.Minute)
	if err != nil || job == nil {
		t.Fatalf("claim worker-a: job=%#v err=%v", job, err)
	}

	workers, err := repo.ListAvailableRuntimeWorkers(ctx, time.Now().UTC().Add(-time.Minute), 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(workers) < 2 {
		t.Fatalf("expected two schedulable workers, got %#v", workers)
	}
	if workers[0].WorkerID != "worker-b" {
		t.Fatalf("capacity-aware scheduler should prefer idle worker-b, order=%#v", workers)
	}
	if workers[0].SchedulingScore > workers[1].SchedulingScore {
		t.Fatalf("scheduling score order is not ascending: %#v", workers)
	}

	topology, err := s.Topology(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if len(topology.Nodes) != 2 || len(topology.Workers) != 2 {
		t.Fatalf("unexpected topology: %#v", topology)
	}
	data, err := json.Marshal(topology)
	if err != nil {
		t.Fatal(err)
	}
	if containsString(string(data), ".invalid:9572") || containsString(string(data), "http://worker-") {
		t.Fatalf("internal worker endpoint leaked through topology: %s", data)
	}
}

func TestV3DispatcherLeaseFailoverUsesMonotonicEpoch(t *testing.T) {
	database, _ := p2Database(t)
	ctx := context.Background()
	repo := repository.NewMySQL(database)

	// Keep the pre-expiry assertion far away from a wall-clock boundary. The
	// repository itself uses MySQL UTC_TIMESTAMP(6) as the authoritative clock,
	// so this test should control lease state with that same clock instead of
	// racing an 80ms lease against scheduler/database latency.
	first, leader, err := repo.AcquireRuntimeDispatcherLease(ctx, "dispatcher-a", time.Minute)
	if err != nil || !leader || first == nil {
		t.Fatalf("dispatcher-a acquire failed: lease=%#v leader=%v err=%v", first, leader, err)
	}
	if first.Epoch != 1 {
		t.Fatalf("first dispatcher epoch=%d want=1", first.Epoch)
	}

	sameEpoch, leader, err := repo.AcquireRuntimeDispatcherLease(ctx, "dispatcher-b", time.Second)
	if err != nil {
		t.Fatal(err)
	}
	if leader {
		t.Fatal("standby dispatcher must not lead before lease expiry")
	}
	if sameEpoch == nil || sameEpoch.Epoch != first.Epoch {
		t.Fatalf("standby should observe same epoch before failover: %#v", sameEpoch)
	}

	result, err := database.ExecContext(
		ctx,
		`
		UPDATE runtime_dispatcher_leases
		SET lease_until = DATE_SUB(UTC_TIMESTAMP(6), INTERVAL 1 SECOND),
		    last_heartbeat_at = UTC_TIMESTAMP(6)
		WHERE lease_name = 'durable-runtime-dispatcher'
		  AND holder_id = 'dispatcher-a'
		`,
	)
	if err != nil {
		t.Fatal(err)
	}
	if affected, err := result.RowsAffected(); err != nil || affected != 1 {
		t.Fatalf("failed to deterministically expire dispatcher-a lease: affected=%d err=%v", affected, err)
	}

	second, leader, err := repo.AcquireRuntimeDispatcherLease(ctx, "dispatcher-b", time.Minute)
	if err != nil || !leader || second == nil {
		t.Fatalf("dispatcher-b failover failed: lease=%#v leader=%v err=%v", second, leader, err)
	}
	if second.Epoch != first.Epoch+1 {
		t.Fatalf("dispatcher epoch must increase exactly once on ownership transfer: first=%d second=%d", first.Epoch, second.Epoch)
	}

	oldOwnerView, oldLeader, err := repo.AcquireRuntimeDispatcherLease(ctx, "dispatcher-a", time.Second)
	if err != nil {
		t.Fatal(err)
	}
	if oldLeader {
		t.Fatal("old dispatcher must not reclaim an unexpired standby-owned lease")
	}
	if oldOwnerView == nil || oldOwnerView.HolderID != "dispatcher-b" || oldOwnerView.Epoch != second.Epoch {
		t.Fatalf("old dispatcher observed wrong authoritative lease: %#v", oldOwnerView)
	}
}

func v3DispatcherLeaseStressIterations(t *testing.T) int {
	t.Helper()
	raw := os.Getenv("V4_1_LEASE_STRESS_ITERATIONS")
	if raw == "" {
		// Keep ordinary package/full-suite runs lightweight. FIX5 acceptance sets
		// this environment variable to 100 and exercises 100 real ownership
		// transfers inside one isolated database instead of recreating/migrating
		// the database 100 times with `go test -count=100`.
		return 1
	}
	iterations, err := strconv.Atoi(raw)
	if err != nil || iterations < 1 {
		t.Fatalf("invalid V4_1_LEASE_STRESS_ITERATIONS=%q: must be a positive integer", raw)
	}
	return iterations
}

func TestV3DispatcherLeaseFailoverStress(t *testing.T) {
	database, _ := p2Database(t)
	ctx := context.Background()
	repo := repository.NewMySQL(database)
	iterations := v3DispatcherLeaseStressIterations(t)

	holder := "dispatcher-stress-0"
	current, leader, err := repo.AcquireRuntimeDispatcherLease(ctx, holder, time.Minute)
	if err != nil || !leader || current == nil {
		t.Fatalf("initial dispatcher acquire failed: lease=%#v leader=%v err=%v", current, leader, err)
	}

	for i := 1; i <= iterations; i++ {
		result, err := database.ExecContext(
			ctx,
			`
			UPDATE runtime_dispatcher_leases
			SET lease_until = DATE_SUB(UTC_TIMESTAMP(6), INTERVAL 1 SECOND),
			    last_heartbeat_at = UTC_TIMESTAMP(6)
			WHERE lease_name = 'durable-runtime-dispatcher'
			  AND holder_id = ?
			`,
			holder,
		)
		if err != nil {
			t.Fatalf("iteration %d expire holder %q: %v", i, holder, err)
		}
		if affected, err := result.RowsAffected(); err != nil || affected != 1 {
			t.Fatalf("iteration %d expire holder %q: affected=%d err=%v", i, holder, affected, err)
		}

		nextHolder := fmt.Sprintf("dispatcher-stress-%d", i)
		next, nextLeader, err := repo.AcquireRuntimeDispatcherLease(ctx, nextHolder, time.Minute)
		if err != nil || !nextLeader || next == nil {
			t.Fatalf("iteration %d takeover by %q failed: lease=%#v leader=%v err=%v", i, nextHolder, next, nextLeader, err)
		}
		if next.Epoch != current.Epoch+1 {
			t.Fatalf("iteration %d epoch must increase exactly once: current=%d next=%d", i, current.Epoch, next.Epoch)
		}

		staleView, staleLeader, err := repo.AcquireRuntimeDispatcherLease(ctx, holder, time.Second)
		if err != nil {
			t.Fatalf("iteration %d stale holder %q acquire: %v", i, holder, err)
		}
		if staleLeader {
			t.Fatalf("iteration %d stale holder %q reclaimed an unexpired lease owned by %q", i, holder, nextHolder)
		}
		if staleView == nil || staleView.HolderID != nextHolder || staleView.Epoch != next.Epoch {
			t.Fatalf("iteration %d stale holder observed wrong authoritative lease: %#v", i, staleView)
		}

		holder = nextHolder
		current = next
	}
}

func TestV3WorkerLossRecoverySafeVsFailClosed(t *testing.T) {
	database, _ := p2Database(t)
	ctx := context.Background()
	repo := repository.NewMySQL(database)

	result, err := database.Exec(`INSERT INTO users(email,password_hash,display_name) VALUES('v3@example.test','fixture','V3')`)
	if err != nil {
		t.Fatal(err)
	}
	uid, _ := result.LastInsertId()
	if _, err = database.Exec(`
        INSERT INTO agents(user_id,name,endpoint,protocol,capabilities_json,status)
        VALUES(?,'V3 General','internal://success','internal','["general"]','ACTIVE')
    `, uid); err != nil {
		t.Fatal(err)
	}

	runtime := newV3RuntimeClient()
	taskService := NewTaskService(repo, repo, repo, runtime, repo, repo)
	s := NewDurableRuntimeService(repo, taskService, runtime, DurableRuntimeConfig{
		Enabled:                true,
		ControlPlaneBaseURL:    "http://control-plane.invalid",
		LeaseDuration:          time.Second,
		ExecutionLeaseDuration: time.Second,
		WorkerStaleAfter:       time.Minute,
		JobDeadline:            time.Minute,
		MaxAttempts:            3,
		MaxQueueDepth:          50,
	})
	v3Heartbeat(t, repo, "worker-a", "node-a", 1)
	v3Heartbeat(t, repo, "worker-b", "node-b", 1)

	safe, err := s.Run(ctx, uid, RunTaskInput{
		Task: "safe retry", Scheduler: "adaptive", Planner: "multi_objective",
		ExecutionMode: "auto", SynthesisMode: "auto",
		Constraints: model.TaskConstraints{MaxLatencyMS: 8000, MaxCost: .15, MinQuality: .8, RetryOnWorkerLoss: true},
	})
	if err != nil {
		t.Fatal(err)
	}
	first, _, err := repo.ClaimNextRuntimeJob(ctx, "worker-a", "safe-lease-a", time.Second)
	if err != nil || first == nil {
		t.Fatalf("safe first claim: %#v %v", first, err)
	}
	if ok, err := repo.MarkRuntimeJobDispatching(ctx, first.ID, "worker-a", "safe-lease-a"); err != nil || !ok {
		t.Fatalf("safe dispatching: %v %v", ok, err)
	}
	if ok, err := repo.MarkRuntimeJobAccepted(ctx, first.ID, "worker-a", "safe-lease-a"); err != nil || !ok {
		t.Fatalf("safe accepted: %v %v", ok, err)
	}
	if _, err := database.Exec(`UPDATE runtime_jobs SET lease_expires_at=DATE_SUB(UTC_TIMESTAMP(6), INTERVAL 1 SECOND) WHERE id=?`, first.ID); err != nil {
		t.Fatal(err)
	}

	requeued, failed, err := repo.RecoverLostAcceptedRuntimeJobs(ctx, time.Now().UTC(), 0, 10)
	if err != nil || requeued != 1 || failed != 0 {
		t.Fatalf("safe recovery requeued=%d failed=%d err=%v", requeued, failed, err)
	}
	second, _, err := repo.ClaimNextRuntimeJob(ctx, "worker-b", "safe-lease-b", time.Second)
	if err != nil || second == nil {
		t.Fatalf("safe second claim: %#v %v", second, err)
	}
	if second.TaskID != safe.Task.ID || second.NodeID == nil || *second.NodeID != "node-b" {
		t.Fatalf("safe job was not reassigned cross-node: %#v", second)
	}
	if second.FenceEpoch <= first.FenceEpoch {
		t.Fatalf("fence epoch must increase after reassignment: first=%d second=%d", first.FenceEpoch, second.FenceEpoch)
	}
	// A stale callback from node-a is ignored before side effects.
	if err := s.Callback(ctx, second.ID, DurableExecutionCallback{
		WorkerID: "worker-a", ExecutionID: second.ExecutionID, LeaseToken: "safe-lease-a",
		FenceEpoch: first.FenceEpoch, Status: "failed", ErrorCategory: "stale-node",
	}); err != nil {
		t.Fatal(err)
	}
	persisted, err := repo.RuntimeJobByID(ctx, second.ID)
	if err != nil || persisted == nil || persisted.Status != "LEASED" {
		t.Fatalf("stale callback changed reassigned job: %#v err=%v", persisted, err)
	}

	// Close the safe fixture so worker-b capacity is available.
	if err := repo.FailRuntimeJob(ctx, second.ID, "test fixture closed"); err != nil {
		t.Fatal(err)
	}

	unsafe, err := s.Run(ctx, uid, RunTaskInput{
		Task: "unsafe retry", Scheduler: "adaptive", Planner: "multi_objective",
		ExecutionMode: "auto", SynthesisMode: "auto",
		Constraints: model.TaskConstraints{MaxLatencyMS: 8000, MaxCost: .15, MinQuality: .8, RetryOnWorkerLoss: false},
	})
	if err != nil {
		t.Fatal(err)
	}
	unsafeJob, _, err := repo.ClaimNextRuntimeJob(ctx, "worker-a", "unsafe-lease", time.Second)
	if err != nil || unsafeJob == nil {
		t.Fatalf("unsafe claim: %#v %v", unsafeJob, err)
	}
	if ok, err := repo.MarkRuntimeJobDispatching(ctx, unsafeJob.ID, "worker-a", "unsafe-lease"); err != nil || !ok {
		t.Fatalf("unsafe dispatching: %v %v", ok, err)
	}
	if ok, err := repo.MarkRuntimeJobAccepted(ctx, unsafeJob.ID, "worker-a", "unsafe-lease"); err != nil || !ok {
		t.Fatalf("unsafe accepted: %v %v", ok, err)
	}
	if _, err := database.Exec(`UPDATE runtime_jobs SET lease_expires_at=DATE_SUB(UTC_TIMESTAMP(6), INTERVAL 1 SECOND) WHERE id=?`, unsafeJob.ID); err != nil {
		t.Fatal(err)
	}
	requeued, failed, err = repo.RecoverLostAcceptedRuntimeJobs(ctx, time.Now().UTC(), 0, 10)
	if err != nil || requeued != 0 || failed != 1 {
		t.Fatalf("unsafe recovery requeued=%d failed=%d err=%v", requeued, failed, err)
	}
	finalUnsafe, err := repo.RuntimeJobByID(ctx, unsafeJob.ID)
	if err != nil || finalUnsafe == nil || finalUnsafe.Status != "FAILED" {
		t.Fatalf("unsafe accepted execution must fail closed: %#v err=%v", finalUnsafe, err)
	}
	_ = unsafe
}

func TestV3NodeCapacityCapsMultipleWorkersOnSameNode(t *testing.T) {
	s, repo, uid := p8Fixture(t)
	ctx := context.Background()
	for _, workerID := range []string{"worker-nodecap-a", "worker-nodecap-b"} {
		if err := repo.HeartbeatRuntimeWorker(ctx, model.RuntimeWorker{
			WorkerID:     workerID,
			NodeID:       "node-cap-1",
			Zone:         "zone-cap",
			Version:      "3.0.0-dev",
			Endpoint:     "http://" + workerID + ".invalid:9572",
			Capacity:     1,
			NodeCapacity: 1,
		}); err != nil {
			t.Fatal(err)
		}
	}

	p8Run(t, s, uid, "node capacity first")
	p8Run(t, s, uid, "node capacity second")

	first, _, err := repo.ClaimNextRuntimeJob(ctx, "worker-nodecap-a", "nodecap-lease-a", time.Minute)
	if err != nil || first == nil {
		t.Fatalf("first node-cap claim: job=%#v err=%v", first, err)
	}
	blocked, _, err := repo.ClaimNextRuntimeJob(ctx, "worker-nodecap-b", "nodecap-lease-b", time.Minute)
	if err != nil {
		t.Fatal(err)
	}
	if blocked != nil {
		t.Fatalf("second worker on same node exceeded node capacity: %#v", blocked)
	}

	if err := repo.FailRuntimeJob(ctx, first.ID, "release node capacity fixture"); err != nil {
		t.Fatal(err)
	}
	second, _, err := repo.ClaimNextRuntimeJob(ctx, "worker-nodecap-b", "nodecap-lease-c", time.Minute)
	if err != nil || second == nil {
		t.Fatalf("node capacity did not reopen after release: job=%#v err=%v", second, err)
	}
}
