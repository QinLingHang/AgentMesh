package model

import "time"

type ProjectRuntimePolicy struct {
	Mode string `json:"mode"`

	Scheduler     string `json:"scheduler"`
	Planner       string `json:"planner"`
	ExecutionMode string `json:"executionMode"`
	SynthesisMode string `json:"synthesisMode"`

	Constraints TaskConstraints `json:"constraints"`
}

type ProjectRuntimeConfig struct {
	ProjectID int64 `json:"projectId"`

	// ResourceOwnerID is the Project owner whose Agent/Tool/MCP registry
	// backs shared Project execution. It is internal control-plane state only.
	ResourceOwnerID int64 `json:"-"`

	AgentMode string  `json:"agentMode"`
	AgentIDs  []int64 `json:"agentIds"`

	ToolMode string  `json:"toolMode"`
	ToolIDs  []int64 `json:"toolIds"`

	MCPMode      string  `json:"mcpMode"`
	MCPServerIDs []int64 `json:"mcpServerIds"`

	Policy ProjectRuntimePolicy `json:"policy"`

	CreatedAt time.Time `json:"createdAt"`
	UpdatedAt time.Time `json:"updatedAt"`
}

type ProjectRuntimeContext struct {
	ProjectID int64 `json:"projectId"`

	// ResourceOwnerID keeps shared Project execution on the Project owner's
	// configured Agent/Tool/MCP pool while request UserID remains the actor.
	ResourceOwnerID int64 `json:"-"`

	AgentMode string  `json:"agentMode"`
	AgentIDs  []int64 `json:"agentIds"`

	ToolMode string  `json:"toolMode"`
	ToolIDs  []int64 `json:"toolIds"`

	MCPMode      string  `json:"mcpMode"`
	MCPServerIDs []int64 `json:"mcpServerIds"`

	Policy ProjectRuntimePolicy `json:"policy"`
}
