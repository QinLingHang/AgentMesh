package router_test

import (
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
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

func TestP33PythonRetrievalThroughGoHTTPAndMySQL(t *testing.T) {
	database, _ := p31Database(t)
	ctx := context.Background()
	repo := repository.NewMySQL(database)
	memoryService := service.NewMemoryService(repo)
	jwt := security.NewJWTManager("p33-test-only-jwt-secret-32-characters", "p33-test", time.Hour)
	server := httptest.NewServer(router.New(router.Dependencies{
		JWT: jwt, InternalToken: p31InternalToken, MemoryHandler: handler.NewMemoryHandler(memoryService),
	}))
	defer server.Close()

	owned, err := repo.CreateMemory(ctx, 1, model.UserMemory{
		Category: "preference", MemoryKey: "preference.coding.explanation", Content: "Compare Go code with Java",
		SourceType: "explicit_user", Confidence: .95, Status: "active",
	})
	if err != nil {
		t.Fatal(err)
	}
	_, err = repo.CreateMemory(ctx, 2, model.UserMemory{
		Category: "preference", MemoryKey: "preference.coding.foreign", Content: "Foreign Go preference",
		SourceType: "manual", Confidence: 1, Status: "active",
	})
	if err != nil {
		t.Fatal(err)
	}
	_, err = repo.CreateMemory(ctx, 1, model.UserMemory{
		Category: "preference", MemoryKey: "preference.coding.disabled", Content: "Disabled Go preference",
		SourceType: "manual", Confidence: 1, Status: "disabled",
	})
	if err != nil {
		t.Fatal(err)
	}

	executable := os.Getenv("AGENTMESH_TEST_PYTHON")
	if executable == "" {
		executable = "python"
	}
	script, err := filepath.Abs(filepath.Join("..", "..", "..", "runtime-python", "tests", "memory_retrieval_http_fixture.py"))
	if err != nil {
		t.Fatal(err)
	}
	command := exec.Command(executable, "-u", script, server.URL, p31InternalToken, "1")
	command.Dir = filepath.Dir(filepath.Dir(script))
	command.Env = append(os.Environ(), "PYTHONDONTWRITEBYTECODE=1", "MEMORY_RETRIEVAL_ENABLED=true")
	output, err := command.CombinedOutput()
	if err != nil {
		t.Fatalf("Python retriever: %v: %s", err, output)
	}
	var results []struct {
		LogicalContext string         `json:"logicalContext"`
		Status         string         `json:"status"`
		IDs            []int64        `json:"ids"`
		Keys           []string       `json:"keys"`
		Trace          map[string]any `json:"trace"`
	}
	if err = json.Unmarshal(output, &results); err != nil {
		t.Fatalf("retriever output %q: %v", output, err)
	}
	if len(results) != 3 {
		t.Fatalf("logical contexts=%d", len(results))
	}
	for _, result := range results {
		if result.Status != "completed" || len(result.IDs) != 1 || result.IDs[0] != owned.ID {
			t.Fatalf("context %s leaked/missed memory: %+v", result.LogicalContext, result)
		}
		traceJSON, _ := json.Marshal(result.Trace)
		if string(traceJSON) == "" || containsAny(string(traceJSON), "Compare Go", "Foreign Go", "Disabled Go") {
			t.Fatalf("trace contains content: %s", traceJSON)
		}
	}
}

func containsAny(value string, needles ...string) bool {
	for _, needle := range needles {
		for i := 0; i+len(needle) <= len(value); i++ {
			if value[i:i+len(needle)] == needle {
				return true
			}
		}
	}
	return false
}
