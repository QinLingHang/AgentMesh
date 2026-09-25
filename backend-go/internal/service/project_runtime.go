package service

import (
	"context"
	"encoding/json"
	"errors"
	"strings"

	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/repository"
	runtimeclient "example.com/agentmesh-control-plane/internal/runtime"
)

type projectRuntimeRepository interface {
	ProjectRuntimeConfig(
		context.Context,
		int64,
		int64,
	) (*model.ProjectRuntimeConfig, error)

	UpdateProjectRuntimeConfig(
		context.Context,
		int64,
		model.ProjectRuntimeConfig,
	) (*model.ProjectRuntimeConfig, error)

	ProjectIDByConversation(
		context.Context,
		int64,
		int64,
	) (*int64, error)
}

type ProjectRuntimeService struct {
	repo projectRuntimeRepository
}

func NewProjectRuntimeService(
	repo projectRuntimeRepository,
) *ProjectRuntimeService {
	return &ProjectRuntimeService{
		repo: repo,
	}
}

func validateBindingMode(
	value string,
) bool {
	return value == "all" ||
		value == "selected"
}

func normalizeProjectRuntimeConfig(
	config model.ProjectRuntimeConfig,
) (model.ProjectRuntimeConfig, error) {
	config.AgentMode = strings.ToLower(
		strings.TrimSpace(
			config.AgentMode,
		),
	)
	config.ToolMode = strings.ToLower(
		strings.TrimSpace(
			config.ToolMode,
		),
	)
	config.MCPMode = strings.ToLower(
		strings.TrimSpace(
			config.MCPMode,
		),
	)
	config.Policy.Mode = strings.ToLower(
		strings.TrimSpace(
			config.Policy.Mode,
		),
	)
	config.Policy.Scheduler = strings.ToLower(
		strings.TrimSpace(
			config.Policy.Scheduler,
		),
	)
	config.Policy.Planner = strings.ToLower(
		strings.TrimSpace(
			config.Policy.Planner,
		),
	)
	config.Policy.ExecutionMode = strings.ToLower(
		strings.TrimSpace(
			config.Policy.ExecutionMode,
		),
	)
	config.Policy.SynthesisMode = strings.ToLower(
		strings.TrimSpace(
			config.Policy.SynthesisMode,
		),
	)

	if config.AgentMode == "" {
		config.AgentMode = "all"
	}
	if config.ToolMode == "" {
		config.ToolMode = "all"
	}
	if config.MCPMode == "" {
		config.MCPMode = "all"
	}
	if config.Policy.Mode == "" {
		config.Policy.Mode = "inherit"
	}
	if config.Policy.Scheduler == "" {
		config.Policy.Scheduler = "adaptive"
	}
	if config.Policy.Planner == "" {
		config.Policy.Planner = "multi_objective"
	}
	if config.Policy.ExecutionMode == "" {
		config.Policy.ExecutionMode = "auto"
	}
	if config.Policy.SynthesisMode == "" {
		config.Policy.SynthesisMode = "auto"
	}

	if config.Policy.Constraints.MaxLatencyMS <= 0 {
		config.Policy.Constraints.MaxLatencyMS = 8000
	}
	if config.Policy.Constraints.MaxCost <= 0 {
		config.Policy.Constraints.MaxCost = 0.15
	}
	if config.Policy.Constraints.MinQuality <= 0 {
		config.Policy.Constraints.MinQuality = 0.8
	}

	if !validateBindingMode(config.AgentMode) ||
		!validateBindingMode(config.ToolMode) ||
		!validateBindingMode(config.MCPMode) {
		return config, ErrInvalidInput
	}

	if config.Policy.Mode != "inherit" &&
		config.Policy.Mode != "project" {
		return config, ErrInvalidInput
	}

	switch config.Policy.Scheduler {
	case "fixed", "capability", "greedy", "adaptive":
	default:
		return config, ErrInvalidInput
	}

	switch config.Policy.Planner {
	case "heuristic", "multi_objective":
	default:
		return config, ErrInvalidInput
	}

	switch config.Policy.ExecutionMode {
	case "auto", "parallel", "sequential":
	default:
		return config, ErrInvalidInput
	}

	switch config.Policy.SynthesisMode {
	case "auto", "always", "never":
	default:
		return config, ErrInvalidInput
	}

	if config.Policy.Constraints.MinQuality > 1 {
		return config, ErrInvalidInput
	}

	config.AgentIDs = uniquePositiveIDs(config.AgentIDs)
	config.ToolIDs = uniquePositiveIDs(config.ToolIDs)
	config.MCPServerIDs = uniquePositiveIDs(config.MCPServerIDs)

	// In all mode the bindings are intentionally irrelevant.
	// Clear stale selections so a deleted account-level resource cannot
	// make an unrelated all-mode save fail a foreign-key/ownership check.
	if config.AgentMode == "all" {
		config.AgentIDs = []int64{}
	}
	if config.ToolMode == "all" {
		config.ToolIDs = []int64{}
	}
	if config.MCPMode == "all" {
		config.MCPServerIDs = []int64{}
	}

	return config, nil
}

func uniquePositiveIDs(
	values []int64,
) []int64 {
	seen := map[int64]struct{}{}
	result := []int64{}

	for _, value := range values {
		if value <= 0 {
			continue
		}
		if _, exists := seen[value]; exists {
			continue
		}
		seen[value] = struct{}{}
		result = append(result, value)
	}

	return result
}

func (s *ProjectRuntimeService) Get(
	ctx context.Context,
	uid int64,
	projectID int64,
) (*model.ProjectRuntimeConfig, error) {
	if projectID <= 0 {
		return nil, ErrInvalidInput
	}

	config, err := s.repo.ProjectRuntimeConfig(
		ctx,
		uid,
		projectID,
	)
	if errors.Is(err, repository.ErrNotOwned) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	if config == nil {
		return nil, ErrNotFound
	}

	return config, nil
}

func (s *ProjectRuntimeService) Update(
	ctx context.Context,
	uid int64,
	projectID int64,
	config model.ProjectRuntimeConfig,
) (*model.ProjectRuntimeConfig, error) {
	if projectID <= 0 {
		return nil, ErrInvalidInput
	}

	config.ProjectID = projectID

	normalized, err := normalizeProjectRuntimeConfig(
		config,
	)
	if err != nil {
		return nil, err
	}

	updated, err := s.repo.UpdateProjectRuntimeConfig(
		ctx,
		uid,
		normalized,
	)
	if errors.Is(err, repository.ErrNotOwned) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}

	return updated, nil
}

type projectRuntimeLookupDiagnostic struct {
	Stage   string
	Outcome string
	Err     error
}

func (s *ProjectRuntimeService) resolveForConversationDetailed(
	ctx context.Context,
	uid int64,
	conversationID int64,
) (*model.ProjectRuntimeContext, []projectRuntimeLookupDiagnostic, error) {
	if conversationID <= 0 {
		return nil, nil, ErrInvalidInput
	}

	diagnostics := make([]projectRuntimeLookupDiagnostic, 0, 2)
	projectID, err := s.repo.ProjectIDByConversation(
		ctx,
		uid,
		conversationID,
	)
	if errors.Is(err, repository.ErrNotOwned) {
		err = ErrNotFound
	}
	conversationOutcome := "MISS"
	if projectID != nil {
		conversationOutcome = "FOUND"
	}
	if err != nil {
		conversationOutcome = "ERROR"
	}
	diagnostics = append(diagnostics, projectRuntimeLookupDiagnostic{
		Stage: "CONVERSATION_OWNERSHIP", Outcome: conversationOutcome, Err: err,
	})
	if err != nil {
		return nil, diagnostics, err
	}
	if projectID == nil {
		return nil, diagnostics, nil
	}

	config, err := s.Get(
		ctx,
		uid,
		*projectID,
	)
	projectOutcome := "FOUND"
	if err != nil {
		projectOutcome = "ERROR"
	}
	diagnostics = append(diagnostics, projectRuntimeLookupDiagnostic{
		Stage: "PROJECT_RUNTIME", Outcome: projectOutcome, Err: err,
	})
	if err != nil {
		return nil, diagnostics, err
	}

	return &model.ProjectRuntimeContext{
		ProjectID:       config.ProjectID,
		ResourceOwnerID: config.ResourceOwnerID,
		AgentMode:       config.AgentMode,
		AgentIDs:        config.AgentIDs,
		ToolMode:        config.ToolMode,
		ToolIDs:         config.ToolIDs,
		MCPMode:         config.MCPMode,
		MCPServerIDs:    config.MCPServerIDs,
		Policy:          config.Policy,
	}, diagnostics, nil
}

func (s *ProjectRuntimeService) ResolveForConversation(
	ctx context.Context,
	uid int64,
	conversationID int64,
) (*model.ProjectRuntimeContext, error) {
	resolved, _, err := s.resolveForConversationDetailed(ctx, uid, conversationID)
	return resolved, err
}

func (s *ProjectRuntimeService) ResolveForConversationWithDiagnostics(
	ctx context.Context,
	uid int64,
	conversationID int64,
) (*model.ProjectRuntimeContext, []projectRuntimeLookupDiagnostic, error) {
	return s.resolveForConversationDetailed(ctx, uid, conversationID)
}

type projectRuntimeResolver interface {
	ResolveForConversation(
		context.Context,
		int64,
		int64,
	) (*model.ProjectRuntimeContext, error)
}

func projectRuntimeResourceUserID(actorUID int64, projectContext *model.ProjectRuntimeContext) int64 {
	if projectContext != nil && projectContext.ResourceOwnerID > 0 {
		return projectContext.ResourceOwnerID
	}
	return actorUID
}

func filterAgentsByProject(
	pool []model.Agent,
	mode string,
	ids []int64,
) []model.Agent {
	if mode != "selected" {
		return pool
	}

	allowed := make(map[int64]struct{}, len(ids))
	for _, id := range ids {
		allowed[id] = struct{}{}
	}

	result := []model.Agent{}
	for _, agent := range pool {
		if _, ok := allowed[agent.ID]; ok {
			result = append(result, agent)
		}
	}

	return result
}

func filterToolsByProject(
	pool []model.Tool,
	mode string,
	ids []int64,
) []model.Tool {
	if mode != "selected" {
		return pool
	}

	allowed := make(map[int64]struct{}, len(ids))
	for _, id := range ids {
		allowed[id] = struct{}{}
	}

	result := []model.Tool{}
	for _, tool := range pool {
		if _, ok := allowed[tool.ID]; ok {
			result = append(result, tool)
		}
	}

	return result
}

func filterMCPByProject(
	pool []model.MCPServer,
	mode string,
	ids []int64,
) []model.MCPServer {
	if mode != "selected" {
		return pool
	}

	allowed := make(map[int64]struct{}, len(ids))
	for _, id := range ids {
		allowed[id] = struct{}{}
	}

	result := []model.MCPServer{}
	for _, server := range pool {
		if _, ok := allowed[server.ID]; ok {
			result = append(result, server)
		}
	}

	return result
}

func applyProjectRuntimePolicy(
	in *RunTaskInput,
	projectContext *model.ProjectRuntimeContext,
) {
	if projectContext == nil ||
		projectContext.Policy.Mode != "project" {
		return
	}

	in.Scheduler = projectContext.Policy.Scheduler
	in.Planner = projectContext.Policy.Planner
	in.ExecutionMode = projectContext.Policy.ExecutionMode
	in.SynthesisMode = projectContext.Policy.SynthesisMode
	// A project default may add constraints but must never erase an explicit
	// request to survive worker loss after the delivery decision was made.
	retryOnWorkerLoss := in.Constraints.RetryOnWorkerLoss
	in.Constraints = projectContext.Policy.Constraints
	in.Constraints.RetryOnWorkerLoss = in.Constraints.RetryOnWorkerLoss || retryOnWorkerLoss
}

func filterProjectRuntimeResources(
	projectContext *model.ProjectRuntimeContext,
	agents []model.Agent,
	tools []model.Tool,
	mcpServers []model.MCPServer,
) (
	[]model.Agent,
	[]model.Tool,
	[]model.MCPServer,
) {
	if projectContext == nil {
		return agents, tools, mcpServers
	}

	return filterAgentsByProject(
			agents,
			projectContext.AgentMode,
			projectContext.AgentIDs,
		), filterToolsByProject(
			tools,
			projectContext.ToolMode,
			projectContext.ToolIDs,
		), filterMCPByProject(
			mcpServers,
			projectContext.MCPMode,
			projectContext.MCPServerIDs,
		)
}

func projectRuntimeTraceEvent(
	projectContext *model.ProjectRuntimeContext,
	agentCount int,
	toolCount int,
	mcpCount int,
) map[string]any {
	if projectContext == nil {
		return nil
	}

	detail, _ := json.Marshal(
		map[string]any{
			"projectId":     projectContext.ProjectID,
			"agentMode":     projectContext.AgentMode,
			"agentCount":    agentCount,
			"toolMode":      projectContext.ToolMode,
			"toolCount":     toolCount,
			"mcpMode":       projectContext.MCPMode,
			"mcpCount":      mcpCount,
			"policyMode":    projectContext.Policy.Mode,
			"scheduler":     projectContext.Policy.Scheduler,
			"planner":       projectContext.Policy.Planner,
			"executionMode": projectContext.Policy.ExecutionMode,
			"synthesisMode": projectContext.Policy.SynthesisMode,
		},
	)

	return map[string]any{
		"kind":      "project_runtime",
		"title":     "Project Runtime Context",
		"status":    "completed",
		"detail":    string(detail),
		"elapsedMs": int64(0),
	}
}

func attachProjectRuntimeTrace(
	response *runtimeclient.ExecuteResponse,
	projectContext *model.ProjectRuntimeContext,
	agentCount int,
	toolCount int,
	mcpCount int,
	effectivePolicy model.ProjectRuntimePolicy,
) {
	if response == nil || projectContext == nil {
		return
	}

	// Report the policy actually sent to Python, including inherited composer
	// values, without mutating the persisted project configuration.
	traceContext := *projectContext
	effectivePolicy.Mode = projectContext.Policy.Mode
	traceContext.Policy = effectivePolicy
	event := projectRuntimeTraceEvent(
		&traceContext,
		agentCount,
		toolCount,
		mcpCount,
	)

	response.Trace = append(
		[]map[string]any{event},
		response.Trace...,
	)
}
