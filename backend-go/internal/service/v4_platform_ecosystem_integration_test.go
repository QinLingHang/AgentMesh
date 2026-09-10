package service

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/repository"
	runtimeclient "example.com/agentmesh-control-plane/internal/runtime"
)

func TestV4ServiceAccountHashScopeIsolationAndRevocation(t *testing.T) {
	database, _ := p2Database(t)
	ctx := context.Background()
	repo := repository.NewMySQL(database)
	userRes, err := database.ExecContext(ctx, "INSERT INTO users(email,password_hash,display_name) VALUES('v4-api@example.test','fixture','V4 API')")
	if err != nil {
		t.Fatal(err)
	}
	uid, _ := userRes.LastInsertId()
	projectRes, err := database.ExecContext(ctx, "INSERT INTO projects(user_id,name,description) VALUES(?,'API Project','fixture')", uid)
	if err != nil {
		t.Fatal(err)
	}
	projectID, _ := projectRes.LastInsertId()
	governance, err := NewGovernanceService(repo, "v4-test-master-key")
	if err != nil {
		t.Fatal(err)
	}
	s := NewEcosystemService(repo, governance, nil, nil, nil, nil, nil)

	credential, err := s.CreateServiceAccount(ctx, uid, projectID, "CI Runner", []string{"tasks:read"}, nil)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(credential.APIKey, "am_sk_") || credential.ServiceAccount.KeyPrefix == "" {
		t.Fatalf("unexpected one-time API credential: %#v", credential)
	}
	var persistedHash string
	if err := database.QueryRowContext(ctx, "SELECT secret_hash FROM api_service_accounts WHERE id=?", credential.ServiceAccount.ID).Scan(&persistedHash); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(persistedHash, credential.APIKey) || len(persistedHash) != 64 {
		t.Fatalf("raw key leaked into persistence: hash=%q", persistedHash)
	}
	sum := sha256.Sum256([]byte(credential.APIKey))
	if persistedHash != strings.ToUpper(hex.EncodeToString(sum[:])) {
		t.Fatal("service account secret hash does not match one-time key")
	}
	principal, err := s.AuthenticateServiceAccount(ctx, credential.APIKey)
	if err != nil || principal.ProjectID != projectID || principal.ActorUserID != uid {
		t.Fatalf("authenticate: principal=%#v err=%v", principal, err)
	}
	if _, _, err := s.RunPublicTask(ctx, principal, PublicRunInput{Task: "scope must deny"}, ""); !errors.Is(err, ErrAPIScopeDenied) {
		t.Fatalf("read-only API key must not run tasks, got %v", err)
	}
	list, err := s.ListServiceAccounts(ctx, uid, projectID)
	if err != nil || len(list) != 1 {
		t.Fatalf("list service accounts: %#v %v", list, err)
	}
	serialized, _ := json.Marshal(list)
	if strings.Contains(string(serialized), credential.APIKey) || strings.Contains(strings.ToLower(string(serialized)), "secret_hash") {
		t.Fatalf("service account list leaked secret material: %s", serialized)
	}
	if err := s.RevokeServiceAccount(ctx, uid, projectID, credential.ServiceAccount.ID); err != nil {
		t.Fatal(err)
	}
	if _, err := s.AuthenticateServiceAccount(ctx, credential.APIKey); !errors.Is(err, ErrAPIKeyInvalid) {
		t.Fatalf("revoked key still authenticates: %v", err)
	}
}

func TestV4MarketplaceValidationInstallLifecycleAndPrivacy(t *testing.T) {
	database, _ := p2Database(t)
	ctx := context.Background()
	repo := repository.NewMySQL(database)
	userRes, err := database.ExecContext(ctx, "INSERT INTO users(email,password_hash,display_name) VALUES('v4-market@example.test','fixture','V4 Market')")
	if err != nil {
		t.Fatal(err)
	}
	uid, _ := userRes.LastInsertId()
	projectRes, err := database.ExecContext(ctx, "INSERT INTO projects(user_id,name,description) VALUES(?,'Market Project','fixture')", uid)
	if err != nil {
		t.Fatal(err)
	}
	projectID, _ := projectRes.LastInsertId()
	governance, err := NewGovernanceService(repo, "v4-test-master-key")
	if err != nil {
		t.Fatal(err)
	}
	runtime := runtimeclient.NewClient("http://127.0.0.1:1", "fixture", time.Second)
	s := NewEcosystemService(repo, governance, NewConversationService(repo, repo), NewProjectService(repo), nil, NewAgentService(repo), NewMCPServerService(repo, runtime))

	manifest := model.EcosystemPackageManifest{
		Kind: "AGENT", Permissions: []string{"knowledge:read"},
		Agent: &model.EcosystemAgentTemplate{Name: "Marketplace Agent", Endpoint: "internal://general", Protocol: "internal", Capabilities: []string{"general"}, Provider: "mock"},
	}
	detail, err := s.CreatePackage(ctx, uid, CreatePackageInput{Slug: "marketplace-agent", Name: "Marketplace Agent", Kind: "AGENT", Summary: "safe public fixture", Description: "fixture", Visibility: "PUBLIC", Version: "1.0.0", Manifest: manifest, Publish: true})
	if err != nil {
		t.Fatal(err)
	}
	if detail.Package.Status != "PUBLISHED" || detail.Package.LatestVersion != "1.0.0" {
		t.Fatalf("publish failed: %#v", detail)
	}
	found, err := s.SearchMarketplace(ctx, "Marketplace", "AGENT", 20)
	if err != nil || len(found) != 1 || found[0].Slug != "marketplace-agent" {
		t.Fatalf("marketplace search: %#v %v", found, err)
	}

	install, err := s.InstallPackage(ctx, uid, projectID, "marketplace-agent", "", nil)
	if err != nil {
		t.Fatal(err)
	}
	if install.ResourceType != "AGENT" || install.ResourceID == nil || !install.Enabled {
		t.Fatalf("materialization failed: %#v", install)
	}
	agents, err := NewAgentService(repo).List(ctx, uid)
	if err != nil || len(agents) != 1 {
		t.Fatalf("materialized agent missing: %#v %v", agents, err)
	}
	disabled, err := s.SetInstallationEnabled(ctx, uid, projectID, install.ID, false)
	if err != nil || disabled.Enabled || disabled.ResourceID != nil {
		t.Fatalf("disable: %#v %v", disabled, err)
	}
	agents, _ = NewAgentService(repo).List(ctx, uid)
	if len(agents) != 0 {
		t.Fatalf("disabled package left runtime agent: %#v", agents)
	}
	enabled, err := s.SetInstallationEnabled(ctx, uid, projectID, install.ID, true)
	if err != nil || !enabled.Enabled || enabled.ResourceID == nil {
		t.Fatalf("enable: %#v %v", enabled, err)
	}
	if err := s.DeleteInstallation(ctx, uid, projectID, install.ID); err != nil {
		t.Fatal(err)
	}
	items, err := s.ListInstallations(ctx, uid, projectID)
	if err != nil || len(items) != 0 {
		t.Fatalf("uninstall left installation: %#v %v", items, err)
	}

	privateMCP := model.EcosystemPackageManifest{Kind: "MCP", MCP: &model.EcosystemMCPTemplate{Name: "unsafe", Endpoint: "https://127.0.0.1/mcp", Transport: "streamable_http"}}
	if _, err := s.DescribePackageValidation("MCP", privateMCP); !errors.Is(err, ErrPackageValidation) {
		t.Fatalf("private MCP endpoint accepted: %v", err)
	}
	secretManifest := manifest
	raw, _ := json.Marshal(secretManifest)
	var generic map[string]any
	_ = json.Unmarshal(raw, &generic)
	generic["api_key"] = "synthetic-placeholder"
	genericRaw, _ := json.Marshal(generic)
	var poisoned model.EcosystemPackageManifest
	_ = json.Unmarshal(genericRaw, &poisoned)
	// Unknown fields are dropped by typed decoding, so package validation also
	// relies on a closed typed manifest: no credential-bearing extension map exists.
	if _, _, err := validateManifest("AGENT", poisoned); err != nil {
		t.Fatal(err)
	}
}

func TestV4PublicAPIIdempotencyProjectBinding(t *testing.T) {
	database, _ := p2Database(t)
	ctx := context.Background()
	repo := repository.NewMySQL(database)
	userRes, err := database.ExecContext(ctx, "INSERT INTO users(email,password_hash,display_name) VALUES('v4-public@example.test','fixture','V4 Public')")
	if err != nil {
		t.Fatal(err)
	}
	uid, _ := userRes.LastInsertId()
	projectRes, err := database.ExecContext(ctx, "INSERT INTO projects(user_id,name,description) VALUES(?,'Public API Project','fixture')", uid)
	if err != nil {
		t.Fatal(err)
	}
	projectID, _ := projectRes.LastInsertId()
	if _, err := database.ExecContext(ctx, `INSERT INTO agents(user_id,name,endpoint,protocol,capabilities_json,status) VALUES(?,'Public General','internal://success','internal','["general"]','ACTIVE')`, uid); err != nil {
		t.Fatal(err)
	}
	governance, err := NewGovernanceService(repo, "v4-test-master-key")
	if err != nil {
		t.Fatal(err)
	}

	runtimeServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/internal/v1/runtime/execute" {
			http.NotFound(w, r)
			return
		}
		var req runtimeclient.ExecuteRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, err.Error(), 400)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]any{
			"request_id": req.RequestID, "status": "COMPLETED", "answer": "public api fixture",
			"citations": []any{}, "scheduler": req.Scheduler,
			"task_profile": map[string]any{"mode": "api"}, "selected_agents": []string{"Public General"},
			"estimated_cost": 0.001, "elapsed_ms": 7, "trace": []any{}, "dag": map[string]any{}, "agent_feedback": []any{},
			"observability": map[string]any{},
		})
	}))
	defer runtimeServer.Close()
	runtime := runtimeclient.NewClient(runtimeServer.URL, "fixture", 2*time.Second)
	tasks := NewTaskService(repo, repo, repo, runtime, repo, repo)
	s := NewEcosystemService(repo, governance, NewConversationService(repo, repo), NewProjectService(repo), tasks, NewAgentService(repo), NewMCPServerService(repo, runtime))
	credential, err := s.CreateServiceAccount(ctx, uid, projectID, "External CI", []string{"tasks:read", "tasks:write", "marketplace:read"}, nil)
	if err != nil {
		t.Fatal(err)
	}
	principal, err := s.AuthenticateServiceAccount(ctx, credential.APIKey)
	if err != nil {
		t.Fatal(err)
	}

	input := PublicRunInput{Task: "public API idempotency", Scheduler: "adaptive", Planner: "multi_objective", ExecutionMode: "auto", SynthesisMode: "auto", Constraints: model.TaskConstraints{MaxLatencyMS: 8000, MaxCost: .15, MinQuality: .8}}
	first, replay, err := s.RunPublicTask(ctx, principal, input, "run-once-key")
	if err != nil || replay || first == nil || first.Task == nil {
		t.Fatalf("first run: %#v replay=%v err=%v", first, replay, err)
	}
	if first.Task.ConversationID == nil {
		t.Fatal("public API did not create project-bound conversation")
	}
	boundProject, err := repo.ProjectIDByConversation(ctx, uid, *first.Task.ConversationID)
	if err != nil || boundProject == nil || *boundProject != projectID {
		t.Fatalf("conversation project binding: %#v %v", boundProject, err)
	}
	second, replay, err := s.RunPublicTask(ctx, principal, input, "run-once-key")
	if err != nil || !replay || second.Task.ID != first.Task.ID {
		t.Fatalf("idempotent replay: first=%#v second=%#v replay=%v err=%v", first, second, replay, err)
	}
	input.Task = "different payload"
	if _, _, err := s.RunPublicTask(ctx, principal, input, "run-once-key"); !errors.Is(err, ErrIdempotencyConflict) {
		t.Fatalf("idempotency mismatch must conflict, got %v", err)
	}
	fetched, err := s.PublicTask(ctx, principal, first.Task.ID)
	if err != nil || fetched.ID != first.Task.ID {
		t.Fatalf("public task read: %#v %v", fetched, err)
	}
}
