package handler

import (
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"strings"
	"time"

	"example.com/agentmesh-control-plane/internal/middleware"
	"example.com/agentmesh-control-plane/internal/model"
	runtimeclient "example.com/agentmesh-control-plane/internal/runtime"
	"example.com/agentmesh-control-plane/internal/service"

	"github.com/gin-gonic/gin"
)

// =========================================================
// Common Response
// =========================================================

func ok(
	c *gin.Context,
	data any,
) {
	c.JSON(
		http.StatusOK,
		gin.H{
			"code":    0,
			"message": "success",
			"data":    data,
		},
	)
}

func fail(
	c *gin.Context,
	status int,
	code int,
	message string,
) {
	c.JSON(
		status,
		gin.H{
			"code":    code,
			"message": message,
			"data":    nil,
		},
	)
}

func uid(
	c *gin.Context,
) int64 {
	value, _ := middleware.UserID(
		c,
	)

	return value
}

func idParam(
	c *gin.Context,
) (int64, bool) {
	value, err := strconv.ParseInt(
		c.Param(
			"id",
		),
		10,
		64,
	)

	if err != nil ||
		value <= 0 {
		fail(
			c,
			http.StatusBadRequest,
			40001,
			"ID 不合法",
		)

		return 0, false
	}

	return value, true
}

// =========================================================
// Domain Error Mapping
//
// Service 层只返回领域错误。
//
// Handler 负责把领域错误转换为：
//
// HTTP Status
// +
// API Error Code
// +
// User-facing Message
// =========================================================

func domain(
	c *gin.Context,
	err error,
) {
	switch {
	case errors.Is(
		err,
		service.ErrInvalidInput,
	):
		fail(
			c,
			http.StatusBadRequest,
			40010,
			"参数不合法",
		)

	case errors.Is(
		err,
		service.ErrNotFound,
	):
		fail(
			c,
			http.StatusNotFound,
			40410,
			"资源不存在",
		)

	case errors.Is(
		err,
		service.ErrForbidden,
	):
		fail(
			c,
			http.StatusForbidden,
			40310,
			"没有执行此操作的权限",
		)

	case errors.Is(
		err,
		service.ErrQuotaExceeded,
	):
		fail(
			c,
			http.StatusTooManyRequests,
			42910,
			"项目额度已达到限制",
		)

	case errors.Is(
		err,
		service.ErrModelAutoRouteNotConfigured,
	):
		fail(
			c,
			http.StatusConflict,
			40921,
			"请至少将一个已启用的个人模型服务加入自动路由",
		)

	case errors.Is(
		err,
		service.ErrModelProviderNotConfigured,
	):
		fail(
			c,
			http.StatusConflict,
			40920,
			"请先在模型设置中启用至少一个可用模型服务",
		)

	case errors.Is(err, service.ErrAttachmentLimit):
		fail(c, http.StatusBadRequest, 40096, "每次任务最多 6 个附件，总大小不超过 20 MB")
	case errors.Is(
		err,
		service.ErrProjectAlreadyBound,
	):
		fail(
			c,
			http.StatusConflict,
			40930,
			"当前项目已属于其他团队工作空间，如需迁移，请先解除原有归属",
		)

	case errors.Is(
		err,
		service.ErrConflict,
	):
		fail(
			c,
			http.StatusConflict,
			40910,
			"当前任务状态不允许执行该操作",
		)

	case errors.Is(
		err,
		service.ErrAlreadyExists,
	):
		fail(
			c,
			http.StatusConflict,
			40911,
			"资源已存在",
		)

	case errors.Is(err, service.ErrPackageValidation):
		fail(c, http.StatusBadRequest, 40012, "生态包清单校验失败，请检查权限、端点和 Manifest")

	case errors.Is(err, service.ErrIdempotencyConflict):
		fail(c, http.StatusConflict, 40940, "幂等键已被其他请求占用或请求内容不一致")

	default:
		fail(
			c,
			http.StatusInternalServerError,
			50000,
			err.Error(),
		)
	}
}

// =========================================================
// Auth
// =========================================================

type AuthHandler struct {
	s *service.AuthService

	cookie string

	secure bool

	maxAge int
}

func NewAuthHandler(
	s *service.AuthService,
	cookie string,
	secure bool,
	ttl time.Duration,
) *AuthHandler {
	return &AuthHandler{
		s:      s,
		cookie: cookie,
		secure: secure,

		maxAge: int(
			ttl.Seconds(),
		),
	}
}

type registerReq struct {
	Email string `json:"email" binding:"required,email"`

	Password string `json:"password" binding:"required"`

	DisplayName string `json:"displayName" binding:"required"`
}

type loginReq struct {
	Email string `json:"email" binding:"required,email"`

	Password string `json:"password" binding:"required"`
}

func (h *AuthHandler) setCookie(
	c *gin.Context,
	value string,
) {
	c.SetSameSite(
		http.SameSiteLaxMode,
	)

	c.SetCookie(
		h.cookie,
		value,
		h.maxAge,
		"/api/auth",
		"",
		h.secure,
		true,
	)
}

func (h *AuthHandler) clearCookie(
	c *gin.Context,
) {
	c.SetSameSite(
		http.SameSiteLaxMode,
	)

	c.SetCookie(
		h.cookie,
		"",
		-1,
		"/api/auth",
		"",
		h.secure,
		true,
	)
}

func authData(
	result *service.AuthResult,
) gin.H {
	return gin.H{
		"accessToken": result.AccessToken,

		"expiresIn": result.ExpiresIn,

		"tokenType": "Bearer",

		"user": result.User,
	}
}

func (h *AuthHandler) Register(
	c *gin.Context,
) {
	var req registerReq

	if c.ShouldBindJSON(
		&req,
	) != nil {
		fail(
			c,
			http.StatusBadRequest,
			40011,
			"注册参数不合法",
		)

		return
	}

	result, err := h.s.Register(
		c,
		req.Email,
		req.Password,
		req.DisplayName,
	)

	if errors.Is(
		err,
		service.ErrEmailExists,
	) {
		fail(
			c,
			http.StatusConflict,
			40901,
			"邮箱已注册",
		)

		return
	}

	if err != nil {
		domain(
			c,
			err,
		)

		return
	}

	h.setCookie(
		c,
		result.RefreshToken,
	)

	c.JSON(
		http.StatusCreated,
		gin.H{
			"code":    0,
			"message": "success",

			"data": authData(
				result,
			),
		},
	)
}

func (h *AuthHandler) Login(
	c *gin.Context,
) {
	var req loginReq

	if c.ShouldBindJSON(
		&req,
	) != nil {
		fail(
			c,
			http.StatusBadRequest,
			40012,
			"登录参数不合法",
		)

		return
	}

	result, err := h.s.Login(
		c,
		req.Email,
		req.Password,
	)

	if errors.Is(
		err,
		service.ErrInvalidCredentials,
	) {
		fail(
			c,
			http.StatusUnauthorized,
			40101,
			"邮箱或密码错误",
		)

		return
	}

	if err != nil {
		domain(
			c,
			err,
		)

		return
	}

	h.setCookie(
		c,
		result.RefreshToken,
	)

	ok(
		c,
		authData(
			result,
		),
	)
}

func (h *AuthHandler) Refresh(
	c *gin.Context,
) {
	raw, err := c.Cookie(
		h.cookie,
	)

	if err != nil {
		h.clearCookie(
			c,
		)

		fail(
			c,
			http.StatusUnauthorized,
			40103,
			"Refresh Token 无效",
		)

		return
	}

	result, err := h.s.Refresh(
		c,
		raw,
	)

	if err != nil {
		h.clearCookie(
			c,
		)

		fail(
			c,
			http.StatusUnauthorized,
			40103,
			"Refresh Token 无效",
		)

		return
	}

	h.setCookie(
		c,
		result.RefreshToken,
	)

	ok(
		c,
		authData(
			result,
		),
	)
}

func (h *AuthHandler) Logout(
	c *gin.Context,
) {
	raw, _ := c.Cookie(
		h.cookie,
	)

	_ = h.s.Logout(
		c,
		raw,
	)

	h.clearCookie(
		c,
	)

	ok(
		c,
		nil,
	)
}

func (h *AuthHandler) Me(
	c *gin.Context,
) {
	user, err := h.s.Me(
		c,
		uid(
			c,
		),
	)

	if err != nil {
		domain(
			c,
			err,
		)

		return
	}

	ok(
		c,
		user,
	)
}

// =========================================================
// Conversation
// =========================================================

type ConversationHandler struct {
	s *service.ConversationService
}

func NewConversationHandler(
	s *service.ConversationService,
) *ConversationHandler {
	return &ConversationHandler{
		s: s,
	}
}

func (h *ConversationHandler) Create(
	c *gin.Context,
) {
	var req struct {
		Title string `json:"title"`
	}

	_ = c.ShouldBindJSON(
		&req,
	)

	conversation, err := h.s.Create(
		c,
		uid(
			c,
		),
		req.Title,
	)

	if err != nil {
		domain(
			c,
			err,
		)

		return
	}

	c.JSON(
		http.StatusCreated,
		gin.H{
			"code":    0,
			"message": "success",
			"data":    conversation,
		},
	)
}

func (h *ConversationHandler) List(
	c *gin.Context,
) {
	conversations, err := h.s.List(
		c,
		uid(
			c,
		),
	)

	if err != nil {
		domain(
			c,
			err,
		)

		return
	}

	ok(
		c,
		conversations,
	)
}

func (h *ConversationHandler) Delete(
	c *gin.Context,
) {
	id, valid := idParam(
		c,
	)

	if !valid {
		return
	}

	if err := h.s.Delete(
		c,
		uid(
			c,
		),
		id,
	); err != nil {
		domain(
			c,
			err,
		)

		return
	}

	ok(
		c,
		nil,
	)
}

func (h *ConversationHandler) Messages(
	c *gin.Context,
) {
	id, valid := idParam(
		c,
	)

	if !valid {
		return
	}

	messages, err := h.s.Messages(
		c,
		uid(
			c,
		),
		id,
	)

	if err != nil {
		domain(
			c,
			err,
		)

		return
	}

	ok(
		c,
		messages,
	)
}

// =========================================================
// Agent
// =========================================================

type AgentHandler struct {
	s *service.AgentService
}

func NewAgentHandler(
	s *service.AgentService,
) *AgentHandler {
	return &AgentHandler{
		s: s,
	}
}

func (h *AgentHandler) Create(
	c *gin.Context,
) {
	var agent model.Agent

	if c.ShouldBindJSON(
		&agent,
	) != nil {
		fail(
			c,
			http.StatusBadRequest,
			40030,
			"Agent 参数不合法",
		)

		return
	}

	created, err := h.s.Create(
		c,
		uid(
			c,
		),
		agent,
	)

	if err != nil {
		domain(
			c,
			err,
		)

		return
	}

	c.JSON(
		http.StatusCreated,
		gin.H{
			"code":    0,
			"message": "success",
			"data":    created,
		},
	)
}

func (h *AgentHandler) List(
	c *gin.Context,
) {
	agents, err := h.s.List(
		c,
		uid(
			c,
		),
	)

	if err != nil {
		domain(
			c,
			err,
		)

		return
	}

	ok(
		c,
		agents,
	)
}

func (h *AgentHandler) Delete(
	c *gin.Context,
) {
	id, valid := idParam(
		c,
	)

	if !valid {
		return
	}

	if err := h.s.Delete(
		c,
		uid(
			c,
		),
		id,
	); err != nil {
		domain(
			c,
			err,
		)

		return
	}

	ok(
		c,
		nil,
	)
}

func (h *AgentHandler) Seed(
	c *gin.Context,
) {
	agents, err := h.s.SeedDemo(
		c,
		uid(
			c,
		),
	)

	if err != nil {
		domain(
			c,
			err,
		)

		return
	}

	ok(
		c,
		agents,
	)
}

// =========================================================
// Task
// =========================================================

type TaskHandler struct {
	s *service.TaskService
}

func NewTaskHandler(
	s *service.TaskService,
) *TaskHandler {
	return &TaskHandler{
		s: s,
	}
}

// =========================================================
// Create / Execute New Task
//
// React only submits:
//
// task
// scheduler
// planner
// executionMode
// synthesisMode
// constraints
//
// continuation 不允许由客户端直接提交。
//
// continuation 是 Go Control Plane 的服务端状态。
// =========================================================

type runReq struct {
	ConversationID *int64 `json:"conversationId"`

	Task string `json:"task" binding:"required"`

	Scheduler string `json:"scheduler"`

	Planner string `json:"planner"`

	ExecutionMode string `json:"executionMode"`

	SynthesisMode string `json:"synthesisMode"`

	ModelSelection model.ModelSelection `json:"modelSelection"`

	AttachmentIDs []int64 `json:"attachmentIds"`

	Constraints model.TaskConstraints `json:"constraints"`
}

func writeNDJSON(c *gin.Context, payload any) error {
	data, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	data = append(data, '\n')
	if _, err := c.Writer.Write(data); err != nil {
		return err
	}
	c.Writer.Flush()
	return nil
}

func (h *TaskHandler) RunStream(c *gin.Context) {
	var req runReq
	if c.ShouldBindJSON(&req) != nil {
		fail(c, http.StatusBadRequest, 40040, "Task 参数不合法")
		return
	}

	c.Header("Content-Type", "application/x-ndjson; charset=utf-8")
	c.Header("Cache-Control", "no-cache, no-transform")
	c.Header("X-Accel-Buffering", "no")
	c.Status(http.StatusOK)
	c.Writer.Flush()

	input := service.RunTaskInput{
		ConversationID: req.ConversationID,
		Task:           req.Task,
		Scheduler:      req.Scheduler,
		Planner:        req.Planner,
		ExecutionMode:  req.ExecutionMode,
		SynthesisMode:  req.SynthesisMode,
		ModelSelection: req.ModelSelection,
		AttachmentIDs:  req.AttachmentIDs,
		Constraints:    req.Constraints,
	}

	var result *service.RunTaskResult
	var err error
	if service.ShouldUseInteractiveFastPath(req.Task, req.AttachmentIDs) {
		result, err = h.s.RunInteractiveStream(c, uid(c), input, func(event runtimeclient.InteractiveStreamEvent) error {
			return writeNDJSON(c, event)
		})
	} else {
		_ = writeNDJSON(c, gin.H{
			"type":    "status",
			"phase":   "agent_runtime",
			"message": "正在进行 Agent 协作执行…",
		})
		result, err = h.s.Run(c, uid(c), input)
	}

	if err != nil {
		_ = writeNDJSON(c, gin.H{
			"type":    "error",
			"message": err.Error(),
		})
		return
	}

	_ = writeNDJSON(c, gin.H{
		"type":   "result",
		"result": result,
	})
}

func (h *TaskHandler) Run(
	c *gin.Context,
) {
	var req runReq

	if c.ShouldBindJSON(
		&req,
	) != nil {
		fail(
			c,
			http.StatusBadRequest,
			40040,
			"Task 参数不合法",
		)

		return
	}

	result, err := h.s.Run(
		c,
		uid(
			c,
		),
		service.RunTaskInput{
			ConversationID: req.ConversationID,

			Task: req.Task,

			Scheduler: req.Scheduler,

			Planner: req.Planner,

			ExecutionMode: req.ExecutionMode,

			SynthesisMode: req.SynthesisMode,

			ModelSelection: req.ModelSelection,

			AttachmentIDs: req.AttachmentIDs,

			Constraints: req.Constraints,
		},
	)

	if err != nil {
		domain(
			c,
			err,
		)

		return
	}

	ok(
		c,
		result,
	)
}

// =========================================================
// Resume Existing Task
//
// Request:
//
// POST /api/tasks/:id/resume
//
// Body:
//
// {
//     "task": "用户补充的信息"
// }
//
// 注意：
//
// React 不传：
//
// protocol
// agentId
// taskId
// contextId
// continuation
//
// Go 根据当前用户 + Task ID
// 从 MySQL 加载 authoritative continuation。
// =========================================================

type resumeTaskReq struct {
	Task string `json:"task"`

	Decision string `json:"decision"`
}

func (h *TaskHandler) Resume(
	c *gin.Context,
) {
	taskID, valid := idParam(
		c,
	)

	if !valid {
		return
	}

	var req resumeTaskReq

	if c.ShouldBindJSON(
		&req,
	) != nil {
		fail(
			c,
			http.StatusBadRequest,
			40041,
			"Resume 参数不合法",
		)

		return
	}

	supplement := strings.TrimSpace(req.Task)
	decision := strings.ToLower(strings.TrimSpace(req.Decision))

	if decision != "" {
		if decision != "approve" && decision != "reject" {
			fail(c, http.StatusBadRequest, 40041, "审批决定不合法")
			return
		}
		supplement = decision
	}

	if supplement == "" {
		fail(c, http.StatusBadRequest, 40041, "Resume 参数不合法")
		return
	}

	result, err := h.s.Resume(
		c,
		uid(
			c,
		),
		taskID,
		supplement,
	)

	if err != nil {
		domain(
			c,
			err,
		)

		return
	}

	ok(
		c,
		result,
	)
}

// =========================================================
// Task History
// =========================================================

func (h *TaskHandler) List(
	c *gin.Context,
) {
	tasks, err := h.s.List(
		c,
		uid(
			c,
		),
	)

	if err != nil {
		domain(
			c,
			err,
		)

		return
	}

	ok(
		c,
		tasks,
	)
}

// =========================================================
// Runtime Plugin List
// =========================================================

func (h *TaskHandler) Plugins(
	c *gin.Context,
) {
	plugins, err := h.s.Plugins(
		c,
	)

	if err != nil {
		domain(
			c,
			err,
		)

		return
	}

	ok(
		c,
		plugins,
	)
}
