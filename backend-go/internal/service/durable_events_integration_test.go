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

type captureDurableLiveStream struct {
	events []model.DurableLiveDelta
}

func (s *captureDurableLiveStream) AppendDelta(_ context.Context, event model.DurableLiveDelta) (string, bool, error) {
	for _, existing := range s.events {
		if existing.FenceEpoch == event.FenceEpoch && existing.Ordinal == event.Ordinal {
			if existing.ExecutionID == event.ExecutionID && existing.Delta == event.Delta {
				return "duplicate", false, nil
			}
			return "", false, errors.New("ordinal conflict")
		}
	}
	s.events = append(s.events, event)
	return "captured", true, nil
}

func (s *captureDurableLiveStream) ReadDeltas(_ context.Context, _ int64, _ string, _ int64) ([]model.DurableLiveDelta, error) {
	return append([]model.DurableLiveDelta(nil), s.events...), nil
}

func TestDurableWorkerDeltaRequiresCurrentFenceAndLease(t *testing.T) {
	s, repo, uid := p8Fixture(t)
	ctx := context.Background()
	capture := &captureDurableLiveStream{}
	s.SetLiveStreamStore(capture)

	submitted := p8Run(t, s, uid, "durable live delta fence")
	if err := repo.HeartbeatRuntimeWorker(ctx, model.RuntimeWorker{
		WorkerID: "delta-worker", Endpoint: "http://runtime.invalid:9572", Capacity: 1,
	}); err != nil {
		t.Fatal(err)
	}
	const lease = "delta-worker-lease"
	job, _, err := repo.ClaimNextRuntimeJob(ctx, "delta-worker", lease, time.Second)
	if err != nil || job == nil {
		t.Fatalf("claim: job=%+v err=%v", job, err)
	}
	if ok, err := repo.MarkRuntimeJobDispatching(ctx, job.ID, "delta-worker", lease); err != nil || !ok {
		t.Fatalf("dispatching: ok=%v err=%v", ok, err)
	}
	if ok, err := repo.MarkRuntimeJobAccepted(ctx, job.ID, "delta-worker", lease); err != nil || !ok {
		t.Fatalf("accepted: ok=%v err=%v", ok, err)
	}

	accepted, err := s.WorkerDelta(ctx, job.ID, DurableWorkerDelta{
		WorkerID: "delta-worker", ExecutionID: job.ExecutionID, LeaseToken: lease,
		FenceEpoch: job.FenceEpoch, Ordinal: 1, Type: "delta", Delta: "hello",
	})
	if err != nil || !accepted || len(capture.events) != 1 {
		t.Fatalf("current delta rejected: accepted=%v events=%+v err=%v", accepted, capture.events, err)
	}
	if capture.events[0].TaskID != submitted.Task.ID || capture.events[0].Delta != "hello" {
		t.Fatalf("unexpected captured delta: %+v", capture.events[0])
	}

	staleAttempts := []struct {
		name  string
		delta DurableWorkerDelta
	}{
		{name: "execution", delta: DurableWorkerDelta{
			WorkerID: "delta-worker", ExecutionID: "stale-execution", LeaseToken: lease,
			FenceEpoch: job.FenceEpoch, Ordinal: 2, Type: "delta", Delta: "stale",
		}},
		{name: "worker", delta: DurableWorkerDelta{
			WorkerID: "stale-worker", ExecutionID: job.ExecutionID, LeaseToken: lease,
			FenceEpoch: job.FenceEpoch, Ordinal: 2, Type: "delta", Delta: "stale",
		}},
		{name: "lease", delta: DurableWorkerDelta{
			WorkerID: "delta-worker", ExecutionID: job.ExecutionID, LeaseToken: "stale-lease",
			FenceEpoch: job.FenceEpoch, Ordinal: 2, Type: "delta", Delta: "stale",
		}},
		{name: "fence", delta: DurableWorkerDelta{
			WorkerID: "delta-worker", ExecutionID: job.ExecutionID, LeaseToken: lease,
			FenceEpoch: job.FenceEpoch + 1, Ordinal: 2, Type: "delta", Delta: "stale",
		}},
	}
	for _, attempt := range staleAttempts {
		t.Run(attempt.name, func(t *testing.T) {
			accepted, err := s.WorkerDelta(ctx, job.ID, attempt.delta)
			if err != nil || accepted || len(capture.events) != 1 {
				t.Fatalf("stale %s must be ignored: accepted=%v events=%+v err=%v", attempt.name, accepted, capture.events, err)
			}
		})
	}
}
