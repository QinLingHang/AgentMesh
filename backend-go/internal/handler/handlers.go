package handler

import (
	"context"
	"encoding/json"
	"errors"
	"log"
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

	case errors.Is(err, service.ErrIdempotencyConflict):
		fail(c, http.StatusConflict, 40941, "该请求标识已用于不同内容，请重新提交")
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

func (h *ConversationHandler) MessagePage(c *gin.Context) {
	id, valid := idParam(c)
	if !valid {
		return
	}

	limit := 50
	if raw := strings.TrimSpace(c.Query("limit")); raw != "" {
		parsed, err := strconv.Atoi(raw)
		if err != nil || parsed <= 0 || parsed > 100 {
			fail(c, http.StatusBadRequest, 40010, "分页参数不合法")
			return
		}
		limit = parsed
	}

	var beforeID int64
	if raw := strings.TrimSpace(c.Query("beforeId")); raw != "" {
		parsed, err := strconv.ParseInt(raw, 10, 64)
		if err != nil || parsed <= 0 {
			fail(c, http.StatusBadRequest, 40010, "分页游标不合法")
			return
		}
		beforeID = parsed
	}

	page, err := h.s.MessagePage(c, uid(c), id, beforeID, limit)
	if err != nil {
		domain(c, err)
		return
	}

	ok(c, page)
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
	ClientRequestID string `json:"clientRequestId"`
	ConversationID  *int64 `json:"conversationId"`

	Task string `json:"task" binding:"required"`

	Scheduler string `json:"scheduler"`

	Planner string `json:"planner"`

	ExecutionMode string `json:"executionMode"`

	SynthesisMode string `json:"synthesisMode"`

	ModelSelection model.ModelSelection `json:"modelSelection"`

	AttachmentIDs []int64 `json:"attachmentIds"`

	RagPolicy model.RagPolicy `json:"ragPolicy"`

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

func (h *TaskHandler) DecideRoute(c *gin.Context) {
	var req runReq
	if c.ShouldBindJSON(&req) != nil {
		fail(c, http.StatusBadRequest, 40040, "Task 参数不合法")
		return
	}
	decision := h.s.DecideDeliveryMode(service.RunTaskInput{
		ClientRequestID: req.ClientRequestID, ConversationID: req.ConversationID,
		Task:           req.Task,
		Scheduler:      req.Scheduler,
		Planner:        req.Planner,
		ExecutionMode:  req.ExecutionMode,
		SynthesisMode:  req.SynthesisMode,
		ModelSelection: req.ModelSelection,
		AttachmentIDs:  req.AttachmentIDs,
		RagPolicy:      req.RagPolicy,
		Constraints:    req.Constraints,
	})
	ok(c, decision)
}

func (h *TaskHandler) RunStream(c *gin.Context) {
	var req runReq
	if c.ShouldBindJSON(&req) != nil {
		fail(c, http.StatusBadRequest, 40040, "Task 参数不合法")
		return
	}
	h.runStreamRequest(c, req, nil, nil)
}

// RunAutoStream is the single-submit endpoint. The server makes its routing
// decision from the SAME validated request that it executes: the browser must
// never issue a second POST after asking a preflight endpoint for a route.
// The legacy direct/durable endpoints remain available for older clients.
// RunAutoStream preserves one POST for every decision and business execution.
// Semantic routing is OFF by default; Shadow never changes the authoritative legacy route.
func (h *TaskHandler) RunAutoStream(c *gin.Context, durable *DurableRuntimeHandler) {
	var req runReq
	if c.ShouldBindJSON(&req) != nil {
		fail(c, http.StatusBadRequest, 40040, "Task 参数不合法")
		return
	}
	input := service.RunTaskInput{
		ClientRequestID: req.ClientRequestID, ConversationID: req.ConversationID, Task: req.Task,
		Scheduler: req.Scheduler, Planner: req.Planner,
		ExecutionMode: req.ExecutionMode, SynthesisMode: req.SynthesisMode,
		ModelSelection: req.ModelSelection, AttachmentIDs: req.AttachmentIDs,
		RagPolicy: req.RagPolicy, Constraints: req.Constraints,
	}
	mode := service.ExecutionRoutingMode()
	var routingDecision *service.ExecutionRouteDecision
	if mode == "OFF" || mode == "SHADOW" || mode == "ENABLED" {
		// First resolve the original submission. A configuration rollback or
		// concurrent retry may not cause a second model/tool execution.
		prior, err := h.s.ResolveExistingSubmission(c.Request.Context(), uid(c), input)
		if err != nil {
			domain(c, err)
			return
		}
		if prior != nil {
			replay := service.ReplaySubmissionResult(prior)
			c.Header("Content-Type", "application/x-ndjson; charset=utf-8")
			_ = writeNDJSON(c, gin.H{"type": "route", "mode": prior.DeliveryMode, "reason": "idempotent_replay"})
			_ = writeNDJSON(c, gin.H{"type": "result", "result": replay})
			return
		}
	}
	if mode == "ENABLED" {
		// Exact task-control utterances are operations on an existing owned Task,
		// not new LLM/Runtime submissions. Never guess among two candidates.
		operation := service.TaskControlOperation(input.Task)
		switch operation {
		case "GET_TASK_STATUS":
			task, err := h.s.StatusTask(c.Request.Context(), uid(c), input)
			if err != nil {
				domain(c, err)
				return
			}
			c.Header("Content-Type", "application/x-ndjson; charset=utf-8")
			_ = writeNDJSON(c, gin.H{"type": "route", "mode": "none", "reason": "authorized_task_status"})
			_ = writeNDJSON(c, gin.H{"type": "result", "result": service.ReplaySubmissionResult(task)})
			return
		case "RESUME_TASK":
			result, err := h.s.ResumeCurrentTask(c.Request.Context(), uid(c), input)
			if err != nil {
				domain(c, err)
				return
			}
			c.Header("Content-Type", "application/x-ndjson; charset=utf-8")
			_ = writeNDJSON(c, gin.H{"type": "route", "mode": "none", "reason": "authorized_task_resume"})
			_ = writeNDJSON(c, gin.H{"type": "result", "result": result})
			return
		case "APPROVAL_REJECT":
			result, err := h.s.RejectCurrentApproval(c.Request.Context(), uid(c), input)
			if err != nil {
				domain(c, err)
				return
			}
			c.Header("Content-Type", "application/x-ndjson; charset=utf-8")
			_ = writeNDJSON(c, gin.H{"type": "route", "mode": "none", "reason": "approval_rejected", "handling": "APPROVAL_REJECT"})
			_ = writeNDJSON(c, gin.H{"type": "result", "result": result})
			return
		case "CANCEL_TASK":
			if durable == nil {
				fail(c, http.StatusServiceUnavailable, 50340, "Durable Runtime 不可用，无法安全取消任务")
				return
			}
			task, err := h.s.PendingTask(c.Request.Context(), uid(c), input)
			if err != nil {
				domain(c, err)
				return
			}
			if task.DeliveryMode != "durable" {
				domain(c, service.ErrConflict)
				return
			}
			cancelled, err := durable.s.Cancel(c.Request.Context(), uid(c), task.ID)
			if err != nil {
				domain(c, err)
				return
			}
			c.Header("Content-Type", "application/x-ndjson; charset=utf-8")
			_ = writeNDJSON(c, gin.H{"type": "route", "mode": "none", "reason": "authorized_task_cancel"})
			_ = writeNDJSON(c, gin.H{"type": "result", "result": service.ReplaySubmissionResult(cancelled)})
			return
		}
	}
	if mode == "SHADOW" {
		// Shadow is read-only and bounded. Never block the original response,
		// create a task, disclose raw request/catalog or run a capability.
		snapshot := input
		actor := uid(c)
		go func() {
			context, cancel := context.WithTimeout(context.Background(), 2*time.Second)
			defer cancel()
			proposal, err := h.s.DecideExecutionRouteShadow(context, actor, snapshot)
			if err != nil {
				log.Print("execution_routing_shadow status=unavailable")
				return
			}
			log.Printf("execution_routing_shadow status=completed strategy=%s reasonCount=%d", proposal.Strategy, len(proposal.ReasonCodes))
		}()
	} else if mode == "ENABLED" {
		var err error
		routingDecision, err = h.s.DecideExecutionRoute(c.Request.Context(), uid(c), input)
		if err != nil {
			// No unsafe fallback to a fabricated Direct answer or new task.
			fail(c, http.StatusServiceUnavailable, 50323, "无法安全确定执行方式，请稍后重试；本次未启动执行")
			return
		}
		if routingDecision.RuntimePath == "NONE" && routingDecision.Disposition == "REJECT" {
			message := "该请求违反当前授权或安全策略，未执行操作"
			if len(routingDecision.UnresolvedRequirements) > 0 {
				message = routingDecision.UnresolvedRequirements[0]
			}
			c.Header("Content-Type", "application/x-ndjson; charset=utf-8")
			_ = writeNDJSON(c, gin.H{"type": "route", "mode": "none", "reason": "policy_rejected", "handling": "REJECT"})
			_ = writeNDJSON(c, gin.H{"type": "error", "message": message})
			return
		}
		if routingDecision.RuntimePath == "NONE" {
			message := "缺少完成请求所需的信息，请补充具体目标或授权"
			if len(routingDecision.UnresolvedRequirements) > 0 {
				message = routingDecision.UnresolvedRequirements[0]
			}
			// Persist the clarification as a suspended Task, not a Runtime job;
			// retries return the same task and cannot duplicate assistant messages.
			result, persistErr := h.s.PersistRoutingClarification(c.Request.Context(), uid(c), input, routingDecision)
			if persistErr != nil {
				domain(c, persistErr)
				return
			}
			c.Header("Content-Type", "application/x-ndjson; charset=utf-8")
			_ = writeNDJSON(c, gin.H{"type": "route", "mode": "none", "reason": "needs_clarification", "decisionVersion": routingDecision.SchemaVersion})
			_ = writeNDJSON(c, gin.H{"type": "clarification", "message": message, "taskId": result.Task.ID})
			_ = writeNDJSON(c, gin.H{"type": "result", "result": result})
			return
		}
		input.ExecutionRoute = routingDecision.Strategy
		input.ExecutionIntent = routingDecision.ExecutionIntent
		input.RoutingReasonCodes = append([]string(nil), routingDecision.ReasonCodes...)
		input.RoutingAnalysisSource = routingDecision.AnalysisSource
		input.RoutingAnalysisLatencyMS = routingDecision.AnalysisLatencyMS
		input.RoutingModelCalls = routingDecision.PreflightModelCalls
		input.RoutingModelTokens = routingDecision.PreflightModelTokens
		input.RoutingModelEstimatedCost = routingDecision.PreflightModelEstimatedCost
		input.RoutingModelCostKnown = routingDecision.PreflightModelCostKnown
	}
	decision := h.s.DecideDeliveryMode(input)
	if routingDecision != nil {
		decision.Mode = routingDecision.DeliveryMode
		decision.Reason = "validated_execution_route"
	}
	if decision.Mode == "durable" {
		if durable == nil {
			fail(c, http.StatusServiceUnavailable, 50340, "Durable Runtime 不可用，不能降级执行需要可靠性的任务")
			return
		}
		result, err := durable.s.Run(c, uid(c), input)
		if err != nil {
			domain(c, err)
			return
		}
		if routingDecision != nil && result != nil {
			if cleanupErr := h.s.SupersedeRoutingClarifications(c.Request.Context(), uid(c), result.Task); cleanupErr != nil {
				log.Print("routing clarification cleanup=deferred")
			}
		}
		c.Header("Content-Type", "application/x-ndjson; charset=utf-8")
		c.Header("Cache-Control", "no-cache, no-transform")
		c.Header("X-Accel-Buffering", "no")
		route := gin.H{"type": "route", "mode": decision.Mode, "reason": decision.Reason}
		if routingDecision != nil {
			route["strategy"] = routingDecision.Strategy
			route["decisionVersion"] = routingDecision.SchemaVersion
			route["reasonCodes"] = routingDecision.ReasonCodes
		}
		_ = writeNDJSON(c, route)
		_ = writeNDJSON(c, gin.H{"type": "result", "result": result})
		return
	}
	h.runStreamRequest(c, req, &decision, routingDecision)
}

func (h *TaskHandler) runStreamRequest(c *gin.Context, req runReq, decision *service.DeliveryDecision, routingDecision *service.ExecutionRouteDecision) {

	c.Header("Content-Type", "application/x-ndjson; charset=utf-8")
	c.Header("Cache-Control", "no-cache, no-transform")
	c.Header("X-Accel-Buffering", "no")
	c.Status(http.StatusOK)
	c.Writer.Flush()
	if decision != nil {
		route := gin.H{"type": "route", "mode": decision.Mode, "reason": decision.Reason}
		if routingDecision != nil {
			route["strategy"] = routingDecision.Strategy
			route["decisionVersion"] = routingDecision.SchemaVersion
			route["reasonCodes"] = routingDecision.ReasonCodes
		}
		_ = writeNDJSON(c, route)
	}

	input := service.RunTaskInput{
		ClientRequestID: req.ClientRequestID, ConversationID: req.ConversationID,
		Task:           req.Task,
		Scheduler:      req.Scheduler,
		Planner:        req.Planner,
		ExecutionMode:  req.ExecutionMode,
		SynthesisMode:  req.SynthesisMode,
		ModelSelection: req.ModelSelection,
		AttachmentIDs:  req.AttachmentIDs,
		RagPolicy:      req.RagPolicy,
		Constraints:    req.Constraints,
	}
	if routingDecision != nil {
		input.ExecutionRoute = routingDecision.Strategy
		input.ExecutionIntent = routingDecision.ExecutionIntent
		input.RoutingReasonCodes = append([]string(nil), routingDecision.ReasonCodes...)
		input.RoutingAnalysisSource = routingDecision.AnalysisSource
		input.RoutingAnalysisLatencyMS = routingDecision.AnalysisLatencyMS
		input.RoutingModelCalls = routingDecision.PreflightModelCalls
		input.RoutingModelTokens = routingDecision.PreflightModelTokens
		input.RoutingModelEstimatedCost = routingDecision.PreflightModelEstimatedCost
		input.RoutingModelCostKnown = routingDecision.PreflightModelCostKnown
	}

	var result *service.RunTaskResult
	var err error
	forceFullRuntimeForKnowledge := req.RagPolicy.Mode == model.RagModeOn || len(req.RagPolicy.SelectedKnowledgeBaseIDs) > 0
	if (routingDecision == nil && !forceFullRuntimeForKnowledge && service.ShouldUseInteractiveFastPath(req.Task, req.AttachmentIDs)) || (routingDecision != nil && routingDecision.Strategy == "FAST_PATH") {
		result, err = h.s.RunInteractiveStream(c, uid(c), input, func(event runtimeclient.InteractiveStreamEvent) error {
			return writeNDJSON(c, event)
		})
	} else {
		_ = writeNDJSON(c, gin.H{
			"type":    "status",
			"phase":   "agent_runtime",
			"message": "正在通过 Runtime 处理请求…",
		})

		streamCtx := runtimeclient.WithStreamEventSink(c, func(event map[string]any) {
			eventType, _ := event["type"].(string)
			if eventType != "trace" && eventType != "delta" {
				return
			}
			if eventType == "delta" {
				delta, ok := event["delta"].(string)
				if !ok || len(delta) > 32*1024 {
					return
				}
			}
			_ = writeNDJSON(c, event)
		})
		result, err = h.s.Run(streamCtx, uid(c), input)
	}

	if err != nil {
		_ = writeNDJSON(c, gin.H{
			"type":    "error",
			"message": err.Error(),
		})
		return
	}

	if routingDecision != nil && result != nil {
		if cleanupErr := h.s.SupersedeRoutingClarifications(c.Request.Context(), uid(c), result.Task); cleanupErr != nil {
			log.Print("routing clarification cleanup=deferred")
		}
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
			ClientRequestID: req.ClientRequestID, ConversationID: req.ConversationID,

			Task: req.Task,

			Scheduler: req.Scheduler,

			Planner: req.Planner,

			ExecutionMode: req.ExecutionMode,

			SynthesisMode: req.SynthesisMode,

			ModelSelection: req.ModelSelection,

			AttachmentIDs: req.AttachmentIDs,

			RagPolicy: req.RagPolicy,

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
