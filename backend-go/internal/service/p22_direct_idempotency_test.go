package service

import (
	"testing"

	"example.com/agentmesh-control-plane/internal/model"
)

func TestP22DirectIdentityIsStableAndRejectsPayloadReuse(t *testing.T) {
	input := RunTaskInput{
		ClientRequestID: "direct_123456789", Task: "检查订单", Scheduler: "adaptive",
		ModelSelection: model.ModelSelection{Mode: "auto"},
	}
	key1, fingerprint1, err := directRequestIdentity(input)
	if err != nil || key1 != "direct_123456789" || len(fingerprint1) != 64 {
		t.Fatalf("unexpected first identity: %q %q %v", key1, fingerprint1, err)
	}
	key2, fingerprint2, err := directRequestIdentity(input)
	if err != nil || key1 != key2 || fingerprint1 != fingerprint2 {
		t.Fatalf("same request must preserve identity")
	}
	input.Task = "删除订单"
	_, changedFingerprint, err := directRequestIdentity(input)
	if err != nil || fingerprint1 == changedFingerprint {
		t.Fatalf("same key with a changed payload must conflict")
	}
	input.ClientRequestID = "bad request id"
	if _, _, err = directRequestIdentity(input); err != ErrInvalidInput {
		t.Fatalf("malformed id must be rejected, got %v", err)
	}
}

func TestP22DirectReplayNeverClaimsPendingCompleted(t *testing.T) {
	task := &model.Task{Status: "RUNNING", TaskText: "查询订单", RequestID: "req"}
	result := replayDirectTask(task)
	if result.Status != "RUNNING" || result.TaskProfile["idempotentReplay"] != true {
		t.Fatalf("pending replay has wrong status: %+v", result)
	}
	answer := "已查到订单"
	task.Status = "COMPLETED"
	task.ResultText = &answer
	result = replayDirectTask(task)
	if result.Answer != answer || result.Status != "COMPLETED" {
		t.Fatalf("completed replay failed: %+v", result)
	}
}
