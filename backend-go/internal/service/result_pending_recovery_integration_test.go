package service

import (
	"context"
	"testing"
	"time"

	"example.com/agentmesh-control-plane/internal/model"
)

// Uses the ordinary Durable Runtime MySQL fixture. The test intentionally skips when no
// isolated test DSN is configured; it must never mutate the user's DB.
func TestEventDeliveryResultPendingHeartbeatSurvivesBrokerDelay(t *testing.T) {
	s, repo, uid := p8Fixture(t)
	ctx := context.Background()
	result := p8Run(t, s, uid, "result pending Kafka")
	worker := model.RuntimeWorker{WorkerID: "worker-event-delivery", Endpoint: "http://worker.invalid", Capacity: 1}
	if err := repo.HeartbeatRuntimeWorker(ctx, worker); err != nil {
		t.Fatal(err)
	}
	job, _, err := repo.ClaimNextRuntimeJob(ctx, worker.WorkerID, "lease-event-delivery", 2*time.Second)
	if err != nil || job == nil {
		t.Fatalf("claim: %#v %v", job, err)
	}
	if result.Task.ID != job.TaskID {
		t.Fatalf("wrong job for task: %#v", job)
	}
	ok, err := repo.MarkRuntimeJobDispatching(ctx, job.ID, worker.WorkerID, "lease-event-delivery")
	if err != nil || !ok {
		t.Fatalf("dispatch: %v %v", ok, err)
	}
	ok, err = repo.MarkRuntimeJobAccepted(ctx, job.ID, worker.WorkerID, "lease-event-delivery")
	if err != nil || !ok {
		t.Fatalf("accept: %v %v", ok, err)
	}

	lease := model.RuntimeExecutionLeaseRef{
		JobID: job.ID, ExecutionID: job.ExecutionID, LeaseToken: "lease-event-delivery",
		FenceEpoch: job.FenceEpoch, ResultPending: true,
	}
	terminal, err := s.Heartbeat(ctx, worker, []model.RuntimeExecutionLeaseRef{lease})
	if err != nil || len(terminal) != 0 {
		t.Fatalf("pending ack: %v %v", terminal, err)
	}
	pending, err := repo.RuntimeJobByID(ctx, job.ID)
	if err != nil || pending.Status != "RESULT_PENDING" || pending.LeaseExpiresAt == nil {
		t.Fatalf("result must be durable pending with renewable lease: %#v %v", pending, err)
	}
	// An expired execution lease must not fail a result already in the outbox.
	requeued, failed, err := repo.RecoverLostAcceptedRuntimeJobs(ctx, time.Now().Add(time.Hour), 0, 50)
	if err != nil || requeued != 0 || failed != 0 {
		t.Fatalf("outbox result incorrectly recovered as worker-loss: %d %d %v", requeued, failed, err)
	}
	begun, err := repo.BeginRuntimeJobCallback(ctx, job.ID, job.ExecutionID, worker.WorkerID, "lease-event-delivery")
	if err != nil || !begun {
		t.Fatalf("pending result must enter callback: %v %v", begun, err)
	}
	// A slow COMPLETING callback must not be failed by the deadline reaper;
	// Kafka replay can still finish it after a consumer/process crash.
	expired, err := repo.ListExpiredAcceptedRuntimeJobs(ctx, time.Now().Add(time.Hour), 50)
	if err != nil {
		t.Fatal(err)
	}
	for _, candidate := range expired {
		if candidate.ID == job.ID {
			t.Fatalf("COMPLETING callback incorrectly treated as expired: %#v", candidate)
		}
	}
	if err := repo.MarkRuntimeJobCompleted(ctx, job.ID); err != nil {
		t.Fatal(err)
	}
	terminal, err = s.Heartbeat(ctx, worker, []model.RuntimeExecutionLeaseRef{lease})
	if err != nil || len(terminal) != 1 || terminal[0] != job.ExecutionID {
		t.Fatalf("missing precise business ack: %v %v", terminal, err)
	}
}
