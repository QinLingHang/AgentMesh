package service

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/repository"
	runtimeclient "example.com/agentmesh-control-plane/internal/runtime"
)

func TestP5ApprovalLifecycleIntegration(t *testing.T) {
	database, _ := p2Database(t)
	ctx := context.Background()
	repo := repository.NewMySQL(database)
	profiles := NewProjectRuntimeService(repo)

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

	uid := insert("INSERT INTO users(email,password_hash,display_name) VALUES('p5@example.test','fixture','P5')")
	projectID := insert("INSERT INTO projects(user_id,name,description) VALUES(?,'P5','fixture')", uid)
	conversationID := insert("INSERT INTO conversations(user_id,title) VALUES(?,'P5 fixture')", uid)
	insert("INSERT INTO project_conversations(project_id,conversation_id) VALUES(?,?)", projectID, conversationID)
	agentID := insert("INSERT INTO agents(user_id,name,endpoint,protocol,capabilities_json) VALUES(?,'General','internal://general','internal','[\"general\"]')", uid)
	toolID := insert("INSERT INTO tools(user_id,name,description,protocol,endpoint,input_schema,risk_level,requires_confirmation,enabled) VALUES(?,'cancel_order','cancel fixture','http','http://fixture/cancel','{\"type\":\"object\"}','high',1,1)", uid)
	mcpID := insert("INSERT INTO mcp_servers(user_id,name,transport,endpoint,enabled) VALUES(?,'P5 MCP','streamable_http','http://fixture/mcp',1)", uid)

	cfg := model.ProjectRuntimeConfig{
		AgentMode:    "selected",
		AgentIDs:     []int64{agentID},
		ToolMode:     "selected",
		ToolIDs:      []int64{toolID},
		MCPMode:      "selected",
		MCPServerIDs: []int64{mcpID},
		Policy:       model.ProjectRuntimePolicy{Mode: "inherit"},
	}
	if _, err := profiles.Update(ctx, uid, projectID, cfg); err != nil {
		t.Fatal(err)
	}

	var mu sync.Mutex
	var requests []runtimeclient.ExecuteRequest
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var req runtimeclient.ExecuteRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		mu.Lock()
		requests = append(requests, req)
		mu.Unlock()

		if req.RequestID == "ambiguous" {
			http.Error(w, "ambiguous upstream failure", http.StatusBadGateway)
			return
		}
		if req.RequestID == "concurrent" {
			time.Sleep(120 * time.Millisecond)
		}
		if req.Continuation != nil && (req.Continuation.Kind == "tool_approval" || strings.EqualFold(req.Continuation.Protocol, "tool_approval")) && strings.EqualFold(req.Task, "approve") {
			if req.Continuation.ToolProtocol == "mcp" {
				if len(req.MCPServers) == 0 {
					http.Error(w, "pending MCP action is outside current scope", http.StatusConflict)
					return
				}
			} else {
				found := false
				for _, tool := range req.Tools {
					if tool.Name == req.Continuation.ToolName && tool.Enabled {
						found = true
						break
					}
				}
				if !found {
					http.Error(w, "pending Tool action is outside current scope", http.StatusConflict)
					return
				}
			}
		}

		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]any{
			"request_id":      req.RequestID,
			"status":          "COMPLETED",
			"answer":          "fixture completed",
			"selected_agents": []string{"General"},
			"trace":           []map[string]any{{"kind": "approval", "title": "Approval Granted", "status": "completed"}},
			"dag":             map[string]any{},
			"elapsed_ms":      1,
			"estimated_cost":  0,
			"agent_feedback":  []any{},
			"citations":       []any{},
		})
	}))
	defer server.Close()

	tasks := NewTaskService(repo, repo, repo, runtimeclient.NewClient(server.URL, "fixture", 5*time.Second), repo, repo, profiles)

	constraints := model.TaskConstraints{MaxLatencyMS: 8000, MaxCost: .15, MinQuality: .8}
	newApprovalTask := func(t *testing.T, requestID, protocol string, arguments map[string]any, conversationOverride ...int64) *model.Task {
		t.Helper()
		// Existing P5 subtests intentionally share their original conversation.
		// A P23 natural-language approval test can supply an isolated conversation
		// so unrelated pending approvals cannot produce a false ambiguity.
		targetConversationID := conversationID
		if len(conversationOverride) > 0 {
			targetConversationID = conversationOverride[0]
		}
		created, err := repo.CreateTask(ctx, model.Task{
			UserID:         uid,
			ConversationID: &targetConversationID,
			RequestID:      requestID,
			TaskText:       "fixture action",
			Scheduler:      "greedy",
			Planner:        "heuristic",
			ExecutionMode:  "auto",
			SynthesisMode:  "auto",
		}, constraints)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := repo.CreateMessage(
			ctx,
			uid,
			targetConversationID,
			"user",
			"fixture action",
			"COMPLETED",
			requestID,
			map[string]any{
				"taskId":       created.ID,
				"runtimePhase": "run",
			},
		); err != nil {
			t.Fatal(err)
		}
		toolName := "cancel_order"
		if protocol == "mcp" {
			toolName = "mcp_pending_cancel_order"
		}
		continuation := &model.TaskContinuation{
			Protocol:             "tool_approval",
			AgentID:              agentID,
			Capability:           "general",
			TaskID:               "approval-" + requestID,
			ContextID:            "fingerprint-" + requestID,
			State:                "AUTH_REQUIRED",
			Kind:                 "tool_approval",
			ApprovalID:           "approval-" + requestID,
			ToolName:             toolName,
			ToolProtocol:         protocol,
			RiskLevel:            "high",
			RequiresConfirmation: true,
			Arguments:            arguments,
			Fingerprint:          "fingerprint-" + requestID,
			Summary:              "fixture approval",
		}
		if err := repo.SuspendTask(ctx, uid, created.ID, "AUTH_REQUIRED", "needs approval", continuation, []string{"General"}, []map[string]any{{"kind": "approval", "title": "Approval Requested"}}, map[string]any{}, 1, 0); err != nil {
			t.Fatal(err)
		}
		return created
	}
	lastRequest := func() runtimeclient.ExecuteRequest {
		mu.Lock()
		defer mu.Unlock()
		return requests[len(requests)-1]
	}

	t.Run("ServerSideContinuationAndApprovalPrivacy", func(t *testing.T) {
		task := newApprovalTask(t, "privacy", "http", map[string]any{
			"order_id": "ORDER-1",
			"password": "secret-value",
			"nested":   map[string]any{"token": "abc"},
			"list":     []any{map[string]any{"otp": "654321"}, "bearer hidden"},
		})
		persisted, err := repo.TaskByID(ctx, uid, task.ID)
		if err != nil {
			t.Fatal(err)
		}
		if persisted.Continuation == nil || persisted.Continuation.Arguments["order_id"] != "ORDER-1" {
			t.Fatal("authoritative continuation was not persisted server-side")
		}
		if persisted.Approval == nil {
			t.Fatal("browser-safe approval projection missing")
		}
		blob, err := json.Marshal(persisted)
		if err != nil {
			t.Fatal(err)
		}
		text := string(blob)
		for _, secret := range []string{"secret-value", "654321", "bearer hidden", `"continuation"`} {
			if strings.Contains(text, secret) {
				t.Fatalf("Task JSON leaked authoritative/sensitive approval data: %s", secret)
			}
		}
		if got := persisted.Approval.ArgumentsPreview["password"]; got != "[REDACTED]" {
			t.Fatalf("password preview=%v", got)
		}
		if got := persisted.Approval.ArgumentsPreview["nested"].(map[string]any)["token"]; got != "[REDACTED]" {
			t.Fatalf("nested token preview=%v", got)
		}
	})

	t.Run("RejectAndApproveUseServerPersistedDecision", func(t *testing.T) {
		rejected := newApprovalTask(t, "reject", "http", map[string]any{"order_id": "ORDER-R"})
		result, err := tasks.Resume(ctx, uid, rejected.ID, "reject")
		if err != nil {
			t.Fatal(err)
		}
		if result.Status != "COMPLETED" {
			t.Fatalf("reject status=%s", result.Status)
		}
		req := lastRequest()
		if req.Task != "reject" || req.Continuation == nil || req.Continuation.Arguments["order_id"] != "ORDER-R" {
			t.Fatalf("reject resume did not use server-side continuation: %+v", req)
		}

		approved := newApprovalTask(t, "approve", "http", map[string]any{"order_id": "ORDER-A"})
		result, err = tasks.Resume(ctx, uid, approved.ID, "approve")
		if err != nil {
			t.Fatal(err)
		}
		if result.Status != "COMPLETED" {
			t.Fatalf("approve status=%s", result.Status)
		}
		req = lastRequest()
		if req.Task != "approve" || req.Continuation == nil || req.Continuation.Arguments["order_id"] != "ORDER-A" {
			t.Fatalf("approve resume did not use exact persisted action: %+v", req)
		}
	})

	t.Run("P23RejectApprovalReusesAuthoritativeP5Resume", func(t *testing.T) {
		// The privacy subtest deliberately leaves an AUTH_REQUIRED task behind.
		// Create and project-bind a separate conversation for this test rather
		// than weakening production's fail-closed multiple-approval behavior.
		approvalConversationID := insert("INSERT INTO conversations(user_id,title) VALUES(?,'P23 approval fixture')", uid)
		insert("INSERT INTO project_conversations(project_id,conversation_id) VALUES(?,?)", projectID, approvalConversationID)
		created := newApprovalTask(t, "p23-reject", "http", map[string]any{"order_id": "ORDER-P23"}, approvalConversationID)
		result, err := tasks.P23RejectCurrentApproval(ctx, uid, RunTaskInput{
			ConversationID: &approvalConversationID, Task: "上一轮审批我不同意，别继续写入",
		})
		if err != nil {
			t.Fatal(err)
		}
		if result.Status != "COMPLETED" || result.Task.ID != created.ID {
			t.Fatalf("rejection must complete existing task only: %+v", result)
		}
		req := lastRequest()
		if req.Task != "reject" || req.Continuation == nil || req.Continuation.ToolName != "cancel_order" {
			t.Fatal("P23 rejection did not use original persisted approval")
		}
		mu.Lock()
		requestCountBeforeReplay := len(requests)
		mu.Unlock()
		if _, err := tasks.P23RejectCurrentApproval(ctx, uid, RunTaskInput{ConversationID: &approvalConversationID}); !errors.Is(err, ErrNotFound) {
			t.Fatalf("replaying approval must not execute twice: %v", err)
		}
		mu.Lock()
		requestCountAfterReplay := len(requests)
		mu.Unlock()
		if requestCountAfterReplay != requestCountBeforeReplay {
			t.Fatal("repeated rejection reached runtime")
		}
	})

	t.Run("P23RejectApprovalRefusesAmbiguousPendingActions", func(t *testing.T) {
		ambiguousConversationID := insert("INSERT INTO conversations(user_id,title) VALUES(?,'P23 ambiguous approvals')", uid)
		insert("INSERT INTO project_conversations(project_id,conversation_id) VALUES(?,?)", projectID, ambiguousConversationID)
		newApprovalTask(t, "p23-ambiguous-one", "http", map[string]any{"order_id": "ORDER-1"}, ambiguousConversationID)
		newApprovalTask(t, "p23-ambiguous-two", "http", map[string]any{"order_id": "ORDER-2"}, ambiguousConversationID)
		mu.Lock()
		before := len(requests)
		mu.Unlock()
		_, err := tasks.P23RejectCurrentApproval(ctx, uid, RunTaskInput{ConversationID: &ambiguousConversationID})
		if !errors.Is(err, ErrConflict) {
			t.Fatalf("multiple approvals must require explicit selection: %v", err)
		}
		mu.Lock()
		after := len(requests)
		mu.Unlock()
		if before != after {
			t.Fatal("ambiguous rejection reached runtime")
		}
	})

	t.Run("NewerConversationTurnInvalidatesOlderToolApproval", func(t *testing.T) {
		stale := newApprovalTask(t, "stale-approval", "http", map[string]any{"order_id": "ORDER-STALE"})

		newer, err := repo.CreateTask(ctx, model.Task{
			UserID:         uid,
			ConversationID: &conversationID,
			RequestID:      "newer-turn",
			TaskText:       "newer user turn",
			Scheduler:      "greedy",
			Planner:        "heuristic",
			ExecutionMode:  "auto",
			SynthesisMode:  "auto",
		}, constraints)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := repo.CreateMessage(
			ctx,
			uid,
			conversationID,
			"user",
			"newer user turn",
			"COMPLETED",
			"newer-turn",
			map[string]any{
				"taskId":       newer.ID,
				"runtimePhase": "run",
			},
		); err != nil {
			t.Fatal(err)
		}

		mu.Lock()
		requestCountBefore := len(requests)
		mu.Unlock()

		_, err = tasks.Resume(ctx, uid, stale.ID, "approve")
		if !errors.Is(err, ErrConflict) {
			t.Fatalf("stale approval resume error=%v, want ErrConflict", err)
		}

		mu.Lock()
		requestCountAfter := len(requests)
		mu.Unlock()
		if requestCountAfter != requestCountBefore {
			t.Fatal("superseded approval reached Runtime")
		}
	})

	t.Run("CurrentToolPermissionAndProjectScopeAreRechecked", func(t *testing.T) {
		task := newApprovalTask(t, "tool-disabled", "http", map[string]any{"order_id": "ORDER-D"})
		if _, err := database.Exec("UPDATE tools SET enabled=0 WHERE id=?", toolID); err != nil {
			t.Fatal(err)
		}
		_, err := tasks.Resume(ctx, uid, task.ID, "approve")
		if err == nil {
			t.Fatal("disabled pending Tool executed")
		}
		if len(lastRequest().Tools) != 0 {
			t.Fatal("disabled Tool remained in resumed runtime pool")
		}
		if _, err := database.Exec("UPDATE tools SET enabled=1 WHERE id=?", toolID); err != nil {
			t.Fatal(err)
		}

		task = newApprovalTask(t, "tool-unbound", "http", map[string]any{"order_id": "ORDER-P"})
		if _, err := database.Exec("DELETE FROM project_tool_bindings WHERE project_id=? AND tool_id=?", projectID, toolID); err != nil {
			t.Fatal(err)
		}
		_, err = tasks.Resume(ctx, uid, task.ID, "approve")
		if err == nil {
			t.Fatal("project-unbound Tool executed")
		}
		if len(lastRequest().Tools) != 0 {
			t.Fatal("unbound Tool remained in resumed project pool")
		}
		if _, err := database.Exec("INSERT INTO project_tool_bindings(project_id,tool_id) VALUES(?,?)", projectID, toolID); err != nil {
			t.Fatal(err)
		}
	})

	t.Run("MCPProjectScopeIsRechecked", func(t *testing.T) {
		task := newApprovalTask(t, "mcp-unbound", "mcp", map[string]any{"order_id": "ORDER-M"})
		if _, err := database.Exec("DELETE FROM project_mcp_bindings WHERE project_id=? AND mcp_server_id=?", projectID, mcpID); err != nil {
			t.Fatal(err)
		}
		_, err := tasks.Resume(ctx, uid, task.ID, "approve")
		if err == nil {
			t.Fatal("project-unbound MCP action executed")
		}
		if len(lastRequest().MCPServers) != 0 {
			t.Fatal("unbound MCP remained in resumed project pool")
		}
		if _, err := database.Exec("INSERT INTO project_mcp_bindings(project_id,mcp_server_id) VALUES(?,?)", projectID, mcpID); err != nil {
			t.Fatal(err)
		}
	})

	t.Run("ConcurrentApproveOnlyOneCASWins", func(t *testing.T) {
		task := newApprovalTask(t, "concurrent", "http", map[string]any{"order_id": "ORDER-C"})
		var wg sync.WaitGroup
		errs := make(chan error, 2)
		for range 2 {
			wg.Add(1)
			go func() {
				defer wg.Done()
				_, err := tasks.Resume(ctx, uid, task.ID, "approve")
				errs <- err
			}()
		}
		wg.Wait()
		close(errs)
		var success, conflict int
		for err := range errs {
			if err == nil {
				success++
			} else if errors.Is(err, ErrConflict) {
				conflict++
			} else {
				t.Fatalf("unexpected concurrent resume error: %v", err)
			}
		}
		if success != 1 || conflict != 1 {
			t.Fatalf("CAS results success=%d conflict=%d", success, conflict)
		}
	})

	t.Run("AmbiguousApprovedFailureIsFailClosed", func(t *testing.T) {
		task := newApprovalTask(t, "ambiguous", "http", map[string]any{"order_id": "ORDER-X"})
		_, err := tasks.Resume(ctx, uid, task.ID, "approve")
		if err == nil {
			t.Fatal("ambiguous approved action unexpectedly succeeded")
		}
		persisted, err := repo.TaskByID(ctx, uid, task.ID)
		if err != nil {
			t.Fatal(err)
		}
		if persisted.Status != "ERROR" || persisted.Continuation != nil {
			t.Fatalf("ambiguous action replay remained possible: status=%s continuation=%+v", persisted.Status, persisted.Continuation)
		}
	})

	t.Run("LegacyResumeTransmitsNoToolOrMCPPools", func(t *testing.T) {
		created, err := repo.CreateTask(ctx, model.Task{
			UserID:         uid,
			ConversationID: &conversationID,
			RequestID:      "legacy",
			TaskText:       "legacy",
			Scheduler:      "greedy",
			Planner:        "heuristic",
			ExecutionMode:  "auto",
			SynthesisMode:  "auto",
		}, constraints)
		if err != nil {
			t.Fatal(err)
		}
		continuation := &model.TaskContinuation{Protocol: "internal", AgentID: agentID, Capability: "general", TaskID: "legacy-task", ContextID: "legacy-context", State: "INPUT_REQUIRED", Kind: "agent"}
		if err := repo.SuspendTask(ctx, uid, created.ID, "INPUT_REQUIRED", "need input", continuation, []string{"General"}, []map[string]any{}, map[string]any{}, 1, 0); err != nil {
			t.Fatal(err)
		}
		_, err = tasks.Resume(ctx, uid, created.ID, "continue")
		if err != nil {
			t.Fatal(err)
		}
		req := lastRequest()
		if len(req.Tools) != 0 || len(req.MCPServers) != 0 {
			t.Fatalf("legacy resume polluted by Tool/MCP pools: tools=%d mcp=%d", len(req.Tools), len(req.MCPServers))
		}
	})
}
