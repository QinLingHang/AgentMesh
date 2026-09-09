package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"strings"
	"time"

	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/repository"
	runtimeclient "example.com/agentmesh-control-plane/internal/runtime"
	"example.com/agentmesh-control-plane/internal/security"

	"github.com/google/uuid"
)

// =========================================================
// Service Errors
// =========================================================

var ErrInvalidInput = errors.New(
	"invalid input",
)

var ErrInvalidCredentials = errors.New(
	"invalid credentials",
)

var ErrEmailExists = errors.New(
	"email exists",
)

var ErrNotFound = errors.New(
	"not found",
)

var ErrRefreshInvalid = errors.New(
	"refresh invalid",
)

var ErrConflict = errors.New(
	"conflict",
)

var ErrAlreadyExists = errors.New(
	"already exists",
)

// =========================================================
// Auth
// =========================================================

type AuthResult struct {
	User *model.User `json:"user"`

	AccessToken string `json:"accessToken"`

	ExpiresIn int64 `json:"expiresIn"`

	RefreshToken string `json:"-"`
}

type AuthService struct {
	users repository.UserRepository

	refresh repository.RefreshRepository

	jwt *security.JWTManager

	refreshTTL time.Duration
}

func NewAuthService(
	users repository.UserRepository,
	refresh repository.RefreshRepository,
	jwt *security.JWTManager,
	refreshTTL time.Duration,
) *AuthService {
	return &AuthService{
		users: users,

		refresh: refresh,

		jwt: jwt,

		refreshTTL: refreshTTL,
	}
}

func (s *AuthService) Register(
	ctx context.Context,
	email string,
	password string,
	name string,
) (*AuthResult, error) {
	email = strings.ToLower(
		strings.TrimSpace(
			email,
		),
	)

	name = strings.TrimSpace(
		name,
	)

	if email == "" ||
		name == "" {
		return nil, ErrInvalidInput
	}

	hash, err := security.HashPassword(
		password,
	)

	if err != nil {
		return nil, ErrInvalidInput
	}

	user, err := s.users.CreateUser(
		ctx,
		email,
		hash,
		name,
	)

	if errors.Is(
		err,
		repository.ErrEmailExists,
	) {
		return nil, ErrEmailExists
	}

	if err != nil {
		return nil, err
	}

	return s.issue(
		ctx,
		user,
	)
}

func (s *AuthService) Login(
	ctx context.Context,
	email string,
	password string,
) (*AuthResult, error) {
	user, err := s.users.UserByEmail(
		ctx,
		strings.ToLower(
			strings.TrimSpace(
				email,
			),
		),
	)

	if err != nil {
		return nil, err
	}

	if user == nil ||
		user.Status != "ACTIVE" ||
		!security.ComparePassword(
			user.PasswordHash,
			password,
		) {
		return nil, ErrInvalidCredentials
	}

	return s.issue(
		ctx,
		user,
	)
}

func (s *AuthService) Refresh(
	ctx context.Context,
	oldRaw string,
) (*AuthResult, error) {
	if strings.TrimSpace(
		oldRaw,
	) == "" {
		return nil, ErrRefreshInvalid
	}

	newRaw, newHash, err :=
		security.GenerateRefreshToken()

	if err != nil {
		return nil, err
	}

	uid, err := s.refresh.RotateRefresh(
		ctx,
		security.HashRefreshToken(
			oldRaw,
		),
		newHash,
		time.Now().
			UTC().
			Add(
				s.refreshTTL,
			),
	)

	if errors.Is(
		err,
		repository.ErrInvalidRefreshToken,
	) {
		return nil, ErrRefreshInvalid
	}

	if err != nil {
		return nil, err
	}

	user, err := s.users.UserByID(
		ctx,
		uid,
	)

	if err != nil ||
		user == nil {
		return nil, ErrRefreshInvalid
	}

	accessToken, err := s.jwt.Generate(
		user.ID,
		user.Email,
	)

	if err != nil {
		return nil, err
	}

	return &AuthResult{
		User: user,

		AccessToken: accessToken,

		ExpiresIn: int64(
			s.jwt.TTL().
				Seconds(),
		),

		RefreshToken: newRaw,
	}, nil
}

func (s *AuthService) Logout(
	ctx context.Context,
	raw string,
) error {
	if raw == "" {
		return nil
	}

	return s.refresh.RevokeRefresh(
		ctx,
		security.HashRefreshToken(
			raw,
		),
	)
}

func (s *AuthService) Me(
	ctx context.Context,
	uid int64,
) (*model.User, error) {
	user, err := s.users.UserByID(
		ctx,
		uid,
	)

	if err != nil {
		return nil, err
	}

	if user == nil {
		return nil, ErrNotFound
	}

	return user, nil
}

func (s *AuthService) issue(
	ctx context.Context,
	user *model.User,
) (*AuthResult, error) {
	accessToken, err := s.jwt.Generate(
		user.ID,
		user.Email,
	)

	if err != nil {
		return nil, err
	}

	raw, hash, err :=
		security.GenerateRefreshToken()

	if err != nil {
		return nil, err
	}

	if err = s.refresh.CreateRefresh(
		ctx,
		user.ID,
		hash,
		time.Now().
			UTC().
			Add(
				s.refreshTTL,
			),
	); err != nil {
		return nil, err
	}

	return &AuthResult{
		User: user,

		AccessToken: accessToken,

		ExpiresIn: int64(
			s.jwt.TTL().
				Seconds(),
		),

		RefreshToken: raw,
	}, nil
}

// =========================================================
// Conversation
// =========================================================

type ConversationService struct {
	repo repository.ConversationRepository

	messages repository.MessageRepository

	attachments *AttachmentService
}

func NewConversationService(
	repo repository.ConversationRepository,
	messages repository.MessageRepository,
) *ConversationService {
	return &ConversationService{
		repo: repo,

		messages: messages,
	}
}

func (s *ConversationService) SetAttachmentService(attachments *AttachmentService) {
	s.attachments = attachments
}

func (s *ConversationService) Create(
	ctx context.Context,
	uid int64,
	title string,
) (*model.Conversation, error) {
	title = strings.TrimSpace(
		title,
	)

	if title == "" {
		title = "新对话"
	}

	return s.repo.CreateConversation(
		ctx,
		uid,
		title,
	)
}

func (s *ConversationService) List(
	ctx context.Context,
	uid int64,
) ([]model.Conversation, error) {
	return s.repo.ListConversations(
		ctx,
		uid,
		50,
	)
}

func (s *ConversationService) Delete(
	ctx context.Context,
	uid int64,
	id int64,
) error {
	if s.attachments != nil {
		if err := s.attachments.DeleteAllForConversation(ctx, uid, id); err != nil && !errors.Is(err, ErrNotFound) {
			return err
		}
	}

	ok, err := s.repo.DeleteConversation(
		ctx,
		uid,
		id,
	)

	if err != nil {
		return err
	}

	if !ok {
		return ErrNotFound
	}

	return nil
}

func (s *ConversationService) Messages(
	ctx context.Context,
	uid int64,
	id int64,
) ([]model.Message, error) {
	messages, err := s.messages.ListMessages(
		ctx,
		uid,
		id,
		300,
	)

	if errors.Is(
		err,
		repository.ErrNotOwned,
	) {
		return nil, ErrNotFound
	}

	return messages, err
}

// =========================================================
// Agent
// =========================================================

type AgentService struct {
	repo repository.AgentRepository
}

func NewAgentService(
	repo repository.AgentRepository,
) *AgentService {
	return &AgentService{
		repo: repo,
	}
}

func normalizeAgent(
	agent model.Agent,
) model.Agent {
	agent.Name = strings.TrimSpace(
		agent.Name,
	)

	agent.Endpoint = strings.TrimSpace(
		agent.Endpoint,
	)

	agent.Protocol = strings.ToLower(
		strings.TrimSpace(
			agent.Protocol,
		),
	)

	agent.Provider = strings.TrimSpace(
		agent.Provider,
	)

	if agent.Protocol == "" {
		agent.Protocol = "http"
	}

	if agent.Provider == "" {
		agent.Provider = "internal"
	}

	if agent.QualityScore <= 0 {
		agent.QualityScore = 0.8
	}

	if agent.AvgLatencyMS <= 0 {
		agent.AvgLatencyMS = 1000
	}

	if agent.SuccessRate <= 0 {
		agent.SuccessRate = 0.95
	}

	if agent.FailureRate < 0 {
		agent.FailureRate = 0
	}

	if agent.Capabilities == nil {
		agent.Capabilities = []string{}
	}

	if agent.CapabilityProfiles == nil {
		agent.CapabilityProfiles =
			[]model.AgentCapabilityProfile{}
	}

	return agent
}

func (s *AgentService) Create(
	ctx context.Context,
	uid int64,
	agent model.Agent,
) (*model.Agent, error) {
	agent = normalizeAgent(
		agent,
	)

	if agent.Name == "" ||
		agent.Endpoint == "" {
		return nil, ErrInvalidInput
	}

	// =====================================================
	// A2A Capability Discovery
	//

	if agent.Protocol != "a2a" &&
		len(
			agent.Capabilities,
		) == 0 {
		return nil, ErrInvalidInput
	}

	return s.repo.CreateAgent(
		ctx,
		uid,
		agent,
	)
}

func (s *AgentService) List(
	ctx context.Context,
	uid int64,
) ([]model.Agent, error) {
	return s.repo.ListAgents(
		ctx,
		uid,
	)
}

func (s *AgentService) Delete(
	ctx context.Context,
	uid int64,
	id int64,
) error {
	ok, err := s.repo.DeleteAgent(
		ctx,
		uid,
		id,
	)

	if err != nil {
		return err
	}

	if !ok {
		return ErrNotFound
	}

	return nil
}

func (s *AgentService) SeedDemo(
	ctx context.Context,
	uid int64,
) ([]model.Agent, error) {
	existing, err := s.repo.ListAgents(
		ctx,
		uid,
	)

	if err != nil {
		return nil, err
	}

	if len(
		existing,
	) > 0 {
		return existing, nil
	}

	seed := []model.Agent{
		{
			Name: "GeneralAgent",

			Description: "通用兜底 Agent",

			Endpoint: "internal://general",

			Protocol: "internal",

			Capabilities: []string{
				"general",
			},

			Provider: "mock",

			QualityScore: 0.84,

			AvgLatencyMS: 600,

			AvgCost: 0.005,

			SuccessRate: 0.98,
		},
		{
			Name: "DocumentAgent",

			Description: "文档分析 Agent",

			Endpoint: "internal://document",

			Protocol: "internal",

			Capabilities: []string{
				"document",
				"summarization",
			},

			Provider: "mock",

			QualityScore: 0.93,

			AvgLatencyMS: 1500,

			AvgCost: 0.020,

			SuccessRate: 0.96,
		},
		{
			Name: "DataAgentPrimary",

			Description: "演示主 Data Agent，可通过 internal://fail/data 模拟故障",

			Endpoint: "internal://fail/data",

			Protocol: "internal",

			Capabilities: []string{
				"data",
			},

			Provider: "mock",

			QualityScore: 0.96,

			AvgLatencyMS: 800,

			AvgCost: 0.010,

			SuccessRate: 0.98,
		},
		{
			Name: "DataAgentBackup",

			Description: "Data Agent 备用节点",

			Endpoint: "internal://data-backup",

			Protocol: "internal",

			Capabilities: []string{
				"data",
			},

			Provider: "mock",

			QualityScore: 0.90,

			AvgLatencyMS: 1200,

			AvgCost: 0.015,

			SuccessRate: 0.95,
		},
		{
			Name: "DiagnosticAgent",

			Description: "HTTP / 系统异常诊断 Agent",

			Endpoint: "internal://diagnostic",

			Protocol: "internal",

			Capabilities: []string{
				"diagnostic",
			},

			Provider: "mock",

			QualityScore: 0.94,

			AvgLatencyMS: 1100,

			AvgCost: 0.018,

			SuccessRate: 0.97,
		},
	}

	result := make(
		[]model.Agent,
		0,
		len(
			seed,
		),
	)

	for _, agent := range seed {
		created, err := s.repo.CreateAgent(
			ctx,
			uid,
			normalizeAgent(
				agent,
			),
		)

		if err != nil {
			return nil, err
		}

		result = append(
			result,
			*created,
		)
	}

	return result, nil
}

// =========================================================
// Tool
// =========================================================

type ToolService struct {
	repo repository.ToolRepository
}

func NewToolService(
	repo repository.ToolRepository,
) *ToolService {
	return &ToolService{
		repo: repo,
	}
}

func normalizeTool(
	tool model.Tool,
) model.Tool {
	tool.Name = strings.TrimSpace(
		tool.Name,
	)

	tool.Protocol = strings.ToLower(
		strings.TrimSpace(
			tool.Protocol,
		),
	)

	if tool.Protocol == "" {
		tool.Protocol = "internal"
	}

	tool.RiskLevel = strings.ToLower(strings.TrimSpace(tool.RiskLevel))

	if tool.RiskLevel == "" {
		tool.RiskLevel = "low"
	}

	if tool.RiskLevel == "high" {
		tool.RequiresConfirmation = true
	}

	if tool.InputSchema == nil {
		tool.InputSchema = map[string]any{
			"type": "object",
		}
	}

	return tool
}

func (s *ToolService) Create(
	ctx context.Context,
	uid int64,
	tool model.Tool,
) (*model.Tool, error) {
	tool = normalizeTool(
		tool,
	)

	if tool.Name == "" {
		return nil, ErrInvalidInput
	}

	if isReservedDesktopToolName(tool.Name) {
		return nil, ErrInvalidInput
	}

	if tool.RiskLevel != "low" &&
		tool.RiskLevel != "medium" &&
		tool.RiskLevel != "high" {
		return nil, ErrInvalidInput
	}

	if tool.Protocol != "internal" &&
		tool.Protocol != "http" {
		return nil, ErrInvalidInput
	}

	if tool.Protocol == "http" &&
		strings.TrimSpace(
			tool.Endpoint,
		) == "" {
		return nil, ErrInvalidInput
	}

	return s.repo.CreateTool(
		ctx,
		uid,
		tool,
	)
}

func (s *ToolService) List(
	ctx context.Context,
	uid int64,
	enabled bool,
) ([]model.Tool, error) {
	return s.repo.ListTools(
		ctx,
		uid,
		enabled,
	)
}

func (s *ToolService) Get(
	ctx context.Context,
	uid int64,
	id int64,
) (*model.Tool, error) {
	tool, err := s.repo.ToolByID(
		ctx,
		uid,
		id,
	)

	if err == nil &&
		tool == nil {
		return nil, ErrNotFound
	}

	return tool, err
}

func (s *ToolService) Update(
	ctx context.Context,
	uid int64,
	id int64,
	tool model.Tool,
) (*model.Tool, error) {
	existing, lookupErr := s.repo.ToolByID(ctx, uid, id)
	if lookupErr != nil {
		return nil, lookupErr
	}
	if existing == nil {
		return nil, ErrNotFound
	}

	if definition, reserved := desktopDefinitionByName(existing.Name); reserved {
		definition.Enabled = tool.Enabled
		tool = normalizeTool(definition)
	} else {
		tool = normalizeTool(tool)
	}

	if tool.Name == "" {
		return nil, ErrInvalidInput
	}

	if isReservedDesktopToolName(tool.Name) && !isReservedDesktopToolName(existing.Name) {
		return nil, ErrInvalidInput
	}

	if tool.RiskLevel != "low" &&
		tool.RiskLevel != "medium" &&
		tool.RiskLevel != "high" {
		return nil, ErrInvalidInput
	}

	updated, err := s.repo.UpdateTool(
		ctx,
		uid,
		id,
		tool,
	)

	if err == nil &&
		updated == nil {
		return nil, ErrNotFound
	}

	return updated, err
}

func (s *ToolService) Delete(
	ctx context.Context,
	uid int64,
	id int64,
) error {
	existing, lookupErr := s.repo.ToolByID(ctx, uid, id)
	if lookupErr != nil {
		return lookupErr
	}
	if existing == nil {
		return ErrNotFound
	}
	if isReservedDesktopToolName(existing.Name) {
		// Official desktop tools are security-governed platform capabilities.
		// Users may disable them, but deleting the canonical contract would make
		// subsequent approval/fingerprint behavior ambiguous.
		return ErrInvalidInput
	}

	ok, err := s.repo.DeleteTool(
		ctx,
		uid,
		id,
	)

	if err != nil {
		return err
	}

	if !ok {
		return ErrNotFound
	}

	return nil
}

func (s *ToolService) SeedDemo(
	ctx context.Context,
	uid int64,
) ([]model.Tool, error) {
	existing, err := s.repo.ListTools(
		ctx,
		uid,
		false,
	)

	if err != nil {
		return nil, err
	}

	byName := map[string]bool{}
	for _, tool := range existing {
		byName[tool.Name] = true
	}

	querySchema := map[string]any{
		"type": "object",
		"properties": map[string]any{
			"query": map[string]any{
				"type": "string",
			},
		},
	}

	definitions := []model.Tool{
		{
			Name:        "calculator",
			Description: "Evaluate a basic arithmetic expression with the sandboxed AgentMesh calculator.",
			Protocol:    "internal",
			InputSchema: map[string]any{
				"type": "object",
				"properties": map[string]any{
					"expression": map[string]any{
						"type": "string",
					},
				},
				"required":             []string{"expression"},
				"additionalProperties": false,
			},
			RiskLevel: "low",
			Enabled:   true,
		},
		{
			Name:        "current_time",
			Description: "Get the current date and time for an IANA timezone.",
			Protocol:    "internal",
			InputSchema: map[string]any{
				"type": "object",
				"properties": map[string]any{
					"timezone": map[string]any{
						"type": "string",
					},
				},
				"additionalProperties": false,
			},
			RiskLevel: "low",
			Enabled:   true,
		},
		{
			Name:        "text_stats",
			Description: "Count characters, words and lines in text.",
			Protocol:    "internal",
			InputSchema: map[string]any{
				"type": "object",
				"properties": map[string]any{
					"text": map[string]any{
						"type": "string",
					},
				},
				"required":             []string{"text"},
				"additionalProperties": false,
			},
			RiskLevel: "low",
			Enabled:   true,
		},
		{
			Name:        "get_order",
			Description: "Deterministic demo order lookup tool.",
			Protocol:    "internal",
			InputSchema: querySchema,
			RiskLevel:   "low",
			Enabled:     true,
		},
		{
			Name:        "get_logistics",
			Description: "Deterministic demo logistics lookup tool.",
			Protocol:    "internal",
			InputSchema: querySchema,
			RiskLevel:   "low",
			Enabled:     true,
		},
		{
			Name:        "diagnose_service",
			Description: "Deterministic demo service diagnosis tool.",
			Protocol:    "internal",
			InputSchema: querySchema,
			RiskLevel:   "low",
			Enabled:     true,
		},
	}

	for _, definition := range definitions {
		if byName[definition.Name] {
			continue
		}

		if _, err = s.repo.CreateTool(
			ctx,
			uid,
			definition,
		); err != nil {
			return nil, err
		}
	}

	return s.repo.ListTools(
		ctx,
		uid,
		false,
	)
}

// =========================================================
// MCP Server
// =========================================================

type MCPServerService struct {
	repo repository.MCPServerRepository

	runtime *runtimeclient.Client

	demoEndpoint string
}

func NewMCPServerService(
	repo repository.MCPServerRepository,
	client *runtimeclient.Client,
	demoEndpoint ...string,
) *MCPServerService {
	endpoint := "http://127.0.0.1:9583/mcp"

	if len(demoEndpoint) > 0 && strings.TrimSpace(demoEndpoint[0]) != "" {
		endpoint = strings.TrimSpace(demoEndpoint[0])
	}

	return &MCPServerService{
		repo: repo,

		runtime: client,

		demoEndpoint: endpoint,
	}
}

func normalizeMCPServer(
	server model.MCPServer,
) model.MCPServer {
	server.Name = strings.TrimSpace(
		server.Name,
	)

	server.Endpoint = strings.TrimSpace(
		server.Endpoint,
	)

	server.Transport = strings.ToLower(
		strings.TrimSpace(
			server.Transport,
		),
	)

	if server.Transport == "" {
		server.Transport = "streamable_http"
	}

	if server.ConnectTimeoutMS <= 0 {
		server.ConnectTimeoutMS = 5000
	}

	if server.CallTimeoutMS <= 0 {
		server.CallTimeoutMS = 10000
	}

	return server
}

func (s *MCPServerService) Create(
	ctx context.Context,
	uid int64,
	server model.MCPServer,
) (*model.MCPServer, error) {
	server = normalizeMCPServer(
		server,
	)

	if server.Name == "" ||
		server.Endpoint == "" ||
		server.Transport != "streamable_http" {
		return nil, ErrInvalidInput
	}

	return s.repo.CreateMCPServer(
		ctx,
		uid,
		server,
	)
}

func (s *MCPServerService) List(
	ctx context.Context,
	uid int64,
	enabled bool,
) ([]model.MCPServer, error) {
	return s.repo.ListMCPServers(
		ctx,
		uid,
		enabled,
	)
}

func (s *MCPServerService) Get(
	ctx context.Context,
	uid int64,
	id int64,
) (*model.MCPServer, error) {
	server, err := s.repo.MCPServerByID(
		ctx,
		uid,
		id,
	)

	if err == nil &&
		server == nil {
		return nil, ErrNotFound
	}

	return server, err
}

func (s *MCPServerService) Update(
	ctx context.Context,
	uid int64,
	id int64,
	server model.MCPServer,
) (*model.MCPServer, error) {
	server = normalizeMCPServer(
		server,
	)

	if server.Name == "" ||
		server.Endpoint == "" ||
		server.Transport != "streamable_http" {
		return nil, ErrInvalidInput
	}

	updated, err := s.repo.UpdateMCPServer(
		ctx,
		uid,
		id,
		server,
	)

	if err == nil &&
		updated == nil {
		return nil, ErrNotFound
	}

	return updated, err
}

func (s *MCPServerService) Delete(
	ctx context.Context,
	uid int64,
	id int64,
) error {
	ok, err := s.repo.DeleteMCPServer(
		ctx,
		uid,
		id,
	)

	if err != nil {
		return err
	}

	if !ok {
		return ErrNotFound
	}

	return nil
}

func (s *MCPServerService) Discover(
	ctx context.Context,
	uid int64,
	id int64,
) (*runtimeclient.MCPDiscoverResponse, error) {
	server, err := s.Get(
		ctx,
		uid,
		id,
	)

	if err != nil {
		return nil, err
	}

	if !server.Enabled {
		return nil, ErrInvalidInput
	}

	return s.runtime.DiscoverMCP(
		ctx,
		*server,
	)
}

func (s *MCPServerService) SeedDemo(
	ctx context.Context,
	uid int64,
) (*model.MCPServer, error) {
	existing, err := s.repo.ListMCPServers(
		ctx,
		uid,
		false,
	)

	if err != nil {
		return nil, err
	}

	for _, server := range existing {
		if server.Name ==
			"AgentMesh Demo MCP" {
			server.Transport = "streamable_http"
			server.Endpoint = s.demoEndpoint
			server.Enabled = true
			server.ConnectTimeoutMS = 3000
			server.CallTimeoutMS = 8000

			updated, updateErr := s.repo.UpdateMCPServer(
				ctx,
				uid,
				server.ID,
				server,
			)
			if updateErr != nil {
				return nil, updateErr
			}
			return updated, nil
		}
	}

	return s.repo.CreateMCPServer(
		ctx,
		uid,
		model.MCPServer{
			Name: "AgentMesh Demo MCP",

			Transport: "streamable_http",

			Endpoint: s.demoEndpoint,

			Enabled: true,

			ConnectTimeoutMS: 3000,

			CallTimeoutMS: 8000,
		},
	)
}

// =========================================================
// Task Service
//
// v1.9.5B
//
// Long-lived Runtime Task
//

type TaskService struct {
	tasks repository.TaskRepository

	agents repository.AgentRepository

	messages repository.MessageRepository

	runtime *runtimeclient.Client

	tools repository.ToolRepository

	mcpServers repository.MCPServerRepository

	projectRuntime projectRuntimeResolver

	governance *GovernanceService

	attachments *AttachmentService
}

func NewTaskService(
	tasks repository.TaskRepository,
	agents repository.AgentRepository,
	messages repository.MessageRepository,
	runtime *runtimeclient.Client,
	tools repository.ToolRepository,
	mcpServers repository.MCPServerRepository,
	projectRuntime ...projectRuntimeResolver,
) *TaskService {
	service := &TaskService{
		tasks:      tasks,
		agents:     agents,
		messages:   messages,
		runtime:    runtime,
		tools:      tools,
		mcpServers: mcpServers,
	}

	if len(projectRuntime) > 0 {
		service.projectRuntime = projectRuntime[0]
	}

	return service
}

func (s *TaskService) SetGovernanceService(governance *GovernanceService) {
	s.governance = governance
}

func (s *TaskService) SetAttachmentService(attachments *AttachmentService) {
	s.attachments = attachments
}

const taskFinalizationTimeout = 5 * time.Second

func conversationIDValue(id *int64) int64 {
	if id == nil {
		return 0
	}
	return *id
}

func taskFinalizationContext(ctx context.Context) (context.Context, context.CancelFunc) {
	// Once Runtime has produced an authoritative result, final task/history
	// persistence must not depend on the browser keeping the HTTP stream open.
	// A bounded detached context prevents a conversation switch or client-side
	// navigation from creating a COMPLETED task with missing assistant history.
	return context.WithTimeout(context.WithoutCancel(ctx), taskFinalizationTimeout)
}

func (s *TaskService) completeTaskWithAssistant(
	ctx context.Context,
	task repository.TaskCompletionWrite,
	message *repository.AssistantMessageWrite,
) error {
	finalizeCtx, cancel := taskFinalizationContext(ctx)
	defer cancel()

	if message != nil {
		if finalizer, ok := s.tasks.(repository.TaskMessageFinalizer); ok {
			_, err := finalizer.CompleteTaskWithAssistantMessage(finalizeCtx, task, *message)
			if err != nil {
				return fmt.Errorf("finalize completed task and assistant history: %w", err)
			}
			return nil
		}
	}

	if err := s.tasks.CompleteTask(
		finalizeCtx,
		task.UserID,
		task.TaskID,
		task.Result,
		task.Selected,
		task.Trace,
		task.DAG,
		task.LatencyMS,
		task.EstimatedCost,
	); err != nil {
		return err
	}

	if message != nil {
		if _, err := s.messages.CreateMessage(
			finalizeCtx,
			message.UserID,
			message.ConversationID,
			"assistant",
			message.Content,
			message.Status,
			message.RequestID,
			message.Metadata,
		); err != nil {
			return fmt.Errorf("persist assistant history after task completion: %w", err)
		}
	}

	return nil
}

func (s *TaskService) suspendTaskWithAssistant(
	ctx context.Context,
	task repository.TaskSuspensionWrite,
	message *repository.AssistantMessageWrite,
) error {
	finalizeCtx, cancel := taskFinalizationContext(ctx)
	defer cancel()

	if message != nil {
		if finalizer, ok := s.tasks.(repository.TaskMessageFinalizer); ok {
			_, err := finalizer.SuspendTaskWithAssistantMessage(finalizeCtx, task, *message)
			if err != nil {
				return fmt.Errorf("finalize suspended task and assistant history: %w", err)
			}
			return nil
		}

	}

	if err := s.tasks.SuspendTask(
		finalizeCtx,
		task.UserID,
		task.TaskID,
		task.Status,
		task.Result,
		task.Continuation,
		task.Selected,
		task.Trace,
		task.DAG,
		task.LatencyMS,
		task.EstimatedCost,
	); err != nil {
		return err
	}

	if message != nil {
		if _, err := s.messages.CreateMessage(
			finalizeCtx,
			message.UserID,
			message.ConversationID,
			"assistant",
			message.Content,
			message.Status,
			message.RequestID,
			message.Metadata,
		); err != nil {
			return fmt.Errorf("persist assistant history after task suspension: %w", err)
		}
	}

	return nil
}

func (s *TaskService) recordRunCost(
	ctx context.Context,
	uid int64,
	taskID int64,
	projectID *int64,
	observability runtimeclient.ObservabilitySummary,
	estimatedCost float64,
) {
	if s.governance == nil || taskID <= 0 || uid <= 0 {
		return
	}
	status := "unavailable"
	if observability.ModelCostKnown {
		status = "estimated"
	}
	s.governance.RecordRunCost(ctx, model.RunCostRecord{
		TaskID: taskID, UserID: uid, ProjectID: projectID,
		Provider: observability.ModelProvider, ModelName: observability.ModelName,
		InputTokens:   int64(observability.ModelInputTokens),
		OutputTokens:  int64(observability.ModelOutputTokens),
		TotalTokens:   int64(observability.ModelTotalTokens),
		EstimatedCost: estimatedCost, CostStatus: status,
	})
}

func (s *TaskService) resolveRequestModelRuntime(
	ctx context.Context,
	uid int64,
	projectContext *model.ProjectRuntimeContext,
) (*runtimeclient.ProjectModelRuntime, error) {
	// Unit tests and isolated service fixtures may intentionally omit the
	// governance service and continue to use the runtime's deterministic mock.
	// Production server wiring always provides governance and therefore requires
	// request-local BYOK instead of silently consuming the platform owner's key.
	if s.governance == nil {
		return nil, nil
	}

	var projectID *int64
	if projectContext != nil && projectContext.ProjectID > 0 {
		id := projectContext.ProjectID
		projectID = &id
	}

	return s.governance.ResolveRequestModelRuntime(ctx, uid, projectID)
}

func (s *TaskService) resolveRequestModelRuntimePool(
	ctx context.Context,
	uid int64,
	projectContext *model.ProjectRuntimeContext,
	selection model.ModelSelection,
) ([]runtimeclient.ProjectModelRuntime, *runtimeclient.ProjectModelRuntime, model.ModelSelection, error) {
	if s.governance == nil {
		normalized := selection
		if strings.TrimSpace(normalized.Mode) == "" {
			normalized.Mode = "auto"
		}
		return nil, nil, normalized, nil
	}

	var projectID *int64
	if projectContext != nil && projectContext.ProjectID > 0 {
		id := projectContext.ProjectID
		projectID = &id
	}
	return s.governance.ResolveRequestModelRuntimePool(ctx, uid, projectID, selection)
}

// =========================================================
// Run Task Input
//

type RunTaskInput struct {
	ConversationID *int64

	Task string

	Scheduler string

	Planner string

	ExecutionMode string

	SynthesisMode string

	ModelSelection model.ModelSelection

	AttachmentIDs []int64

	Constraints model.TaskConstraints
}

func isContinuationTurn(task string) bool {
	normalized := strings.ToLower(strings.TrimSpace(task))
	if normalized == "" {
		return false
	}

	trimmed := strings.Trim(normalized, " \t\r\n，。！？!?；;：:、,.~～…")
	compact := strings.NewReplacer(
		" ", "", "\t", "", "\r", "", "\n", "",
		"，", "", "。", "", "！", "", "？", "", "!", "", "?", "",
		"；", "", ";", "", "：", "", ":", "", "、", "", ",", "", ".", "",
		"~", "", "～", "", "…", "",
	).Replace(trimmed)
	if compact == "" {
		return false
	}

	// Bare option replies such as “1”, “2”, “A” or “B” are inherently
	// dependent on the immediately preceding assistant turn. Treat them as
	// continuation turns so they cannot become context-blind new topics.
	if len([]rune(compact)) == 1 {
		r := []rune(compact)[0]
		if (r >= '0' && r <= '9') || (r >= 'a' && r <= 'd') {
			return true
		}
	}

	exact := map[string]struct{}{
		"继续": {}, "继续吧": {}, "继续讲": {}, "接着": {}, "接着说": {},
		"可以": {}, "好的": {}, "好": {}, "行": {}, "没问题": {},
		"然后呢": {}, "下一步": {}, "下一步呢": {}, "展开": {}, "展开讲讲": {},
		"详细点": {}, "再说说": {}, "再来": {}, "对": {}, "对的": {},
		"是": {}, "是的": {}, "continue": {}, "goon": {}, "yes": {}, "ok": {}, "okay": {},
	}
	if _, ok := exact[compact]; ok {
		return true
	}

	if len([]rune(compact)) > 14 {
		return false
	}
	prefixes := []string{
		"继续", "那继续", "好继续", "好的继续", "可以继续",
		"接着", "那接着", "然后", "下一步", "展开", "再说", "再来",
		"continue", "goon",
	}
	for _, prefix := range prefixes {
		if strings.HasPrefix(compact, prefix) {
			return true
		}
	}
	return false
}

// ShouldUseInteractiveFastPath keeps ordinary chat and request-local file/image
// analysis off the expensive multi-agent orchestration path. Requests that
// may need Project Knowledge, Tool/MCP/Skill discovery, durable memory or
// external side effects continue through the full Agent Runtime even when the
// user does not name a capability explicitly.
func ShouldUseInteractiveFastPath(task string, attachmentIDs []int64) bool {
	text := strings.ToLower(strings.TrimSpace(task))
	if text == "" {
		return false
	}

	// Short continuation turns are intentionally routed through the full
	// Runtime. They depend almost entirely on the immediately preceding turn
	// and may need to continue a Tool/MCP/Skill/Knowledge workflow. Treating
	// “可以/继续/好的” as a brand-new fast-path chat turn can silently switch
	// topics or drop an agentic capability context.
	if isContinuationTurn(text) {
		return false
	}

	agenticSignals := []string{
		// Project Knowledge / Memory
		"知识库", "项目知识", "项目资料", "项目文档", "项目文件", "当前项目", "本项目", "这个项目",
		"我们项目", "根据资料", "根据文档", "从文档", "agentmesh", "roadmap", "代码库", "repository",
		"你记得", "还记得", "记得我", "我的偏好", "记住", "忘记",
		"project knowledge", "knowledge base", "remember", "my preference", "forget",

		// Personal / GLOBAL Knowledge. The Runtime discovery layer decides
		// whether retrieval is actually relevant, but these cues must reach the
		// full Runtime first; otherwise FastPath can never discover the user's
		// uploaded/global knowledge.
		"我的简历", "我简历", "这份简历", "那份简历", "简历", "履历",
		"我的资料", "我的文档", "我的文件", "个人资料", "我上传", "上传的", "之前上传",
		"my resume", "my cv", "uploaded document", "uploaded file", "my document",

		// Tool / MCP / external integrations
		"调用工具", "使用工具", "执行工具", "mcp", "查询订单", "订单状态", "物流", "退款", "支付",
		"发邮件", "发送邮件", "邮箱", "天气", "创建记录", "删除记录", "写入",
		"github", "gitlab", "jira", "slack", "notion", "gmail", "outlook", "飞书", "钉钉", "企业微信",
		"pull request", "issue", "use tool", "call tool", "order status", "shipping", "refund", "send email",

		// Generic capability intent. Custom HTTP tools cannot be known to the
		// Control Plane fast-path classifier ahead of time, so action/data verbs
		// route into full Runtime where the request-scoped capability resolver can
		// rank the actual catalog. Explanatory chat such as “什么是/有什么区别” has
		// none of these verbs and keeps true-token streaming.
		"查询", "查一下", "查找", "搜索", "检索", "获取", "读取", "列出", "统计", "计算",
		"帮我查", "帮我看", "看看", "查看", "检查",
		"同步", "更新", "提交", "发布", "创建", "新建", "删除", "发送", "执行", "运行", "打开",
		"现在几点", "当前时间", "实时", "最新",
		"query", "lookup", "search", "fetch", "get ", "list ", "read ", "calculate", "compute",
		"sync", "update", "submit", "publish", "create", "delete", "send", "execute", "run ", "open ",

		// Desktop Agent. These phrases must reach the full Runtime so the
		// capability resolver can discover local.* autonomously.
		"本机", "本地文件", "本地目录", "桌面", "文件夹", "目录", "路径", "磁盘",
		"打开软件", "打开应用", "启动应用", "启动软件", "vscode", "chrome", "edge", "浏览器", "记事本",
		"命令行", "终端", "powershell", "pwsh", "shell", "cmd", "截图", "屏幕", "窗口",
		"鼠标", "键盘", "点击", "双击", "右键", "拖拽", "快捷键",
		"local.fs.", "local.app.", "local.tool.", "local.terminal.", "local.ui.",
		"desktop", "local file", "local folder", "command line", "terminal", "screenshot", "window", "mouse", "keyboard",

		// Skill / work execution
		"代码审查", "审查代码", "代码评审", "分析项目", "调试项目", "运行测试", "生成测试",
		"code review", "review code", "debug project", "run tests",
	}
	for _, signal := range agenticSignals {
		if strings.Contains(text, signal) {
			return false
		}
	}

	// Explicit filesystem paths are agentic even when the user does not use a
	// keyword such as “本机” or “调用工具”.
	if strings.Contains(text, ":\\") || strings.Contains(text, ":/") {
		return false
	}

	// Request-local attachments keep the low-latency multimodal path only when
	// the task itself did not express any agentic/capability intent above.
	if len(attachmentIDs) > 0 {
		return true
	}

	// Very large prompts usually represent explicit work rather than chat. The
	// full runtime keeps its Planner/Scheduler semantics for those requests.
	return len([]rune(text)) <= 4000
}

func boundedInteractiveHistory(messages []model.Message) []runtimeclient.InteractiveMessage {
	result := make([]runtimeclient.InteractiveMessage, 0, 8)
	budget := 6000
	for i := len(messages) - 1; i >= 0 && len(result) < 8 && budget > 0; i-- {
		message := messages[i]
		role := strings.ToLower(strings.TrimSpace(message.Role))
		if role != "user" && role != "assistant" {
			continue
		}
		content := strings.TrimSpace(message.Content)
		if content == "" {
			continue
		}
		runes := []rune(content)
		limit := 1200
		if limit > budget {
			limit = budget
		}
		if len(runes) > limit {
			// The tail of an assistant answer often contains the exact follow-up
			// choices (“1/2/3”, “要不要继续…”) that the next short user turn
			// refers to. Keep both the beginning and the newest tail instead of
			// truncating the tail away.
			head := limit / 3
			tail := limit - head
			content = string(runes[:head]) + " …[中间省略]… " + string(runes[len(runes)-tail:])
		} else {
			content = string(runes)
		}
		budget -= len(runes)
		result = append(result, runtimeclient.InteractiveMessage{Role: role, Content: content})
	}
	for left, right := 0, len(result)-1; left < right; left, right = left+1, right-1 {
		result[left], result[right] = result[right], result[left]
	}
	return result
}

// RunInteractiveStream executes the direct, true-token-streaming path used by
// ordinary chat and request-local attachments. It deliberately bypasses RAG,
// MCP discovery, evaluator and multi-agent planning; those remain available via
// Run for agentic requests.
func (s *TaskService) RunInteractiveStream(
	ctx context.Context,
	uid int64,
	in RunTaskInput,
	emit func(runtimeclient.InteractiveStreamEvent) error,
) (*RunTaskResult, error) {
	in.Task = strings.TrimSpace(in.Task)
	if in.Task == "" {
		return nil, ErrInvalidInput
	}
	if in.Scheduler == "" {
		in.Scheduler = "adaptive"
	}
	if in.Planner == "" {
		in.Planner = "multi_objective"
	}
	if in.ExecutionMode == "" {
		in.ExecutionMode = "auto"
	}
	if in.SynthesisMode == "" {
		in.SynthesisMode = "auto"
	}
	if in.Constraints.MaxLatencyMS <= 0 {
		in.Constraints.MaxLatencyMS = 8000
	}
	if in.Constraints.MaxCost <= 0 {
		in.Constraints.MaxCost = 0.15
	}
	if in.Constraints.MinQuality <= 0 {
		in.Constraints.MinQuality = 0.8
	}

	var projectRuntimeContext *model.ProjectRuntimeContext
	if s.projectRuntime != nil && in.ConversationID != nil {
		resolved, err := s.projectRuntime.ResolveForConversation(ctx, uid, *in.ConversationID)
		if err != nil {
			return nil, err
		}
		projectRuntimeContext = resolved
		if s.governance != nil && projectRuntimeContext != nil {
			if err := s.governance.CheckQuota(ctx, uid, projectRuntimeContext.ProjectID); err != nil {
				return nil, err
			}
		}
	}

	var history []runtimeclient.InteractiveMessage
	if in.ConversationID != nil {
		previous, err := s.messages.ListMessages(ctx, uid, *in.ConversationID, 12)
		if errors.Is(err, repository.ErrNotOwned) {
			return nil, ErrNotFound
		}
		if err != nil {
			return nil, err
		}
		history = boundedInteractiveHistory(previous)
	}

	var runtimeAttachments []runtimeclient.RuntimeAttachment
	var attachmentMeta []map[string]any
	if len(in.AttachmentIDs) > 0 {
		if in.ConversationID == nil || s.attachments == nil {
			return nil, ErrInvalidInput
		}
		var err error
		runtimeAttachments, attachmentMeta, err = s.attachments.ResolveForRuntime(ctx, uid, *in.ConversationID, in.AttachmentIDs)
		if err != nil {
			return nil, err
		}
	}

	modelPool, projectModel, normalizedSelection, err := s.resolveRequestModelRuntimePool(ctx, uid, projectRuntimeContext, in.ModelSelection)
	if err != nil {
		return nil, err
	}
	in.ModelSelection = normalizedSelection

	requestID := uuid.NewString()
	if in.ConversationID != nil {
		if _, err := s.messages.CreateMessage(ctx, uid, *in.ConversationID, "user", in.Task, "COMPLETED", requestID, map[string]any{
			"runtimePhase": "interactive_stream",
			"attachments":  attachmentMeta,
		}); err != nil {
			if errors.Is(err, repository.ErrNotOwned) {
				return nil, ErrNotFound
			}
			return nil, err
		}
	}

	task, err := s.tasks.CreateTask(ctx, model.Task{
		UserID: uid, ConversationID: in.ConversationID, RequestID: requestID, TaskText: in.Task,
		Scheduler: in.Scheduler, Planner: in.Planner, ExecutionMode: in.ExecutionMode, SynthesisMode: in.SynthesisMode,
		ModelSelection: in.ModelSelection,
	}, in.Constraints)
	if err != nil {
		return nil, err
	}

	if emit != nil {
		if err := emit(runtimeclient.InteractiveStreamEvent{Type: "meta", Mode: "interactive_stream"}); err != nil {
			_ = s.tasks.FailTask(ctx, uid, task.ID, err.Error(), 0)
			return nil, err
		}
	}

	started := time.Now()
	answer := strings.Builder{}
	var done runtimeclient.InteractiveStreamEvent
	var modelRoute runtimeclient.InteractiveStreamEvent
	streamErr := s.runtime.StreamInteractive(ctx, runtimeclient.InteractiveStreamRequest{
		UserID: uid, RequestID: requestID, ConversationID: in.ConversationID, Task: in.Task,
		History: history, ProjectModel: projectModel, ModelPool: modelPool,
		ModelSelection: runtimeclient.ModelSelection{Mode: in.ModelSelection.Mode, ServiceID: in.ModelSelection.ServiceID},
		Scheduler:      in.Scheduler, Constraints: in.Constraints, Attachments: runtimeAttachments,
	}, func(event runtimeclient.InteractiveStreamEvent) error {
		if event.Type == "delta" {
			answer.WriteString(event.Delta)
		}
		if event.Type == "model_route" {
			modelRoute = event
		}
		if event.Type == "done" {
			done = event
			if strings.TrimSpace(event.Content) != "" && answer.Len() == 0 {
				answer.WriteString(event.Content)
			}
		}
		if emit != nil {
			return emit(event)
		}
		return nil
	})
	elapsed := time.Since(started).Milliseconds()
	if streamErr != nil {
		_ = s.tasks.FailTask(ctx, uid, task.ID, streamErr.Error(), elapsed)
		return nil, streamErr
	}

	finalAnswer := strings.TrimSpace(answer.String())
	if finalAnswer == "" {
		finalAnswer = "模型没有返回可展示的内容，请重试。"
	}
	cost := 0.0
	if done.EstimatedCost != nil {
		cost = *done.EstimatedCost
	}
	if done.LatencyMS > 0 {
		elapsed = done.LatencyMS
	}
	selectedAgents := []string{"InteractiveFastPath"}
	routeDetail, _ := json.Marshal(map[string]any{
		"mode":        modelRoute.Mode,
		"reason":      modelRoute.Reason,
		"provider":    modelRoute.Provider,
		"model":       modelRoute.Model,
		"serviceId":   modelRoute.ServiceID,
		"serviceName": modelRoute.ServiceName,
	})
	trace := []map[string]any{
		{
			"kind": "model_route", "title": "Model Route", "status": "completed",
			"detail": string(routeDetail),
		},
		{
			"kind": "model", "title": "Interactive Stream", "status": "completed",
			"detail": "direct token streaming", "elapsedMs": elapsed,
		},
	}
	dag := map[string]any{
		"nodes": []map[string]any{{"id": "interactive-model", "label": "Interactive Model", "kind": "model", "status": "completed"}},
		"edges": []map[string]any{},
	}
	resolvedProvider := done.Provider
	if strings.TrimSpace(modelRoute.Provider) != "" {
		resolvedProvider = modelRoute.Provider
	}
	resolvedModel := done.Model
	if strings.TrimSpace(modelRoute.Model) != "" {
		resolvedModel = modelRoute.Model
	}
	observability := runtimeclient.ObservabilitySummary{
		ModelCalls: 1, ModelInputTokens: done.InputTokens, ModelOutputTokens: done.OutputTokens,
		ModelTotalTokens: done.TotalTokens, ModelLatencyMS: elapsed,
		ModelProvider: resolvedProvider, ModelName: resolvedModel,
		AgentAttempts: 1, AgentSuccesses: 1, DAGCompletedNodes: 1,
	}
	if done.EstimatedCost != nil {
		observability.ModelEstimatedCost = cost
		observability.ModelCostKnown = true
	}

	var assistantMessage *repository.AssistantMessageWrite
	if in.ConversationID != nil {
		assistantMessage = &repository.AssistantMessageWrite{
			UserID: uid, ConversationID: conversationIDValue(in.ConversationID), Content: finalAnswer, Status: "COMPLETED", RequestID: requestID,
			Metadata: map[string]any{
				"taskId": task.ID, "runtimePhase": "interactive_stream", "status": "COMPLETED",
				"selectedAgents": selectedAgents, "trace": trace, "dag": dag,
				"scheduler": in.Scheduler, "planner": in.Planner,
				"executionMode": in.ExecutionMode, "synthesisMode": in.SynthesisMode,
				"observability": observability, "citations": []runtimeclient.RuntimeCitation{},
			},
		}
	}

	if err := s.completeTaskWithAssistant(ctx, repository.TaskCompletionWrite{
		UserID: uid, TaskID: task.ID, ConversationID: conversationIDValue(in.ConversationID), Result: finalAnswer, Selected: selectedAgents, Trace: trace, DAG: dag,
		LatencyMS: elapsed, EstimatedCost: cost,
	}, assistantMessage); err != nil {
		if errors.Is(err, repository.ErrInvalidTaskState) {
			return nil, ErrConflict
		}
		return nil, err
	}
	var costProjectID *int64
	if s.governance != nil && projectRuntimeContext != nil {
		s.governance.RecordUsage(ctx, projectRuntimeContext.ProjectID, int64(done.TotalTokens), cost, 0)
		pid := projectRuntimeContext.ProjectID
		costProjectID = &pid
	}
	s.recordRunCost(ctx, uid, task.ID, costProjectID, observability, cost)

	task.Status = "COMPLETED"
	task.ResultText = &finalAnswer
	task.SelectedAgents = selectedAgents
	task.Trace = trace
	task.DAG = dag
	task.LatencyMS = &elapsed
	task.EstimatedCost = &cost

	return &RunTaskResult{
		Task: task, Status: "COMPLETED", Answer: finalAnswer, Citations: []runtimeclient.RuntimeCitation{},
		Scheduler: in.Scheduler, Planner: in.Planner, ExecutionMode: in.ExecutionMode, SynthesisMode: in.SynthesisMode,
		TaskProfile:    map[string]any{"mode": "interactive_stream", "requiredCapabilities": []string{"general"}},
		SelectedAgents: selectedAgents, EstimatedCost: cost, ElapsedMS: elapsed, Trace: trace, DAG: dag,
		AgentFeedback: []model.AgentFeedback{}, Observability: observability, Scorecard: nil,
	}, nil
}

// =========================================================
// Run Task Result
//
//
// Go Task ID
// +
// =========================================================

type RunTaskResult struct {
	Task *model.Task `json:"task"`

	Status string `json:"status"`

	Answer string `json:"answer"`

	Citations []runtimeclient.RuntimeCitation `json:"citations"`

	Scheduler string `json:"scheduler"`

	Planner string `json:"planner"`

	ExecutionMode string `json:"executionMode"`

	SynthesisMode string `json:"synthesisMode"`

	TaskProfile map[string]any `json:"taskProfile"`

	SelectedAgents []string `json:"selectedAgents"`

	EstimatedCost float64 `json:"estimatedCost"`

	ElapsedMS int64 `json:"elapsedMs"`

	Trace []map[string]any `json:"trace"`

	DAG map[string]any `json:"dag"`

	AgentFeedback []model.AgentFeedback `json:"agentFeedback"`

	Observability runtimeclient.ObservabilitySummary `json:"observability"`

	Scorecard *runtimeclient.RunScorecard `json:"scorecard"`
}

// =========================================================
// Runtime Continuation Mapping
//
// runtime package
//

func runtimeContinuationToModel(
	value *runtimeclient.Continuation,
) *model.TaskContinuation {
	if value == nil {
		return nil
	}

	return &model.TaskContinuation{
		Protocol: value.Protocol,

		AgentID: value.AgentID,

		Capability: value.Capability,

		TaskID: value.TaskID,

		ContextID: value.ContextID,

		State: value.State,

		Kind: value.Kind,

		ApprovalID: value.ApprovalID,

		ToolName: value.ToolName,

		ToolProtocol: value.ToolProtocol,

		RiskLevel: value.RiskLevel,

		RequiresConfirmation: value.RequiresConfirmation,

		Arguments: value.Arguments,

		Fingerprint: value.Fingerprint,

		Summary: value.Summary,
	}
}

func modelContinuationToRuntime(
	value *model.TaskContinuation,
) *runtimeclient.Continuation {
	if value == nil {
		return nil
	}

	return &runtimeclient.Continuation{
		Protocol: value.Protocol,

		AgentID: value.AgentID,

		Capability: value.Capability,

		TaskID: value.TaskID,

		ContextID: value.ContextID,

		State: value.State,

		Kind: value.Kind,

		ApprovalID: value.ApprovalID,

		ToolName: value.ToolName,

		ToolProtocol: value.ToolProtocol,

		RiskLevel: value.RiskLevel,

		RequiresConfirmation: value.RequiresConfirmation,

		Arguments: value.Arguments,

		Fingerprint: value.Fingerprint,

		Summary: value.Summary,
	}
}

// =========================================================
// Runtime Status Normalization
// =========================================================

func normalizeRuntimeStatus(
	value string,
) string {
	status := strings.ToUpper(
		strings.TrimSpace(
			value,
		),
	)

	// Backward compatibility with older Runtime responses.
	if status == "" {
		return "COMPLETED"
	}

	return status
}

func normalizeRuntimeCitations(
	value []runtimeclient.RuntimeCitation,
) []runtimeclient.RuntimeCitation {
	if value == nil {
		return []runtimeclient.RuntimeCitation{}
	}

	return value
}

// =========================================================
// Build API Result
// =========================================================

func buildRunTaskResult(
	task *model.Task,
	response *runtimeclient.ExecuteResponse,
	scheduler string,
	planner string,
	executionMode string,
	synthesisMode string,
) *RunTaskResult {
	return &RunTaskResult{
		Task: task,

		Status: task.Status,

		Answer: response.Answer,

		Citations: normalizeRuntimeCitations(
			response.Citations,
		),

		Scheduler: scheduler,

		Planner: planner,

		ExecutionMode: executionMode,

		SynthesisMode: synthesisMode,

		TaskProfile: response.TaskProfile,

		SelectedAgents: response.SelectedAgents,

		EstimatedCost: response.EstimatedCost,

		ElapsedMS: response.ElapsedMS,

		Trace: response.Trace,

		DAG: response.DAG,

		AgentFeedback: response.AgentFeedback,

		Observability: response.Observability,

		Scorecard: response.Scorecard,
	}
}

// =========================================================
// Load Runtime Resources
// =========================================================

func (s *TaskService) loadRuntimeResources(
	ctx context.Context,
	uid int64,
) (
	[]model.Agent,
	[]model.Tool,
	[]model.MCPServer,
	error,
) {
	agentPool, err := s.agents.ListAgents(
		ctx,
		uid,
	)

	if err != nil {
		return nil, nil, nil, err
	}

	if len(
		agentPool,
	) == 0 {
		return nil, nil, nil, errors.New(
			"当前还没有注册 Agent",
		)
	}

	toolPool := []model.Tool{}

	if s.tools != nil {
		toolPool, err = s.tools.ListTools(
			ctx,
			uid,
			true,
		)

		if err != nil {
			return nil, nil, nil, err
		}
	}

	mcpPool := []model.MCPServer{}

	if s.mcpServers != nil {
		mcpPool, err =
			s.mcpServers.ListMCPServers(
				ctx,
				uid,
				true,
			)

		if err != nil {
			return nil, nil, nil, err
		}
	}

	return agentPool,
		toolPool,
		mcpPool,
		nil
}

// =========================================================
// Run New Task
// =========================================================

func (s *TaskService) Run(
	ctx context.Context,
	uid int64,
	in RunTaskInput,
) (*RunTaskResult, error) {
	// =====================================================
	// 1. Normalize Input
	// =====================================================

	in.Task = strings.TrimSpace(
		in.Task,
	)

	if in.Task == "" {
		return nil, ErrInvalidInput
	}

	in.Scheduler = strings.ToLower(
		strings.TrimSpace(
			in.Scheduler,
		),
	)

	in.Planner = strings.ToLower(
		strings.TrimSpace(
			in.Planner,
		),
	)

	in.ExecutionMode = strings.ToLower(
		strings.TrimSpace(
			in.ExecutionMode,
		),
	)

	in.SynthesisMode = strings.ToLower(
		strings.TrimSpace(
			in.SynthesisMode,
		),
	)

	// =====================================================
	// 2. Defaults
	// =====================================================

	if in.Scheduler == "" {
		in.Scheduler = "greedy"
	}

	if in.Planner == "" {
		in.Planner = "heuristic"
	}

	if in.ExecutionMode == "" {
		in.ExecutionMode = "auto"
	}

	if in.SynthesisMode == "" {
		in.SynthesisMode = "auto"
	}

	// =====================================================
	// P2 Project Runtime Context
	//
	// Conversation -> Project -> Runtime bindings/policy.
	// Non-project conversations keep the existing account-wide behavior.
	// =====================================================

	var projectRuntimeContext *model.ProjectRuntimeContext

	if s.projectRuntime != nil && in.ConversationID != nil {
		resolvedContext, resolveErr :=
			s.projectRuntime.ResolveForConversation(
				ctx,
				uid,
				*in.ConversationID,
			)

		if resolveErr != nil {
			return nil, resolveErr
		}

		projectRuntimeContext = resolvedContext

		if s.governance != nil && projectRuntimeContext != nil {
			if quotaErr := s.governance.CheckQuota(ctx, uid, projectRuntimeContext.ProjectID); quotaErr != nil {
				return nil, quotaErr
			}
		}

		applyProjectRuntimePolicy(
			&in,
			projectRuntimeContext,
		)
	}

	// =====================================================
	// 3. Runtime Policy Validation
	// =====================================================

	switch in.Scheduler {
	case
		"fixed",
		"capability",
		"greedy",
		"adaptive":

	default:
		return nil, ErrInvalidInput
	}

	switch in.Planner {
	case
		"heuristic",
		"multi_objective":

	default:
		return nil, ErrInvalidInput
	}

	switch in.ExecutionMode {
	case
		"auto",
		"parallel",
		"sequential":

	default:
		return nil, ErrInvalidInput
	}

	switch in.SynthesisMode {
	case
		"auto",
		"always",
		"never":

	default:
		return nil, ErrInvalidInput
	}

	// =====================================================
	// 4. Constraints
	// =====================================================

	if in.Constraints.MaxLatencyMS <= 0 {
		in.Constraints.MaxLatencyMS = 8000
	}

	if in.Constraints.MaxCost <= 0 {
		in.Constraints.MaxCost = 0.15
	}

	if in.Constraints.MinQuality <= 0 {
		in.Constraints.MinQuality = 0.8
	}

	// =====================================================
	// 4.1 Request-local attachments
	// =====================================================

	var runtimeAttachments []runtimeclient.RuntimeAttachment
	var attachmentMeta []map[string]any
	if len(in.AttachmentIDs) > 0 {
		if in.ConversationID == nil || s.attachments == nil {
			return nil, ErrInvalidInput
		}
		var attachmentErr error
		runtimeAttachments, attachmentMeta, attachmentErr = s.attachments.ResolveForRuntime(
			ctx, uid, *in.ConversationID, in.AttachmentIDs,
		)
		if attachmentErr != nil {
			return nil, attachmentErr
		}
	}

	// =====================================================
	// Request-local BYOK preflight. Do this before persisting the message/task so
	// an unconfigured account gets a clean configuration error instead of a
	// failed task record.
	// =====================================================
	modelPool, projectModel, normalizedSelection, err := s.resolveRequestModelRuntimePool(ctx, uid, projectRuntimeContext, in.ModelSelection)
	if err != nil {
		return nil, err
	}
	in.ModelSelection = normalizedSelection

	// =====================================================
	// 4.2 Authoritative recent conversation history
	//
	// The Go/MySQL conversation log contains turns produced by both the
	// low-latency interactive path and the full Agent Runtime.  Send the same
	// recent context into full Runtime requests so a routing-path change cannot
	// split short-term conversation memory.  Load before persisting this turn so
	// `req.task` is not duplicated inside history.
	// =====================================================
	var history []runtimeclient.InteractiveMessage
	if in.ConversationID != nil {
		previous, historyErr := s.messages.ListMessages(ctx, uid, *in.ConversationID, 12)
		if errors.Is(historyErr, repository.ErrNotOwned) {
			return nil, ErrNotFound
		}
		if historyErr != nil {
			return nil, historyErr
		}
		history = boundedInteractiveHistory(previous)
	}

	// =====================================================
	// 5. Logical Request ID
	//

	requestID := uuid.NewString()

	// =====================================================
	// 6. Persist Initial User Message
	// =====================================================

	if in.ConversationID != nil {
		_, err := s.messages.CreateMessage(
			ctx,
			uid,
			*in.ConversationID,
			"user",
			in.Task,
			"COMPLETED",
			requestID,
			map[string]any{
				"runtimePhase": "initial",
				"attachments":  attachmentMeta,
			},
		)

		if errors.Is(
			err,
			repository.ErrNotOwned,
		) {
			return nil, ErrNotFound
		}

		if err != nil {
			return nil, err
		}
	}

	// =====================================================
	// 7. Create Long-lived Task
	// =====================================================

	task, err := s.tasks.CreateTask(
		ctx,
		model.Task{
			UserID: uid,

			ConversationID: in.ConversationID,

			RequestID: requestID,

			TaskText: in.Task,

			Scheduler: in.Scheduler,

			Planner: in.Planner,

			ExecutionMode: in.ExecutionMode,

			SynthesisMode: in.SynthesisMode,

			ModelSelection: in.ModelSelection,
		},
		in.Constraints,
	)

	if err != nil {
		return nil, err
	}

	// =====================================================
	// 8. Runtime Resources
	// =====================================================

	agentPool,
		toolPool,
		mcpPool,
		err :=
		s.loadRuntimeResources(
			ctx,
			projectRuntimeResourceUserID(uid, projectRuntimeContext),
		)

	if err != nil {
		_ = s.tasks.FailTask(
			ctx,
			uid,
			task.ID,
			err.Error(),
			0,
		)

		return nil, err
	}

	agentPool,
		toolPool,
		mcpPool =
		filterProjectRuntimeResources(
			projectRuntimeContext,
			agentPool,
			toolPool,
			mcpPool,
		)

	if len(agentPool) == 0 {
		message := "project runtime has no enabled agents"

		_ = s.tasks.FailTask(
			ctx,
			uid,
			task.ID,
			message,
			0,
		)

		return nil, errors.New(message)
	}

	// =====================================================
	// 9. Go -> Python Runtime
	// =====================================================

	started := time.Now()

	response, err := s.runtime.Execute(
		ctx,
		runtimeclient.ExecuteRequest{
			UserID: uid,

			RequestID: requestID,

			ConversationID: in.ConversationID,

			Task: in.Task,

			History: history,

			Scheduler: in.Scheduler,

			Planner: in.Planner,

			ExecutionMode: in.ExecutionMode,

			SynthesisMode: in.SynthesisMode,

			Constraints: in.Constraints,

			Agents: agentPool,

			Tools: toolPool,

			MCPServers: mcpPool,

			Continuation: nil,

			ProjectModel: projectModel,

			ModelPool: modelPool,

			ModelSelection: runtimeclient.ModelSelection{Mode: in.ModelSelection.Mode, ServiceID: in.ModelSelection.ServiceID},

			Attachments: runtimeAttachments,
		},
	)

	if err != nil {
		elapsed := time.Since(
			started,
		).Milliseconds()

		_ = s.tasks.FailTask(
			ctx,
			uid,
			task.ID,
			err.Error(),
			elapsed,
		)

		return nil, err
	}

	attachProjectRuntimeTrace(
		response,
		projectRuntimeContext,
		len(agentPool),
		len(toolPool),
		len(mcpPool),
		model.ProjectRuntimePolicy{
			Scheduler: in.Scheduler, Planner: in.Planner,
			ExecutionMode: in.ExecutionMode, SynthesisMode: in.SynthesisMode,
			Constraints: in.Constraints,
		},
	)
	var runCostProjectID *int64
	if s.governance != nil && projectRuntimeContext != nil {
		s.governance.RecordUsage(ctx, projectRuntimeContext.ProjectID, int64(response.Observability.ModelTotalTokens), response.EstimatedCost, int64(response.Observability.ToolCalls))
		pid := projectRuntimeContext.ProjectID
		runCostProjectID = &pid
	}
	s.recordRunCost(ctx, uid, task.ID, runCostProjectID, response.Observability, response.EstimatedCost)

	runtimeStatus :=
		normalizeRuntimeStatus(
			response.Status,
		)

	// =====================================================
	// 10. Runtime Suspend
	//
	// RUNNING
	// =====================================================

	if runtimeStatus == "INPUT_REQUIRED" ||
		runtimeStatus == "AUTH_REQUIRED" {
		if response.Continuation == nil {
			_ = s.tasks.FailTask(
				ctx,
				uid,
				task.ID,
				"runtime suspended without continuation",
				response.ElapsedMS,
			)

			return nil, errors.New(
				"runtime suspended without continuation",
			)
		}

		continuation :=
			runtimeContinuationToModel(
				response.Continuation,
			)

		var assistantMessage *repository.AssistantMessageWrite
		if in.ConversationID != nil {
			assistantMessage = &repository.AssistantMessageWrite{
				UserID: uid, ConversationID: conversationIDValue(in.ConversationID), Content: response.Answer, Status: runtimeStatus, RequestID: requestID,
				Metadata: map[string]any{
					"taskId": task.ID, "runtimePhase": "suspended", "status": runtimeStatus,
				},
			}
		}

		if err = s.suspendTaskWithAssistant(
			ctx,
			repository.TaskSuspensionWrite{
				UserID: uid, TaskID: task.ID, ConversationID: conversationIDValue(in.ConversationID), Status: runtimeStatus, Result: response.Answer, Continuation: continuation,
				Selected: response.SelectedAgents, Trace: response.Trace, DAG: response.DAG,
				LatencyMS: response.ElapsedMS, EstimatedCost: response.EstimatedCost,
			},
			assistantMessage,
		); err != nil {
			if errors.Is(
				err,
				repository.ErrInvalidTaskState,
			) {
				return nil, ErrConflict
			}

			return nil, err
		}

		task.Status =
			runtimeStatus

		task.ResultText =
			&response.Answer

		task.SelectedAgents =
			response.SelectedAgents

		task.Trace =
			response.Trace

		task.DAG =
			response.DAG

		task.LatencyMS =
			&response.ElapsedMS

		task.EstimatedCost =
			&response.EstimatedCost

		task.Continuation =
			continuation

		// Reload the server-side projection so a tool approval is immediately
		// available to the UI without exposing authoritative arguments.
		if refreshed, loadErr := s.tasks.TaskByID(ctx, uid, task.ID); loadErr == nil && refreshed != nil {
			task = refreshed
		}

		return buildRunTaskResult(
			task,
			response,
			in.Scheduler,
			in.Planner,
			in.ExecutionMode,
			in.SynthesisMode,
		), nil
	}

	// =====================================================
	// 11. Unsupported Runtime State
	// =====================================================

	if runtimeStatus != "COMPLETED" {
		message :=
			"unsupported runtime status: " +
				runtimeStatus

		_ = s.tasks.FailTask(
			ctx,
			uid,
			task.ID,
			message,
			response.ElapsedMS,
		)

		return nil, errors.New(
			message,
		)
	}

	// =====================================================
	// 12. RUNNING -> COMPLETED
	// =====================================================

	var assistantMessage *repository.AssistantMessageWrite
	if in.ConversationID != nil {
		assistantMessage = &repository.AssistantMessageWrite{
			UserID: uid, ConversationID: conversationIDValue(in.ConversationID), Content: response.Answer, Status: "COMPLETED", RequestID: requestID,
			Metadata: map[string]any{
				"taskId":         task.ID,
				"runtimePhase":   "completed",
				"trace":          response.Trace,
				"dag":            response.DAG,
				"selectedAgents": response.SelectedAgents,
				"taskProfile":    response.TaskProfile,
				"scheduler":      in.Scheduler,
				"planner":        in.Planner,
				"executionMode":  in.ExecutionMode,
				"synthesisMode":  in.SynthesisMode,
				"observability":  response.Observability,
				"scorecard":      response.Scorecard,
				"agentFeedback":  response.AgentFeedback,
				"citations":      normalizeRuntimeCitations(response.Citations),
			},
		}
	}

	if err = s.completeTaskWithAssistant(
		ctx,
		repository.TaskCompletionWrite{
			UserID: uid, TaskID: task.ID, ConversationID: conversationIDValue(in.ConversationID), Result: response.Answer, Selected: response.SelectedAgents,
			Trace: response.Trace, DAG: response.DAG, LatencyMS: response.ElapsedMS, EstimatedCost: response.EstimatedCost,
		},
		assistantMessage,
	); err != nil {
		if errors.Is(
			err,
			repository.ErrInvalidTaskState,
		) {
			return nil, ErrConflict
		}

		return nil, err
	}

	// =====================================================
	// 13. Capability Experience Feedback
	// =====================================================

	if err = s.agents.RecordAgentFeedback(
		ctx,
		uid,
		task.RequestID,
		response.AgentFeedback,
	); err != nil {
		// Feedback is auxiliary telemetry. Once task state and assistant history
		// have committed atomically, a feedback write must not turn the user's
		// successful task into an apparent execution failure.
		log.Printf("agent feedback persistence failed after task finalization: %v", err)
	}

	// =====================================================
	// 15. Update DTO
	// =====================================================

	task.Status =
		"COMPLETED"

	task.ResultText =
		&response.Answer

	task.SelectedAgents =
		response.SelectedAgents

	task.Trace =
		response.Trace

	task.DAG =
		response.DAG

	task.LatencyMS =
		&response.ElapsedMS

	task.EstimatedCost =
		&response.EstimatedCost

	task.Continuation =
		nil

	task.Approval = nil

	return buildRunTaskResult(
		task,
		response,
		in.Scheduler,
		in.Planner,
		in.ExecutionMode,
		in.SynthesisMode,
	), nil
}

// =========================================================
// Resume Existing Long-lived Task
//
// React:
//
// POST /api/tasks/:id/resume
//
// {
// }
//
// Go:
//
// task ID
// =========================================================

func (s *TaskService) Resume(
	ctx context.Context,
	uid int64,
	taskID int64,
	supplement string,
) (*RunTaskResult, error) {
	// =====================================================
	// 1. Validate Supplemental Input
	// =====================================================

	supplement = strings.TrimSpace(
		supplement,
	)

	if supplement == "" {
		return nil, ErrInvalidInput
	}

	// =====================================================
	// 2. Load Authoritative Task
	//
	// WHERE id=? AND user_id=?
	// =====================================================

	task, err := s.tasks.TaskByID(
		ctx,
		uid,
		taskID,
	)

	if err != nil {
		return nil, err
	}

	if task == nil {
		return nil, ErrNotFound
	}

	if task.Status != "INPUT_REQUIRED" &&
		task.Status != "AUTH_REQUIRED" {
		return nil, ErrConflict
	}

	if task.Continuation == nil {
		return nil, ErrConflict
	}

	isToolApproval := strings.EqualFold(
		task.Continuation.Protocol,
		"tool_approval",
	) || task.Continuation.Kind == "tool_approval"

	if isToolApproval {
		decision := strings.ToLower(supplement)
		if decision != "approve" && decision != "reject" {
			return nil, ErrInvalidInput
		}
	}

	// =====================================================
	// 3. Save Previous Suspend Snapshot
	//

	previousStatus :=
		task.Status

	previousContinuation :=
		task.Continuation

	previousResult := ""

	if task.ResultText != nil {
		previousResult =
			*task.ResultText
	}

	previousLatency := int64(
		0,
	)

	if task.LatencyMS != nil {
		previousLatency =
			*task.LatencyMS
	}

	previousCost := 0.0

	if task.EstimatedCost != nil {
		previousCost =
			*task.EstimatedCost
	}

	// =====================================================
	// 4. Reload Current Runtime Resources
	//
	// A suspended approval is never permission to bypass current state.
	// If an Agent/Tool/MCP was disabled or removed from the Project while
	// waiting for the user, the resumed action must fail closed.
	// =====================================================

	var projectRuntimeContext *model.ProjectRuntimeContext
	if s.projectRuntime != nil && task.ConversationID != nil {
		projectRuntimeContext, err = s.projectRuntime.ResolveForConversation(ctx, uid, *task.ConversationID)
		if err != nil {
			return nil, err
		}
		if s.governance != nil && projectRuntimeContext != nil {
			if quotaErr := s.governance.CheckQuota(ctx, uid, projectRuntimeContext.ProjectID); quotaErr != nil {
				return nil, quotaErr
			}
		}
	}

	agentPool, toolPool, mcpPool, err := s.loadRuntimeResources(
		ctx,
		projectRuntimeResourceUserID(uid, projectRuntimeContext),
	)

	if err != nil {
		return nil, err
	}

	if projectRuntimeContext != nil {
		agentPool, toolPool, mcpPool = filterProjectRuntimeResources(
			projectRuntimeContext,
			agentPool,
			toolPool,
			mcpPool,
		)
	}

	// Legacy A2A continuation resumes the original remote Agent task only.
	// Tool/MCP pools are transmitted exclusively for server-side tool approval
	// continuation, where the exact persisted action must be revalidated against
	// the current enabled/project-scoped resources before execution.
	if !isToolApproval {
		toolPool = nil
		mcpPool = nil
	}

	if len(agentPool) == 0 {
		return nil, ErrNotFound
	}

	// =====================================================
	// 5. Verify Continuation Agent Ownership
	//

	foundAgent := false

	for _, agent := range agentPool {
		if agent.ID !=
			task.Continuation.AgentID {
			continue
		}

		foundAgent = true

		agentProtocol :=
			strings.ToLower(
				strings.TrimSpace(
					agent.Protocol,
				),
			)

		continuationProtocol :=
			strings.ToLower(
				strings.TrimSpace(
					task.Continuation.Protocol,
				),
			)

		if !isToolApproval && agentProtocol !=
			continuationProtocol {
			return nil, ErrConflict
		}

		break
	}

	if !foundAgent {
		return nil, ErrNotFound
	}

	// =====================================================
	// 6. CAS:
	//
	// INPUT_REQUIRED / AUTH_REQUIRED
	//

	started, err :=
		s.tasks.BeginTaskResume(
			ctx,
			uid,
			task.ID,
		)

	if err != nil {
		return nil, err
	}

	if !started {
		return nil, ErrConflict
	}

	task.Status =
		"RUNNING"

	// =====================================================
	// Restore Previous Suspension
	//

	restoreSuspension := func() {
		_ = s.tasks.SuspendTask(
			ctx,
			uid,
			task.ID,
			previousStatus,
			previousResult,
			previousContinuation,
			task.SelectedAgents,
			task.Trace,
			task.DAG,
			previousLatency,
			previousCost,
		)
	}

	// =====================================================
	// 7. Persist Supplemental User Message
	// =====================================================

	if task.ConversationID != nil {
		messageContent := supplement
		if isToolApproval {
			if strings.EqualFold(supplement, "approve") {
				messageContent = "确认执行"
			} else {
				messageContent = "取消操作"
			}
		}

		_, err = s.messages.CreateMessage(
			ctx,
			uid,
			*task.ConversationID,
			"user",
			messageContent,
			"COMPLETED",
			task.RequestID,
			map[string]any{
				"taskId": task.ID,

				"runtimePhase": "resume",
			},
		)

		if err != nil {
			restoreSuspension()

			if errors.Is(
				err,
				repository.ErrNotOwned,
			) {
				return nil, ErrNotFound
			}

			return nil, err
		}
	}

	modelPool, projectModel, normalizedSelection, err := s.resolveRequestModelRuntimePool(ctx, uid, projectRuntimeContext, task.ModelSelection)
	if err != nil {
		restoreSuspension()
		return nil, err
	}
	task.ModelSelection = normalizedSelection

	// =====================================================
	// 8. Python Runtime Resume
	//
	//
	// RAG
	// Scheduler
	// Planner
	// Tool/MCP preload
	//

	response, err := s.runtime.Execute(
		ctx,
		runtimeclient.ExecuteRequest{
			UserID: uid,

			RequestID: task.RequestID,

			ConversationID: task.ConversationID,

			Task: supplement,

			Scheduler: task.Scheduler,

			Planner: task.Planner,

			ExecutionMode: task.ExecutionMode,

			SynthesisMode: task.SynthesisMode,

			Constraints: task.Constraints,

			Agents: agentPool,

			Tools: toolPool,

			MCPServers: mcpPool,

			Continuation: modelContinuationToRuntime(
				task.Continuation,
			),

			ProjectModel: projectModel,

			ModelPool: modelPool,

			ModelSelection: runtimeclient.ModelSelection{Mode: task.ModelSelection.Mode, ServiceID: task.ModelSelection.ServiceID},
		},
	)

	if err != nil {
		if isToolApproval {
			// At-most-once safety: an approved side-effect may have reached the
			// external system before a transport failure became visible. Do not
			// restore AUTH_REQUIRED and invite a duplicate execution.
			_ = s.tasks.FailTask(
				ctx,
				uid,
				task.ID,
				"approved action failed or execution outcome is ambiguous",
				0,
			)
		} else {
			restoreSuspension()
		}

		return nil, err
	}

	attachProjectRuntimeTrace(response, projectRuntimeContext, len(agentPool), len(toolPool), len(mcpPool),
		model.ProjectRuntimePolicy{
			Scheduler: task.Scheduler, Planner: task.Planner,
			ExecutionMode: task.ExecutionMode, SynthesisMode: task.SynthesisMode,
			Constraints: task.Constraints,
		})
	var runCostProjectID *int64
	if s.governance != nil && projectRuntimeContext != nil {
		s.governance.RecordUsage(ctx, projectRuntimeContext.ProjectID, int64(response.Observability.ModelTotalTokens), response.EstimatedCost, int64(response.Observability.ToolCalls))
		pid := projectRuntimeContext.ProjectID
		runCostProjectID = &pid
	}
	s.recordRunCost(ctx, uid, task.ID, runCostProjectID, response.Observability, response.EstimatedCost)

	runtimeStatus :=
		normalizeRuntimeStatus(
			response.Status,
		)

	// =====================================================
	// RUNNING
	// =====================================================

	if runtimeStatus == "INPUT_REQUIRED" ||
		runtimeStatus == "AUTH_REQUIRED" {
		if response.Continuation == nil {
			_ = s.tasks.FailTask(
				ctx,
				uid,
				task.ID,
				"runtime suspended without continuation",
				response.ElapsedMS,
			)

			return nil, errors.New(
				"runtime suspended without continuation",
			)
		}

		continuation :=
			runtimeContinuationToModel(
				response.Continuation,
			)

		var assistantMessage *repository.AssistantMessageWrite
		if task.ConversationID != nil {
			assistantMessage = &repository.AssistantMessageWrite{
				UserID: uid, ConversationID: conversationIDValue(task.ConversationID), Content: response.Answer, Status: runtimeStatus, RequestID: task.RequestID,
				Metadata: map[string]any{
					"taskId": task.ID, "runtimePhase": "suspended", "status": runtimeStatus,
				},
			}
		}

		if err = s.suspendTaskWithAssistant(
			ctx,
			repository.TaskSuspensionWrite{
				UserID: uid, TaskID: task.ID, ConversationID: conversationIDValue(task.ConversationID), Status: runtimeStatus, Result: response.Answer, Continuation: continuation,
				Selected: response.SelectedAgents, Trace: response.Trace, DAG: response.DAG,
				LatencyMS: response.ElapsedMS, EstimatedCost: response.EstimatedCost,
			},
			assistantMessage,
		); err != nil {
			if errors.Is(
				err,
				repository.ErrInvalidTaskState,
			) {
				return nil, ErrConflict
			}

			return nil, err
		}

		task.Status =
			runtimeStatus

		task.ResultText =
			&response.Answer

		task.SelectedAgents =
			response.SelectedAgents

		task.Trace =
			response.Trace

		task.DAG =
			response.DAG

		task.LatencyMS =
			&response.ElapsedMS

		task.EstimatedCost =
			&response.EstimatedCost

		task.Continuation =
			continuation

		if refreshed, loadErr := s.tasks.TaskByID(ctx, uid, task.ID); loadErr == nil && refreshed != nil {
			task = refreshed
		}

		return buildRunTaskResult(
			task,
			response,
			task.Scheduler,
			task.Planner,
			task.ExecutionMode,
			task.SynthesisMode,
		), nil
	}

	// =====================================================
	// 10. Unsupported Runtime Status
	// =====================================================

	if runtimeStatus != "COMPLETED" {
		message :=
			"unsupported runtime status: " +
				runtimeStatus

		_ = s.tasks.FailTask(
			ctx,
			uid,
			task.ID,
			message,
			response.ElapsedMS,
		)

		return nil, errors.New(
			message,
		)
	}

	// =====================================================
	// 11. RUNNING -> COMPLETED
	//

	var assistantMessage *repository.AssistantMessageWrite
	if task.ConversationID != nil {
		assistantMessage = &repository.AssistantMessageWrite{
			UserID: uid, ConversationID: conversationIDValue(task.ConversationID), Content: response.Answer, Status: "COMPLETED", RequestID: task.RequestID,
			Metadata: map[string]any{
				"taskId":         task.ID,
				"runtimePhase":   "resume_completed",
				"trace":          response.Trace,
				"dag":            response.DAG,
				"selectedAgents": response.SelectedAgents,
				"taskProfile":    response.TaskProfile,
				"observability":  response.Observability,
				"scorecard":      response.Scorecard,
				"agentFeedback":  response.AgentFeedback,
				"citations":      normalizeRuntimeCitations(response.Citations),
			},
		}
	}

	if err = s.completeTaskWithAssistant(
		ctx,
		repository.TaskCompletionWrite{
			UserID: uid, TaskID: task.ID, ConversationID: conversationIDValue(task.ConversationID), Result: response.Answer, Selected: response.SelectedAgents,
			Trace: response.Trace, DAG: response.DAG, LatencyMS: response.ElapsedMS, EstimatedCost: response.EstimatedCost,
		},
		assistantMessage,
	); err != nil {
		if errors.Is(
			err,
			repository.ErrInvalidTaskState,
		) {
			return nil, ErrConflict
		}

		return nil, err
	}

	// =====================================================
	// 12. Capability Feedback
	//

	if err =
		s.agents.RecordAgentFeedback(
			ctx,
			uid,
			task.RequestID,
			response.AgentFeedback,
		); err != nil {
		log.Printf("agent feedback persistence failed after resumed task finalization: %v", err)
	}

	// =====================================================
	// 14. Update DTO
	// =====================================================

	task.Status =
		"COMPLETED"

	task.ResultText =
		&response.Answer

	task.SelectedAgents =
		response.SelectedAgents

	task.Trace =
		response.Trace

	task.DAG =
		response.DAG

	task.LatencyMS =
		&response.ElapsedMS

	task.EstimatedCost =
		&response.EstimatedCost

	task.Continuation =
		nil

	task.Approval = nil

	return buildRunTaskResult(
		task,
		response,
		task.Scheduler,
		task.Planner,
		task.ExecutionMode,
		task.SynthesisMode,
	), nil
}

// =========================================================
// Task List
// =========================================================

func (s *TaskService) List(
	ctx context.Context,
	uid int64,
) ([]model.Task, error) {
	return s.tasks.ListTasks(
		ctx,
		uid,
		50,
	)
}

// =========================================================
// Runtime Plugins
// =========================================================

func (s *TaskService) Plugins(
	ctx context.Context,
) ([]runtimeclient.PluginInfo, error) {
	return s.runtime.Plugins(
		ctx,
	)
}
