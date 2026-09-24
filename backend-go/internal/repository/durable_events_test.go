package repository

import "testing"

func TestKnowledgeRuntimeDurableEventFingerprintSeparatesFenceAndExecution(t *testing.T) {
	original := durableEventFingerprint("RUNNING", "LEASED", "execution-a", 1)
	if original != durableEventFingerprint("RUNNING", "LEASED", "execution-a", 1) {
		t.Fatal("identical snapshots must deduplicate")
	}
	for _, candidate := range []string{
		durableEventFingerprint("RUNNING", "LEASED", "execution-a", 2),
		durableEventFingerprint("RUNNING", "LEASED", "execution-b", 1),
		durableEventFingerprint("QUEUED", "LEASED", "execution-a", 1),
		durableEventFingerprint("RUNNING", "ACCEPTED", "execution-a", 1),
	} {
		if original == candidate {
			t.Fatal("distinct task states, attempts or fences cannot share a replay key")
		}
	}
}

func TestKnowledgeRuntimeWorkerPhaseFingerprintDedupesByAttemptAndOrdinal(t *testing.T) {
	base := workerPhaseFingerprint("exec-a", 2, 1)
	if base != workerPhaseFingerprint("exec-a", 2, 1) {
		t.Fatal("worker phase must be idempotent")
	}
	for _, other := range []string{
		workerPhaseFingerprint("exec-a", 3, 1),
		workerPhaseFingerprint("exec-b", 2, 1),
		workerPhaseFingerprint("exec-a", 2, 2),
		durableEventFingerprint("RUNNING", "ACCEPTED", "exec-a", 2),
	} {
		if base == other {
			t.Fatal("two phases, attempts or event types must not share one replay key")
		}
	}
}
