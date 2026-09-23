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
type P23UnderstandingRequest struct {
	SchemaVersion            string                `json:"schemaVersion"`
	Task                     string                `json:"task"`
	RagMode                  string                `json:"ragMode"`
	HasAttachments           bool                  `json:"hasAttachments"`
	ModelReadableAttachments bool                  `json:"modelReadableAttachments"`
	ContinuationState        string                `json:"continuationState"`
	AllowModel               bool                  `json:"allowModel"`
	ProjectModel             *ProjectModelRuntime  `json:"projectModel,omitempty"`
	ModelPool                []ProjectModelRuntime `json:"modelPool,omitempty"`
	ModelSelection           ModelSelection        `json:"modelSelection"`
	Constraints              model.TaskConstraints `json:"constraints"`
}

type P23UnderstandingResponse struct {
	SchemaVersion          string   `json:"schemaVersion"`
	ExecutionRoute         string   `json:"executionRoute"`
	Disposition            string   `json:"disposition"`
	KnowledgeDependency    string   `json:"knowledgeDependency"`
	CapabilityRequired     bool     `json:"capabilityRequired"`
	ReasonCodes            []string `json:"reasonCodes"`
	UnresolvedRequirements []string `json:"unresolvedRequirements"`
	AnalysisSource         string   `json:"analysisSource"`
	ModelCalls             int      `json:"modelCalls"`
	ModelTokens            int      `json:"modelTokens"`
	ModelEstimatedCost     float64  `json:"modelEstimatedCost"`
	ModelCostKnown         bool     `json:"modelCostKnown"`
}

// UnderstandP23 is a bounded internal-only suggestion, not execution permission.
// Dedicated timeout also bounds preflight when the ordinary Runtime timeout is long.
func (c *Client) UnderstandP23(ctx context.Context, in P23UnderstandingRequest) (*P23UnderstandingResponse, error) {
	if c == nil {
		return nil, errors.New("runtime unavailable")
	}
	ctx, cancel := context.WithTimeout(ctx, 2800*time.Millisecond)
	defer cancel()
	raw, err := json.Marshal(in)
	if err != nil {
		return nil, err
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+"/internal/v1/p23/understand", bytes.NewReader(raw))
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
		return nil, errors.New("p23 preflight unavailable")
	}
	limited := io.LimitReader(response.Body, 64*1024+1)
	data, err := io.ReadAll(limited)
	if err != nil {
		return nil, err
	}
	if len(data) > 64*1024 {
		return nil, errors.New("p23 preflight response too large")
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	var out P23UnderstandingResponse
	if err := decoder.Decode(&out); err != nil {
		return nil, err
	}
	if err := decoder.Decode(&struct{}{}); err != io.EOF {
		return nil, errors.New("trailing route data")
	}
	if out.SchemaVersion != "p23.v2" {
		return nil, errors.New("unsupported p23 decision schema")
	}
	return &out, nil
}
