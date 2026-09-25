package service

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"testing"
	"time"

	dbschema "example.com/agentmesh-control-plane/internal/db"
	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/repository"
	runtimeclient "example.com/agentmesh-control-plane/internal/runtime"
	mysql "github.com/go-sql-driver/mysql"
)

// Uses the production schema, repositories, TaskService and HTTP runtime client.
//
// The service package contains many integration tests that all need the same
// production schema. Rebuilding and migrating a brand-new schema for every
// test made the package spend almost the entire 10 minute Go test timeout on
// repeated DDL. The package-level fixture below creates and migrates one
// isolated schema once, while p2Database gives every test a fresh connection
// pool and clears all rows before use. A mutex keeps database-backed tests
// isolated even if a future test opts into t.Parallel().
var p2SharedFixture struct {
	sync.Mutex
	once      sync.Once
	admin     *sql.DB
	database  string
	dsn       string
	sourceDSN string
	err       error
}

func TestMain(m *testing.M) {
	code := m.Run()
	p2CleanupSharedDatabase()
	os.Exit(code)
}

func p2Database(t *testing.T) (*sql.DB, string) {
	t.Helper()
	dsn := strings.TrimSpace(os.Getenv("QA_TEST_MYSQL_DSN"))
	if dsn == "" {
		t.Skip("set QA_TEST_MYSQL_DSN to run isolated MySQL acceptance tests")
	}

	p2SharedFixture.Lock()
	locked := true
	defer func() {
		if locked {
			p2SharedFixture.Unlock()
		}
	}()

	if err := p2EnsureSharedDatabase(dsn); err != nil {
		t.Fatal(err)
	}
	if p2SharedFixture.sourceDSN != dsn {
		t.Fatalf("QA_TEST_MYSQL_DSN changed during service test process")
	}

	database, err := sql.Open("mysql", p2SharedFixture.dsn)
	if err != nil {
		t.Fatal(err)
	}
	if err := database.Ping(); err != nil {
		database.Close()
		t.Fatal(err)
	}
	if err := p2ResetSharedDatabase(database); err != nil {
		database.Close()
		t.Fatalf("reset isolated service database: %v", err)
	}

	// Hold the package fixture lock until this test has fully cleaned up. This
	// prevents data leakage if a database-backed test becomes parallel later.
	locked = false
	t.Cleanup(func() {
		if err := database.Close(); err != nil {
			t.Errorf("close isolated service database: %v", err)
		}
		p2SharedFixture.Unlock()
	})
	t.Logf("isolated shared database: %s", p2SharedFixture.database)
	return database, p2SharedFixture.dsn
}

func p2EnsureSharedDatabase(dsn string) error {
	p2SharedFixture.once.Do(func() {
		p2SharedFixture.sourceDSN = dsn
		cfg, err := mysql.ParseDSN(dsn)
		if err != nil {
			p2SharedFixture.err = err
			return
		}
		cfg.DBName = ""
		cfg.ParseTime = true
		admin, err := sql.Open("mysql", cfg.FormatDSN())
		if err != nil {
			p2SharedFixture.err = err
			return
		}
		if err = admin.Ping(); err != nil {
			admin.Close()
			p2SharedFixture.err = err
			return
		}

		name := fmt.Sprintf("agentmesh_service_test_%d_%d", os.Getpid(), time.Now().UnixNano())
		if _, err = admin.Exec("CREATE DATABASE `" + name + "` CHARACTER SET utf8mb4"); err != nil {
			admin.Close()
			p2SharedFixture.err = err
			return
		}

		dbCfg := *cfg
		dbCfg.DBName = name
		dbCfg.MultiStatements = true
		database, err := sql.Open("mysql", dbCfg.FormatDSN())
		if err != nil {
			_, _ = admin.Exec("DROP DATABASE IF EXISTS `" + name + "`")
			admin.Close()
			p2SharedFixture.err = err
			return
		}

		raw, err := os.ReadFile(filepath.Join("..", "..", "..", "infra", "mysql", "init", "001_schema.sql"))
		if err != nil {
			database.Close()
			_, _ = admin.Exec("DROP DATABASE IF EXISTS `" + name + "`")
			admin.Close()
			p2SharedFixture.err = err
			return
		}
		schema := string(raw)
		pos := strings.Index(schema, "CREATE TABLE")
		if pos < 0 {
			database.Close()
			_, _ = admin.Exec("DROP DATABASE IF EXISTS `" + name + "`")
			admin.Close()
			p2SharedFixture.err = errors.New("base schema has no tables")
			return
		}
		if _, err = database.Exec(schema[pos:]); err != nil {
			database.Close()
			_, _ = admin.Exec("DROP DATABASE IF EXISTS `" + name + "`")
			admin.Close()
			p2SharedFixture.err = err
			return
		}

		migrationCtx, cancelMigration := context.WithTimeout(context.Background(), 60*time.Second)
		err = dbschema.Migrate(migrationCtx, database)
		cancelMigration()
		if err != nil {
			database.Close()
			_, _ = admin.Exec("DROP DATABASE IF EXISTS `" + name + "`")
			admin.Close()
			p2SharedFixture.err = fmt.Errorf("initialize isolated service database: %w", err)
			return
		}
		if err = database.Close(); err != nil {
			_, _ = admin.Exec("DROP DATABASE IF EXISTS `" + name + "`")
			admin.Close()
			p2SharedFixture.err = err
			return
		}

		p2SharedFixture.admin = admin
		p2SharedFixture.database = name
		p2SharedFixture.dsn = dbCfg.FormatDSN()
	})
	return p2SharedFixture.err
}

func p2ResetSharedDatabase(database *sql.DB) error {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	conn, err := database.Conn(ctx)
	if err != nil {
		return err
	}
	defer conn.Close()

	rows, err := conn.QueryContext(ctx, `
		SELECT TABLE_NAME
		FROM information_schema.TABLES
		WHERE TABLE_SCHEMA = DATABASE()
		  AND TABLE_TYPE = 'BASE TABLE'
		ORDER BY TABLE_NAME`)
	if err != nil {
		return err
	}
	var tables []string
	for rows.Next() {
		var table string
		if err := rows.Scan(&table); err != nil {
			rows.Close()
			return err
		}
		tables = append(tables, table)
	}
	if err := rows.Err(); err != nil {
		rows.Close()
		return err
	}
	if err := rows.Close(); err != nil {
		return err
	}

	if _, err := conn.ExecContext(ctx, "SET FOREIGN_KEY_CHECKS=0"); err != nil {
		return err
	}
	reenable := true
	defer func() {
		if reenable {
			_, _ = conn.ExecContext(context.Background(), "SET FOREIGN_KEY_CHECKS=1")
		}
	}()
	for _, table := range tables {
		quoted := "`" + strings.ReplaceAll(table, "`", "``") + "`"
		if _, err := conn.ExecContext(ctx, "DELETE FROM "+quoted); err != nil {
			return fmt.Errorf("clear %s: %w", table, err)
		}
	}
	if _, err := conn.ExecContext(ctx, "SET FOREIGN_KEY_CHECKS=1"); err != nil {
		return err
	}
	reenable = false
	return nil
}

func p2CleanupSharedDatabase() {
	p2SharedFixture.Lock()
	defer p2SharedFixture.Unlock()
	if p2SharedFixture.admin == nil || p2SharedFixture.database == "" {
		return
	}
	_, _ = p2SharedFixture.admin.Exec("DROP DATABASE IF EXISTS `" + p2SharedFixture.database + "`")
	_ = p2SharedFixture.admin.Close()
	p2SharedFixture.admin = nil
	p2SharedFixture.database = ""
	p2SharedFixture.dsn = ""
}

func TestProjectRuntimeDatabaseAcceptance(t *testing.T) {
	database, dsn := p2Database(t)
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
	uid := insert("INSERT INTO users(email,password_hash,display_name) VALUES('qa-a@example.test','fixture','QA Database A')")
	other := insert("INSERT INTO users(email,password_hash,display_name) VALUES('qa-b@example.test','fixture','QA Database B')")
	projectA := insert("INSERT INTO projects(user_id,name,description) VALUES(?,'A','fixture')", uid)
	projectB := insert("INSERT INTO projects(user_id,name,description) VALUES(?,'B','fixture')", uid)
	foreignProject := insert("INSERT INTO projects(user_id,name,description) VALUES(?,'Foreign','fixture')", other)
	conversation := func(owner, project int64) int64 {
		id := insert("INSERT INTO conversations(user_id,title) VALUES(?,'QA Database fixture')", owner)
		if project > 0 {
			insert("INSERT INTO project_conversations(project_id,conversation_id) VALUES(?,?)", project, id)
		}
		return id
	}
	convA, convB, normal, foreignConv := conversation(uid, projectA), conversation(uid, projectB), conversation(uid, 0), conversation(other, foreignProject)
	agent := func(owner int64, name string) int64 {
		return insert("INSERT INTO agents(user_id,name,endpoint,protocol,capabilities_json) VALUES(?,?,'http://fixture.invalid','a2a','[\"general\"]')", owner, name)
	}
	tool := func(owner int64, name string) int64 {
		return insert("INSERT INTO tools(user_id,name,input_schema) VALUES(?,?,'{}')", owner, name)
	}
	mcp := func(owner int64, name string) int64 {
		return insert("INSERT INTO mcp_servers(user_id,name,endpoint) VALUES(?,?,'http://fixture.invalid/mcp')", owner, name)
	}
	a1, a2, ax := agent(uid, "A1"), agent(uid, "A2"), agent(other, "Foreign")
	t1, t2, tx := tool(uid, "T1"), tool(uid, "T2"), tool(other, "Foreign")
	m1, m2, mx := mcp(uid, "M1"), mcp(uid, "M2"), mcp(other, "Foreign")
	selected := model.ProjectRuntimeConfig{AgentMode: "selected", AgentIDs: []int64{a1}, ToolMode: "selected", ToolIDs: []int64{t1}, MCPMode: "selected", MCPServerIDs: []int64{m1}, Policy: model.ProjectRuntimePolicy{Mode: "project", Scheduler: "fixed", Planner: "multi_objective", ExecutionMode: "sequential", SynthesisMode: "never", Constraints: model.TaskConstraints{MaxLatencyMS: 3210, MaxCost: .07, MinQuality: .92}}}
	save := func(t *testing.T, project int64, cfg model.ProjectRuntimeConfig) *model.ProjectRuntimeConfig {
		t.Helper()
		got, err := profiles.Update(ctx, uid, project, cfg)
		if err != nil {
			t.Fatal(err)
		}
		return got
	}
	requests := make(chan runtimeclient.ExecuteRequest, 64)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/internal/v1/runtime/execute" || r.Method != "POST" {
			http.Error(w, "unexpected request", 400)
			return
		}
		var req runtimeclient.ExecuteRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, err.Error(), 400)
			return
		}
		requests <- req
		response := map[string]any{"status": "COMPLETED", "answer": "fixture answer", "trace": []map[string]any{{"kind": "task", "title": "Task"}}, "selectedAgents": []string{}, "dag": map[string]any{}}
		if req.Task == "suspend" {
			response["status"] = "INPUT_REQUIRED"
			response["continuation"] = &runtimeclient.Continuation{Protocol: "a2a", AgentID: a1, TaskID: "external-fixture", ContextID: "fixture", State: "INPUT_REQUIRED"}
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(response)
	}))
	defer server.Close()
	tasks := NewTaskService(repo, repo, repo, runtimeclient.NewClient(server.URL, "fixture", 5*time.Second), repo, repo, profiles)
	input := func(conv int64) RunTaskInput {
		return RunTaskInput{ConversationID: &conv, Task: "validate", Scheduler: "greedy", Planner: "heuristic", ExecutionMode: "parallel", SynthesisMode: "always", Constraints: model.TaskConstraints{MaxLatencyMS: 4567, MaxCost: .13, MinQuality: .81}}
	}
	run := func(t *testing.T, conv int64) (*RunTaskResult, runtimeclient.ExecuteRequest) {
		t.Helper()
		res, err := tasks.Run(ctx, uid, input(conv))
		if err != nil {
			t.Fatal(err)
		}
		select {
		case req := <-requests:
			return res, req
		default:
			t.Fatal("runtime HTTP request missing")
			return nil, runtimeclient.ExecuteRequest{}
		}
	}
	pools := func(t *testing.T, req runtimeclient.ExecuteRequest, aa, tt, mm []int64) {
		t.Helper()
		a, b, c := []int64{}, []int64{}, []int64{}
		for _, v := range req.Agents {
			a = append(a, v.ID)
			if v.UserID != uid || v.Status != "ACTIVE" {
				t.Errorf("unsafe agent: %+v", v)
			}
		}
		for _, v := range req.Tools {
			b = append(b, v.ID)
			if v.UserID != uid || !v.Enabled {
				t.Error("unsafe tool")
			}
		}
		for _, v := range req.MCPServers {
			c = append(c, v.ID)
			if v.UserID != uid || !v.Enabled {
				t.Error("unsafe MCP")
			}
		}
		if !reflect.DeepEqual(a, aa) || !reflect.DeepEqual(b, tt) || !reflect.DeepEqual(c, mm) {
			t.Errorf("pools agents=%v tools=%v MCP=%v; want %v %v %v", a, b, c, aa, tt, mm)
		}
	}

	t.Run("ConversationOwnershipFailClosed", func(t *testing.T) {
		// NULL project is legitimate ONLY after verifying conversation ownership.
		pid, err := repo.ProjectIDByConversation(ctx, uid, normal)
		if err != nil || pid != nil {
			t.Fatalf("owned unbound conversation: project=%v err=%v", pid, err)
		}
		if resolved, err := profiles.ResolveForConversation(ctx, uid, normal); err != nil || resolved != nil {
			t.Fatalf("owned unbound conversation resolution: %v %v", resolved, err)
		}
		pid, err = repo.ProjectIDByConversation(ctx, uid, convA)
		if err != nil || pid == nil || *pid != projectA {
			t.Fatalf("owned project conversation: project=%v err=%v", pid, err)
		}
		for _, id := range []int64{foreignConv, 999999999} {
			if _, err := repo.ProjectIDByConversation(ctx, uid, id); !errors.Is(err, repository.ErrNotOwned) {
				t.Errorf("foreign or missing repository conversation %d: %v", id, err)
			}
			if _, err := profiles.ResolveForConversation(ctx, uid, id); !errors.Is(err, ErrNotFound) {
				t.Errorf("foreign or missing service conversation %d: %v", id, err)
			}
		}
		// Deliberately create an unauthorized binding inside the isolated QA DB:
		// an owned conversation must not fall back to account-wide resources.
		if _, err := database.ExecContext(ctx,
			"INSERT INTO project_conversations(project_id,conversation_id) VALUES(?,?)",
			foreignProject, normal); err != nil {
			t.Fatal(err)
		}
		defer func() {
			if _, err := database.ExecContext(ctx,
				"DELETE FROM project_conversations WHERE conversation_id=? AND project_id=?",
				normal, foreignProject); err != nil {
				t.Errorf("restore isolated test binding: %v", err)
			}
		}()
		if _, err := repo.ProjectIDByConversation(ctx, uid, normal); !errors.Is(err, repository.ErrNotOwned) {
			t.Fatalf("inaccessible project must not become unbound: %v", err)
		}
		if _, err := tasks.Run(ctx, uid, input(normal)); !errors.Is(err, ErrNotFound) {
			t.Fatalf("inaccessible project reached task service: %v", err)
		}
		select {
		case <-requests:
			t.Fatal("inaccessible project reached runtime")
		default:
		}
	})

	t.Run("DefaultAllAndPersistence", func(t *testing.T) {
		cfg, err := profiles.Get(ctx, uid, projectA)
		if err != nil {
			t.Fatal(err)
		}
		if cfg.AgentMode != "all" || cfg.ToolMode != "all" || cfg.MCPMode != "all" || cfg.Policy.Mode != "inherit" {
			t.Fatalf("defaults=%+v", cfg)
		}
		_, req := run(t, convA)
		pools(t, req, []int64{a1, a2}, []int64{t1, t2}, []int64{m1, m2})
		saved := save(t, projectA, selected)
		fresh, err := sql.Open("mysql", dsn)
		if err != nil {
			t.Fatal(err)
		}
		defer fresh.Close()
		loaded, err := NewProjectRuntimeService(repository.NewMySQL(fresh)).Get(ctx, uid, projectA)
		if err != nil {
			t.Fatal(err)
		}
		if !reflect.DeepEqual(saved, loaded) {
			t.Fatalf("new connection lost persisted config: %+v / %+v", saved, loaded)
		}
		b, err := profiles.Get(ctx, uid, projectB)
		if err != nil {
			t.Fatal(err)
		}
		if b.AgentMode != "all" || b.ToolMode != "all" || b.MCPMode != "all" || b.Policy.Mode != "inherit" {
			t.Fatal("A update affected B")
		}
	})
	t.Run("SelectedPayloadAndProjectPolicy", func(t *testing.T) {
		save(t, projectA, selected)
		res, req := run(t, convA)
		pools(t, req, []int64{a1}, []int64{t1}, []int64{m1})
		p := selected.Policy
		if req.Scheduler != p.Scheduler || req.Planner != p.Planner || req.ExecutionMode != p.ExecutionMode || req.SynthesisMode != p.SynthesisMode || req.Constraints != p.Constraints {
			t.Fatalf("HTTP policy mismatch: %+v", req)
		}
		if len(res.Trace) != 2 || res.Trace[0]["kind"] != "project_runtime" {
			t.Fatalf("trace=%v", res.Trace)
		}
		persisted, err := repo.TaskByID(ctx, uid, res.Task.ID)
		if err != nil {
			t.Fatal(err)
		}
		persistedJSON, err := json.Marshal(persisted.Trace)
		if err != nil {
			t.Fatal(err)
		}
		responseJSON, err := json.Marshal(res.Trace)
		if err != nil {
			t.Fatal(err)
		}
		if string(persistedJSON) != string(responseJSON) {
			t.Fatal("trace persistence mismatch")
		}
	})
	t.Run("ABAndNormalIsolation", func(t *testing.T) {
		save(t, projectA, selected)
		b := selected
		b.AgentIDs = []int64{a2}
		b.ToolIDs = []int64{t2}
		b.MCPServerIDs = []int64{m2}
		b.Policy.Mode = "inherit"
		save(t, projectB, b)
		_, a := run(t, convA)
		pools(t, a, []int64{a1}, []int64{t1}, []int64{m1})
		_, r := run(t, convB)
		pools(t, r, []int64{a2}, []int64{t2}, []int64{m2})
		composer := input(convB)
		if r.Scheduler != composer.Scheduler || r.Planner != composer.Planner || r.ExecutionMode != composer.ExecutionMode || r.SynthesisMode != composer.SynthesisMode || r.Constraints != composer.Constraints {
			t.Fatal("inherit changed composer payload")
		}
		res, n := run(t, normal)
		pools(t, n, []int64{a1, a2}, []int64{t1, t2}, []int64{m1, m2})
		if len(res.Trace) != 1 || res.Trace[0]["kind"] != "task" {
			t.Fatal("normal trace polluted")
		}
		if n.Scheduler != composer.Scheduler || n.Constraints != composer.Constraints {
			t.Fatal("normal policy polluted")
		}
	})
	t.Run("DisableAfterBinding", func(t *testing.T) {
		both := selected
		both.AgentIDs = []int64{a1, a2}
		both.ToolIDs = []int64{t1, t2}
		both.MCPServerIDs = []int64{m1, m2}
		save(t, projectA, both)
		insert("UPDATE agents SET status='DISABLED' WHERE id=?", a1)
		insert("UPDATE tools SET enabled=0 WHERE id=?", t1)
		insert("UPDATE mcp_servers SET enabled=0 WHERE id=?", m1)
		defer func() {
			insert("UPDATE agents SET status='ACTIVE' WHERE id=?", a1)
			insert("UPDATE tools SET enabled=1 WHERE id=?", t1)
			insert("UPDATE mcp_servers SET enabled=1 WHERE id=?", m1)
		}()
		_, req := run(t, convA)
		pools(t, req, []int64{a2}, []int64{t2}, []int64{m2})
		save(t, projectA, model.ProjectRuntimeConfig{})
		_, req = run(t, convA)
		pools(t, req, []int64{a2}, []int64{t2}, []int64{m2})
		_, req = run(t, normal)
		pools(t, req, []int64{a2}, []int64{t2}, []int64{m2})
	})
	t.Run("InvalidAndForeignIDsRollback", func(t *testing.T) {
		baseline := save(t, projectA, selected)
		for _, resource := range []string{"agent", "tool", "mcp"} {
			for _, id := range []int64{999999, map[string]int64{"agent": ax, "tool": tx, "mcp": mx}[resource]} {
				t.Run(fmt.Sprintf("%s_%d", resource, id), func(t *testing.T) {
					bad := selected
					switch resource {
					case "agent":
						bad.AgentIDs = []int64{id}
					case "tool":
						bad.ToolIDs = []int64{id}
					case "mcp":
						bad.MCPServerIDs = []int64{id}
					}
					if _, err := profiles.Update(ctx, uid, projectA, bad); !errors.Is(err, ErrNotFound) {
						t.Fatalf("invalid binding accepted: %v", err)
					}
					after, err := profiles.Get(ctx, uid, projectA)
					if err != nil {
						t.Fatal(err)
					}
					if !reflect.DeepEqual(baseline, after) {
						t.Fatal("failed save changed persisted profile")
					}
				})
			}
		}
		for _, id := range []int64{foreignProject, 999999} {
			if _, err := profiles.Get(ctx, uid, id); !errors.Is(err, ErrNotFound) {
				t.Errorf("foreign/missing project read: %v", err)
			}
			if _, err := profiles.Update(ctx, uid, id, selected); !errors.Is(err, ErrNotFound) {
				t.Errorf("foreign/missing project update: %v", err)
			}
		}
		if _, err := tasks.Run(ctx, uid, input(foreignConv)); !errors.Is(err, ErrNotFound) {
			t.Errorf("foreign conversation accepted: %v", err)
		}
		select {
		case <-requests:
			t.Error("foreign conversation reached runtime")
		default:
		}
	})
	t.Run("EmptySelectionFailsClosed", func(t *testing.T) {
		bad := selected
		bad.AgentIDs = []int64{}
		save(t, projectA, bad)
		if _, err := tasks.Run(ctx, uid, input(convA)); err == nil {
			t.Fatal("empty agent binding accepted")
		}
		select {
		case <-requests:
			t.Error("empty selection reached runtime")
		default:
		}
	})
	t.Run("UnavailableAndStaleForeignBindings", func(t *testing.T) {
		cfg := selected
		cfg.AgentIDs = []int64{a1, a2}
		save(t, projectA, cfg)
		insert("UPDATE agents SET status='UNAVAILABLE' WHERE id=?", a1)
		defer insert("UPDATE agents SET status='ACTIVE' WHERE id=?", a1)
		// Model legacy/corrupt cross-user bindings: runtime still intersects
		// with the real account-owned enabled repository pool.
		insert("INSERT INTO project_agent_bindings(project_id,agent_id) VALUES(?,?)", projectA, ax)
		insert("INSERT INTO project_tool_bindings(project_id,tool_id) VALUES(?,?)", projectA, tx)
		insert("INSERT INTO project_mcp_bindings(project_id,mcp_server_id) VALUES(?,?)", projectA, mx)
		_, req := run(t, convA)
		pools(t, req, []int64{a2}, []int64{t1}, []int64{m1})
	})
	t.Run("SelectedEmptyToolsAndMCP", func(t *testing.T) {
		cfg := selected
		cfg.ToolIDs = []int64{}
		cfg.MCPServerIDs = []int64{}
		save(t, projectA, cfg)
		_, req := run(t, convA)
		pools(t, req, []int64{a1}, []int64{}, []int64{})
	})
	t.Run("KnowledgeScopeDatabaseRegression", func(t *testing.T) {
		ka, err := repo.EnsureDefaultProjectKnowledgeBase(ctx, uid, projectA, "A")
		if err != nil {
			t.Fatal(err)
		}
		kb, err := repo.EnsureDefaultProjectKnowledgeBase(ctx, uid, projectB, "B")
		if err != nil {
			t.Fatal(err)
		}
		kg, err := repo.EnsureDefaultGlobalKnowledgeBase(ctx, uid)
		if err != nil {
			t.Fatal(err)
		}
		for _, tc := range []struct {
			conv, kb int64
			mode     string
		}{{convA, ka.ID, "PROJECT"}, {convB, kb.ID, "PROJECT"}, {normal, kg.ID, "GLOBAL"}} {
			scope, err := repo.ResolveRuntimeKnowledgeScope(ctx, uid, &tc.conv)
			if err != nil {
				t.Fatal(err)
			}
			if scope.Mode != tc.mode || !reflect.DeepEqual(scope.KnowledgeBaseIDs, []int64{tc.kb}) {
				t.Errorf("scope=%+v", scope)
			}
		}
		if _, err := repo.ResolveRuntimeKnowledgeScope(ctx, uid, &foreignConv); !errors.Is(err, repository.ErrNotOwned) {
			t.Errorf("foreign knowledge scope: %v", err)
		}
	})
	t.Run("TraceMatchesEffectiveInheritedPolicy", func(t *testing.T) {
		cfg := selected
		cfg.Policy.Mode = "inherit"
		save(t, projectA, cfg)
		res, req := run(t, convA)
		var detail map[string]any
		if err := json.Unmarshal([]byte(res.Trace[0]["detail"].(string)), &detail); err != nil {
			t.Fatal(err)
		}
		expected := map[string]any{"projectId": float64(projectA), "agentMode": "selected", "agentCount": float64(1), "toolMode": "selected", "toolCount": float64(1), "mcpMode": "selected", "mcpCount": float64(1), "policyMode": "inherit", "scheduler": req.Scheduler, "planner": req.Planner, "executionMode": req.ExecutionMode, "synthesisMode": req.SynthesisMode}
		if !reflect.DeepEqual(detail, expected) {
			t.Errorf("Trace must report HTTP policy; got %v; want %v", detail, expected)
		}
	})
	t.Run("ResumeRejectsAgentRemovedFromProject", func(t *testing.T) {
		save(t, projectA, selected)
		in := input(convA)
		in.Task = "suspend"
		res, err := tasks.Run(ctx, uid, in)
		if err != nil {
			t.Fatal(err)
		}
		<-requests
		changed := selected
		changed.AgentIDs = []int64{a2}
		save(t, projectA, changed)
		_, err = tasks.Resume(ctx, uid, res.Task.ID, "continue")
		if err == nil {
			t.Error("resume executed agent removed from project bindings")
		}
		select {
		case req := <-requests:
			t.Errorf("forbidden resume reached Python: agent=%d pool=%v", req.Continuation.AgentID, req.Agents)
		default:
		}
		persisted, err := repo.TaskByID(ctx, uid, res.Task.ID)
		if err != nil {
			t.Fatal(err)
		}
		if persisted.Status != "INPUT_REQUIRED" {
			t.Fatalf("rejected resume changed state: %s", persisted.Status)
		}
		// Restoring the binding permits the same continuation; filtering must
		// still apply to its transmitted agent pool and trace.
		save(t, projectA, selected)
		resumed, err := tasks.Resume(ctx, uid, res.Task.ID, "continue")
		if err != nil {
			t.Fatal(err)
		}
		req := <-requests
		pools(t, req, []int64{a1}, []int64{}, []int64{})
		if len(resumed.Trace) != 2 || resumed.Trace[0]["kind"] != "project_runtime" {
			t.Fatalf("resume trace=%v", resumed.Trace)
		}
	})
	t.Run("NormalResumeHasNoProjectRuntime", func(t *testing.T) {
		in := input(normal)
		in.Task = "suspend"
		res, err := tasks.Run(ctx, uid, in)
		if err != nil {
			t.Fatal(err)
		}
		<-requests
		res, err = tasks.Resume(ctx, uid, res.Task.ID, "continue")
		if err != nil {
			t.Fatal(err)
		}
		req := <-requests
		pools(t, req, []int64{a1, a2}, []int64{}, []int64{})
		if len(res.Trace) != 1 || res.Trace[0]["kind"] != "task" {
			t.Fatalf("normal resume trace=%v", res.Trace)
		}
	})
}
