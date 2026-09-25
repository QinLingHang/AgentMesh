package service

import (
	"context"
	"errors"
	"testing"
	"time"

	"example.com/agentmesh-control-plane/internal/model"
)

// Uses p2Database's isolated test database. It must never run against a
// development or production database: the fixture creates/drops its own DB.
func TestKnowledgeRuntimeDurableEventReplayOwnershipAndFence(t *testing.T) {
	s, repo, uid := p8Fixture(t)
	ctx := context.Background()
	submitted := p8Run(t, s, uid, "event journal integration")
	taskID := submitted.Task.ID
	initial, status, err := s.TaskEvents(ctx, uid, taskID, 0)
	if err != nil || status != "QUEUED" || len(initial) != 1 || initial[0].Status != "QUEUED" {
		t.Fatalf("initial event: events=%+v status=%s error=%v", initial, status, err)
	}
	cursor := initial[0].Sequence
	if cursor <= 0 || initial[0].FenceEpoch != 0 {
		t.Fatalf("invalid queue cursor/fence: %+v", initial[0])
	}

	// Repeated polling cannot produce a second event for the same state.
	replayed, _, err := s.TaskEvents(ctx, uid, taskID, 0)
	if err != nil || len(replayed) != 1 || replayed[0].Sequence != cursor {
		t.Fatalf("replay is not stable: events=%+v error=%v", replayed, err)
	}
	noChanges, _, err := s.TaskEvents(ctx, uid, taskID, cursor)
	if err != nil || len(noChanges) != 0 {
		t.Fatalf("duplicate event: %+v error=%v", noChanges, err)
	}
	if _, _, err := s.TaskEvents(ctx, uid+999, taskID, 0); !errors.Is(err, ErrNotFound) {
		t.Fatalf("cross-user event read must be rejected, got %v", err)
	}

	if err := repo.HeartbeatRuntimeWorker(ctx, model.RuntimeWorker{
		WorkerID: "knowledge-runtime-events-worker", Endpoint: "http://runtime.invalid:9572", Capacity: 1,
	}); err != nil {
		t.Fatal(err)
	}
	job, _, err := repo.ClaimNextRuntimeJob(ctx, "knowledge-runtime-events-worker", "knowledge-runtime-events-lease", time.Second)
	if err != nil || job == nil {
		t.Fatalf("could not claim event test job: %+v, %v", job, err)
	}
	running, status, err := s.TaskEvents(ctx, uid, taskID, cursor)
	if err != nil || status != "RUNNING" || len(running) != 1 || running[0].FenceEpoch != job.FenceEpoch {
		t.Fatalf("leased event: %+v status=%s err=%v", running, status, err)
	}
	if running[0].Sequence <= cursor {
		t.Fatal("sequence must advance after lease")
	}
	cursor = running[0].Sequence

	if _, err := repo.CancelRuntimeTask(ctx, uid, taskID); err != nil {
		t.Fatal(err)
	}
	canceled, status, err := s.TaskEvents(ctx, uid, taskID, cursor)
	if err != nil || status != "CANCELED" || len(canceled) != 1 || canceled[0].Status != "CANCELED" {
		t.Fatalf("cancellation event: %+v status=%s err=%v", canceled, status, err)
	}
	// Replay a history from zero, even after terminal completion.
	all, _, err := s.TaskEvents(ctx, uid, taskID, 0)
	if err != nil || len(all) != 3 {
		t.Fatalf("expected queued/leased/canceled history: %+v err=%v", all, err)
	}
	for i := 1; i < len(all); i++ {
		if all[i].Sequence <= all[i-1].Sequence {
			t.Fatalf("replay sequence must increase: %+v", all)
		}
	}
}
