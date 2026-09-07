package service

import (
	"encoding/json"
	"testing"

	runtimeclient "example.com/agentmesh-control-plane/internal/runtime"
)

func TestRunTaskResultExposesCitations(t *testing.T) {
	documentType := "agentmesh-demo"
	chunkIndex := 0
	start := 0
	end := 127

	result := RunTaskResult{
		Answer: "AgentMesh uses Milvus [1].",
		Citations: []runtimeclient.RuntimeCitation{
			{
				CitationID:   1,
				Label:        "[1]",
				DocumentID:   "chunk_dc85b0",
				Source:       "agentmesh-rag",
				Score:        0.955176,
				DocumentType: &documentType,
				ChunkIndex:   &chunkIndex,
				Start:        &start,
				End:          &end,
			},
		},
	}

	raw, err := json.Marshal(result)
	if err != nil {
		t.Fatal(err)
	}

	var payload map[string]any
	if err = json.Unmarshal(raw, &payload); err != nil {
		t.Fatal(err)
	}

	rawCitations, ok := payload["citations"].([]any)
	if !ok {
		t.Fatalf("citations field missing: %s", raw)
	}

	if len(rawCitations) != 1 {
		t.Fatalf("expected 1 citation, got %d", len(rawCitations))
	}

	citation, ok := rawCitations[0].(map[string]any)
	if !ok {
		t.Fatalf("invalid citation payload: %s", raw)
	}

	if citation["citationId"] != float64(1) {
		t.Fatalf("unexpected citation id: %v", citation["citationId"])
	}

	if citation["label"] != "[1]" {
		t.Fatalf("unexpected label: %v", citation["label"])
	}

	if citation["source"] != "agentmesh-rag" {
		t.Fatalf("unexpected source: %v", citation["source"])
	}
}

func TestNormalizeRuntimeCitationsReturnsEmptySliceForNil(t *testing.T) {
	result := normalizeRuntimeCitations(nil)

	if result == nil {
		t.Fatal("expected empty citation slice, got nil")
	}

	if len(result) != 0 {
		t.Fatalf("expected empty citation slice, got %d", len(result))
	}
}
