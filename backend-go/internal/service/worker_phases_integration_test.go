package service

import (
	"context"
	"errors"
	"testing"
	"time"

	"example.com/agentmesh-control-plane/internal/model"
)

// The durable-runtime fixture uses an isolated disposable database; never use development DB.
func TestKnowledgeRuntimeWorkerPhaseFenceDedupeAndOwnerReplay(t *testing.T) {
	s, repo, uid := p8Fixture(t)
	ctx := context.Background()
	taskID := p8Run(t, s, uid, "worker phase journal").Task.ID
	if err := repo.HeartbeatRuntimeWorker(ctx, model.RuntimeWorker{
		WorkerID: "phase-worker", Endpoint: "http://runtime.invalid:9572", Capacity: 1,
	}); err != nil {
		t.Fatal(err)
	}
	job, _, err := repo.ClaimNextRuntimeJob(ctx, "phase-worker", "phase-test-lease", 30*time.Second)
	if err != nil || job == nil || job.FenceEpoch <= 0 {
		t.Fatalf("claim job: %+v %v", job, err)
	}
	if accepted, err := repo.MarkRuntimeJobDispatching(ctx, job.ID, "phase-worker", "phase-test-lease"); err != nil || !accepted {
		t.Fatalf("dispatch: %t %v", accepted, err)
	}
	if accepted, err := repo.MarkRuntimeJobAccepted(ctx, job.ID, "phase-worker", "phase-test-lease"); err != nil || !accepted {
		t.Fatalf("accept: %t %v", accepted, err)
	}
	phase := DurableWorkerPhase{
		WorkerID: "phase-worker", ExecutionID: job.ExecutionID, LeaseToken: "phase-test-lease",
		FenceEpoch: job.FenceEpoch, Ordinal: 1, Phase: "tool", Status: "running",
	}
	if accepted, err := s.WorkerPhase(ctx, job.ID, phase); err != nil || !accepted {
		t.Fatalf("phase accepted: %t %v", accepted, err)
	}
	if accepted, err := s.WorkerPhase(ctx, job.ID, phase); err != nil || accepted {
		t.Fatalf("duplicate must not insert again: %t %v", accepted, err)
	}
	wrong := phase
	wrong.FenceEpoch++
	if accepted, err := s.WorkerPhase(ctx, job.ID, wrong); err != nil || accepted {
		t.Fatalf("stale fence must not insert: %t %v", accepted, err)
	}
	wrong = phase
	wrong.LeaseToken = "wrong-lease"
	wrong.Ordinal = 2
	if accepted, err := s.WorkerPhase(ctx, job.ID, wrong); err != nil || accepted {
		t.Fatalf("wrong lease must not insert: %t %v", accepted, err)
	}
	if _, _, err := s.TaskEvents(ctx, uid+1, taskID, 0); !errors.Is(err, ErrNotFound) {
		t.Fatalf("cross-user event replay must be rejected: %v", err)
	}
	events, _, err := s.TaskEvents(ctx, uid, taskID, 0)
	if err != nil {
		t.Fatal(err)
	}
	traceCount := 0
	for _, event := range events {
		if event.EventType == "trace" {
			traceCount++
			if event.Phase != "tool" || event.PhaseStatus != "running" || event.FenceEpoch != job.FenceEpoch {
				t.Fatalf("unexpected worker phase: %+v", event)
			}
		}
	}
	if traceCount != 1 {
		t.Fatalf("one worker phase should be replayed, got %d: %+v", traceCount, events)
	}
	if _, err := repo.CancelRuntimeTask(ctx, uid, taskID); err != nil {
		t.Fatal(err)
	}
	phase.Ordinal = 3
	if accepted, err := s.WorkerPhase(ctx, job.ID, phase); err != nil || accepted {
		t.Fatalf("cancelled task cannot accept phases: %t %v", accepted, err)
	}
}

func TestKnowledgeRuntimeWorkerPhaseRejectsUntrustedMetadata(t *testing.T) {
	s := &DurableRuntimeService{}
	for _, invalid := range []DurableWorkerPhase{
		{WorkerID: "w", ExecutionID: "e", LeaseToken: "l", FenceEpoch: 1, Ordinal: 1, Phase: "payment_details", Status: "running"},
		{WorkerID: "w", ExecutionID: "e", LeaseToken: "l", FenceEpoch: 1, Ordinal: 1, Phase: "tool", Status: "secret"},
		{WorkerID: "w", ExecutionID: "e", LeaseToken: "l", FenceEpoch: 0, Ordinal: 1, Phase: "tool", Status: "running"},
		{WorkerID: "w", ExecutionID: "e", LeaseToken: "l", FenceEpoch: 1, Ordinal: 257, Phase: "tool", Status: "running"},
	} {
		if _, err := s.WorkerPhase(context.Background(), 1, invalid); !errors.Is(err, ErrInvalidInput) {
			t.Fatalf("invalid phase was not rejected: %+v, err=%v", invalid, err)
		}
	}
}
