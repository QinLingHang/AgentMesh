package router_test

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strconv"
	"testing"
	"time"

	"example.com/agentmesh-control-plane/internal/handler"
	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/repository"
	"example.com/agentmesh-control-plane/internal/router"
	"example.com/agentmesh-control-plane/internal/security"
	"example.com/agentmesh-control-plane/internal/service"
	"net/http/httptest"
)

func itoa(value int64) string { return strconv.FormatInt(value, 10) }

func p31RawCall(t *testing.T, base, method, path, internal string, body any, want int) json.RawMessage {
	t.Helper()
	raw, err := json.Marshal(body)
	if err != nil {
		t.Fatal(err)
	}
	req, err := http.NewRequest(method, base+path, bytes.NewReader(raw))
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Content-Type", "application/json")
	if internal != "" {
		req.Header.Set("X-Internal-Token", internal)
	}
	res, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer res.Body.Close()
	payload, err := io.ReadAll(res.Body)
	if err != nil {
		t.Fatal(err)
	}
	if res.StatusCode != want {
		t.Fatalf("HTTP %d want %d: %s", res.StatusCode, want, payload)
	}
	return payload
}

func TestP32AutomaticMemoryHTTPPersistenceAndAuthority(t *testing.T) {
	database, _ := p31Database(t)
	ctx := context.Background()
	repo := repository.NewMySQL(database)
	memoryService := service.NewMemoryService(repo)
	jwt := security.NewJWTManager("p32-test-only-jwt-secret-32-characters", "p32-test", time.Hour)
	server := httptest.NewServer(router.New(router.Dependencies{JWT: jwt, InternalToken: p31InternalToken, MemoryHandler: handler.NewMemoryHandler(memoryService)}))
	defer server.Close()
	post := func(t *testing.T, user int64, body map[string]any, wantStatus int) service.MemoryUpsertResult {
		t.Helper()
		raw := p31Decode[struct {
			Data service.MemoryUpsertResult `json:"data"`
		}](t,
			p31RawCall(t, server.URL, "POST", "/internal/v1/users/"+itoa(user)+"/memories/upsert", p31InternalToken, body, wantStatus))
		return raw.Data
	}
	inferred := func(key, content string) map[string]any {
		return map[string]any{"category": "goal", "memoryKey": key, "content": content, "sourceType": "inferred_user", "confidence": .8}
	}
	explicit := func(key, content string) map[string]any {
		return map[string]any{"category": "goal", "memoryKey": key, "content": content, "sourceType": "explicit_user", "confidence": .98}
	}

	t.Run("InternalTokenAndOwnership", func(t *testing.T) {
		p31RawCall(t, server.URL, "POST", "/internal/v1/users/1/memories/upsert", "", explicit("auth.key", "x"), 401)
		p31RawCall(t, server.URL, "POST", "/internal/v1/users/1/memories/upsert", "wrong", explicit("auth.key", "x"), 401)
		a := post(t, 1, explicit("shared.key", "A"), 200)
		b := post(t, 2, explicit("shared.key", "B"), 200)
		if a.Action != "created" || b.Action != "created" || a.Memory.UserID != 1 || b.Memory.UserID != 2 || a.Memory.ID == b.Memory.ID {
			t.Fatalf("ownership A=%+v B=%+v", a, b)
		}
		foreign, err := repo.MemoryByID(ctx, 2, a.Memory.ID)
		if err != nil || foreign != nil {
			t.Fatal("cross-user row visible")
		}
	})
	t.Run("CreatedUpdatedUnchangedPreserved", func(t *testing.T) {
		created := post(t, 1, inferred("authority.inferred", "v1"), 200)
		if created.Action != "created" {
			t.Fatal(created.Action)
		}
		unchanged := post(t, 1, inferred("authority.inferred", "v1"), 200)
		if unchanged.Action != "unchanged" || unchanged.Memory.ID != created.Memory.ID {
			t.Fatal(unchanged.Action)
		}
		updated := post(t, 1, inferred("authority.inferred", "v2"), 200)
		if updated.Action != "updated" || updated.Memory.ID != created.Memory.ID || updated.Memory.Content != "v2" {
			t.Fatal(updated.Action)
		}
		explicitUpdate := post(t, 1, explicit("authority.inferred", "explicit v3"), 200)
		if explicitUpdate.Action != "updated" || explicitUpdate.Memory.SourceType != "explicit_user" {
			t.Fatal(explicitUpdate.Action)
		}
		preserved := post(t, 1, inferred("authority.inferred", "forbidden v4"), 200)
		if preserved.Action != "preserved" || preserved.Memory.Content != "explicit v3" {
			t.Fatal(preserved.Action)
		}
		manual, err := repo.CreateMemory(ctx, 1, model.UserMemory{Category: "goal", MemoryKey: "authority.manual", Content: "manual", SourceType: "manual", Confidence: 1, Status: "active"})
		if err != nil {
			t.Fatal(err)
		}
		preserved = post(t, 1, inferred("authority.manual", "inferred overwrite"), 200)
		if preserved.Action != "preserved" || preserved.Memory.ID != manual.ID || preserved.Memory.Content != "manual" {
			t.Fatal(preserved.Action)
		}
		var count int
		if err = database.QueryRow("SELECT COUNT(*) FROM user_memories WHERE user_id=1 AND memory_key='authority.inferred'").Scan(&count); err != nil || count != 1 {
			t.Fatalf("duplicates=%d err=%v", count, err)
		}
	})
	t.Run("Validation", func(t *testing.T) {
		for _, body := range []map[string]any{
			{"category": "goal", "memoryKey": "bad key", "content": "x", "sourceType": "inferred_user"},
			{"category": "goal", "memoryKey": "valid.key", "content": "x", "sourceType": "manual"},
			{"category": "goal", "memoryKey": "valid.key", "content": "x", "sourceType": "unknown"},
		} {
			post(t, 1, body, 400)
		}
		post(t, 999999, explicit("missing.user", "x"), 500)
	})
	t.Run("PythonRuntimeToGoHTTPToMySQL", func(t *testing.T) {
		executable := os.Getenv("AGENTMESH_TEST_PYTHON")
		if executable == "" {
			executable = "python"
		}
		script, err := filepath.Abs(filepath.Join("..", "..", "..", "runtime-python", "tests", "memory_writer_http_fixture.py"))
		if err != nil {
			t.Fatal(err)
		}
		command := exec.Command(executable, "-u", script, server.URL, p31InternalToken, "1")
		command.Dir = filepath.Dir(filepath.Dir(script))
		command.Env = append(os.Environ(), "PYTHONDONTWRITEBYTECODE=1")
		output, err := command.CombinedOutput()
		if err != nil {
			t.Fatalf("Python writer: %v: %s", err, output)
		}
		var outcomes []map[string]any
		if err = json.Unmarshal(output, &outcomes); err != nil {
			t.Fatalf("writer output %q: %v", output, err)
		}
		actions := []string{}
		for _, outcome := range outcomes {
			writes := outcome["writes"].([]any)
			actions = append(actions, writes[0].(map[string]any)["action"].(string))
		}
		if !reflect.DeepEqual(actions, []string{"created", "unchanged", "created"}) {
			t.Fatalf("actions=%v", actions)
		}
		for _, key := range []string{"preference.response_language", "goal.career.target_role"} {
			memory, err := repo.MemoryByKey(ctx, 1, key)
			if err != nil || memory == nil {
				t.Fatalf("missing real writer row %s: %v", key, err)
			}
			if memory.UserID != 1 {
				t.Fatal("writer changed ownership")
			}
		}
	})
}
