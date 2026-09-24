package runtime

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"example.com/agentmesh-control-plane/internal/model"
)

func TestExecuteRequestMapsMCPServers(
	t *testing.T,
) {
	payloadBytes, err := json.Marshal(
		ExecuteRequest{
			UserID: 7,

			MCPServers: []model.MCPServer{
				{
					ID: 9,

					UserID: 7,

					Name: "demo",

					Transport: "streamable_http",

					Endpoint: "http://localhost/mcp",

					Enabled: true,
				},
			},
		},
	)

	if err != nil {
		t.Fatal(
			err,
		)
	}

	var payload map[string]any

	if err = json.Unmarshal(
		payloadBytes,
		&payload,
	); err != nil {
		t.Fatal(
			err,
		)
	}

	servers := payload["mcp_servers"].([]any)

	server := servers[0].(map[string]any)

	if server["id"] != float64(
		9,
	) {
		t.Fatalf(
			"unexpected MCP id: %s",
			payloadBytes,
		)
	}

	if server["userId"] != float64(
		7,
	) {
		t.Fatalf(
			"unexpected MCP userId: %s",
			payloadBytes,
		)
	}

	if server["transport"] != "streamable_http" {
		t.Fatalf(
			"unexpected MCP transport: %s",
			payloadBytes,
		)
	}
}

func TestExecuteRequestMapsRuntimePolicies(
	t *testing.T,
) {
	payloadBytes, err := json.Marshal(
		ExecuteRequest{
			UserID: 7,

			RequestID: "req-1",

			Task: "Analyze data",

			Scheduler: "adaptive",

			Planner: "multi_objective",

			ExecutionMode: "auto",

			SynthesisMode: "auto",
		},
	)

	if err != nil {
		t.Fatal(
			err,
		)
	}

	var payload map[string]any

	if err = json.Unmarshal(
		payloadBytes,
		&payload,
	); err != nil {
		t.Fatal(
			err,
		)
	}

	if payload["scheduler"] != "adaptive" {
		t.Fatalf(
			"unexpected scheduler: %s",
			payloadBytes,
		)
	}

	if payload["planner"] != "multi_objective" {
		t.Fatalf(
			"unexpected planner: %s",
			payloadBytes,
		)
	}

	if payload["executionMode"] != "auto" {
		t.Fatalf(
			"unexpected executionMode: %s",
			payloadBytes,
		)
	}

	if payload["synthesisMode"] != "auto" {
		t.Fatalf(
			"unexpected synthesisMode: %s",
			payloadBytes,
		)
	}
}

func TestExecuteRequestMapsCapabilityProfiles(
	t *testing.T,
) {
	payloadBytes, err := json.Marshal(
		ExecuteRequest{
			Agents: []model.Agent{
				{
					ID: 4,

					Name: "DataAgent",

					Capabilities: []string{
						"data",
					},

					CapabilityProfiles: []model.AgentCapabilityProfile{
						{
							Capability: "data",

							QualityScore: 0.9,

							AvgLatencyMS: 300,

							AvgCost: 0.01,

							SuccessRate: 0.98,

							FailureRate: 0.02,

							SampleCount: 5,
						},
					},
				},
			},
		},
	)

	if err != nil {
		t.Fatal(
			err,
		)
	}

	var payload map[string]any

	if err = json.Unmarshal(
		payloadBytes,
		&payload,
	); err != nil {
		t.Fatal(
			err,
		)
	}

	agents := payload["agents"].([]any)

	agent := agents[0].(map[string]any)

	profiles := agent["capabilityProfiles"].([]any)

	profile := profiles[0].(map[string]any)

	if profile["capability"] != "data" {
		t.Fatalf(
			"unexpected capability profile: %s",
			payloadBytes,
		)
	}

	if profile["sampleCount"] != float64(
		5,
	) {
		t.Fatalf(
			"unexpected sample count: %s",
			payloadBytes,
		)
	}
}

func TestExecuteResponseMapsObservability(
	t *testing.T,
) {
	raw := []byte(
		`{
			"request_id":"req-1",
			"status":"COMPLETED",
			"answer":"ok",
			"continuation":null,
			"scheduler":"adaptive",
			"task_profile":{},
			"selected_agents":["DataAgent"],
			"estimated_cost":0.01,
			"elapsed_ms":100,
			"trace":[],
			"dag":{},
			"agent_feedback":[],
			"observability":{
				"modelCalls":2,
				"modelInputTokens":100,
				"modelOutputTokens":50,
				"modelTotalTokens":150,
				"modelLatencyMs":80,
				"toolCalls":1,
				"mcpEvents":0,
				"agentAttempts":1,
				"agentSuccesses":1,
				"agentFailures":0,
				"reschedules":0,
				"dagCompletedNodes":2,
				"dagSkippedNodes":1,
				"qualityEvaluations":1,
				"averageQuality":0.91,
				"modelEstimatedCost":0.0025,
				"modelCostKnown":true,
				"toolSuccesses":1,
				"toolFailures":0
			},
			"scorecard":{
				"evaluator":"deterministic_scorecard_v1",
				"status":"pass",
				"overallScore":0.93,
				"taskSuccess":1,
				"answerQuality":0.91,
				"groundedness":1,
				"toolReliability":1,
				"ragQuality":1,
				"memoryContribution":1,
				"budgetCompliance":1,
				"latencyMs":100,
				"estimatedCost":0.01,
				"modelEstimatedCost":0.0025,
				"modelTokens":150,
				"failureCategory":"none",
				"violations":[],
				"signals":{"latencyBudgetPassed":true}
			}
		}`,
	)

	var response ExecuteResponse

	if err := json.Unmarshal(
		raw,
		&response,
	); err != nil {
		t.Fatal(
			err,
		)
	}

	if response.Observability.ModelCalls != 2 {
		t.Fatalf(
			"unexpected model calls: %d",
			response.Observability.ModelCalls,
		)
	}

	if response.Observability.ModelTotalTokens != 150 {
		t.Fatalf(
			"unexpected total tokens: %d",
			response.Observability.ModelTotalTokens,
		)
	}

	if response.Observability.AverageQuality != 0.91 {
		t.Fatalf(
			"unexpected average quality: %f",
			response.Observability.AverageQuality,
		)
	}

	if response.Observability.ModelEstimatedCost != 0.0025 || !response.Observability.ModelCostKnown || response.Observability.ToolSuccesses != 1 {
		t.Fatalf("unexpected evaluation telemetry: %+v", response.Observability)
	}

	if response.Scorecard == nil || response.Scorecard.OverallScore != 0.93 || response.Scorecard.Status != "pass" {
		t.Fatalf("unexpected evaluation scorecard: %+v", response.Scorecard)
	}
}

func TestExecuteRequestMapsConversationID(
	t *testing.T,
) {
	conversationID := int64(
		123,
	)

	body, err := json.Marshal(
		ExecuteRequest{
			UserID: 7,

			RequestID: "req-memory-1",

			ConversationID: &conversationID,

			Task: "remember this",
		},
	)

	if err != nil {
		t.Fatal(
			err,
		)
	}

	var payload map[string]any

	if err = json.Unmarshal(
		body,
		&payload,
	); err != nil {
		t.Fatal(
			err,
		)
	}

	if payload["conversationId"] != float64(
		123,
	) {
		t.Fatalf(
			"unexpected conversationId mapping: %s",
			body,
		)
	}
}

func TestExecuteRequestOmitsNilConversationID(
	t *testing.T,
) {
	body, err := json.Marshal(
		ExecuteRequest{
			UserID: 7,

			RequestID: "req-memory-none",

			Task: "hello",
		},
	)

	if err != nil {
		t.Fatal(
			err,
		)
	}

	var payload map[string]any

	if err = json.Unmarshal(
		body,
		&payload,
	); err != nil {
		t.Fatal(
			err,
		)
	}

	if _, exists := payload["conversationId"]; exists {
		t.Fatalf(
			"conversationId should be omitted when nil: %s",
			body,
		)
	}
}

// ============================================================
// Runtime Continuation
// ============================================================

func TestExecuteRequestMapsContinuation(
	t *testing.T,
) {
	body, err := json.Marshal(
		ExecuteRequest{
			UserID: 7,

			RequestID: "req-resume",

			Task: "补充远程 Agent 所需的信息",

			Continuation: &Continuation{
				Protocol: "a2a",

				AgentID: 9,

				Capability: "document",

				TaskID: "remote-task-123",

				ContextID: "remote-context-456",

				State: "INPUT_REQUIRED",
			},
		},
	)

	if err != nil {
		t.Fatal(
			err,
		)
	}

	var payload map[string]any

	if err = json.Unmarshal(
		body,
		&payload,
	); err != nil {
		t.Fatal(
			err,
		)
	}

	continuation, ok := payload["continuation"].(map[string]any)

	if !ok {
		t.Fatalf(
			"continuation missing: %s",
			body,
		)
	}

	if continuation["protocol"] != "a2a" {
		t.Fatalf(
			"unexpected protocol: %s",
			body,
		)
	}

	if continuation["agentId"] != float64(
		9,
	) {
		t.Fatalf(
			"unexpected agentId: %s",
			body,
		)
	}

	if continuation["taskId"] != "remote-task-123" {
		t.Fatalf(
			"unexpected taskId: %s",
			body,
		)
	}

	if continuation["contextId"] != "remote-context-456" {
		t.Fatalf(
			"unexpected contextId: %s",
			body,
		)
	}
}

func TestExecuteResponseMapsRuntimeSuspension(
	t *testing.T,
) {
	raw := []byte(
		`{
			"request_id":"req-1",
			"status":"INPUT_REQUIRED",
			"answer":"Please provide the target Agent endpoint.",
			"continuation":{
				"protocol":"a2a",
				"agentId":9,
				"capability":"document",
				"taskId":"remote-task-123",
				"contextId":"remote-context-456",
				"state":"INPUT_REQUIRED"
			},
			"scheduler":"adaptive",
			"task_profile":{},
			"selected_agents":["RemoteResearchAgent"],
			"estimated_cost":0,
			"elapsed_ms":100,
			"trace":[],
			"dag":{},
			"agent_feedback":[],
			"observability":{
				"modelCalls":0,
				"modelInputTokens":0,
				"modelOutputTokens":0,
				"modelTotalTokens":0,
				"modelLatencyMs":0,
				"toolCalls":0,
				"mcpEvents":0,
				"agentAttempts":0,
				"agentSuccesses":0,
				"agentFailures":0,
				"reschedules":0,
				"dagCompletedNodes":1,
				"dagSkippedNodes":0,
				"qualityEvaluations":0,
				"averageQuality":0
			}
		}`,
	)

	var response ExecuteResponse

	if err := json.Unmarshal(
		raw,
		&response,
	); err != nil {
		t.Fatal(
			err,
		)
	}

	if response.Status != "INPUT_REQUIRED" {
		t.Fatalf(
			"unexpected status: %s",
			response.Status,
		)
	}

	if response.Continuation == nil {
		t.Fatal(
			"expected continuation",
		)
	}

	if response.Continuation.Protocol != "a2a" {
		t.Fatalf(
			"unexpected protocol: %+v",
			response.Continuation,
		)
	}

	if response.Continuation.AgentID != 9 {
		t.Fatalf(
			"unexpected agent id: %+v",
			response.Continuation,
		)
	}

	if response.Continuation.TaskID != "remote-task-123" {
		t.Fatalf(
			"unexpected task id: %+v",
			response.Continuation,
		)
	}

	if response.Continuation.ContextID != "remote-context-456" {
		t.Fatalf(
			"unexpected context id: %+v",
			response.Continuation,
		)
	}

	if response.Observability.AgentFailures != 0 {
		t.Fatalf(
			"INPUT_REQUIRED must not be an agent failure: %+v",
			response.Observability,
		)
	}
}

func TestExecuteResponseMapsCitations(
	t *testing.T,
) {
	raw := []byte(
		`{
			"request_id":"citation-test",
			"status":"COMPLETED",
			"answer":"AgentMesh uses Milvus [1].",
			"citations":[
				{
					"citationId":1,
					"label":"[1]",
					"documentId":"chunk_dc85b0",
					"source":"agentmesh-rag",
					"score":0.955176,
					"documentType":"agentmesh-demo",
					"chunkIndex":0,
					"start":0,
					"end":127
				}
			],
			"continuation":null,
			"scheduler":"adaptive",
			"task_profile":{},
			"selected_agents":["DocumentAgent"],
			"estimated_cost":0.01,
			"elapsed_ms":100,
			"trace":[],
			"dag":{},
			"agent_feedback":[],
			"observability":{
				"modelCalls":1,
				"modelInputTokens":10,
				"modelOutputTokens":10,
				"modelTotalTokens":20,
				"modelLatencyMs":50,
				"toolCalls":0,
				"mcpEvents":0,
				"agentAttempts":1,
				"agentSuccesses":1,
				"agentFailures":0,
				"reschedules":0,
				"dagCompletedNodes":1,
				"dagSkippedNodes":0,
				"qualityEvaluations":0,
				"averageQuality":0
			}
		}`,
	)

	var response ExecuteResponse

	if err := json.Unmarshal(
		raw,
		&response,
	); err != nil {
		t.Fatal(
			err,
		)
	}

	if len(
		response.Citations,
	) != 1 {
		t.Fatalf(
			"expected 1 citation, got %d",
			len(
				response.Citations,
			),
		)
	}

	citation := response.Citations[0]

	if citation.CitationID != 1 {
		t.Fatalf(
			"unexpected citation id: %d",
			citation.CitationID,
		)
	}

	if citation.Label != "[1]" {
		t.Fatalf(
			"unexpected label: %s",
			citation.Label,
		)
	}

	if citation.DocumentID != "chunk_dc85b0" {
		t.Fatalf(
			"unexpected document id: %s",
			citation.DocumentID,
		)
	}

	if citation.Source != "agentmesh-rag" {
		t.Fatalf(
			"unexpected source: %s",
			citation.Source,
		)
	}

	if citation.DocumentType == nil ||
		*citation.DocumentType != "agentmesh-demo" {
		t.Fatal(
			"unexpected document type",
		)
	}

	if citation.ChunkIndex == nil ||
		*citation.ChunkIndex != 0 {
		t.Fatal(
			"unexpected chunk index",
		)
	}

	if citation.Start == nil ||
		*citation.Start != 0 {
		t.Fatal(
			"unexpected start",
		)
	}

	if citation.End == nil ||
		*citation.End != 127 {
		t.Fatal(
			"unexpected end",
		)
	}
}

func TestP9ExecuteRequestMapsProjectModelWithoutPublicProjection(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var payload map[string]any
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			t.Fatal(err)
		}
		projectModel, ok := payload["projectModel"].(map[string]any)
		if !ok {
			t.Fatalf("projectModel missing: %#v", payload)
		}
		if projectModel["apiKey"] != "tenant-secret" || projectModel["modelName"] != "tenant-model" {
			t.Fatalf("project model mismatch: %#v", projectModel)
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"request_id": "governance", "status": "COMPLETED", "answer": "ok", "citations": []any{}, "scheduler": "greedy", "task_profile": map[string]any{}, "selected_agents": []string{}, "estimated_cost": 0, "elapsed_ms": 1, "trace": []any{}, "dag": map[string]any{}, "agent_feedback": []any{}, "observability": map[string]any{}})
	}))
	defer server.Close()
	client := NewClient(server.URL, "internal-test-token", time.Second)
	_, err := client.Execute(context.Background(), ExecuteRequest{UserID: 1, RequestID: "governance", Task: "hello", Scheduler: "greedy", Agents: []model.Agent{{ID: 1, Name: "General", Endpoint: "internal://general", Protocol: "internal", Capabilities: []string{"general"}}}, ProjectModel: &ProjectModelRuntime{Provider: "openai-compatible", BaseURL: "https://api.example.test/v1", ModelName: "tenant-model", APIKey: "tenant-secret"}})
	if err != nil {
		t.Fatal(err)
	}
}
