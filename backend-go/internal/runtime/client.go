package runtime

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"example.com/agentmesh-control-plane/internal/model"
)

type Client struct {
	baseURL string
	token   string
	http    *http.Client
}

func NewClient(
	baseURL string,
	token string,
	timeout time.Duration,
) *Client {
	return &Client{
		baseURL: strings.TrimRight(
			baseURL,
			"/",
		),
		token: token,
		http: &http.Client{
			Timeout: timeout,
		},
	}
}

// ============================================================
// Runtime Continuation
//

type Continuation struct {
	Protocol string `json:"protocol"`

	AgentID int64 `json:"agentId"`

	Capability string `json:"capability"`

	TaskID string `json:"taskId"`

	ContextID string `json:"contextId"`

	State string `json:"state"`

	Kind string `json:"kind,omitempty"`

	ApprovalID string `json:"approvalId,omitempty"`

	ToolName string `json:"toolName,omitempty"`

	ToolProtocol string `json:"toolProtocol,omitempty"`

	RiskLevel string `json:"riskLevel,omitempty"`

	RequiresConfirmation bool `json:"requiresConfirmation,omitempty"`

	Arguments map[string]any `json:"arguments,omitempty"`

	Fingerprint string `json:"fingerprint,omitempty"`

	Summary string `json:"summary,omitempty"`
}

// ============================================================
// Runtime Observability
// ============================================================

type ObservabilitySummary struct {
	ModelCalls int `json:"modelCalls"`

	ModelInputTokens int `json:"modelInputTokens"`

	ModelOutputTokens int `json:"modelOutputTokens"`

	ModelTotalTokens int `json:"modelTotalTokens"`

	ModelLatencyMS int64 `json:"modelLatencyMs"`

	ToolCalls int `json:"toolCalls"`

	MCPEvents int `json:"mcpEvents"`

	AgentAttempts int `json:"agentAttempts"`

	AgentSuccesses int `json:"agentSuccesses"`

	AgentFailures int `json:"agentFailures"`

	Reschedules int `json:"reschedules"`

	DAGCompletedNodes int `json:"dagCompletedNodes"`

	DAGSkippedNodes int `json:"dagSkippedNodes"`

	QualityEvaluations int `json:"qualityEvaluations"`

	AverageQuality float64 `json:"averageQuality"`

	ModelEstimatedCost float64 `json:"modelEstimatedCost"`

	ModelCostKnown bool `json:"modelCostKnown"`

	ModelProvider string `json:"modelProvider"`

	ModelName string `json:"modelName"`

	RetrievalMode string `json:"retrievalMode"`

	RAGLatencyMS int64 `json:"ragLatencyMs"`

	RAGRawHits int `json:"ragRawHits"`

	RAGHits int `json:"ragHits"`

	RAGContextHits int `json:"ragContextHits"`

	RAGTextCandidates int `json:"ragTextCandidates"`

	RAGVisualCandidates int `json:"ragVisualCandidates"`

	ToolSuccesses int `json:"toolSuccesses"`

	ToolFailures int `json:"toolFailures"`
}

// ============================================================
// P6 Run Scorecard
// ============================================================

type RunScorecard struct {
	Evaluator string `json:"evaluator"`

	Status string `json:"status"`

	OverallScore float64 `json:"overallScore"`

	TaskSuccess float64 `json:"taskSuccess"`

	AnswerQuality float64 `json:"answerQuality"`

	Groundedness float64 `json:"groundedness"`

	Correctness float64 `json:"correctness"`

	CitationQuality float64 `json:"citationQuality"`

	TaskCompletion float64 `json:"taskCompletion"`

	JudgeReason string `json:"judgeReason"`

	ToolReliability float64 `json:"toolReliability"`

	RAGQuality float64 `json:"ragQuality"`

	MemoryContribution float64 `json:"memoryContribution"`

	BudgetCompliance float64 `json:"budgetCompliance"`

	LatencyMS int64 `json:"latencyMs"`

	EstimatedCost float64 `json:"estimatedCost"`

	ModelEstimatedCost float64 `json:"modelEstimatedCost"`

	ModelTokens int `json:"modelTokens"`

	FailureCategory string `json:"failureCategory"`

	Violations []string `json:"violations"`

	Signals map[string]any `json:"signals"`
}

// ============================================================
// P9 request-local Project BYOK model runtime. APIKey is sent only over the
// trusted internal Go -> Python channel and is never returned to browsers.
// ============================================================
type ProjectModelRuntime struct {
	ServiceID       int64  `json:"serviceId,omitempty"`
	ServiceName     string `json:"serviceName,omitempty"`
	Provider        string `json:"provider"`
	BaseURL         string `json:"baseUrl"`
	ModelName       string `json:"modelName"`
	VisionModelName string `json:"visionModelName,omitempty"`
	APIKey          string `json:"apiKey"`
	AutoRoute       bool   `json:"autoRoute,omitempty"`
	IsDefault       bool   `json:"isDefault,omitempty"`
}

type ModelSelection struct {
	Mode      string `json:"mode"`
	ServiceID *int64 `json:"serviceId,omitempty"`
}

// ============================================================
// Request-local Attachment
// ============================================================

type RuntimeAttachment struct {
	ID            int64  `json:"id"`
	Name          string `json:"name"`
	MediaType     string `json:"mediaType"`
	Extension     string `json:"extension"`
	SizeBytes     int64  `json:"sizeBytes"`
	ContentBase64 string `json:"contentBase64"`
}

// ============================================================
// Runtime Execute Request
// ============================================================

type ExecuteRequest struct {
	UserID int64 `json:"user_id"`

	RequestID string `json:"request_id"`

	ConversationID *int64 `json:"conversationId,omitempty"`

	Task string `json:"task"`

	// Recent authoritative conversation history from the Go control plane.
	// This bridges ordinary interactive-stream turns and full Agent Runtime
	// turns so routing-path changes do not split short-term context.
	History []InteractiveMessage `json:"history,omitempty"`

	Scheduler string `json:"scheduler"`

	Planner string `json:"planner,omitempty"`

	ExecutionMode string `json:"executionMode,omitempty"`

	SynthesisMode string `json:"synthesisMode,omitempty"`

	Constraints model.TaskConstraints `json:"constraints"`

	Agents []model.Agent `json:"agents"`

	Tools []model.Tool `json:"tools,omitempty"`

	MCPServers []model.MCPServer `json:"mcp_servers,omitempty"`

	Continuation *Continuation `json:"continuation,omitempty"`

	ProjectModel *ProjectModelRuntime `json:"projectModel,omitempty"`

	ModelPool []ProjectModelRuntime `json:"modelPool,omitempty"`

	ModelSelection ModelSelection `json:"modelSelection,omitempty"`

	// AttachmentIDs are persisted only in the durable queue envelope. They are
	// resolved again under the current user/conversation boundary immediately
	// before dispatch so raw bytes are never stored in MySQL job payloads.
	AttachmentIDs []int64 `json:"attachmentIds,omitempty"`

	Attachments []RuntimeAttachment `json:"attachments,omitempty"`
}

// ============================================================
// Runtime Citation
//
// Python RuntimeCitation
//
// This is a transport DTO.
//
// It preserves only the public citation/provenance contract
// returned by Python Runtime.
// ============================================================

type RuntimeCitation struct {
	CitationID int `json:"citationId"`

	Label string `json:"label"`

	DocumentID string `json:"documentId"`

	Source string `json:"source"`

	Score float64 `json:"score"`

	DocumentType *string `json:"documentType"`

	ChunkIndex *int `json:"chunkIndex"`

	Start *int `json:"start"`

	End *int `json:"end"`

	PageNumber *int `json:"pageNumber"`

	AssetID *string `json:"assetId"`

	Modality *string `json:"modality"`

	VisualType *string `json:"visualType"`
}

// ============================================================
// Interactive streaming fast path
// ============================================================

type InteractiveMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type InteractiveStreamRequest struct {
	UserID         int64                 `json:"user_id"`
	RequestID      string                `json:"request_id"`
	ConversationID *int64                `json:"conversationId,omitempty"`
	Task           string                `json:"task"`
	History        []InteractiveMessage  `json:"history,omitempty"`
	ProjectModel   *ProjectModelRuntime  `json:"projectModel,omitempty"`
	ModelPool      []ProjectModelRuntime `json:"modelPool,omitempty"`
	ModelSelection ModelSelection        `json:"modelSelection,omitempty"`
	Scheduler      string                `json:"scheduler,omitempty"`
	Constraints    model.TaskConstraints `json:"constraints,omitempty"`
	Attachments    []RuntimeAttachment   `json:"attachments,omitempty"`
}

type InteractiveStreamEvent struct {
	Type          string           `json:"type"`
	Delta         string           `json:"delta,omitempty"`
	Content       string           `json:"content,omitempty"`
	Message       string           `json:"message,omitempty"`
	Model         string           `json:"model,omitempty"`
	Provider      string           `json:"provider,omitempty"`
	Mode          string           `json:"mode,omitempty"`
	Reason        string           `json:"reason,omitempty"`
	ServiceID     int64            `json:"serviceId,omitempty"`
	ServiceName   string           `json:"serviceName,omitempty"`
	InputTokens   int              `json:"input_tokens,omitempty"`
	OutputTokens  int              `json:"output_tokens,omitempty"`
	TotalTokens   int              `json:"total_tokens,omitempty"`
	LatencyMS     int64            `json:"latency_ms,omitempty"`
	EstimatedCost *float64         `json:"estimated_cost,omitempty"`
	Attachments   []map[string]any `json:"attachments,omitempty"`
}

func (c *Client) StreamInteractive(
	ctx context.Context,
	req InteractiveStreamRequest,
	onEvent func(InteractiveStreamEvent) error,
) error {
	body, err := json.Marshal(req)
	if err != nil {
		return err
	}

	r, err := http.NewRequestWithContext(
		ctx,
		http.MethodPost,
		c.baseURL+"/internal/v1/runtime/interactive-stream",
		bytes.NewReader(body),
	)
	if err != nil {
		return err
	}
	r.Header.Set("Content-Type", "application/json")
	r.Header.Set("X-Internal-Token", c.token)

	streamClient := *c.http
	// A streaming response is bounded by the request context and provider-side
	// timeout. http.Client.Timeout would otherwise abort the full body even
	// after healthy deltas have begun arriving.
	streamClient.Timeout = 0
	resp, err := streamClient.Do(r)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode/100 != 2 {
		return fmt.Errorf("runtime returned %s", resp.Status)
	}

	decoder := json.NewDecoder(resp.Body)
	for {
		var event InteractiveStreamEvent
		if err := decoder.Decode(&event); err != nil {
			if err == io.EOF {
				return nil
			}
			return err
		}
		if onEvent != nil {
			if err := onEvent(event); err != nil {
				return err
			}
		}
		if event.Type == "error" {
			if strings.TrimSpace(event.Message) == "" {
				return fmt.Errorf("interactive stream failed")
			}
			return fmt.Errorf("interactive stream failed: %s", event.Message)
		}
	}
}

// ============================================================
// Runtime Execute Response
// ============================================================

type ExecuteResponse struct {
	RequestID string `json:"request_id"`

	Status string `json:"status"`

	Answer string `json:"answer"`

	Citations []RuntimeCitation `json:"citations"`

	Continuation *Continuation `json:"continuation"`

	Scheduler string `json:"scheduler"`

	TaskProfile map[string]any `json:"task_profile"`

	SelectedAgents []string `json:"selected_agents"`

	EstimatedCost float64 `json:"estimated_cost"`

	ElapsedMS int64 `json:"elapsed_ms"`

	Trace []map[string]any `json:"trace"`

	DAG map[string]any `json:"dag"`

	AgentFeedback []model.AgentFeedback `json:"agent_feedback"`

	Observability ObservabilitySummary `json:"observability"`

	Scorecard *RunScorecard `json:"scorecard"`
}

// ============================================================
// MCP
// ============================================================

type MCPDiscoverRequest struct {
	Server model.MCPServer `json:"server"`
}

type MCPDiscoverResponse struct {
	Tools []map[string]any `json:"tools"`
}

// ============================================================
// Plugin
// ============================================================

type PluginInfo struct {
	ID string `json:"id"`

	Name string `json:"name"`

	Version string `json:"version"`

	Kind string `json:"kind"`

	Status string `json:"status"`

	Provider string `json:"provider,omitempty"`

	Model string `json:"model,omitempty"`
}

// ============================================================
// Execute Runtime
// ============================================================

func (
	c *Client,
) Execute(
	ctx context.Context,
	req ExecuteRequest,
) (*ExecuteResponse, error) {
	body, err := json.Marshal(
		req,
	)

	if err != nil {
		return nil, err
	}

	r, err := http.NewRequestWithContext(
		ctx,
		http.MethodPost,
		c.baseURL+
			"/internal/v1/runtime/execute",
		bytes.NewReader(
			body,
		),
	)

	if err != nil {
		return nil, err
	}

	r.Header.Set(
		"Content-Type",
		"application/json",
	)

	r.Header.Set(
		"X-Internal-Token",
		c.token,
	)

	resp, err := c.http.Do(
		r,
	)

	if err != nil {
		return nil, err
	}

	defer resp.Body.Close()

	if (resp.StatusCode / 100) != 2 {
		return nil, fmt.Errorf(
			"runtime returned %s",
			resp.Status,
		)
	}

	var out ExecuteResponse

	if err = json.NewDecoder(
		resp.Body,
	).Decode(
		&out,
	); err != nil {
		return nil, err
	}

	return &out, nil
}

// ============================================================
// Runtime Plugins
// ============================================================

func (
	c *Client,
) Plugins(
	ctx context.Context,
) ([]PluginInfo, error) {
	r, err := http.NewRequestWithContext(
		ctx,
		http.MethodGet,
		c.baseURL+
			"/internal/v1/runtime/plugins",
		nil,
	)

	if err != nil {
		return nil, err
	}

	r.Header.Set(
		"X-Internal-Token",
		c.token,
	)

	resp, err := c.http.Do(
		r,
	)

	if err != nil {
		return nil, err
	}

	defer resp.Body.Close()

	if (resp.StatusCode / 100) != 2 {
		return nil, fmt.Errorf(
			"runtime returned %s",
			resp.Status,
		)
	}

	var out []PluginInfo

	if err = json.NewDecoder(
		resp.Body,
	).Decode(
		&out,
	); err != nil {
		return nil, err
	}

	return out, nil
}

// ============================================================
// MCP Discovery
// ============================================================

func (
	c *Client,
) DiscoverMCP(
	ctx context.Context,
	server model.MCPServer,
) (*MCPDiscoverResponse, error) {
	body, err := json.Marshal(
		MCPDiscoverRequest{
			Server: server,
		},
	)

	if err != nil {
		return nil, err
	}

	r, err := http.NewRequestWithContext(
		ctx,
		http.MethodPost,
		c.baseURL+
			"/internal/v1/mcp/discover",
		bytes.NewReader(
			body,
		),
	)

	if err != nil {
		return nil, err
	}

	r.Header.Set(
		"Content-Type",
		"application/json",
	)

	r.Header.Set(
		"X-Internal-Token",
		c.token,
	)

	resp, err := c.http.Do(
		r,
	)

	if err != nil {
		return nil, err
	}

	defer resp.Body.Close()

	if (resp.StatusCode / 100) != 2 {
		return nil, fmt.Errorf(
			"runtime MCP discover returned %s",
			resp.Status,
		)
	}

	var out MCPDiscoverResponse

	if err = json.NewDecoder(
		resp.Body,
	).Decode(
		&out,
	); err != nil {
		return nil, err
	}

	return &out, nil
}
