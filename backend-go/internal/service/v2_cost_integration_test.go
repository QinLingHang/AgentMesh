package service

import (
	"context"
	"testing"
	"time"

	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/repository"
)

func TestV2CostAccountingAggregationIsolationAndFilters(t *testing.T) {
	database, _ := p2Database(t)
	ctx := context.Background()
	repo := repository.NewMySQL(database)
	governance, err := NewGovernanceService(repo, "v2-cost-test-master-key-32-bytes")
	if err != nil {
		t.Fatal(err)
	}

	insert := func(query string, args ...any) int64 {
		t.Helper()
		result, execErr := database.Exec(query, args...)
		if execErr != nil {
			t.Fatal(execErr)
		}
		id, idErr := result.LastInsertId()
		if idErr != nil {
			t.Fatal(idErr)
		}
		return id
	}

	owner := insert("INSERT INTO users(email,password_hash,display_name) VALUES('v2-cost-owner@example.test','fixture','Owner')")
	viewer := insert("INSERT INTO users(email,password_hash,display_name) VALUES('v2-cost-viewer@example.test','fixture','Viewer')")
	outsider := insert("INSERT INTO users(email,password_hash,display_name) VALUES('v2-cost-outsider@example.test','fixture','Outsider')")
	project := insert("INSERT INTO projects(user_id,name,description) VALUES(?,'V2 Cost Project','fixture')", owner)
	foreignProject := insert("INSERT INTO projects(user_id,name,description) VALUES(?,'Foreign V2 Cost Project','fixture')", outsider)

	if _, err = governance.AddMember(ctx, owner, project, "v2-cost-viewer@example.test", "VIEWER"); err != nil {
		t.Fatal(err)
	}

	ownerProject := project
	viewerProject := project
	foreign := foreignProject
	governance.RecordRunCost(ctx, model.RunCostRecord{
		TaskID: 81001, UserID: owner, ProjectID: &ownerProject,
		Provider: "mock", ModelName: "mock-v2",
		InputTokens: 100, OutputTokens: 50, TotalTokens: 150,
		EstimatedCost: 0.01, CostStatus: "estimated",
	})
	// Same run can contain multiple model phases. The repository must accumulate
	// usage instead of overwriting the first phase.
	governance.RecordRunCost(ctx, model.RunCostRecord{
		TaskID: 81001, UserID: owner, ProjectID: &ownerProject,
		Provider: "mock", ModelName: "mock-v2",
		InputTokens: 20, OutputTokens: 10, TotalTokens: 30,
		EstimatedCost: 0.002, CostStatus: "estimated",
	})
	governance.RecordRunCost(ctx, model.RunCostRecord{
		TaskID: 81002, UserID: viewer, ProjectID: &viewerProject,
		Provider: "openai_compatible", ModelName: "vision-v2",
		InputTokens: 200, OutputTokens: 100, TotalTokens: 300,
		EstimatedCost: 0, CostStatus: "unavailable",
	})
	governance.RecordRunCost(ctx, model.RunCostRecord{
		TaskID: 81003, UserID: outsider, ProjectID: &foreign,
		Provider: "mock", ModelName: "foreign-model",
		InputTokens: 999, OutputTokens: 1, TotalTokens: 1000,
		EstimatedCost: 9.99, CostStatus: "estimated",
	})

	run, err := governance.RunCost(ctx, owner, 81001)
	if err != nil {
		t.Fatal(err)
	}
	if run.InputTokens != 120 || run.OutputTokens != 60 || run.TotalTokens != 180 || run.EstimatedCost != 0.012 {
		t.Fatalf("run accumulation mismatch: %+v", run)
	}
	if _, err = governance.RunCost(ctx, viewer, 81001); err != ErrNotFound {
		t.Fatalf("run cost must remain user scoped, got %v", err)
	}

	ownerSummary, err := governance.CostSummary(ctx, owner, nil, model.CostQuery{})
	if err != nil {
		t.Fatal(err)
	}
	if ownerSummary.RunCount != 1 || ownerSummary.TotalTokens != 180 || ownerSummary.KnownCostRuns != 1 || ownerSummary.UnknownCostRuns != 0 {
		t.Fatalf("owner cost summary mismatch: %+v", ownerSummary)
	}

	projectSummary, err := governance.CostSummary(ctx, viewer, &project, model.CostQuery{})
	if err != nil {
		t.Fatal(err)
	}
	if projectSummary.RunCount != 2 || projectSummary.TotalTokens != 480 || projectSummary.KnownCostRuns != 1 || projectSummary.UnknownCostRuns != 1 {
		t.Fatalf("project aggregation mismatch: %+v", projectSummary)
	}

	filtered, err := governance.CostSummary(ctx, owner, &project, model.CostQuery{Provider: "mock", ModelName: "mock-v2"})
	if err != nil {
		t.Fatal(err)
	}
	if filtered.RunCount != 1 || filtered.TotalTokens != 180 || len(filtered.Breakdown) != 1 {
		t.Fatalf("provider/model filter mismatch: %+v", filtered)
	}

	// Preserve the existing governance IDOR-hiding contract: unrelated users must not
	// learn whether a foreign project exists, so project-scoped cost access
	// returns ErrNotFound rather than ErrForbidden.
	if _, err = governance.CostSummary(ctx, outsider, &project, model.CostQuery{}); err != ErrNotFound {
		t.Fatalf("foreign project cost must be hidden as not found, got %v", err)
	}

	from := time.Now().Add(time.Hour)
	to := time.Now()
	if _, err = governance.CostSummary(ctx, owner, nil, model.CostQuery{From: &from, To: &to}); err != ErrInvalidInput {
		t.Fatalf("invalid time range must fail closed, got %v", err)
	}
}
