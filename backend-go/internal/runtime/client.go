package runtime

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"example.com/agentmesh-control-plane/internal/model"
)

type Client struct {
	baseURL           string
	token             string
	http              *http.Client
	streamIdleTimeout time.Duration
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
		token:             token,
		streamIdleTimeout: timeout,
		http: &http.Client{
			Timeout: timeout,
		},
	}
}

func (c *Client) streamingHTTPClient() *http.Client {
	streamClient := *c.http
	// Streaming bodies are bounded by request context, an inactivity deadline
	// and Runtime/provider execution deadlines. A whole-response Client.Timeout
	// would abort healthy streams merely because total execution exceeded it.
	streamClient.Timeout = 0
	return &streamClient
}

type RuntimeStreamPartialSummary struct {
	EventCount         int
	TraceEventCount    int
	DeltaEventCount    int
	LastTraceKind      string
	LastTraceStatus    string
	LastTraceElapsedMS int64
}

type RuntimeStreamError struct {
	Cause   error
	Partial RuntimeStreamPartialSummary
}

func (e *RuntimeStreamError) Error() string {
	if e == nil || e.Cause == nil {
		return "runtime stream failed"
	}
	return e.Cause.Error()
}

func (e *RuntimeStreamError) Unwrap() error {
	if e == nil {
		return nil
	}
	return e.Cause
}

func (e *RuntimeStreamError) PartialTrace() []map[string]any {
	if e == nil || e.Partial.EventCount == 0 {
		return nil
	}
	return []map[string]any{{
		"kind":            "runtime_stream_partial_summary",
		"title":           "Runtime stream partial summary",
		"status":          "error",
		"detail":          "bounded transport diagnostics; no prompt or trace detail persisted",
		"elapsedMs":       e.Partial.LastTraceElapsedMS,
		"eventCount":      e.Partial.EventCount,
		"traceCount":      e.Partial.TraceEventCount,
		"deltaCount":      e.Partial.DeltaEventCount,
		"lastTraceKind":   e.Partial.LastTraceKind,
		"lastTraceStatus": e.Partial.LastTraceStatus,
	}}
}

func runtimeStreamError(cause error, partial RuntimeStreamPartialSummary) error {
	if cause == nil {
		cause = errors.New("runtime stream failed")
	}
	return &RuntimeStreamError{Cause: cause, Partial: partial}
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
// Evaluation Run Scorecard
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
// Governance request-local Project BYOK model runtime. APIKey is sent only over the
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
	ExecutionRoute string `json:"executionRoute,omitempty"`
	UserID         int64  `json:"user_id"`

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

	RagPolicy model.RagPolicy `json:"ragPolicy"`

	EffectiveRagPolicy model.EffectiveRagPolicy `json:"effectiveRagPolicy"`

	KnowledgeCatalog []model.KnowledgeCatalogItem `json:"knowledgeCatalog,omitempty"`

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

	streamClient := c.streamingHTTPClient()
	resp, err := streamClient.Do(r)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode/100 != 2 {
		return fmt.Errorf("runtime returned %s", resp.Status)
	}

	decoder := json.NewDecoder(resp.Body)
	// EOF is not evidence of model success. A transport that closes after a
	// partial delta (or before sending any events) must never allow Go to
	// persist a truncated answer as COMPLETED. The terminal done event is the
	// sole success signal for this protocol.
	var accumulated strings.Builder
	sawDelta := false
	sawDone := false
	for {
		var event InteractiveStreamEvent
		if err := decoder.Decode(&event); err != nil {
			if err == io.EOF {
				if sawDone {
					return nil
				}
				return errors.New("interactive stream ended without a done event")
			}
			return err
		}
		if sawDone {
			return errors.New("interactive stream emitted an event after done")
		}
		switch event.Type {
		case "delta":
			sawDelta = true
			accumulated.WriteString(event.Delta)
		case "done":
			// The provider's final answer and its actual token deltas must
			// agree byte-for-byte. Do not forward a false done event to the
			// browser before checking the invariant.
			if sawDelta && event.Content != accumulated.String() {
				return errors.New("interactive stream final answer does not match deltas")
			}
			sawDone = true
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
// Full Runtime stream bridge
//
// The sink is request-local observability only. It never becomes part of the
// authoritative Runtime state and a disconnected consumer must not cancel the
// underlying task.
// ============================================================

type StreamEventSink func(map[string]any)

type streamEventSinkKey struct{}

func WithStreamEventSink(ctx context.Context, sink StreamEventSink) context.Context {
	if sink == nil {
		return ctx
	}
	// Browser/request cancellation only stops best-effort delivery to that
	// consumer; it must not cancel the authoritative Runtime execution or its
	// final persistence. Runtime/provider deadlines and executeStream's idle
	// timeout remain the bounded execution controls. context.WithoutCancel keeps
	// request-scoped values while removing the transport deadline/Done signal.
	authoritative := context.WithoutCancel(ctx)
	return context.WithValue(authoritative, streamEventSinkKey{}, sink)
}

func streamEventSinkFromContext(ctx context.Context) StreamEventSink {
	if ctx == nil {
		return nil
	}
	sink, _ := ctx.Value(streamEventSinkKey{}).(StreamEventSink)
	return sink
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
	if sink := streamEventSinkFromContext(ctx); sink != nil {
		return c.executeStream(ctx, req, sink)
	}

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
		return nil, runtimeResponseError(resp)
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

func (c *Client) executeStream(
	ctx context.Context,
	req ExecuteRequest,
	sink StreamEventSink,
) (*ExecuteResponse, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return nil, err
	}
	r, err := http.NewRequestWithContext(
		ctx,
		http.MethodPost,
		c.baseURL+"/internal/v1/runtime/execute-stream",
		bytes.NewReader(body),
	)
	if err != nil {
		return nil, err
	}
	r.Header.Set("Content-Type", "application/json")
	r.Header.Set("X-Internal-Token", c.token)

	streamClient := c.streamingHTTPClient()
	resp, err := streamClient.Do(r)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if (resp.StatusCode / 100) != 2 {
		return nil, runtimeResponseError(resp)
	}

	type scanResult struct {
		line []byte
		err  error
		done bool
	}
	scanner := bufio.NewScanner(resp.Body)
	scanner.Buffer(make([]byte, 64*1024), 4*1024*1024)
	scanCh := make(chan scanResult, 1)
	stopScan := make(chan struct{})
	defer close(stopScan)
	go func() {
		for scanner.Scan() {
			item := scanResult{line: append([]byte(nil), scanner.Bytes()...)}
			select {
			case scanCh <- item:
			case <-stopScan:
				return
			}
		}
		item := scanResult{err: scanner.Err(), done: true}
		select {
		case scanCh <- item:
		case <-stopScan:
		}
	}()

	var idleTimer *time.Timer
	var idleC <-chan time.Time
	if c.streamIdleTimeout > 0 {
		idleTimer = time.NewTimer(c.streamIdleTimeout)
		idleC = idleTimer.C
		defer idleTimer.Stop()
	}
	resetIdle := func() {
		if idleTimer == nil {
			return
		}
		if !idleTimer.Stop() {
			select {
			case <-idleTimer.C:
			default:
			}
		}
		idleTimer.Reset(c.streamIdleTimeout)
	}

	partial := RuntimeStreamPartialSummary{}
	var final *ExecuteResponse
	for {
		select {
		case <-ctx.Done():
			_ = resp.Body.Close()
			return nil, runtimeStreamError(ctx.Err(), partial)
		case <-idleC:
			_ = resp.Body.Close()
			return nil, runtimeStreamError(
				fmt.Errorf("runtime stream idle timeout after %s", c.streamIdleTimeout), partial,
			)
		case item := <-scanCh:
			if item.done {
				if item.err != nil {
					return nil, runtimeStreamError(item.err, partial)
				}
				if final == nil {
					return nil, runtimeStreamError(errors.New("runtime stream ended without result"), partial)
				}
				return final, nil
			}
			resetIdle()
			line := bytes.TrimSpace(item.line)
			if len(line) == 0 {
				continue
			}
			var event map[string]any
			if err := json.Unmarshal(line, &event); err != nil {
				return nil, runtimeStreamError(fmt.Errorf("invalid runtime stream event: %w", err), partial)
			}
			partial.EventCount++
			typeValue, _ := event["type"].(string)
			switch typeValue {
			case "trace":
				partial.TraceEventCount++
				if trace, ok := event["trace"].(map[string]any); ok {
					partial.LastTraceKind, _ = trace["kind"].(string)
					partial.LastTraceStatus, _ = trace["status"].(string)
					switch value := trace["elapsedMs"].(type) {
					case float64:
						partial.LastTraceElapsedMS = int64(value)
					case int64:
						partial.LastTraceElapsedMS = value
					case int:
						partial.LastTraceElapsedMS = int64(value)
					}
				}
			case "delta":
				partial.DeltaEventCount++
			}

			if sink != nil {
				// Observability sinks are deliberately fail-open. A client-side stream
				// writer failure must not alter the Runtime result.
				func() {
					defer func() { _ = recover() }()
					sink(event)
				}()
			}

			switch typeValue {
			case "result":
				raw, err := json.Marshal(event["result"])
				if err != nil {
					return nil, runtimeStreamError(err, partial)
				}
				var out ExecuteResponse
				if err := json.Unmarshal(raw, &out); err != nil {
					return nil, runtimeStreamError(err, partial)
				}
				final = &out
			case "error":
				message, _ := event["message"].(string)
				if strings.TrimSpace(message) == "" {
					message = "runtime stream failed"
				}
				nodeID, _ := event["nodeId"].(string)
				causeCategory, _ := event["causeCategory"].(string)
				if strings.TrimSpace(nodeID) != "" || strings.TrimSpace(causeCategory) != "" {
					return nil, runtimeStreamError(fmt.Errorf(
						"%s [node=%s cause=%s]",
						message, strings.TrimSpace(nodeID), strings.TrimSpace(causeCategory),
					), partial)
				}
				return nil, runtimeStreamError(errors.New(message), partial)
			}
		}
	}
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
