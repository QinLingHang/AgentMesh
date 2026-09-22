package service

import (
	"testing"

	"example.com/agentmesh-control-plane/internal/model"
)

func TestRagV11DefaultDoesNotEnableGlobal(t *testing.T) {
	withProject := normalizeRagPolicy(model.RagPolicy{}, true)
	if withProject.Mode != model.RagModeAuto || len(withProject.Scopes) != 1 || withProject.Scopes[0] != model.RagScopeProject {
		t.Fatalf("project default must be AUTO + PROJECT, got %+v", withProject)
	}
	withoutProject := normalizeRagPolicy(model.RagPolicy{}, false)
	if withoutProject.Mode != model.RagModeAuto || len(withoutProject.Scopes) != 0 {
		t.Fatalf("no-project default must have empty scope: %+v", withoutProject)
	}
}

func TestRagV11ExplicitEmptyScopesDoesNotFallback(t *testing.T) {
	policy := normalizeRagPolicy(model.RagPolicy{Mode: model.RagModeOn, Scopes: []model.RagScope{}}, true)
	if len(policy.Scopes) != 0 {
		t.Fatalf("explicit empty scopes broadened to %v", policy.Scopes)
	}
}

func TestRagV11GlobalMustBeExplicit(t *testing.T) {
	policy := normalizeRagPolicy(model.RagPolicy{Scopes: []model.RagScope{model.RagScopeUserGlobal}}, true)
	if len(policy.Scopes) != 1 || policy.Scopes[0] != model.RagScopeUserGlobal {
		t.Fatalf("explicit global scope not honored: %+v", policy)
	}
}

func TestRagV11SnapshotIsUpperBoundAfterRevocation(t *testing.T) {
	snapshot := model.EffectiveRagPolicy{
		Mode: model.RagModeOn, AllowedScopes: []model.RagScope{model.RagScopeProject},
		AllowedKnowledgeBaseIDs: []int64{10, 11}, ExplicitlySelectedIDs: []int64{10}, PolicyVersion: "rag-v1.1",
	}
	live := model.EffectiveRagPolicy{AllowedKnowledgeBaseIDs: []int64{11, 12}}
	catalog := []model.KnowledgeCatalogItem{{KnowledgeBaseID: 11, Name: "still allowed"}, {KnowledgeBaseID: 12, Name: "newly granted"}}
	effective, visible := constrainEffectiveRagPolicyToSnapshot(snapshot, live, catalog)
	if len(effective.AllowedKnowledgeBaseIDs) != 1 || effective.AllowedKnowledgeBaseIDs[0] != 11 || len(effective.ExplicitlySelectedIDs) != 0 || len(visible) != 1 || visible[0].KnowledgeBaseID != 11 {
		t.Fatalf("snapshot/live intersection incorrect: effective=%+v catalog=%+v", effective, visible)
	}
}

func TestP22RouteExplicitReliabilityWins(t *testing.T) {
	svc := &TaskService{}
	in := RunTaskInput{Task: "你好", Constraints: model.TaskConstraints{RetryOnWorkerLoss: true}}
	route := svc.DecideDeliveryMode(in)
	if route.Mode != "durable" || route.Reason != "retry_on_worker_loss" {
		t.Fatalf("unexpected route: %+v", route)
	}
}

func TestP22RouteLongTaskAndShortChat(t *testing.T) {
	svc := &TaskService{}
	if got := svc.DecideDeliveryMode(RunTaskInput{Task: "检查整个仓库，运行所有测试"}); got.Mode != "durable" || got.Reason != "long_running_intent" {
		t.Fatalf("long work must use reliable queue: %+v", got)
	}
	if got := svc.DecideDeliveryMode(RunTaskInput{Task: "你好"}); got.Mode != "direct" {
		t.Fatalf("ordinary chat should stay interactive: %+v", got)
	}
}
