package runtime

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"example.com/agentmesh-control-plane/internal/model"
)

func TestV2IndexKnowledgeCarriesRequestLocalModelOnlyInsideInternalMultipart(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/internal/v1/knowledge/index" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		if got := r.Header.Get("X-Internal-Token"); got != "internal-test-token" {
			t.Fatalf("unexpected internal token: %q", got)
		}
		if strings.Contains(r.Header.Get("Authorization"), "tenant-secret") {
			t.Fatal("BYOK secret must not be projected into public-style authorization headers")
		}
		if err := r.ParseMultipartForm(1 << 20); err != nil {
			t.Fatal(err)
		}
		var runtime ProjectModelRuntime
		if err := json.Unmarshal([]byte(r.FormValue("projectModel")), &runtime); err != nil {
			t.Fatalf("projectModel is not valid JSON: %v", err)
		}
		if runtime.APIKey != "tenant-secret" || runtime.ModelName != "tenant-model" || runtime.VisionModelName != "tenant-vision" {
			t.Fatalf("request-local model mismatch: %#v", runtime)
		}
		_ = json.NewEncoder(w).Encode(KnowledgeIndexResponse{
			ChunkCount:          2,
			TextChunkCount:      1,
			VisualEvidenceCount: 1,
			PageCount:           1,
			VisualStatus:        "completed",
		})
	}))
	defer server.Close()

	client := NewClient(server.URL, "internal-test-token", time.Second)
	file := model.KnowledgeFile{
		ID:              9,
		KnowledgeBaseID: 8,
		UserID:          7,
		OriginalName:    "synthetic.pdf",
		Extension:       "pdf",
		ChecksumSHA256:  strings.Repeat("a", 64),
	}
	out, err := client.IndexKnowledge(
		context.Background(),
		file,
		strings.NewReader("synthetic"),
		&ProjectModelRuntime{
			Provider:        "openai-compatible",
			BaseURL:         "https://api.example.test/v1",
			ModelName:       "tenant-model",
			VisionModelName: "tenant-vision",
			APIKey:          "tenant-secret",
		},
	)
	if err != nil {
		t.Fatal(err)
	}
	if out.VisualEvidenceCount != 1 || out.VisualStatus != "completed" {
		t.Fatalf("unexpected response: %#v", out)
	}
}
