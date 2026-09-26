package runtime

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"time"

	"example.com/agentmesh-control-plane/internal/model"
)

// The binary router carries only intent and approved request-local model
// configuration; complete capability catalogs, schemas and private Knowledge
// never cross the preflight boundary. Actual discovery stays inside Runtime.
type PreviousTurnContext struct {
	Exists         bool   `json:"exists"`
	ExecutionRoute string `json:"executionRoute"`
	Status         string `json:"status"`
	RuntimePhase   string `json:"runtimePhase"`
	KnowledgeUsed  bool   `json:"knowledgeUsed"`
	ToolUsed       bool   `json:"toolUsed"`
	MCPUsed        bool   `json:"mcpUsed"`
}

type ExecutionRoutingRequest struct {
	SchemaVersion            string                `json:"schemaVersion"`
	Task                     string                `json:"task"`
	RagMode                  string                `json:"ragMode"`
	HasAttachments           bool                  `json:"hasAttachments"`
	ModelReadableAttachments bool                  `json:"modelReadableAttachments"`
	ContinuationState        string                `json:"continuationState"`
	PreviousTurn             PreviousTurnContext   `json:"previousTurn"`
	AllowModel               bool                  `json:"allowModel"`
	ProjectModel             *ProjectModelRuntime  `json:"projectModel,omitempty"`
	ModelPool                []ProjectModelRuntime `json:"modelPool,omitempty"`
	ModelSelection           ModelSelection        `json:"modelSelection"`
	Constraints              model.TaskConstraints `json:"constraints"`
}

// ExecutionIntent is the P24 authoritative WHAT contract. It carries only
// semantic facts and abstract capability requirements; concrete resource IDs
// and authorization decisions are intentionally impossible to encode here.
type ExecutionIntentContinuation struct {
	IsContinuation bool    `json:"isContinuation"`
	Relation       string  `json:"relation"`
	Confidence     float64 `json:"confidence"`
}

type ExecutionIntentReference struct {
	Type                         string `json:"type"`
	ResolvableFromTrustedHistory bool   `json:"resolvableFromTrustedHistory"`
	RequiresExternalResolution   bool   `json:"requiresExternalResolution"`
	TargetScope                  string `json:"targetScope"`
	TrustedHistoryResolution     string `json:"trustedHistoryResolution"`
}

type ExecutionIntentClarification struct {
	Required      bool     `json:"required"`
	ReasonCode    string   `json:"reasonCode"`
	MissingFields []string `json:"missingFields"`
}

type ExecutionIntentDependencies struct {
	Knowledge      string `json:"knowledge"`
	Memory         bool   `json:"memory"`
	FreshData      bool   `json:"freshData"`
	Attachment     bool   `json:"attachment"`
	ExternalSystem bool   `json:"externalSystem"`
	Tool           bool   `json:"tool"`
	MCP            bool   `json:"mcp"`
	Agent          bool   `json:"agent"`
	MultiStep      bool   `json:"multiStep"`
	SideEffect     bool   `json:"sideEffect"`
}

type ExecutionIntentCapabilities struct {
	RequiredCapabilities  []string `json:"requiredCapabilities"`
	ForbiddenCapabilities []string `json:"forbiddenCapabilities"`
}

type ExecutionIntent struct {
	Version          string                       `json:"version"`
	UserIntent       string                       `json:"userIntent"`
	TaskType         string                       `json:"taskType"`
	Continuation     ExecutionIntentContinuation  `json:"continuation"`
	Reference        ExecutionIntentReference     `json:"reference"`
	Clarification    ExecutionIntentClarification `json:"clarification"`
	Dependencies     ExecutionIntentDependencies  `json:"dependencies"`
	Capabilities     ExecutionIntentCapabilities  `json:"capabilities"`
	RequestedEffects []string                     `json:"requestedEffects"`
	ForbiddenActions []string                     `json:"forbiddenActions"`
	RagPreference    string                       `json:"ragPreference"`
	ExplanationOnly  bool                         `json:"explanationOnly"`
	Confidence       float64                      `json:"confidence"`
	SemanticSource   string                       `json:"semanticSource"`
	ReasonCodes      []string                     `json:"reasonCodes"`
}

type ExecutionRoutingResponse struct {
	SchemaVersion          string           `json:"schemaVersion"`
	ExecutionRoute         string           `json:"executionRoute"`
	Disposition            string           `json:"disposition"`
	KnowledgeDependency    string           `json:"knowledgeDependency"`
	CapabilityRequired     bool             `json:"capabilityRequired"`
	ReasonCodes            []string         `json:"reasonCodes"`
	UnresolvedRequirements []string         `json:"unresolvedRequirements"`
	AnalysisSource         string           `json:"analysisSource"`
	ModelCalls             int              `json:"modelCalls"`
	ModelTokens            int              `json:"modelTokens"`
	ModelEstimatedCost     float64          `json:"modelEstimatedCost"`
	ModelCostKnown         bool             `json:"modelCostKnown"`
	ExecutionIntent        *ExecutionIntent `json:"executionIntent"`
}

// UnderstandExecutionRoute is a bounded internal-only suggestion, not execution permission.
// Dedicated timeout also bounds preflight when the ordinary Runtime timeout is long.
func (c *Client) UnderstandExecutionRoute(ctx context.Context, in ExecutionRoutingRequest) (*ExecutionRoutingResponse, error) {
	if c == nil {
		return nil, errors.New("runtime unavailable")
	}
	ctx, cancel := context.WithTimeout(ctx, 3200*time.Millisecond)
	defer cancel()
	raw, err := json.Marshal(in)
	if err != nil {
		return nil, err
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+"/internal/v1/routing/understand", bytes.NewReader(raw))
	if err != nil {
		return nil, err
	}
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("X-Internal-Token", c.token)
	response, err := c.http.Do(request)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return nil, errors.New("execution routing preflight unavailable")
	}
	limited := io.LimitReader(response.Body, 64*1024+1)
	data, err := io.ReadAll(limited)
	if err != nil {
		return nil, err
	}
	if len(data) > 64*1024 {
		return nil, errors.New("execution routing preflight response too large")
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	var out ExecutionRoutingResponse
	if err := decoder.Decode(&out); err != nil {
		return nil, err
	}
	if err := decoder.Decode(&struct{}{}); err != io.EOF {
		return nil, errors.New("trailing route data")
	}
	if out.SchemaVersion != "execution-routing.v1" {
		return nil, errors.New("unsupported execution routing schema")
	}
	return &out, nil
}
