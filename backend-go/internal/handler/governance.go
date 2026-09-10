package handler

import (
	"net/http"
	"strconv"
	"time"

	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/service"
	"github.com/gin-gonic/gin"
)

type GovernanceHandler struct{ s *service.GovernanceService }

func NewGovernanceHandler(s *service.GovernanceService) *GovernanceHandler {
	return &GovernanceHandler{s: s}
}

func projectIDParam(c *gin.Context) (int64, bool) {
	v, err := strconv.ParseInt(c.Param("id"), 10, 64)
	if err != nil || v <= 0 {
		fail(c, http.StatusBadRequest, 40090, "项目 ID 不合法")
		return 0, false
	}
	return v, true
}

func (h *GovernanceHandler) Overview(c *gin.Context) {
	pid, okv := projectIDParam(c)
	if !okv {
		return
	}
	data, err := h.s.Overview(c, uid(c), pid)
	if err != nil {
		domain(c, err)
		return
	}
	ok(c, data)
}
func (h *GovernanceHandler) AddMember(c *gin.Context) {
	pid, okv := projectIDParam(c)
	if !okv {
		return
	}
	var req struct {
		Email string `json:"email" binding:"required,email"`
		Role  string `json:"role" binding:"required"`
	}
	if c.ShouldBindJSON(&req) != nil {
		fail(c, http.StatusBadRequest, 40091, "成员参数不合法")
		return
	}
	item, err := h.s.AddMember(c, uid(c), pid, req.Email, req.Role)
	if err != nil {
		domain(c, err)
		return
	}
	c.JSON(http.StatusCreated, gin.H{"code": 0, "message": "success", "data": item})
}
func (h *GovernanceHandler) RemoveMember(c *gin.Context) {
	pid, okv := projectIDParam(c)
	if !okv {
		return
	}
	memberID, err := strconv.ParseInt(c.Param("userId"), 10, 64)
	if err != nil || memberID <= 0 {
		fail(c, http.StatusBadRequest, 40092, "成员 ID 不合法")
		return
	}
	if err := h.s.RemoveMember(c, uid(c), pid, memberID); err != nil {
		domain(c, err)
		return
	}
	ok(c, nil)
}
func (h *GovernanceHandler) UpdateQuota(c *gin.Context) {
	pid, okv := projectIDParam(c)
	if !okv {
		return
	}
	var q model.ProjectQuota
	if c.ShouldBindJSON(&q) != nil {
		fail(c, http.StatusBadRequest, 40093, "额度参数不合法")
		return
	}
	saved, err := h.s.UpdateQuota(c, uid(c), pid, q)
	if err != nil {
		domain(c, err)
		return
	}
	ok(c, saved)
}
func (h *GovernanceHandler) CreateSecret(c *gin.Context) {
	pid, okv := projectIDParam(c)
	if !okv {
		return
	}
	var req struct {
		Name  string `json:"name" binding:"required"`
		Kind  string `json:"kind" binding:"required"`
		Value string `json:"value" binding:"required"`
	}
	if c.ShouldBindJSON(&req) != nil {
		fail(c, http.StatusBadRequest, 40094, "密钥参数不合法")
		return
	}
	saved, err := h.s.CreateSecret(c, uid(c), pid, req.Name, req.Kind, req.Value)
	if err != nil {
		domain(c, err)
		return
	}
	c.JSON(http.StatusCreated, gin.H{"code": 0, "message": "success", "data": saved})
}
func (h *GovernanceHandler) DeleteSecret(c *gin.Context) {
	pid, okv := projectIDParam(c)
	if !okv {
		return
	}
	id, err := strconv.ParseInt(c.Param("secretId"), 10, 64)
	if err != nil || id <= 0 {
		fail(c, http.StatusBadRequest, 40095, "密钥 ID 不合法")
		return
	}
	if err := h.s.DeleteSecret(c, uid(c), pid, id); err != nil {
		domain(c, err)
		return
	}
	ok(c, nil)
}
func (h *GovernanceHandler) UpsertProvider(c *gin.Context) {
	pid, okv := projectIDParam(c)
	if !okv {
		return
	}
	var p model.ProjectModelProvider
	if c.ShouldBindJSON(&p) != nil {
		fail(c, http.StatusBadRequest, 40096, "模型供应商参数不合法")
		return
	}
	saved, err := h.s.UpsertProvider(c, uid(c), pid, p)
	if err != nil {
		domain(c, err)
		return
	}
	ok(c, saved)
}
func (h *GovernanceHandler) Audit(c *gin.Context) {
	pid, okv := projectIDParam(c)
	if !okv {
		return
	}
	limit, _ := strconv.Atoi(c.DefaultQuery("limit", "100"))
	items, err := h.s.Audit(c, uid(c), pid, limit)
	if err != nil {
		domain(c, err)
		return
	}
	ok(c, items)
}

func (h *GovernanceHandler) CreateOrganization(c *gin.Context) {
	var req struct {
		Name string `json:"name" binding:"required"`
	}
	if c.ShouldBindJSON(&req) != nil {
		fail(c, http.StatusBadRequest, 40097, "组织参数不合法")
		return
	}
	item, err := h.s.CreateOrganization(c, uid(c), req.Name)
	if err != nil {
		domain(c, err)
		return
	}
	c.JSON(http.StatusCreated, gin.H{"code": 0, "message": "success", "data": item})
}
func (h *GovernanceHandler) ListOrganizations(c *gin.Context) {
	items, err := h.s.ListOrganizations(c, uid(c))
	if err != nil {
		domain(c, err)
		return
	}
	ok(c, items)
}
func (h *GovernanceHandler) AddOrganizationMember(c *gin.Context) {
	orgID, err := strconv.ParseInt(c.Param("organizationId"), 10, 64)
	if err != nil || orgID <= 0 {
		fail(c, http.StatusBadRequest, 40098, "组织 ID 不合法")
		return
	}
	var req struct {
		Email string `json:"email" binding:"required,email"`
		Role  string `json:"role" binding:"required"`
	}
	if c.ShouldBindJSON(&req) != nil {
		fail(c, http.StatusBadRequest, 40099, "组织成员参数不合法")
		return
	}
	item, err := h.s.AddOrganizationMember(c, uid(c), orgID, req.Email, req.Role)
	if err != nil {
		domain(c, err)
		return
	}
	ok(c, item)
}
func (h *GovernanceHandler) BindOrganizationProject(c *gin.Context) {
	orgID, err := strconv.ParseInt(c.Param("organizationId"), 10, 64)
	if err != nil || orgID <= 0 {
		fail(c, http.StatusBadRequest, 40100, "组织 ID 不合法")
		return
	}
	pid, err := strconv.ParseInt(c.Param("projectId"), 10, 64)
	if err != nil || pid <= 0 {
		fail(c, http.StatusBadRequest, 40101, "项目 ID 不合法")
		return
	}
	if err := h.s.BindProjectToOrganization(c, uid(c), orgID, pid); err != nil {
		domain(c, err)
		return
	}
	ok(c, nil)
}

func (h *GovernanceHandler) GetUserModelProvider(c *gin.Context) {
	item, err := h.s.GetUserModelProvider(c, uid(c))
	if err != nil {
		domain(c, err)
		return
	}
	ok(c, item)
}

func (h *GovernanceHandler) UpsertUserModelProvider(c *gin.Context) {
	var req model.UserModelProviderInput
	if c.ShouldBindJSON(&req) != nil {
		fail(c, http.StatusBadRequest, 40102, "模型配置参数不合法")
		return
	}
	item, err := h.s.UpsertUserModelProvider(c, uid(c), req)
	if err != nil {
		domain(c, err)
		return
	}
	ok(c, item)
}

func (h *GovernanceHandler) DeleteUserModelProvider(c *gin.Context) {
	if err := h.s.DeleteUserModelProvider(c, uid(c)); err != nil {
		domain(c, err)
		return
	}
	ok(c, nil)
}

func (h *GovernanceHandler) ListUserModelServices(c *gin.Context) {
	items, err := h.s.ListUserModelServices(c, uid(c))
	if err != nil {
		domain(c, err)
		return
	}
	ok(c, items)
}

func (h *GovernanceHandler) CreateUserModelService(c *gin.Context) {
	var req model.UserModelServiceInput
	if c.ShouldBindJSON(&req) != nil {
		fail(c, http.StatusBadRequest, 40104, "模型服务参数不合法")
		return
	}
	item, err := h.s.CreateUserModelService(c, uid(c), req)
	if err != nil {
		domain(c, err)
		return
	}
	ok(c, item)
}

func (h *GovernanceHandler) UpdateUserModelService(c *gin.Context) {
	id, err := strconv.ParseInt(c.Param("serviceId"), 10, 64)
	if err != nil || id <= 0 {
		fail(c, http.StatusBadRequest, 40105, "模型服务 ID 不合法")
		return
	}
	var req model.UserModelServiceInput
	if c.ShouldBindJSON(&req) != nil {
		fail(c, http.StatusBadRequest, 40104, "模型服务参数不合法")
		return
	}
	item, err := h.s.UpdateUserModelService(c, uid(c), id, req)
	if err != nil {
		domain(c, err)
		return
	}
	ok(c, item)
}

func (h *GovernanceHandler) DeleteUserModelService(c *gin.Context) {
	id, err := strconv.ParseInt(c.Param("serviceId"), 10, 64)
	if err != nil || id <= 0 {
		fail(c, http.StatusBadRequest, 40105, "模型服务 ID 不合法")
		return
	}
	if err := h.s.DeleteUserModelService(c, uid(c), id); err != nil {
		domain(c, err)
		return
	}
	ok(c, nil)
}

func parseOptionalTime(c *gin.Context, key string) (*time.Time, bool) {
	raw := c.Query(key)
	if raw == "" {
		return nil, true
	}
	value, err := time.Parse(time.RFC3339, raw)
	if err != nil {
		fail(c, http.StatusBadRequest, 40103, key+" 必须为 RFC3339 时间")
		return nil, false
	}
	return &value, true
}

func costQuery(c *gin.Context) (model.CostQuery, bool) {
	from, okv := parseOptionalTime(c, "from")
	if !okv {
		return model.CostQuery{}, false
	}
	to, okv := parseOptionalTime(c, "to")
	if !okv {
		return model.CostQuery{}, false
	}
	return model.CostQuery{
		From:      from,
		To:        to,
		Provider:  c.Query("provider"),
		ModelName: c.Query("model"),
	}, true
}

func (h *GovernanceHandler) UserCostSummary(c *gin.Context) {
	query, okv := costQuery(c)
	if !okv {
		return
	}
	data, err := h.s.CostSummary(c, uid(c), nil, query)
	if err != nil {
		domain(c, err)
		return
	}
	ok(c, data)
}

func (h *GovernanceHandler) ProjectCostSummary(c *gin.Context) {
	pid, okv := projectIDParam(c)
	if !okv {
		return
	}
	query, okv := costQuery(c)
	if !okv {
		return
	}
	data, err := h.s.CostSummary(c, uid(c), &pid, query)
	if err != nil {
		domain(c, err)
		return
	}
	ok(c, data)
}

func (h *GovernanceHandler) RunCost(c *gin.Context) {
	taskID, err := strconv.ParseInt(c.Param("taskId"), 10, 64)
	if err != nil || taskID <= 0 {
		fail(c, http.StatusBadRequest, 40104, "任务 ID 不合法")
		return
	}
	data, err := h.s.RunCost(c, uid(c), taskID)
	if err != nil {
		domain(c, err)
		return
	}
	ok(c, data)
}
