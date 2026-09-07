package service

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/repository"
	runtimeclient "example.com/agentmesh-control-plane/internal/runtime"
)

// Reuses the existing isolated-MySQL fixture from P2 so P6 validates the real
// TaskService -> MessageRepository persistence path instead of a mock metadata
// container. The test is skipped only when the existing integration DSN is not
// configured, matching the project's established acceptance-test convention.
func TestP6ScorecardPersistsInAssistantMessageMetadata(t *testing.T) {
	database, _ := p2Database(t)
	ctx := context.Background()
	repo := repository.NewMySQL(database)

	insert := func(query string, args ...any) int64 {
		t.Helper()
		result, err := database.Exec(query, args...)
		if err != nil {
			t.Fatal(err)
		}
		id, err := result.LastInsertId()
		if err != nil {
			t.Fatal(err)
		}
		return id
	}

	uid := insert("INSERT INTO users(email,password_hash,display_name) VALUES('p6-scorecard@example.test','fixture','P6 Scorecard')")
	conversationID := insert("INSERT INTO conversations(user_id,title) VALUES(?,'P6 persistence')", uid)
	insert("INSERT INTO agents(user_id,name,endpoint,protocol,capabilities_json) VALUES(?,'General','internal://general','internal','[\"general\"]')", uid)

	expectedScore := 0.873
	runtimeServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/internal/v1/runtime/execute" {
			http.Error(w, "unexpected runtime request", http.StatusBadRequest)
			return
		}
		response := map[string]any{
			"request_id":      "fixture",
			"status":          "COMPLETED",
			"answer":          "fixture answer",
			"scheduler":       "greedy",
			"task_profile":    map[string]any{"required_capabilities": []string{"general"}, "complexity": "low", "risk_level": "low", "modality": []string{"text"}, "parallelizable": false},
			"selected_agents": []string{"General"},
			"estimated_cost":  0.01,
			"elapsed_ms":      12,
			"trace":           []map[string]any{{"kind": "task", "title": "Task Completed", "status": "completed"}},
			"dag":             map[string]any{"nodes": []any{}, "edges": []any{}},
			"agent_feedback":  []any{},
			"observability":   map[string]any{"modelCalls": 1, "modelCostKnown": true, "modelEstimatedCost": 0.0},
			"scorecard": map[string]any{
				"evaluator":          "p6_deterministic_v1",
				"status":             "pass",
				"overallScore":       expectedScore,
				"taskSuccess":        1.0,
				"answerQuality":      0.9,
				"groundedness":       1.0,
				"toolReliability":    1.0,
				"ragQuality":         1.0,
				"memoryContribution": 1.0,
				"budgetCompliance":   1.0,
				"latencyMs":          12,
				"estimatedCost":      0.01,
				"modelEstimatedCost": 0.0,
				"modelTokens":        42,
				"failureCategory":    "none",
				"violations":         []string{},
				"signals":            map[string]any{"ragMode": "not_required"},
			},
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(response)
	}))
	defer runtimeServer.Close()

	profiles := NewProjectRuntimeService(repo)
	tasks := NewTaskService(
		repo,
		repo,
		repo,
		runtimeclient.NewClient(runtimeServer.URL, "fixture", 5*time.Second),
		repo,
		repo,
		profiles,
	)

	result, err := tasks.Run(ctx, uid, RunTaskInput{
		ConversationID: &conversationID,
		Task:           "validate p6 scorecard persistence",
		Scheduler:      "greedy",
		Planner:        "heuristic",
		ExecutionMode:  "sequential",
		SynthesisMode:  "never",
		Constraints:    model.TaskConstraints{MaxLatencyMS: 5000, MaxCost: .2, MinQuality: .5},
	})
	if err != nil {
		t.Fatal(err)
	}
	if result.Scorecard == nil || result.Scorecard.OverallScore != expectedScore {
		t.Fatalf("runtime scorecard not transported: %+v", result.Scorecard)
	}

	messages, err := repo.ListMessages(ctx, uid, conversationID, 20)
	if err != nil {
		t.Fatal(err)
	}
	var assistant *model.Message
	for i := range messages {
		if messages[i].Role == "assistant" && messages[i].Status == "COMPLETED" {
			assistant = &messages[i]
		}
	}
	if assistant == nil {
		t.Fatal("completed assistant message not persisted")
	}
	raw, ok := assistant.Metadata["scorecard"]
	if !ok || raw == nil {
		t.Fatalf("scorecard missing from persisted metadata: %+v", assistant.Metadata)
	}
	payload, ok := raw.(map[string]any)
	if !ok {
		t.Fatalf("unexpected persisted scorecard type %T", raw)
	}
	got, _ := payload["overallScore"].(float64)
	if got != expectedScore {
		t.Fatalf("persisted overallScore=%v want=%v payload=%+v", got, expectedScore, payload)
	}
	if _, exists := payload["answer"]; exists {
		t.Fatal("raw answer must not be embedded inside scorecard metadata")
	}
}
