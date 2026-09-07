package service

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	dbschema "example.com/agentmesh-control-plane/internal/db"
	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/repository"
	runtimeclient "example.com/agentmesh-control-plane/internal/runtime"
)

func TestP9GovernanceRBACSecretQuotaAndAudit(t *testing.T) {
	database, _ := p2Database(t)
	ctx := context.Background()
	if err := dbschema.EnsureGovernanceSchema(ctx, database); err != nil {
		t.Fatal(err)
	}
	repo := repository.NewMySQL(database)
	governance, err := NewGovernanceService(repo, "p9-test-master-key-32-bytes-minimum")
	if err != nil {
		t.Fatal(err)
	}
	insert := func(query string, args ...any) int64 {
		res, err := database.Exec(query, args...)
		if err != nil {
			t.Fatal(err)
		}
		id, err := res.LastInsertId()
		if err != nil {
			t.Fatal(err)
		}
		return id
	}
	owner := insert("INSERT INTO users(email,password_hash,display_name) VALUES('p9-owner@example.test','fixture','Owner')")
	developer := insert("INSERT INTO users(email,password_hash,display_name) VALUES('p9-dev@example.test','fixture','Developer')")
	viewer := insert("INSERT INTO users(email,password_hash,display_name) VALUES('p9-viewer@example.test','fixture','Viewer')")
	project := insert("INSERT INTO projects(user_id,name,description) VALUES(?,'Enterprise Project','fixture')", owner)

	if _, err = governance.AddMember(ctx, owner, project, "p9-dev@example.test", "DEVELOPER"); err != nil {
		t.Fatal(err)
	}
	if _, err = governance.AddMember(ctx, owner, project, "p9-viewer@example.test", "VIEWER"); err != nil {
		t.Fatal(err)
	}
	if role, err := governance.RequireRole(ctx, developer, project, "DEVELOPER"); err != nil || role != "DEVELOPER" {
		t.Fatalf("developer access role=%s err=%v", role, err)
	}
	if _, err := governance.RequireRole(ctx, viewer, project, "DEVELOPER"); err != ErrForbidden {
		t.Fatalf("viewer must be forbidden, got %v", err)
	}

	secretValue := "sk-p9-super-secret-value"
	secret, err := governance.CreateSecret(ctx, owner, project, "MODEL_API_KEY", "MODEL_API_KEY", secretValue)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(secret.MaskedHint, secretValue) {
		t.Fatal("plaintext leaked in secret projection")
	}
	var raw []byte
	if err := database.QueryRow("SELECT ciphertext FROM project_secrets WHERE id=?", secret.ID).Scan(&raw); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(raw), secretValue) {
		t.Fatal("plaintext stored at rest")
	}
	resolved, err := governance.ResolveSecret(ctx, developer, project, secret.ID)
	if err != nil || resolved != secretValue {
		t.Fatalf("internal decrypt failed value=%q err=%v", resolved, err)
	}

	if _, err := governance.UpsertProvider(ctx, owner, project, model.ProjectModelProvider{Provider: "openai-compatible", BaseURL: "http://127.0.0.1:8080/v1", ModelName: "x", SecretID: &secret.ID, Enabled: true}); err != ErrInvalidInput {
		t.Fatalf("SSRF loopback must be rejected, got %v", err)
	}
	provider, err := governance.UpsertProvider(ctx, owner, project, model.ProjectModelProvider{Provider: "openai-compatible", BaseURL: "https://api.example.test/v1", ModelName: "model-x", SecretID: &secret.ID, Enabled: true})
	if err != nil {
		t.Fatal(err)
	}
	if provider.SecretID == nil || *provider.SecretID != secret.ID {
		t.Fatalf("provider secret binding missing: %+v", provider)
	}
	projectModel, err := governance.ResolveProjectModelRuntime(ctx, developer, project)
	if err != nil {
		t.Fatal(err)
	}
	if projectModel.APIKey != secretValue || projectModel.ModelName != "model-x" {
		t.Fatalf("request-local model mismatch: %+v", projectModel)
	}

	_, err = governance.UpdateQuota(ctx, owner, project, model.ProjectQuota{RequestsPerMinute: 2, ConcurrentTasks: 3, MonthlyTokenLimit: 1000, MonthlyCostLimit: 10, DailyToolActionLimit: 5})
	if err != nil {
		t.Fatal(err)
	}
	if err := governance.CheckQuota(ctx, developer, project); err != nil {
		t.Fatal(err)
	}
	if err := governance.CheckQuota(ctx, developer, project); err != nil {
		t.Fatal(err)
	}
	if err := governance.CheckQuota(ctx, developer, project); err != ErrQuotaExceeded {
		t.Fatalf("request rate must block third request, got %v", err)
	}
	governance.RecordUsage(ctx, project, 123, 1.25, 2)
	overview, err := governance.Overview(ctx, owner, project)
	if err != nil {
		t.Fatal(err)
	}
	if overview.Usage.TokenCount < 123 || overview.Usage.EstimatedCost < 1.25 {
		t.Fatalf("usage not recorded: %+v", overview.Usage)
	}
	if len(overview.Audit) == 0 {
		t.Fatal("audit log empty")
	}
	auditJSON, err := json.Marshal(overview.Audit)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(auditJSON), secretValue) {
		t.Fatal("secret plaintext leaked into audit persistence/projection")
	}
	for _, event := range overview.Audit {
		for k, v := range event.Metadata {
			if strings.Contains(strings.ToLower(k), "key") && v != "[REDACTED]" {
				t.Fatalf("audit secret-like metadata not redacted: %+v", event.Metadata)
			}
		}
	}
}

func TestP9SharedProjectDiscoveryAndConversationAssignment(t *testing.T) {
	database, _ := p2Database(t)
	ctx := context.Background()
	if err := dbschema.EnsureGovernanceSchema(ctx, database); err != nil {
		t.Fatal(err)
	}
	repo := repository.NewMySQL(database)
	insert := func(q string, args ...any) int64 {
		r, e := database.Exec(q, args...)
		if e != nil {
			t.Fatal(e)
		}
		id, _ := r.LastInsertId()
		return id
	}
	owner := insert("INSERT INTO users(email,password_hash,display_name) VALUES('p9-share-owner@example.test','fixture','Owner')")
	dev := insert("INSERT INTO users(email,password_hash,display_name) VALUES('p9-share-dev@example.test','fixture','Dev')")
	project := insert("INSERT INTO projects(user_id,name,description) VALUES(?,'Shared','fixture')", owner)
	if _, e := database.Exec("INSERT INTO project_members(project_id,user_id,role) VALUES(?,?,'DEVELOPER')", project, dev); e != nil {
		t.Fatal(e)
	}
	conv := insert("INSERT INTO conversations(user_id,title) VALUES(?,'Dev conversation')", dev)
	projects, err := repo.ListProjects(ctx, dev)
	if err != nil {
		t.Fatal(err)
	}
	found := false
	for _, p := range projects {
		if p.ID == project {
			found = true
		}
	}
	if !found {
		t.Fatal("shared project not discoverable")
	}
	if err := repo.AssignConversationToProject(ctx, dev, project, conv); err != nil {
		t.Fatal(err)
	}
	pid, err := repo.ProjectIDByConversation(ctx, dev, conv)
	if err != nil || pid == nil || *pid != project {
		t.Fatalf("shared project runtime scope missing pid=%v err=%v", pid, err)
	}
}

func TestP9ProjectKnowledgeSharedButOwnerGlobalKnowledgeIsNot(t *testing.T) {
	database, _ := p2Database(t)
	ctx := context.Background()
	if err := dbschema.EnsureGovernanceSchema(ctx, database); err != nil {
		t.Fatal(err)
	}
	repo := repository.NewMySQL(database)
	insert := func(q string, args ...any) int64 {
		r, e := database.Exec(q, args...)
		if e != nil {
			t.Fatal(e)
		}
		id, _ := r.LastInsertId()
		return id
	}
	owner := insert("INSERT INTO users(email,password_hash,display_name) VALUES('p9-k-owner@example.test','fixture','Owner')")
	member := insert("INSERT INTO users(email,password_hash,display_name) VALUES('p9-k-member@example.test','fixture','Member')")
	project := insert("INSERT INTO projects(user_id,name,description) VALUES(?,'Knowledge Shared','fixture')", owner)
	if _, err := database.Exec("INSERT INTO project_members(project_id,user_id,role) VALUES(?,?,'VIEWER')", project, member); err != nil {
		t.Fatal(err)
	}
	projectBase := insert("INSERT INTO knowledge_bases(user_id,identity_key,name,scope,project_id,is_default) VALUES(?,'project:test:default','Project KB','PROJECT',?,1)", owner, project)
	globalBase := insert("INSERT INTO knowledge_bases(user_id,identity_key,name,scope,project_id,is_default) VALUES(?,'global:p9-owner','Owner Global','GLOBAL',NULL,0)", owner)
	insert("INSERT INTO project_knowledge_files(project_id,knowledge_base_id,user_id,original_name,media_type,extension,size_bytes,checksum_sha256,storage_key,status) VALUES(?,?,?,'project.txt','text/plain','txt',10,REPEAT('a',64),'p9/project.txt','READY')", project, projectBase, owner)
	insert("INSERT INTO project_knowledge_files(project_id,knowledge_base_id,user_id,original_name,media_type,extension,size_bytes,checksum_sha256,storage_key,status) VALUES(NULL,?,?, 'global.txt','text/plain','txt',10,REPEAT('b',64),'p9/global.txt','READY')", globalBase, owner)
	files, err := repo.ListKnowledgeFilesByProject(ctx, member, project)
	if err != nil {
		t.Fatal(err)
	}
	if len(files) != 1 || files[0].OriginalName != "project.txt" {
		t.Fatalf("shared project knowledge unavailable: %+v", files)
	}
	bases, err := repo.ListKnowledgeBases(ctx, member)
	if err != nil {
		t.Fatal(err)
	}
	seenProject, seenOwnerGlobal := false, false
	for _, b := range bases {
		if b.ID == projectBase {
			seenProject = true
		}
		if b.ID == globalBase {
			seenOwnerGlobal = true
		}
	}
	if !seenProject {
		t.Fatal("shared PROJECT knowledge base missing")
	}
	if seenOwnerGlobal {
		t.Fatal("owner GLOBAL knowledge leaked to member")
	}
}

func TestP9OrganizationWorkspaceAndBindingAuthorization(t *testing.T) {
	database, _ := p2Database(t)
	ctx := context.Background()
	repo := repository.NewMySQL(database)
	governance, err := NewGovernanceService(repo, "p9-test-master-key-32-bytes-minimum")
	if err != nil {
		t.Fatal(err)
	}
	insert := func(query string, args ...any) int64 {
		t.Helper()
		res, err := database.Exec(query, args...)
		if err != nil {
			t.Fatal(err)
		}
		id, err := res.LastInsertId()
		if err != nil {
			t.Fatal(err)
		}
		return id
	}

	owner := insert("INSERT INTO users(email,password_hash,display_name) VALUES('p9-org-owner@example.test','fixture','Owner')")
	admin := insert("INSERT INTO users(email,password_hash,display_name) VALUES('p9-org-admin@example.test','fixture','Admin')")
	developer := insert("INSERT INTO users(email,password_hash,display_name) VALUES('p9-org-dev@example.test','fixture','Developer')")
	outsider := insert("INSERT INTO users(email,password_hash,display_name) VALUES('p9-org-outsider@example.test','fixture','Outsider')")
	project := insert("INSERT INTO projects(user_id,name,description) VALUES(?,'Org Project','fixture')", owner)
	foreignProject := insert("INSERT INTO projects(user_id,name,description) VALUES(?,'Foreign Project','fixture')", outsider)

	org, err := governance.CreateOrganization(ctx, owner, "Platform Team")
	if err != nil {
		t.Fatal(err)
	}
	if org.OwnerID != owner || org.Name != "Platform Team" {
		t.Fatalf("unexpected organization: %+v", org)
	}
	if role, err := repo.OrganizationRole(ctx, owner, org.ID); err != nil || role != "OWNER" {
		t.Fatalf("owner organization role=%q err=%v", role, err)
	}
	ownerOrganizations, err := governance.ListOrganizations(ctx, owner)
	if err != nil {
		t.Fatal(err)
	}
	if len(ownerOrganizations) != 1 || ownerOrganizations[0].ID != org.ID {
		t.Fatalf("owner organizations=%+v", ownerOrganizations)
	}
	outsiderOrganizations, err := governance.ListOrganizations(ctx, outsider)
	if err != nil {
		t.Fatal(err)
	}
	if len(outsiderOrganizations) != 0 {
		t.Fatalf("unrelated user discovered organizations: %+v", outsiderOrganizations)
	}

	if member, err := governance.AddOrganizationMember(ctx, owner, org.ID, "p9-org-admin@example.test", "ADMIN"); err != nil || member == nil || member.Role != "ADMIN" {
		t.Fatalf("owner could not add org admin member=%+v err=%v", member, err)
	}
	adminOrganizations, err := governance.ListOrganizations(ctx, admin)
	if err != nil {
		t.Fatal(err)
	}
	if len(adminOrganizations) != 1 || adminOrganizations[0].ID != org.ID {
		t.Fatalf("organization member list visibility=%+v", adminOrganizations)
	}
	if member, err := governance.AddOrganizationMember(ctx, admin, org.ID, "p9-org-dev@example.test", "DEVELOPER"); err != nil || member == nil || member.Role != "DEVELOPER" {
		t.Fatalf("org admin could not add developer member=%+v err=%v", member, err)
	}
	if _, err := governance.AddOrganizationMember(ctx, developer, org.ID, "p9-org-outsider@example.test", "VIEWER"); err != ErrForbidden {
		t.Fatalf("org developer must not manage membership, got %v", err)
	}

	if err := governance.BindProjectToOrganization(ctx, admin, org.ID, project); err != ErrForbidden {
		t.Fatalf("org admin without Project ownership must not bind, got %v", err)
	}
	if err := governance.BindProjectToOrganization(ctx, owner, org.ID, foreignProject); err != ErrForbidden {
		t.Fatalf("organization owner must not bind someone else's Project, got %v", err)
	}
	if err := governance.BindProjectToOrganization(ctx, owner, org.ID, project); err != nil {
		t.Fatalf("organization/project owner bind failed: %v", err)
	}
	// Repeating the same PUT-style binding must be idempotent.
	if err := governance.BindProjectToOrganization(
		ctx,
		owner,
		org.ID,
		project,
	); err != nil {
		t.Fatalf(
			"repeated organization/project bind must be idempotent: %v",
			err,
		)
	}

	otherOrg, err := governance.CreateOrganization(
		ctx,
		owner,
		"other organization",
	)
	if err != nil {
		t.Fatalf("create second organization: %v", err)
	}
	if err := governance.BindProjectToOrganization(
		ctx,
		owner,
		otherOrg.ID,
		project,
	); err != ErrProjectAlreadyBound {
		t.Fatalf(
			"project already bound to another organization must conflict, got %v",
			err,
		)
	}
	var persistedOrgID int64
	if err := database.QueryRow(
		`SELECT organization_id
	 FROM organization_projects
	 WHERE project_id=?`,
		project,
	).Scan(&persistedOrgID); err != nil {
		t.Fatalf("read organization project binding: %v", err)
	}

	if persistedOrgID != org.ID {
		t.Fatalf(
			"project binding changed unexpectedly: got org=%d want org=%d",
			persistedOrgID,
			org.ID,
		)
	}
	var boundOrg int64
	if err := database.QueryRow("SELECT organization_id FROM organization_projects WHERE project_id=?", project).Scan(&boundOrg); err != nil {
		t.Fatal(err)
	}
	if boundOrg != org.ID {
		t.Fatalf("project bound to organization %d; want %d", boundOrg, org.ID)
	}
}

func TestP9ProjectRBACOrderingAndIDORDenial(t *testing.T) {
	database, _ := p2Database(t)
	ctx := context.Background()
	repo := repository.NewMySQL(database)
	governance, err := NewGovernanceService(repo, "p9-test-master-key-32-bytes-minimum")
	if err != nil {
		t.Fatal(err)
	}
	insert := func(query string, args ...any) int64 {
		t.Helper()
		res, err := database.Exec(query, args...)
		if err != nil {
			t.Fatal(err)
		}
		id, err := res.LastInsertId()
		if err != nil {
			t.Fatal(err)
		}
		return id
	}
	owner := insert("INSERT INTO users(email,password_hash,display_name) VALUES('p9-rbac-owner@example.test','fixture','Owner')")
	admin := insert("INSERT INTO users(email,password_hash,display_name) VALUES('p9-rbac-admin@example.test','fixture','Admin')")
	developer := insert("INSERT INTO users(email,password_hash,display_name) VALUES('p9-rbac-dev@example.test','fixture','Developer')")
	viewer := insert("INSERT INTO users(email,password_hash,display_name) VALUES('p9-rbac-viewer@example.test','fixture','Viewer')")
	outsider := insert("INSERT INTO users(email,password_hash,display_name) VALUES('p9-rbac-outsider@example.test','fixture','Outsider')")
	project := insert("INSERT INTO projects(user_id,name,description) VALUES(?,'RBAC Project','fixture')", owner)

	if _, err := governance.AddMember(ctx, owner, project, "p9-rbac-admin@example.test", "ADMIN"); err != nil {
		t.Fatal(err)
	}
	if _, err := governance.AddMember(ctx, admin, project, "p9-rbac-dev@example.test", "DEVELOPER"); err != nil {
		t.Fatal(err)
	}
	if _, err := governance.AddMember(ctx, admin, project, "p9-rbac-viewer@example.test", "VIEWER"); err != nil {
		t.Fatal(err)
	}

	checks := []struct {
		name    string
		uid     int64
		minimum string
		role    string
		err     error
	}{
		{"owner-owner", owner, "OWNER", "OWNER", nil},
		{"owner-admin", owner, "ADMIN", "OWNER", nil},
		{"admin-admin", admin, "ADMIN", "ADMIN", nil},
		{"admin-owner-denied", admin, "OWNER", "ADMIN", ErrForbidden},
		{"developer-developer", developer, "DEVELOPER", "DEVELOPER", nil},
		{"developer-admin-denied", developer, "ADMIN", "DEVELOPER", ErrForbidden},
		{"viewer-viewer", viewer, "VIEWER", "VIEWER", nil},
		{"viewer-developer-denied", viewer, "DEVELOPER", "VIEWER", ErrForbidden},
		{"outsider-hidden", outsider, "VIEWER", "", ErrNotFound},
	}
	for _, tc := range checks {
		t.Run(tc.name, func(t *testing.T) {
			role, err := governance.RequireRole(ctx, tc.uid, project, tc.minimum)
			if err != tc.err || role != tc.role {
				t.Fatalf("RequireRole role=%q err=%v; want role=%q err=%v", role, err, tc.role, tc.err)
			}
		})
	}

	if err := governance.CheckQuota(ctx, viewer, project); err != ErrForbidden {
		t.Fatalf("VIEWER must not execute protected project work, got %v", err)
	}
	if err := governance.CheckQuota(ctx, developer, project); err != nil {
		t.Fatalf("DEVELOPER shared execution gate failed: %v", err)
	}
	if _, err := governance.UpdateQuota(ctx, developer, project, model.ProjectQuota{RequestsPerMinute: 10, ConcurrentTasks: 2, MonthlyTokenLimit: 100, MonthlyCostLimit: 10, DailyToolActionLimit: 10}); err != ErrForbidden {
		t.Fatalf("DEVELOPER must not manage quota, got %v", err)
	}
	if _, err := governance.Overview(ctx, outsider, project); err != ErrNotFound {
		t.Fatalf("unrelated user governance IDOR must be hidden, got %v", err)
	}
	if err := governance.CheckQuota(ctx, outsider, project); err != ErrNotFound {
		t.Fatalf("unrelated user execution IDOR must be hidden, got %v", err)
	}
}

func TestP9SharedProjectDoesNotShareUserGlobalMemory(t *testing.T) {
	database, _ := p2Database(t)
	ctx := context.Background()
	if err := dbschema.EnsureMemorySchema(ctx, database); err != nil {
		t.Fatal(err)
	}
	repo := repository.NewMySQL(database)
	governance, err := NewGovernanceService(repo, "p9-test-master-key-32-bytes-minimum")
	if err != nil {
		t.Fatal(err)
	}
	insert := func(query string, args ...any) int64 {
		t.Helper()
		res, err := database.Exec(query, args...)
		if err != nil {
			t.Fatal(err)
		}
		id, err := res.LastInsertId()
		if err != nil {
			t.Fatal(err)
		}
		return id
	}
	owner := insert("INSERT INTO users(email,password_hash,display_name) VALUES('p9-memory-owner@example.test','fixture','Owner')")
	member := insert("INSERT INTO users(email,password_hash,display_name) VALUES('p9-memory-member@example.test','fixture','Member')")
	project := insert("INSERT INTO projects(user_id,name,description) VALUES(?,'Memory Shared Project','fixture')", owner)
	if _, err := governance.AddMember(ctx, owner, project, "p9-memory-member@example.test", "DEVELOPER"); err != nil {
		t.Fatal(err)
	}

	ownerMemory, err := repo.CreateMemory(ctx, owner, model.UserMemory{Category: "profile", MemoryKey: "owner.private.preference", Content: "owner-only-memory", SourceType: "manual", Confidence: 1, Status: "active"})
	if err != nil {
		t.Fatal(err)
	}
	memberMemory, err := repo.CreateMemory(ctx, member, model.UserMemory{Category: "profile", MemoryKey: "member.preference", Content: "member-memory", SourceType: "manual", Confidence: 1, Status: "active"})
	if err != nil {
		t.Fatal(err)
	}
	memories, err := repo.ListActiveMemories(ctx, member, 20)
	if err != nil {
		t.Fatal(err)
	}
	if len(memories) != 1 || memories[0].ID != memberMemory.ID || memories[0].UserID != member {
		t.Fatalf("member memory scope leaked or lost: %+v", memories)
	}
	got, err := repo.MemoryByID(ctx, member, ownerMemory.ID)
	if err != nil {
		t.Fatal(err)
	}
	if got != nil {
		t.Fatalf("owner user-global Memory leaked through shared Project: %+v", got)
	}
}

func TestP9QuotaDimensionsFailClosedAndSuppressRuntime(t *testing.T) {
	newFixture := func(t *testing.T) (*repository.MySQL, *GovernanceService, int64, int64, int64) {
		t.Helper()
		database, _ := p2Database(t)
		repo := repository.NewMySQL(database)
		governance, err := NewGovernanceService(repo, "p9-test-master-key-32-bytes-minimum")
		if err != nil {
			t.Fatal(err)
		}
		insert := func(query string, args ...any) int64 {
			t.Helper()
			res, err := database.Exec(query, args...)
			if err != nil {
				t.Fatal(err)
			}
			id, err := res.LastInsertId()
			if err != nil {
				t.Fatal(err)
			}
			return id
		}
		owner := insert("INSERT INTO users(email,password_hash,display_name) VALUES(CONCAT('p9-quota-owner-',UUID(),'@example.test'),'fixture','Owner')")
		developer := insert("INSERT INTO users(email,password_hash,display_name) VALUES(CONCAT('p9-quota-dev-',UUID(),'@example.test'),'fixture','Developer')")
		project := insert("INSERT INTO projects(user_id,name,description) VALUES(?,'Quota Project','fixture')", owner)
		if _, err := database.Exec("INSERT INTO project_members(project_id,user_id,role) VALUES(?,?,'DEVELOPER')", project, developer); err != nil {
			t.Fatal(err)
		}
		return repo, governance, owner, developer, project
	}
	quota := func(concurrent, tokens int64, cost float64, tools int64) model.ProjectQuota {
		return model.ProjectQuota{RequestsPerMinute: 1000, ConcurrentTasks: concurrent, MonthlyTokenLimit: tokens, MonthlyCostLimit: cost, DailyToolActionLimit: tools}
	}

	t.Run("ConcurrentTasks", func(t *testing.T) {
		repo, governance, owner, developer, project := newFixture(t)
		ctx := context.Background()
		if _, err := governance.UpdateQuota(ctx, owner, project, quota(1, 1000, 100, 100)); err != nil {
			t.Fatal(err)
		}
		conversation, err := repo.CreateConversation(ctx, developer, "quota concurrent")
		if err != nil {
			t.Fatal(err)
		}
		if err := repo.AssignConversationToProject(ctx, developer, project, conversation.ID); err != nil {
			t.Fatal(err)
		}
		convID := conversation.ID
		if _, err := repo.CreateTask(ctx, model.Task{UserID: developer, ConversationID: &convID, RequestID: "p9-concurrent-active", TaskText: "active", Scheduler: "greedy", Planner: "heuristic", ExecutionMode: "auto", SynthesisMode: "auto"}, model.TaskConstraints{MaxLatencyMS: 1000, MaxCost: 1, MinQuality: .8}); err != nil {
			t.Fatal(err)
		}
		if err := governance.CheckQuota(ctx, developer, project); err != ErrQuotaExceeded {
			t.Fatalf("concurrent task limit must fail closed, got %v", err)
		}
	})

	t.Run("MonthlyTokens", func(t *testing.T) {
		_, governance, owner, developer, project := newFixture(t)
		ctx := context.Background()
		if _, err := governance.UpdateQuota(ctx, owner, project, quota(10, 100, 100, 100)); err != nil {
			t.Fatal(err)
		}
		governance.RecordUsage(ctx, project, 100, 0, 0)
		if err := governance.CheckQuota(ctx, developer, project); err != ErrQuotaExceeded {
			t.Fatalf("monthly token limit must fail closed, got %v", err)
		}
	})

	t.Run("MonthlyCost", func(t *testing.T) {
		_, governance, owner, developer, project := newFixture(t)
		ctx := context.Background()
		if _, err := governance.UpdateQuota(ctx, owner, project, quota(10, 1000, 2.5, 100)); err != nil {
			t.Fatal(err)
		}
		governance.RecordUsage(ctx, project, 0, 2.5, 0)
		if err := governance.CheckQuota(ctx, developer, project); err != ErrQuotaExceeded {
			t.Fatalf("monthly cost limit must fail closed, got %v", err)
		}
	})

	t.Run("DailyToolActions", func(t *testing.T) {
		_, governance, owner, developer, project := newFixture(t)
		ctx := context.Background()
		if _, err := governance.UpdateQuota(ctx, owner, project, quota(10, 1000, 100, 3)); err != nil {
			t.Fatal(err)
		}
		governance.RecordUsage(ctx, project, 0, 0, 3)
		if err := governance.CheckQuota(ctx, developer, project); err != ErrQuotaExceeded {
			t.Fatalf("daily tool-action limit must fail closed, got %v", err)
		}
	})

	t.Run("RuntimeSuppressedAfterQuotaRejection", func(t *testing.T) {
		repo, governance, owner, developer, project := newFixture(t)
		ctx := context.Background()
		if _, err := governance.UpdateQuota(ctx, owner, project, quota(10, 1, 100, 100)); err != nil {
			t.Fatal(err)
		}
		governance.RecordUsage(ctx, project, 1, 0, 0)
		conversation, err := repo.CreateConversation(ctx, developer, "quota runtime")
		if err != nil {
			t.Fatal(err)
		}
		if err := repo.AssignConversationToProject(ctx, developer, project, conversation.ID); err != nil {
			t.Fatal(err)
		}
		var runtimeCalls atomic.Int64
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			runtimeCalls.Add(1)
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"status":"COMPLETED","answer":"must-not-run","trace":[],"selectedAgents":[],"dag":{}}`))
		}))
		defer server.Close()
		tasks := NewTaskService(repo, repo, repo, runtimeclient.NewClient(server.URL, "fixture", 2*time.Second), repo, repo, NewProjectRuntimeService(repo))
		tasks.SetGovernanceService(governance)
		convID := conversation.ID
		if _, err := tasks.Run(ctx, developer, RunTaskInput{ConversationID: &convID, Task: "must be rejected before runtime"}); err != ErrQuotaExceeded {
			t.Fatalf("runtime task must return quota error, got %v", err)
		}
		if got := runtimeCalls.Load(); got != 0 {
			t.Fatalf("quota rejection fell through to runtime: calls=%d", got)
		}
	})
}

func TestP9AuditActorResourceResultAndSensitiveMetadataRedaction(t *testing.T) {
	database, _ := p2Database(t)
	ctx := context.Background()
	repo := repository.NewMySQL(database)
	governance, err := NewGovernanceService(repo, "p9-test-master-key-32-bytes-minimum")
	if err != nil {
		t.Fatal(err)
	}
	insert := func(query string, args ...any) int64 {
		t.Helper()
		res, err := database.Exec(query, args...)
		if err != nil {
			t.Fatal(err)
		}
		id, err := res.LastInsertId()
		if err != nil {
			t.Fatal(err)
		}
		return id
	}
	owner := insert("INSERT INTO users(email,password_hash,display_name) VALUES('p9-audit-owner@example.test','fixture','Owner')")
	project := insert("INSERT INTO projects(user_id,name,description) VALUES(?,'Audit Project','fixture')", owner)

	if _, err := governance.UpdateQuota(ctx, owner, project, model.ProjectQuota{RequestsPerMinute: 77, ConcurrentTasks: 7, MonthlyTokenLimit: 700, MonthlyCostLimit: 70, DailyToolActionLimit: 700}); err != nil {
		t.Fatal(err)
	}
	governance.audit(ctx, owner, project, "project.audit.redaction_probe", "project", "audit-probe", "SUCCESS", map[string]any{
		"password":         "password-plaintext",
		"accessToken":      "token-plaintext",
		"credential":       "credential-plaintext",
		"clientSecret":     "secret-plaintext",
		"apiKey":           "key-plaintext",
		"otpCode":          "123456",
		"nonSensitiveNote": "safe",
	})

	events, err := governance.Audit(ctx, owner, project, 100)
	if err != nil {
		t.Fatal(err)
	}
	var quotaEvent, probe *model.AuditEvent
	for i := range events {
		event := &events[i]
		switch event.Action {
		case "project.quota.update":
			quotaEvent = event
		case "project.audit.redaction_probe":
			probe = event
		}
	}
	if quotaEvent == nil {
		t.Fatal("real governance audit event missing")
	}
	if quotaEvent.ActorUserID != owner || quotaEvent.ProjectID == nil || *quotaEvent.ProjectID != project || quotaEvent.ResourceType != "project_quota" || quotaEvent.ResourceID != strconv.FormatInt(project, 10) || quotaEvent.Result != "SUCCESS" {
		t.Fatalf("governance audit identity/resource/result mismatch: %+v", quotaEvent)
	}
	if probe == nil {
		t.Fatal("redaction probe audit event missing")
	}
	if probe.ActorUserID != owner || probe.ProjectID == nil || *probe.ProjectID != project || probe.ResourceType != "project" || probe.ResourceID != "audit-probe" || probe.Result != "SUCCESS" {
		t.Fatalf("redaction probe identity/resource/result mismatch: %+v", probe)
	}
	for _, key := range []string{"password", "accessToken", "credential", "clientSecret", "apiKey", "otpCode"} {
		if probe.Metadata[key] != "[REDACTED]" {
			t.Fatalf("sensitive audit metadata %s leaked: %+v", key, probe.Metadata)
		}
	}
	if probe.Metadata["nonSensitiveNote"] != "safe" {
		t.Fatalf("non-sensitive metadata should remain useful: %+v", probe.Metadata)
	}
}

func TestP9SharedProjectExecutionUsesOwnerResourcesAndRecordsRuntimeUsage(t *testing.T) {
	database, _ := p2Database(t)
	ctx := context.Background()
	repo := repository.NewMySQL(database)
	governance, err := NewGovernanceService(repo, "p9-test-master-key-32-bytes-minimum")
	if err != nil {
		t.Fatal(err)
	}
	insert := func(query string, args ...any) int64 {
		t.Helper()
		res, err := database.Exec(query, args...)
		if err != nil {
			t.Fatal(err)
		}
		id, err := res.LastInsertId()
		if err != nil {
			t.Fatal(err)
		}
		return id
	}

	owner := insert("INSERT INTO users(email,password_hash,display_name) VALUES('p9-exec-owner@example.test','fixture','Owner')")
	developer := insert("INSERT INTO users(email,password_hash,display_name) VALUES('p9-exec-dev@example.test','fixture','Developer')")
	project := insert("INSERT INTO projects(user_id,name,description) VALUES(?,'Execution Shared Project','fixture')", owner)
	if _, err := governance.AddMember(ctx, owner, project, "p9-exec-dev@example.test", "DEVELOPER"); err != nil {
		t.Fatal(err)
	}
	conversation, err := repo.CreateConversation(ctx, developer, "shared execution")
	if err != nil {
		t.Fatal(err)
	}
	if err := repo.AssignConversationToProject(ctx, developer, project, conversation.ID); err != nil {
		t.Fatal(err)
	}
	ownerAgent := insert("INSERT INTO agents(user_id,name,endpoint,protocol,capabilities_json) VALUES(?,'Owner Agent','http://fixture.invalid','a2a','[\"general\"]')", owner)
	profiles := NewProjectRuntimeService(repo)
	if _, err := profiles.Update(ctx, owner, project, model.ProjectRuntimeConfig{
		AgentMode: "selected", AgentIDs: []int64{ownerAgent},
		ToolMode: "all", MCPMode: "all",
		Policy: model.ProjectRuntimePolicy{Mode: "project", Scheduler: "greedy", Planner: "heuristic", ExecutionMode: "auto", SynthesisMode: "auto", Constraints: model.TaskConstraints{MaxLatencyMS: 5000, MaxCost: 10, MinQuality: .8}},
	}); err != nil {
		t.Fatal(err)
	}
	if _, err := governance.UpdateQuota(ctx, owner, project, model.ProjectQuota{RequestsPerMinute: 100, ConcurrentTasks: 10, MonthlyTokenLimit: 10000, MonthlyCostLimit: 100, DailyToolActionLimit: 100}); err != nil {
		t.Fatal(err)
	}

	requestSeen := make(chan runtimeclient.ExecuteRequest, 1)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/internal/v1/runtime/execute" {
			http.NotFound(w, r)
			return
		}
		var req runtimeclient.ExecuteRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		requestSeen <- req
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"status":"COMPLETED","answer":"shared-ok","selected_agents":["Owner Agent"],"estimated_cost":2.75,"elapsed_ms":12,"trace":[],"dag":{},"observability":{"modelTotalTokens":321,"toolCalls":4}}`))
	}))
	defer server.Close()

	tasks := NewTaskService(repo, repo, repo, runtimeclient.NewClient(server.URL, "fixture", 2*time.Second), repo, repo, profiles)
	tasks.SetGovernanceService(governance)
	convID := conversation.ID
	result, err := tasks.Run(ctx, developer, RunTaskInput{ConversationID: &convID, Task: "execute shared project"})
	if err != nil {
		t.Fatal(err)
	}
	if result == nil || result.Answer != "shared-ok" {
		t.Fatalf("shared project execution result=%+v", result)
	}
	select {
	case req := <-requestSeen:
		if req.UserID != developer {
			t.Fatalf("runtime actor user_id=%d; want member %d", req.UserID, developer)
		}
		if len(req.Agents) != 1 || req.Agents[0].ID != ownerAgent || req.Agents[0].UserID != owner {
			t.Fatalf("shared execution did not use owner project Agent pool: %+v", req.Agents)
		}
	default:
		t.Fatal("runtime request not observed")
	}
	overview, err := governance.Overview(ctx, owner, project)
	if err != nil {
		t.Fatal(err)
	}
	if overview.Usage.TokenCount < 321 || overview.Usage.EstimatedCost < 2.75 || overview.Usage.ToolActionCount < 4 {
		t.Fatalf("runtime observability usage was not persisted: %+v", overview.Usage)
	}
}

func TestP9ViewerCannotFallThroughToSharedProjectRuntime(t *testing.T) {
	database, _ := p2Database(t)
	ctx := context.Background()
	repo := repository.NewMySQL(database)
	governance, err := NewGovernanceService(repo, "p9-test-master-key-32-bytes-minimum")
	if err != nil {
		t.Fatal(err)
	}
	insert := func(query string, args ...any) int64 {
		t.Helper()
		res, err := database.Exec(query, args...)
		if err != nil {
			t.Fatal(err)
		}
		id, err := res.LastInsertId()
		if err != nil {
			t.Fatal(err)
		}
		return id
	}
	owner := insert("INSERT INTO users(email,password_hash,display_name) VALUES('p9-viewexec-owner@example.test','fixture','Owner')")
	viewer := insert("INSERT INTO users(email,password_hash,display_name) VALUES('p9-viewexec-viewer@example.test','fixture','Viewer')")
	project := insert("INSERT INTO projects(user_id,name,description) VALUES(?,'Viewer Protected Project','fixture')", owner)
	if _, err := governance.AddMember(ctx, owner, project, "p9-viewexec-viewer@example.test", "VIEWER"); err != nil {
		t.Fatal(err)
	}
	conversation, err := repo.CreateConversation(ctx, viewer, "viewer blocked")
	if err != nil {
		t.Fatal(err)
	}
	// Simulate a stale or forged persisted binding that bypassed the normal
	// front-door assignment authorization. AssignConversationToProject must
	// continue to reject VIEWER members in production; this fixture write is
	// intentionally direct so the test can reach TaskService.Run and prove the
	// runtime governance recheck fails closed as a second line of defense.
	if _, err := database.ExecContext(
		ctx,
		"INSERT INTO project_conversations(project_id,conversation_id) VALUES(?,?)",
		project,
		conversation.ID,
	); err != nil {
		t.Fatal(err)
	}
	ownerAgent := insert("INSERT INTO agents(user_id,name,endpoint,protocol,capabilities_json) VALUES(?,'Protected Owner Agent','http://fixture.invalid','a2a','[\"general\"]')", owner)
	profiles := NewProjectRuntimeService(repo)
	if _, err := profiles.Update(ctx, owner, project, model.ProjectRuntimeConfig{AgentMode: "selected", AgentIDs: []int64{ownerAgent}, ToolMode: "all", MCPMode: "all"}); err != nil {
		t.Fatal(err)
	}

	var runtimeCalls atomic.Int64
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		runtimeCalls.Add(1)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"status":"COMPLETED","answer":"must-not-run","trace":[],"selected_agents":[],"dag":{}}`))
	}))
	defer server.Close()
	tasks := NewTaskService(repo, repo, repo, runtimeclient.NewClient(server.URL, "fixture", 2*time.Second), repo, repo, profiles)
	tasks.SetGovernanceService(governance)
	convID := conversation.ID
	if _, err := tasks.Run(ctx, viewer, RunTaskInput{ConversationID: &convID, Task: "viewer must not execute"}); err != ErrForbidden {
		t.Fatalf("VIEWER execution must fail with forbidden, got %v", err)
	}
	if got := runtimeCalls.Load(); got != 0 {
		t.Fatalf("VIEWER governance denial fell through to runtime: calls=%d", got)
	}
}
