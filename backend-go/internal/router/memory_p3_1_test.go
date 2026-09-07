package router_test

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"sync"
	"testing"
	"time"

	dbschema "example.com/agentmesh-control-plane/internal/db"
	"example.com/agentmesh-control-plane/internal/handler"
	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/repository"
	"example.com/agentmesh-control-plane/internal/router"
	runtimeclient "example.com/agentmesh-control-plane/internal/runtime"
	"example.com/agentmesh-control-plane/internal/security"
	"example.com/agentmesh-control-plane/internal/service"
	"example.com/agentmesh-control-plane/internal/storage"
	"github.com/gin-gonic/gin"
)

func p31Decode[T any](t *testing.T, raw json.RawMessage) T {
	t.Helper()
	var value T
	if err := json.Unmarshal(raw, &value); err != nil {
		t.Fatal(err)
	}
	return value
}

func TestP31MemoryFoundation(t *testing.T) {
	database, dsn := p31Database(t)
	ctx := context.Background()
	repo := repository.NewMySQL(database)
	memories := service.NewMemoryService(repo)
	jwt := security.NewJWTManager("p31-test-only-jwt-secret-32-characters", "p31-test", time.Hour)
	tokenA, err := jwt.Generate(1, "p31-a@example.test")
	if err != nil {
		t.Fatal(err)
	}
	tokenB, err := jwt.Generate(2, "p31-b@example.test")
	if err != nil {
		t.Fatal(err)
	}
	gin.SetMode(gin.TestMode)
	// Use router.New, including its real JWT/internal-token middleware. Unused
	// routes retain their nil handlers and are never invoked by this suite.
	memoryHandler := handler.NewMemoryHandler(memories)
	server := httptest.NewServer(router.New(router.Dependencies{JWT: jwt, InternalToken: p31InternalToken, MemoryHandler: memoryHandler}))
	defer server.Close()
	client := &http.Client{Timeout: 10 * time.Second}
	call := func(t *testing.T, method, path, token, internal string, body any, want int) json.RawMessage {
		t.Helper()
		var input io.Reader
		if body != nil {
			raw, err := json.Marshal(body)
			if err != nil {
				t.Fatal(err)
			}
			input = bytes.NewReader(raw)
		}
		req, err := http.NewRequest(method, server.URL+path, input)
		if err != nil {
			t.Fatal(err)
		}
		req.Header.Set("Content-Type", "application/json")
		if token != "" {
			req.Header.Set("Authorization", "Bearer "+token)
		}
		if internal != "" {
			req.Header.Set("X-Internal-Token", internal)
		}
		res, err := client.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		defer res.Body.Close()
		raw, err := io.ReadAll(res.Body)
		if err != nil {
			t.Fatal(err)
		}
		if res.StatusCode != want {
			t.Fatalf("%s %s: HTTP %d want %d: %s", method, path, res.StatusCode, want, raw)
		}
		var envelope struct {
			Code int             `json:"code"`
			Data json.RawMessage `json:"data"`
		}
		if err = json.Unmarshal(raw, &envelope); err != nil {
			t.Fatalf("invalid response: %s", raw)
		}
		if want < 300 && envelope.Code != 0 {
			t.Fatalf("success envelope code=%d", envelope.Code)
		}
		return envelope.Data
	}
	create := func(t *testing.T, token, key, category, content string) model.UserMemory {
		t.Helper()
		return p31Decode[model.UserMemory](t, call(t, "POST", "/api/memories", token, "", map[string]any{"category": category, "memoryKey": key, "content": content}, 201))
	}
	mustExec := func(t *testing.T, q string, args ...any) {
		t.Helper()
		if _, err := database.Exec(q, args...); err != nil {
			t.Fatal(err)
		}
	}

	t.Run("SchemaAndModel", func(t *testing.T) {
		rows, err := database.Query("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='user_memories'")
		if err != nil {
			t.Fatal(err)
		}
		defer rows.Close()
		columns := map[string]bool{}
		for rows.Next() {
			var column string
			if err = rows.Scan(&column); err != nil {
				t.Fatal(err)
			}
			columns[column] = true
		}
		if err = rows.Err(); err != nil {
			t.Fatal(err)
		}
		for _, name := range []string{"id", "user_id", "category", "memory_key", "content", "source_type", "confidence", "status", "last_accessed_at", "created_at", "updated_at"} {
			if !columns[name] {
				t.Errorf("missing column %s", name)
			}
		}
		if len(columns) != 11 || columns["project_id"] || columns["conversation_id"] {
			t.Fatalf("memory scope schema=%v", columns)
		}
		var uniqueColumns string
		err = database.QueryRow("SELECT GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='user_memories' AND INDEX_NAME='uk_user_memory_key' AND NON_UNIQUE=0").Scan(&uniqueColumns)
		if err != nil {
			t.Fatal(err)
		}
		if uniqueColumns != "user_id,memory_key" {
			t.Fatalf("unique constraint=%s", uniqueColumns)
		}
		raw, err := json.Marshal(model.UserMemory{})
		if err != nil {
			t.Fatal(err)
		}
		fields := p31Decode[map[string]any](t, raw)
		if len(fields) != 11 {
			t.Fatalf("model fields=%v", fields)
		}
		for _, key := range []string{"projectId", "project_id", "conversationId"} {
			if _, ok := fields[key]; ok {
				t.Fatalf("unexpected scope field %s", key)
			}
		}
		var constraint string
		if err = database.QueryRow("SELECT REFERENCED_TABLE_NAME FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='user_memories' AND COLUMN_NAME='user_id' AND REFERENCED_TABLE_NAME IS NOT NULL").Scan(&constraint); err != nil || constraint != "users" {
			t.Fatalf("user ownership FK=%s err=%v", constraint, err)
		}
	})

	t.Run("RepositoryCRUDOwnershipAndPersistence", func(t *testing.T) {
		input := model.UserMemory{UserID: 2, Category: "fact", MemoryKey: "repo.key", Content: "repository evidence", SourceType: "manual", Confidence: .7, Status: "active"}
		a, err := repo.CreateMemory(ctx, 1, input)
		if err != nil {
			t.Fatal(err)
		}
		if a.UserID != 1 || a.LastAccessedAt != nil {
			t.Fatalf("repository create=%+v", a)
		}
		if _, err = repo.CreateMemory(ctx, 1, input); !errors.Is(err, repository.ErrMemoryKeyExists) {
			t.Fatalf("duplicate not rejected: %v", err)
		}
		b, err := repo.CreateMemory(ctx, 2, input)
		if err != nil {
			t.Fatal(err)
		}
		if b.ID == a.ID {
			t.Fatal("cross-user key is not independent")
		}
		own, err := repo.MemoryByKey(ctx, 1, input.MemoryKey)
		if err != nil || own == nil || own.ID != a.ID {
			t.Fatalf("ByKey owner result=%+v err=%v", own, err)
		}
		foreign, err := repo.MemoryByID(ctx, 1, b.ID)
		if err != nil || foreign != nil {
			t.Fatalf("foreign ID readable: %v %v", foreign, err)
		}
		foreign, err = repo.UpdateMemory(ctx, 1, b.ID, input)
		if err != nil || foreign != nil {
			t.Fatalf("foreign ID update: %v %v", foreign, err)
		}
		if ok, err := repo.DeleteMemory(ctx, 1, b.ID); err != nil || ok {
			t.Fatalf("foreign delete=%v err=%v", ok, err)
		}
		if err = repo.TouchMemoryAccess(ctx, 1, b.ID); err != nil {
			t.Fatal(err)
		}
		bAfter, err := repo.MemoryByID(ctx, 2, b.ID)
		if err != nil {
			t.Fatal(err)
		}
		if !reflect.DeepEqual(b, bAfter) {
			t.Fatal("foreign mutation changed B")
		}
		same, err := repo.UpdateMemory(ctx, 1, a.ID, *a)
		if err != nil || same == nil || same.ID != a.ID {
			t.Fatalf("no-op update incorrectly missing: %v", err)
		}
		input.Content = "updated repository evidence"
		updated, err := repo.UpdateMemory(ctx, 1, a.ID, input)
		if err != nil {
			t.Fatal(err)
		}
		fresh, err := sql.Open("mysql", dsn)
		if err != nil {
			t.Fatal(err)
		}
		defer fresh.Close()
		persisted, err := repository.NewMySQL(fresh).MemoryByID(ctx, 1, a.ID)
		if err != nil || !reflect.DeepEqual(persisted, updated) {
			t.Fatalf("independent connection persistence: %v", err)
		}
		if err = dbschema.EnsureMemorySchema(ctx, database); err != nil {
			t.Fatal(err)
		}
		persisted, err = repo.MemoryByID(ctx, 1, a.ID)
		if err != nil || persisted == nil || persisted.Content != input.Content {
			t.Fatal("repeat migration lost data")
		}
		if ok, err := repo.DeleteMemory(ctx, 1, a.ID); err != nil || !ok {
			t.Fatalf("delete=%v err=%v", ok, err)
		}
		if missing, err := repo.MemoryByID(ctx, 1, a.ID); err != nil || missing != nil {
			t.Fatal("hard delete did not remove row")
		}
		if _, err = repo.CreateMemory(ctx, 999999, input); err == nil {
			t.Fatal("nonexistent user accepted despite FK")
		}
	})

	t.Run("CRUDHTTPNormalizationAndAccessTimestamp", func(t *testing.T) {
		a := create(t, tokenA, "  Coding.Style  ", " PREFERENCE ", "  concise explanation  ")
		if a.MemoryKey != "coding.style" || a.Category != "preference" || a.Content != "concise explanation" || a.SourceType != "explicit_user" || a.Confidence != 1 || a.Status != "active" || a.LastAccessedAt != nil {
			t.Fatalf("create normalized=%+v", a)
		}
		listed := p31Decode[[]model.UserMemory](t, call(t, "GET", "/api/memories?keyword=coding.style", tokenA, "", nil, 200))
		if len(listed) != 1 || listed[0].ID != a.ID || listed[0].LastAccessedAt != nil {
			t.Fatalf("list result=%+v", listed)
		}
		path := fmt.Sprintf("/api/memories/%d", a.ID)
		got := p31Decode[model.UserMemory](t, call(t, "GET", path, tokenA, "", nil, 200))
		if got.LastAccessedAt == nil {
			t.Fatal("GET did not touch last_accessed_at")
		}
		mustExec(t, "UPDATE user_memories SET last_accessed_at='2000-01-01 00:00:00' WHERE id=?", a.ID)
		got = p31Decode[model.UserMemory](t, call(t, "GET", path, tokenA, "", nil, 200))
		if got.LastAccessedAt == nil || got.LastAccessedAt.Year() <= 2000 {
			t.Fatal("GET did not refresh old access timestamp")
		}
		patch := map[string]any{"category": " PROFILE ", "memoryKey": " CODING.RENAMED ", "content": " updated ", "sourceType": " MANUAL ", "confidence": 0.0, "status": " ACTIVE "}
		got = p31Decode[model.UserMemory](t, call(t, "PATCH", path, tokenA, "", patch, 200))
		if got.Category != "profile" || got.MemoryKey != "coding.renamed" || got.Content != "updated" || got.SourceType != "manual" || got.Confidence != 0 || got.Status != "active" {
			t.Fatalf("PATCH result=%+v", got)
		}
		got = p31Decode[model.UserMemory](t, call(t, "PATCH", path, tokenA, "", map[string]any{"content": "updated"}, 200))
		if got.ID != a.ID {
			t.Fatal("no-op PATCH failed")
		}
		byKey, err := memories.ByKey(ctx, 1, " CODING.RENAMED ")
		if err != nil || byKey.ID != a.ID {
			t.Fatalf("service ByKey normalization: %v", err)
		}
		call(t, "DELETE", path, tokenA, "", nil, 200)
		call(t, "GET", path, tokenA, "", nil, 404)
		call(t, "DELETE", path, tokenA, "", nil, 404)
	})

	t.Run("HTTPAuthenticationAndUserOwnership", func(t *testing.T) {
		b := create(t, tokenB, "private.b", "fact", "B secret evidence")
		path := fmt.Sprintf("/api/memories/%d", b.ID)
		for _, method := range []string{"GET", "PATCH", "DELETE"} {
			var body any
			if method == "PATCH" {
				body = map[string]string{"content": "hijacked"}
			}
			call(t, method, path, tokenA, "", body, 404)
			call(t, method, path, "", "", body, 401)
		}
		call(t, "POST", "/api/memories", "", "", map[string]string{"category": "fact", "memoryKey": "forbidden", "content": "no"}, 401)
		call(t, "GET", "/api/memories", "invalid-jwt", "", nil, 401)
		call(t, "GET", "/api/memories", "", p31InternalToken, nil, 401)
		after, err := repo.MemoryByID(ctx, 2, b.ID)
		if err != nil || !reflect.DeepEqual(&b, after) {
			t.Fatal("cross-user HTTP changed B including access timestamp")
		}
		rows := p31Decode[[]model.UserMemory](t, call(t, "GET", "/api/memories?userId=2", tokenA, "", nil, 200))
		for _, row := range rows {
			if row.UserID != 1 {
				t.Fatal("query userId overrode JWT")
			}
		}
		spoof := p31Decode[model.UserMemory](t, call(t, "POST", "/api/memories", tokenA, "", map[string]any{"userId": 2, "projectId": 999, "category": "fact", "memoryKey": "spoof.owner", "content": "JWT owns this"}, 201))
		if spoof.UserID != 1 {
			t.Fatal("body userId overrode JWT")
		}
		if _, err := memories.Get(ctx, 1, b.ID); !errors.Is(err, service.ErrNotFound) {
			t.Fatalf("service foreign Get: %v", err)
		}
		content := "foreign mutation"
		if _, err := memories.Update(ctx, 1, b.ID, service.UpdateMemoryInput{Content: &content}); !errors.Is(err, service.ErrNotFound) {
			t.Fatalf("service foreign Update: %v", err)
		}
		if err := memories.Delete(ctx, 1, b.ID); !errors.Is(err, service.ErrNotFound) {
			t.Fatalf("service foreign Delete: %v", err)
		}
	})

	t.Run("MemoryKeyUniquenessIncludingConcurrentWriters", func(t *testing.T) {
		a := create(t, tokenA, " Unique.Key ", "goal", "A goal")
		create(t, tokenB, "unique.key", "goal", "B goal")
		call(t, "POST", "/api/memories", tokenA, "", map[string]string{"category": "goal", "memoryKey": " UNIQUE.KEY ", "content": "duplicate"}, 409)
		second := create(t, tokenA, "unique.second", "goal", "unchanged")
		call(t, "PATCH", fmt.Sprintf("/api/memories/%d", second.ID), tokenA, "", map[string]string{"memoryKey": a.MemoryKey, "content": "should rollback"}, 409)
		unchanged, err := repo.MemoryByID(ctx, 1, second.ID)
		if err != nil || !reflect.DeepEqual(&second, unchanged) {
			t.Fatal("duplicate-key update partially changed row")
		}
		results := make(chan error, 8)
		var wg sync.WaitGroup
		for i := 0; i < 8; i++ {
			wg.Add(1)
			go func() {
				defer wg.Done()
				_, err := memories.Create(ctx, 1, service.CreateMemoryInput{Category: "fact", MemoryKey: " concurrent.KEY ", Content: "one winner"})
				results <- err
			}()
		}
		wg.Wait()
		close(results)
		successes := 0
		for err := range results {
			if err == nil {
				successes++
			} else if !errors.Is(err, service.ErrAlreadyExists) {
				t.Errorf("concurrent create unexpected error: %v", err)
			}
		}
		if successes != 1 {
			t.Fatalf("concurrent unique-key winners=%d", successes)
		}
	})

	t.Run("ValidationAndLexicalFilters", func(t *testing.T) {
		for i, patch := range []map[string]any{{"category": "unknown"}, {"memoryKey": "has space"}, {"memoryKey": "_bad"}, {"memoryKey": strings.Repeat("x", 129)}, {"content": "   "}, {"content": strings.Repeat("界", 8001)}, {"confidence": -0.1}, {"confidence": 1.1}, {"sourceType": "inferred"}, {"status": "archived"}} {
			body := map[string]any{"category": "fact", "memoryKey": fmt.Sprintf("invalid.%d", i), "content": "valid"}
			for key, value := range patch {
				body[key] = value
			}
			call(t, "POST", "/api/memories", tokenA, "", body, 400)
		}
		a := create(t, tokenA, "filters.alpha", "workflow", "needleAlpha content")
		create(t, tokenA, "filters.beta", "profile", "needleBeta content")
		create(t, tokenB, "filters.alpha", "workflow", "needleAlpha foreign")
		for _, query := range []string{"category=workflow&keyword=needleAlpha", "keyword=filters.alpha", "status=active&keyword=needleAlpha", "keyword=needleAlpha&limit=1"} {
			rows := p31Decode[[]model.UserMemory](t, call(t, "GET", "/api/memories?"+query, tokenA, "", nil, 200))
			if len(rows) != 1 || rows[0].ID != a.ID {
				t.Fatalf("filter %s=%+v", query, rows)
			}
		}
		rows := p31Decode[[]model.UserMemory](t, call(t, "GET", "/api/memories?keyword=%27%20OR%201%3D1%20--", tokenA, "", nil, 200))
		if len(rows) != 0 {
			t.Fatal("SQL-like keyword changed query semantics")
		}
		for _, query := range []string{"category=unknown", "status=archived", "limit=0", "limit=-1", "limit=abc", "keyword=" + strings.Repeat("x", 129)} {
			call(t, "GET", "/api/memories?"+query, tokenA, "", nil, 400)
		}
		path := fmt.Sprintf("/api/memories/%d", a.ID)
		call(t, "PATCH", path, tokenA, "", map[string]any{}, 400)
		call(t, "PATCH", path, tokenA, "", map[string]any{"content": " "}, 400)
		call(t, "GET", "/api/memories/0", tokenA, "", nil, 400)
		call(t, "GET", "/api/memories/not-an-id", tokenA, "", nil, 400)
		if _, err := memories.Create(ctx, 0, service.CreateMemoryInput{}); !errors.Is(err, service.ErrInvalidInput) {
			t.Fatalf("invalid service UID=%v", err)
		}
	})

	t.Run("InternalRuntimeContractAndLimits", func(t *testing.T) {
		path := "/internal/v1/users/1/memories"
		call(t, "GET", path, "", "", nil, 401)
		call(t, "GET", path, tokenA, "wrong", nil, 401)
		call(t, "GET", path, tokenA, "", nil, 401)
		mustExec(t, "INSERT INTO user_memories(user_id,category,memory_key,content,source_type,confidence,status) VALUES(1,'fact','internal.inactive','do not return','manual',1,'archived')")
		rows := p31Decode[[]model.UserMemory](t, call(t, "GET", path+"?status=archived&userId=2", "", p31InternalToken, nil, 200))
		for _, row := range rows {
			if row.UserID != 1 || row.Status != "active" || row.MemoryKey == "internal.inactive" {
				t.Fatalf("unsafe internal row=%+v", row)
			}
		}
		brows := p31Decode[[]model.UserMemory](t, call(t, "GET", "/internal/v1/users/2/memories", tokenA, p31InternalToken, nil, 200))
		if len(brows) == 0 {
			t.Fatal("B fixtures missing")
		}
		for _, row := range brows {
			if row.UserID != 2 {
				t.Fatal("internal path user not respected")
			}
		}
		empty := call(t, "GET", "/internal/v1/users/999999/memories", "", p31InternalToken, nil, 200)
		if string(empty) != "[]" {
			t.Fatalf("empty contract=%s", empty)
		}
		call(t, "GET", "/internal/v1/users/0/memories", "", p31InternalToken, nil, 400)
		call(t, "GET", path+"?limit=bad", "", p31InternalToken, nil, 400)

		forgetVictim := create(t, tokenA, "internal.forget.victim", "preference", "forget me")
		forgetPath := fmt.Sprintf("/internal/v1/users/%d/memories/%d", forgetVictim.UserID, forgetVictim.ID)
		call(t, "DELETE", forgetPath, "", "wrong", nil, 401)
		call(t, "DELETE", fmt.Sprintf("/internal/v1/users/2/memories/%d", forgetVictim.ID), "", p31InternalToken, nil, 404)
		call(t, "DELETE", forgetPath, "", p31InternalToken, nil, 200)
		call(t, "GET", fmt.Sprintf("/api/memories/%d", forgetVictim.ID), tokenA, "", nil, 404)
		// Bulk fixture verifies the actual returned cardinality, not just constants.
		for i := 0; i < 205; i++ {
			mustExec(t, "INSERT INTO user_memories(user_id,category,memory_key,content,source_type,confidence,status) VALUES(1,'other',?,'limit evidence','manual',1,'active')", fmt.Sprintf("limits.%03d", i))
		}
		for _, tc := range []struct {
			path, token, internal string
			want                  int
		}{{"/api/memories", tokenA, "", 100}, {"/api/memories?limit=999", tokenA, "", 200}, {path, "", p31InternalToken, 100}, {path + "?limit=999", "", p31InternalToken, 200}, {path + "?limit=1", "", p31InternalToken, 1}} {
			got := p31Decode[[]model.UserMemory](t, call(t, "GET", tc.path, tc.token, tc.internal, nil, 200))
			if len(got) != tc.want {
				t.Errorf("%s length=%d want=%d", tc.path, len(got), tc.want)
			}
		}
		active, err := memories.ListActiveForUser(ctx, 1, 999)
		if err != nil || len(active) != 200 {
			t.Fatalf("service internal limit: %d %v", len(active), err)
		}
		filtered, err := repo.ListMemories(ctx, 1, model.MemoryFilter{Status: "archived", Limit: 100})
		if err != nil || len(filtered) != 1 || filtered[0].MemoryKey != "internal.inactive" {
			t.Fatalf("repository status filter: %v %v", filtered, err)
		}
	})

	t.Run("UserGlobalScopeAcrossConversationContexts", func(t *testing.T) {
		mustExec(t, "INSERT INTO projects(id,user_id,name,description) VALUES(101,1,'A','fixture'),(102,1,'B','fixture')")
		mustExec(t, "INSERT INTO conversations(id,user_id,title) VALUES(101,1,'normal'),(102,1,'project A'),(103,1,'project B')")
		mustExec(t, "INSERT INTO project_conversations(project_id,conversation_id) VALUES(101,102),(102,103)")
		a := create(t, tokenA, "global.identity", "profile", "one user store")
		for _, contextQuery := range []string{"conversationId=101", "conversationId=102&projectId=101", "conversationId=103&projectId=102"} {
			rows := p31Decode[[]model.UserMemory](t, call(t, "GET", "/api/memories?keyword=global.identity&"+contextQuery, tokenA, "", nil, 200))
			if len(rows) != 1 || rows[0].ID != a.ID || rows[0].UserID != 1 {
				t.Fatalf("scope %s=%+v", contextQuery, rows)
			}
		}
		call(t, "PATCH", fmt.Sprintf("/api/memories/%d?projectId=101&conversationId=102", a.ID), tokenA, "", map[string]string{"content": "updated user-wide"}, 200)
		rows := p31Decode[[]model.UserMemory](t, call(t, "GET", "/api/memories?keyword=global.identity&projectId=102&conversationId=103", tokenA, "", nil, 200))
		if len(rows) != 1 || rows[0].Content != "updated user-wide" {
			t.Fatal("project context partitioned Memory")
		}
		// Project deletion must not cascade into user-global Memory.
		mustExec(t, "INSERT INTO projects(id,user_id,name,description) VALUES(104,1,'Disposable','fixture')")
		mustExec(t, "DELETE FROM projects WHERE id=104")
		byKey, err := memories.ByKey(ctx, 1, "global.identity")
		if err != nil || byKey.ID != a.ID {
			t.Fatal("project deletion affected user Memory")
		}
	})

	t.Run("ProjectKnowledgeHTTPIndexRetrievalNeverWritesMemory", func(t *testing.T) {
		// Independent projects so this subtest can also run by its own -run filter.
		mustExec(t, "INSERT INTO projects(id,user_id,name,description) VALUES(201,1,'Knowledge A','fixture'),(202,1,'Knowledge B','fixture')")
		mustExec(t, "INSERT INTO conversations(id,user_id,title) VALUES(201,1,'Knowledge A'),(202,1,'Knowledge B'),(203,1,'Global')")
		mustExec(t, "INSERT INTO project_conversations(project_id,conversation_id) VALUES(201,201),(202,202)")
		// Baseline nonempty Memory catches both unexpected creates and mutations.
		create(t, tokenA, "boundary.sentinel", "fact", "explicit Memory remains unchanged")
		snapshot := func() string {
			t.Helper()
			all := []model.UserMemory{}
			for _, uid := range []int64{1, 2} {
				items, err := repo.ListMemories(ctx, uid, model.MemoryFilter{Limit: 10000})
				if err != nil {
					t.Fatal(err)
				}
				all = append(all, items...)
			}
			raw, err := json.Marshal(all)
			if err != nil {
				t.Fatal(err)
			}
			return string(raw)
		}
		before := snapshot()
		pythonURL := p31PythonKnowledgeHost(t)
		objects, err := storage.NewLocalObjectStore(t.TempDir())
		if err != nil {
			t.Fatal(err)
		}
		knowledge := service.NewKnowledgeService(repo, objects, 1<<20, runtimeclient.NewClient(pythonURL, p31InternalToken, 10*time.Second))
		control := httptest.NewServer(router.New(router.Dependencies{JWT: jwt, InternalToken: p31InternalToken, MemoryHandler: memoryHandler, KnowledgeHandler: handler.NewKnowledgeHandler(knowledge, 1<<20)}))
		defer control.Close()
		upload := func(path, name string) model.KnowledgeFile {
			t.Helper()
			var body bytes.Buffer
			writer := multipart.NewWriter(&body)
			part, err := writer.CreateFormFile("file", name)
			if err != nil {
				t.Fatal(err)
			}
			if _, err = io.WriteString(part, "AgentMesh evidence "+name); err != nil {
				t.Fatal(err)
			}
			if err = writer.Close(); err != nil {
				t.Fatal(err)
			}
			req, err := http.NewRequest("POST", control.URL+path, &body)
			if err != nil {
				t.Fatal(err)
			}
			req.Header.Set("Authorization", "Bearer "+tokenA)
			req.Header.Set("Content-Type", writer.FormDataContentType())
			res, err := client.Do(req)
			if err != nil {
				t.Fatal(err)
			}
			defer res.Body.Close()
			raw, err := io.ReadAll(res.Body)
			if err != nil {
				t.Fatal(err)
			}
			if res.StatusCode != 201 {
				t.Fatalf("knowledge upload HTTP %d: %s", res.StatusCode, raw)
			}
			envelope := p31Decode[struct {
				Data model.KnowledgeFile `json:"data"`
			}](t, raw)
			for deadline := time.Now().Add(15 * time.Second); time.Now().Before(deadline); time.Sleep(30 * time.Millisecond) {
				file, err := repo.KnowledgeFileByID(ctx, 1, envelope.Data.ID)
				if err != nil {
					t.Fatal(err)
				}
				if file.Status == "READY" {
					if file.ChunkCount <= 0 {
						t.Fatal("READY without chunks")
					}
					if snapshot() != before {
						t.Fatal("Knowledge upload/index changed user_memories")
					}
					return *file
				}
				if file.Status == "ERROR" {
					t.Fatalf("indexing error=%v", file.ErrorMessage)
				}
			}
			t.Fatal("knowledge indexing deadline exceeded")
			return model.KnowledgeFile{}
		}
		a := upload("/api/projects/201/knowledge/files", "project-a.txt")
		b := upload("/api/projects/202/knowledge/files", "project-b.txt")
		global, err := repo.EnsureDefaultGlobalKnowledgeBase(ctx, 1)
		if err != nil {
			t.Fatal(err)
		}
		g := upload(fmt.Sprintf("/api/knowledge/bases/%d/files", global.ID), "global.txt")
		if a.ProjectID == nil || *a.ProjectID != 201 || a.Scope != model.KnowledgeBaseScopeProject || b.ProjectID == nil || *b.ProjectID != 202 || g.ProjectID != nil || g.Scope != model.KnowledgeBaseScopeGlobal {
			t.Fatal("knowledge upload changed project/global ownership scope")
		}
		for _, tc := range []struct {
			conv, wantFile int64
			mode           string
		}{{201, a.ID, "PROJECT"}, {202, b.ID, "PROJECT"}, {203, g.ID, "GLOBAL"}} {
			raw, err := json.Marshal(map[string]any{"control_url": control.URL, "user_id": 1, "conversation_id": tc.conv})
			if err != nil {
				t.Fatal(err)
			}
			req, err := http.NewRequest("POST", pythonURL+"/test/retrieve", bytes.NewReader(raw))
			if err != nil {
				t.Fatal(err)
			}
			req.Header.Set("Content-Type", "application/json")
			req.Header.Set("X-Internal-Token", p31InternalToken)
			res, err := client.Do(req)
			if err != nil {
				t.Fatal(err)
			}
			raw, err = io.ReadAll(res.Body)
			res.Body.Close()
			if err != nil {
				t.Fatal(err)
			}
			if res.StatusCode != 200 {
				t.Fatalf("retrieval HTTP %d: %s", res.StatusCode, raw)
			}
			got := p31Decode[struct {
				Mode    string  `json:"mode"`
				FileIDs []int64 `json:"fileIds"`
			}](t, raw)
			if got.Mode != tc.mode || !reflect.DeepEqual(got.FileIDs, []int64{tc.wantFile}) {
				t.Fatalf("conversation %d scoped retrieval=%s", tc.conv, raw)
			}
			if snapshot() != before {
				t.Fatal("real scoped RAG retrieval changed user_memories")
			}
		}
	})
}
