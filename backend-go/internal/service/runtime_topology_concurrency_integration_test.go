package service

import (
	"context"
	"fmt"
	"sync"
	"testing"
	"time"

	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/repository"
)

func TestRuntimeTopologyHeartbeatAndStaleDetectionConvergeConcurrently(t *testing.T) {
	database, _ := p2Database(t)
	database.SetMaxOpenConns(12)
	repo := repository.NewMySQL(database)
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	const rounds = 40
	worker := model.RuntimeWorker{
		WorkerID: "topology-live-worker", NodeID: "topology-live-node",
		Endpoint: "http://runtime.invalid:9572", Capacity: 3, NodeCapacity: 4,
	}
	stale := model.RuntimeWorker{
		WorkerID: "topology-stale-worker", NodeID: "topology-stale-node",
		Endpoint: "http://runtime.invalid:9573", Capacity: 2, NodeCapacity: 2,
	}
	if err := repo.HeartbeatRuntimeWorker(ctx, worker); err != nil {
		t.Fatal(err)
	}
	if err := repo.HeartbeatRuntimeWorker(ctx, stale); err != nil {
		t.Fatal(err)
	}
	old := time.Now().UTC().Add(-time.Hour)
	if _, err := database.ExecContext(ctx, `UPDATE runtime_workers SET last_heartbeat_at=?`, old); err != nil {
		t.Fatal(err)
	}
	if _, err := database.ExecContext(ctx, `UPDATE runtime_nodes SET last_heartbeat_at=?`, old); err != nil {
		t.Fatal(err)
	}
	userResult, err := database.ExecContext(ctx, `
		INSERT INTO users(email,password_hash,display_name) VALUES(?,?,?)
	`, "topology-race@example.test", "fixture", "Topology race")
	if err != nil {
		t.Fatal(err)
	}
	uid, _ := userResult.LastInsertId()
	taskResult, err := database.ExecContext(ctx, `
		INSERT INTO tasks(
			user_id,request_id,task_text,scheduler,planner,execution_mode,synthesis_mode,delivery_mode,status
		) VALUES(?,?,?,?,?,?,?,?,'RUNNING')
	`, uid, "topology-race-request", "topology race", "adaptive", "heuristic", "auto", "auto", "durable")
	if err != nil {
		t.Fatal(err)
	}
	taskID, _ := taskResult.LastInsertId()
	jobResult, err := database.ExecContext(ctx, `
		INSERT INTO runtime_jobs(
			task_id,user_id,request_id,execution_id,request_json,status,worker_id,node_id,
			lease_token,fence_epoch,attempt_count,max_attempts,deadline_at,next_attempt_at
		) VALUES(?,?,?,?,?,'ACCEPTED',?,?,?,7,1,3,?,UTC_TIMESTAMP(6))
	`, taskID, uid, "topology-race-request", "topology-race-execution", `{}`,
		worker.WorkerID, worker.NodeID, "topology-race-lease", time.Now().UTC().Add(time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	jobID, _ := jobResult.LastInsertId()

	start := make(chan struct{})
	errCh := make(chan error, rounds*2)
	var wg sync.WaitGroup
	for i := 0; i < rounds; i++ {
		wg.Add(2)
		go func() {
			defer wg.Done()
			<-start
			if err := repo.HeartbeatRuntimeWorker(ctx, worker); err != nil {
				errCh <- fmt.Errorf("heartbeat: %w", err)
			}
		}()
		go func() {
			defer wg.Done()
			<-start
			if _, _, err := repo.MarkStaleRuntimeTopology(ctx, time.Now().UTC().Add(-time.Minute)); err != nil {
				errCh <- fmt.Errorf("mark stale: %w", err)
			}
		}()
	}
	close(start)
	wg.Wait()
	close(errCh)
	for err := range errCh {
		t.Error(err)
	}
	if t.Failed() {
		return
	}

	// A final heartbeat/scan pair proves convergence without timing sleeps. The
	// stale predicate is rechecked by the UPDATE, so this active heartbeat wins.
	if err := repo.HeartbeatRuntimeWorker(ctx, worker); err != nil {
		t.Fatal(err)
	}
	if _, _, err := repo.MarkStaleRuntimeTopology(ctx, time.Now().UTC().Add(-time.Minute)); err != nil {
		t.Fatal(err)
	}

	var workerStatus, staleStatus, nodeStatus string
	var capacity, workerCount, activeExecutions int
	if err := database.QueryRowContext(ctx, `SELECT status FROM runtime_workers WHERE worker_id=?`, worker.WorkerID).Scan(&workerStatus); err != nil {
		t.Fatal(err)
	}
	if err := database.QueryRowContext(ctx, `SELECT status FROM runtime_workers WHERE worker_id=?`, stale.WorkerID).Scan(&staleStatus); err != nil {
		t.Fatal(err)
	}
	if err := database.QueryRowContext(ctx, `SELECT status, capacity, worker_count, active_executions FROM runtime_nodes WHERE node_id=?`, worker.NodeID).
		Scan(&nodeStatus, &capacity, &workerCount, &activeExecutions); err != nil {
		t.Fatal(err)
	}
	if workerStatus != "ACTIVE" || nodeStatus != "ACTIVE" {
		t.Fatalf("live topology did not converge: worker=%s node=%s", workerStatus, nodeStatus)
	}
	if staleStatus != "OFFLINE" {
		t.Fatalf("stale worker status=%s, want OFFLINE", staleStatus)
	}
	if capacity != 3 || workerCount != 1 || activeExecutions != 1 {
		t.Fatalf("node aggregate capacity=%d workers=%d active=%d", capacity, workerCount, activeExecutions)
	}
	var executionID, jobStatus, taskStatus string
	var fenceEpoch int64
	if err := database.QueryRowContext(ctx, `
		SELECT j.execution_id,j.fence_epoch,j.status,t.status
		FROM runtime_jobs j JOIN tasks t ON t.id=j.task_id WHERE j.id=?
	`, jobID).Scan(&executionID, &fenceEpoch, &jobStatus, &taskStatus); err != nil {
		t.Fatal(err)
	}
	if executionID != "topology-race-execution" || fenceEpoch != 7 || jobStatus != "ACCEPTED" || taskStatus != "RUNNING" {
		t.Fatalf("topology maintenance changed task/job/fence: execution=%s fence=%d job=%s task=%s",
			executionID, fenceEpoch, jobStatus, taskStatus)
	}
}
