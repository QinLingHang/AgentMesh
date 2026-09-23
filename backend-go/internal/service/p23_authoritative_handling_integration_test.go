package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/repository"
	runtimeclient "example.com/agentmesh-control-plane/internal/runtime"
)

type p23FrozenHandlingCase struct {
	CaseID           string `json:"caseId"`
	Query            string `json:"query"`
	ExpectedHandling string `json:"expectedHandling"`
	FixtureID        string `json:"fixtureId"`
}

type p23FrozenHandlingFixtureCatalog struct {
	Fixtures []p23FrozenHandlingFixture `json:"fixtures"`
}

type p23FrozenHandlingFixture struct {
	FixtureID string `json:"fixtureId"`
	CaseID    string `json:"caseId"`
	Tasks     []struct {
		State string `json:"state"`
	} `json:"tasks"`
	ExpectedInvariants map[string]any `json:"expectedInvariants"`
}

type p23AuthoritativeHandlingEvidence struct {
	CaseID           string         `json:"caseId"`
	ExpectedHandling string         `json:"expectedHandling"`
	ActualHandling   string         `json:"actualHandling"`
	Passed           bool           `json:"passed"`
	Evidence         map[string]any `json:"evidence,omitempty"`
}

type p23AuthoritativeHandlingReport struct {
	SchemaVersion string                             `json:"schemaVersion"`
	Scope         string                             `json:"scope"`
	Cases         []p23AuthoritativeHandlingEvidence `json:"cases"`
}

func p23RepositoryRoot(t *testing.T) string {
	t.Helper()
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("cannot resolve P23 handling test source path")
	}
	return filepath.Clean(filepath.Join(filepath.Dir(file), "..", "..", ".."))
}

func p23LoadFrozenHandlingAssets(t *testing.T) ([]p23FrozenHandlingCase, map[string]p23FrozenHandlingFixture) {
	t.Helper()
	root := p23RepositoryRoot(t)
	datasetPath := filepath.Join(root, "runtime-python", "tests", "fixtures", "p23_human_eval_v1.jsonl")
	fixturePath := filepath.Join(root, "runtime-python", "tests", "fixtures", "p23_eval_fixtures_v1.json")

	datasetRaw, err := os.ReadFile(datasetPath)
	if err != nil {
		t.Fatal(err)
	}
	var cases []p23FrozenHandlingCase
	for _, line := range strings.Split(string(datasetRaw), "\n") {
		if strings.TrimSpace(line) == "" {
			continue
		}
		var row p23FrozenHandlingCase
		if err := json.Unmarshal([]byte(line), &row); err != nil {
			t.Fatal(err)
		}
		switch row.ExpectedHandling {
		case "TASK_STATUS", "RESUME", "CANCEL", "APPROVAL_REJECT":
			cases = append(cases, row)
		}
	}

	fixtureRaw, err := os.ReadFile(fixturePath)
	if err != nil {
		t.Fatal(err)
	}
	var catalog p23FrozenHandlingFixtureCatalog
	if err := json.Unmarshal(fixtureRaw, &catalog); err != nil {
		t.Fatal(err)
	}
	fixtures := make(map[string]p23FrozenHandlingFixture, len(catalog.Fixtures))
	for _, fixture := range catalog.Fixtures {
		fixtures[fixture.FixtureID] = fixture
	}
	if len(cases) == 0 {
		t.Fatal("frozen dataset contains no Go-owned P23 handling cases")
	}
	return cases, fixtures
}

func p23ExpectedTaskOperation(handling string) string {
	switch handling {
	case "TASK_STATUS":
		return "GET_TASK_STATUS"
	case "RESUME":
		return "RESUME_TASK"
	case "CANCEL":
		return "CANCEL_TASK"
	case "APPROVAL_REJECT":
		return "APPROVAL_REJECT"
	default:
		return ""
	}
}

func p23CreateDirectTaskFixture(t *testing.T, state string) (*TaskService, *repository.MySQL, int64, int64, *model.Task) {
	t.Helper()
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
	uid := insert("INSERT INTO users(email,password_hash,display_name) VALUES(?,?,?)",
		fmt.Sprintf("p23-handling-%d@example.test", time.Now().UnixNano()), "fixture", "P23 Handling")
	conversationID := insert("INSERT INTO conversations(user_id,title) VALUES(?,'P23 handling fixture')", uid)
	runtimeHTTP := runtimeclient.NewClient("http://127.0.0.1:1", "fixture", time.Second)
	service := NewTaskService(repo, repo, repo, runtimeHTTP, repo, repo)
	created, err := repo.CreateTask(ctx, model.Task{
		UserID: uid, ConversationID: &conversationID, RequestID: fmt.Sprintf("p23-handling-%d", time.Now().UnixNano()),
		TaskText: "frozen handling fixture", Scheduler: "adaptive", Planner: "multi_objective",
		ExecutionMode: "auto", SynthesisMode: "auto",
	}, model.TaskConstraints{MaxLatencyMS: 8000, MaxCost: .15, MinQuality: .8})
	if err != nil {
		t.Fatal(err)
	}
	if state == "INPUT_REQUIRED" {
		continuation := &model.TaskContinuation{Protocol: "a2a", State: "INPUT_REQUIRED", Kind: "input_required", Summary: "fixture input required"}
		if err := repo.SuspendTask(ctx, uid, created.ID, "INPUT_REQUIRED", "needs input", continuation, nil, nil, map[string]any{}, 0, 0); err != nil {
			t.Fatal(err)
		}
		created, err = repo.TaskByID(ctx, uid, created.ID)
		if err != nil {
			t.Fatal(err)
		}
	}
	return service, repo, uid, conversationID, created
}

func p23TaskCount(t *testing.T, repo *repository.MySQL, uid int64) int {
	t.Helper()
	items, err := repo.ListTasks(context.Background(), uid, 100)
	if err != nil {
		t.Fatal(err)
	}
	return len(items)
}

func p23VerifyStatusHandling(t *testing.T) map[string]any {
	t.Helper()
	service, repo, uid, conversationID, created := p23CreateDirectTaskFixture(t, "RUNNING")
	before := p23TaskCount(t, repo, uid)
	resolved, err := service.P23StatusTask(context.Background(), uid, RunTaskInput{ConversationID: &conversationID})
	if err != nil {
		t.Fatal(err)
	}
	if resolved.ID != created.ID || resolved.Status != "RUNNING" {
		t.Fatalf("status resolved wrong task: %+v", resolved)
	}
	after := p23TaskCount(t, repo, uid)
	if before != after {
		t.Fatalf("TASK_STATUS created a new task: before=%d after=%d", before, after)
	}
	return map[string]any{"taskIdReused": true, "createNewTask": false, "status": resolved.Status}
}

func p23VerifyResumeHandling(t *testing.T) map[string]any {
	t.Helper()
	service, repo, uid, conversationID, created := p23CreateDirectTaskFixture(t, "INPUT_REQUIRED")
	before := p23TaskCount(t, repo, uid)
	result, err := service.P23ResumeCurrentTask(context.Background(), uid, RunTaskInput{ConversationID: &conversationID})
	if err != nil {
		t.Fatal(err)
	}
	if result.Task == nil || result.Task.ID != created.ID || result.Task.Status != "INPUT_REQUIRED" {
		t.Fatalf("resume must reference the original suspended task only: %+v", result)
	}
	after := p23TaskCount(t, repo, uid)
	if before != after {
		t.Fatalf("RESUME created a new task: before=%d after=%d", before, after)
	}
	return map[string]any{"taskIdReused": true, "createNewTask": false, "status": result.Task.Status, "automaticReplay": false}
}

func p23VerifyCancelHandling(t *testing.T) map[string]any {
	t.Helper()
	service, repo, uid := p8Fixture(t)
	ctx := context.Background()
	conversation, err := repo.CreateConversation(ctx, uid, "P23 cancel fixture")
	if err != nil {
		t.Fatal(err)
	}
	result, err := service.Run(ctx, uid, RunTaskInput{
		ConversationID: &conversation.ID, Task: "durable cancel fixture", Scheduler: "adaptive", Planner: "multi_objective",
		ExecutionMode: "auto", SynthesisMode: "auto",
		Constraints: model.TaskConstraints{MaxLatencyMS: 8000, MaxCost: .15, MinQuality: .8},
	})
	if err != nil {
		t.Fatal(err)
	}
	before := p23TaskCount(t, repo, uid)
	pending, err := service.taskService.P23PendingTask(ctx, uid, RunTaskInput{ConversationID: &conversation.ID})
	if err != nil || pending.ID != result.Task.ID {
		t.Fatalf("cancel did not resolve original task: task=%+v err=%v", pending, err)
	}
	cancelled, err := service.Cancel(ctx, uid, pending.ID)
	if err != nil {
		t.Fatal(err)
	}
	if cancelled.Status != "CANCELED" {
		t.Fatalf("cancelled status=%s", cancelled.Status)
	}
	after := p23TaskCount(t, repo, uid)
	if before != after {
		t.Fatalf("CANCEL created a new task: before=%d after=%d", before, after)
	}
	return map[string]any{"taskIdReused": true, "createNewTask": false, "status": cancelled.Status}
}

func p23VerifyApprovalRejectHandling(t *testing.T) map[string]any {
	t.Helper()
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
	uid := insert("INSERT INTO users(email,password_hash,display_name) VALUES(?,?,?)",
		fmt.Sprintf("p23-approval-%d@example.test", time.Now().UnixNano()), "fixture", "P23 Approval")
	conversationID := insert("INSERT INTO conversations(user_id,title) VALUES(?,'P23 approval fixture')", uid)
	agentID := insert("INSERT INTO agents(user_id,name,endpoint,protocol,capabilities_json,status) VALUES(?,'P23 Agent','internal://general','internal','[\"general\"]','ACTIVE')", uid)
	insert("INSERT INTO tools(user_id,name,description,protocol,endpoint,input_schema,risk_level,requires_confirmation,enabled) VALUES(?,'record.write','write fixture','http','http://fixture/write','{\"type\":\"object\"}','high',1,1)", uid)

	var runtimeCalls int
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		runtimeCalls++
		var request runtimeclient.ExecuteRequest
		if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		if request.Task != "reject" {
			http.Error(w, "unexpected approval decision", http.StatusConflict)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]any{
			"request_id": request.RequestID, "status": "COMPLETED", "answer": "approval rejected",
			"selected_agents": []string{"P23 Agent"}, "trace": []any{}, "dag": map[string]any{},
			"elapsed_ms": 1, "estimated_cost": 0, "agent_feedback": []any{}, "citations": []any{},
		})
	}))
	defer server.Close()

	service := NewTaskService(repo, repo, repo, runtimeclient.NewClient(server.URL, "fixture", 5*time.Second), repo, repo)
	created, err := repo.CreateTask(ctx, model.Task{
		UserID: uid, ConversationID: &conversationID, RequestID: "p23-approval-reject", TaskText: "write fixture",
		Scheduler: "adaptive", Planner: "multi_objective", ExecutionMode: "auto", SynthesisMode: "auto",
	}, model.TaskConstraints{MaxLatencyMS: 8000, MaxCost: .15, MinQuality: .8})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := repo.CreateMessage(ctx, uid, conversationID, "user", "write fixture", "COMPLETED", "p23-approval-reject", map[string]any{"taskId": created.ID}); err != nil {
		t.Fatal(err)
	}
	continuation := &model.TaskContinuation{
		Protocol: "tool_approval", AgentID: agentID, Capability: "general", TaskID: "approval-p23", ContextID: "fixture",
		State: "AUTH_REQUIRED", Kind: "tool_approval", ApprovalID: "approval-p23", ToolName: "record.write", ToolProtocol: "http",
		RiskLevel: "high", RequiresConfirmation: true, Arguments: map[string]any{"record": "fixture"}, Fingerprint: "fixture", Summary: "fixture write",
	}
	if err := repo.SuspendTask(ctx, uid, created.ID, "AUTH_REQUIRED", "needs approval", continuation, []string{"P23 Agent"}, nil, map[string]any{}, 0, 0); err != nil {
		t.Fatal(err)
	}
	before := p23TaskCount(t, repo, uid)
	result, err := service.P23RejectCurrentApproval(ctx, uid, RunTaskInput{ConversationID: &conversationID})
	if err != nil {
		t.Fatal(err)
	}
	if result.Task == nil || result.Task.ID != created.ID || result.Status != "COMPLETED" {
		t.Fatalf("approval rejection did not complete original task: %+v", result)
	}
	after := p23TaskCount(t, repo, uid)
	if before != after {
		t.Fatalf("APPROVAL_REJECT created a new task: before=%d after=%d", before, after)
	}
	if runtimeCalls != 1 {
		t.Fatalf("approval rejection runtime calls=%d, want 1 authoritative rejection", runtimeCalls)
	}
	if _, err := service.P23RejectCurrentApproval(ctx, uid, RunTaskInput{ConversationID: &conversationID}); !errors.Is(err, ErrNotFound) {
		t.Fatalf("replayed approval rejection must not execute again: %v", err)
	}
	if runtimeCalls != 1 {
		t.Fatal("replayed approval rejection reached Runtime")
	}
	return map[string]any{"taskIdReused": true, "createNewTask": false, "writeCount": 0, "replaySideEffect": false}
}

func TestP23FrozenAuthoritativeHandlingIntegration(t *testing.T) {
	if strings.TrimSpace(os.Getenv("P2_TEST_MYSQL_DSN")) == "" {
		t.Skip("set P2_TEST_MYSQL_DSN to run isolated P23 authoritative Handling acceptance")
	}
	cases, fixtures := p23LoadFrozenHandlingAssets(t)
	report := p23AuthoritativeHandlingReport{
		SchemaVersion: "p23.handling.authoritative.v1",
		Scope:         "GO_TASK_OPERATION_AND_DB_STATE",
		Cases:         make([]p23AuthoritativeHandlingEvidence, 0, len(cases)),
	}

	for _, row := range cases {
		row := row
		fixture, ok := fixtures[row.FixtureID]
		if !ok {
			t.Fatalf("%s fixture %s missing", row.CaseID, row.FixtureID)
		}
		actual := ""
		var evidence map[string]any
		ok = t.Run(row.CaseID, func(t *testing.T) {
			operation := P23TaskOperation(row.Query)
			expectedOperation := p23ExpectedTaskOperation(row.ExpectedHandling)
			if operation != expectedOperation {
				t.Fatalf("task operation=%q, want %q", operation, expectedOperation)
			}
			if len(fixture.Tasks) != 1 {
				t.Fatalf("authoritative task operation fixture must contain exactly one task, got %d", len(fixture.Tasks))
			}
			switch row.ExpectedHandling {
			case "TASK_STATUS":
				if fixture.Tasks[0].State != "RUNNING" {
					t.Fatalf("TASK_STATUS fixture state=%s", fixture.Tasks[0].State)
				}
				evidence = p23VerifyStatusHandling(t)
			case "RESUME":
				if fixture.Tasks[0].State != "INPUT_REQUIRED" {
					t.Fatalf("RESUME fixture state=%s", fixture.Tasks[0].State)
				}
				evidence = p23VerifyResumeHandling(t)
			case "CANCEL":
				evidence = p23VerifyCancelHandling(t)
			case "APPROVAL_REJECT":
				if fixture.Tasks[0].State != "AUTH_REQUIRED" {
					t.Fatalf("APPROVAL_REJECT fixture state=%s", fixture.Tasks[0].State)
				}
				evidence = p23VerifyApprovalRejectHandling(t)
			default:
				t.Fatalf("unexpected Go-owned handling %s", row.ExpectedHandling)
			}
			actual = row.ExpectedHandling
		})
		report.Cases = append(report.Cases, p23AuthoritativeHandlingEvidence{
			CaseID: row.CaseID, ExpectedHandling: row.ExpectedHandling, ActualHandling: actual, Passed: ok, Evidence: evidence,
		})
	}

	if path := strings.TrimSpace(os.Getenv("P23_AUTHORITATIVE_HANDLING_REPORT")); path != "" {
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		raw, err := json.MarshalIndent(report, "", "  ")
		if err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, append(raw, '\n'), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	for _, row := range report.Cases {
		if !row.Passed {
			t.Fatalf("authoritative Handling failed for %s", row.CaseID)
		}
	}
}
