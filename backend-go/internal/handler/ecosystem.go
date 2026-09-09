package handler

import (
	"errors"
	"net/http"
	"strconv"
	"strings"
	"time"

	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/service"
	"github.com/gin-gonic/gin"
)

type EcosystemHandler struct {
	s *service.EcosystemService
}

func NewEcosystemHandler(s *service.EcosystemService) *EcosystemHandler {
	return &EcosystemHandler{s: s}
}

func ecosystemProjectID(c *gin.Context) (int64, bool) {
	value, err := strconv.ParseInt(c.Param("id"), 10, 64)
	if err != nil || value <= 0 {
		fail(c, http.StatusBadRequest, 40200, "项目 ID 不合法")
		return 0, false
	}
	return value, true
}

func ecosystemPositiveParam(c *gin.Context, name string, code int, message string) (int64, bool) {
	value, err := strconv.ParseInt(c.Param(name), 10, 64)
	if err != nil || value <= 0 {
		fail(c, http.StatusBadRequest, code, message)
		return 0, false
	}
	return value, true
}

func (h *EcosystemHandler) Overview(c *gin.Context) {
	data, err := h.s.EcosystemOverview(c)
	if err != nil {
		domain(c, err)
		return
	}
	ok(c, data)
}

func (h *EcosystemHandler) SearchPackages(c *gin.Context) {
	limit, _ := strconv.Atoi(c.DefaultQuery("limit", "50"))
	items, err := h.s.SearchPackagesForUser(c, uid(c), c.Query("q"), c.Query("kind"), limit)
	if err != nil {
		domain(c, err)
		return
	}
	ok(c, items)
}

func (h *EcosystemHandler) PackageDetail(c *gin.Context) {
	item, err := h.s.PackageDetail(c, uid(c), c.Param("slug"))
	if err != nil {
		domain(c, err)
		return
	}
	ok(c, item)
}

func (h *EcosystemHandler) CreatePackage(c *gin.Context) {
	var req service.CreatePackageInput
	if c.ShouldBindJSON(&req) != nil {
		fail(c, http.StatusBadRequest, 40201, "生态包参数不合法")
		return
	}
	item, err := h.s.CreatePackage(c, uid(c), req)
	if err != nil {
		domain(c, err)
		return
	}
	c.JSON(http.StatusCreated, gin.H{"code": 0, "message": "success", "data": item})
}

func (h *EcosystemHandler) AddPackageVersion(c *gin.Context) {
	var req struct {
		Version  string                         `json:"version" binding:"required"`
		Manifest model.EcosystemPackageManifest `json:"manifest" binding:"required"`
	}
	if c.ShouldBindJSON(&req) != nil {
		fail(c, http.StatusBadRequest, 40202, "版本参数不合法")
		return
	}
	item, err := h.s.AddPackageVersion(c, uid(c), c.Param("slug"), req.Version, req.Manifest)
	if err != nil {
		domain(c, err)
		return
	}
	c.JSON(http.StatusCreated, gin.H{"code": 0, "message": "success", "data": item})
}

func (h *EcosystemHandler) PublishPackage(c *gin.Context) {
	var req struct {
		Version string `json:"version" binding:"required"`
	}
	if c.ShouldBindJSON(&req) != nil {
		fail(c, http.StatusBadRequest, 40203, "发布版本不合法")
		return
	}
	item, err := h.s.PublishPackage(c, uid(c), c.Param("slug"), req.Version)
	if err != nil {
		domain(c, err)
		return
	}
	ok(c, item)
}

func (h *EcosystemHandler) ValidatePackage(c *gin.Context) {
	var req struct {
		Kind     string                         `json:"kind" binding:"required"`
		Manifest model.EcosystemPackageManifest `json:"manifest" binding:"required"`
	}
	if c.ShouldBindJSON(&req) != nil {
		fail(c, http.StatusBadRequest, 40204, "包校验参数不合法")
		return
	}
	data, err := h.s.DescribePackageValidation(req.Kind, req.Manifest)
	if err != nil {
		domain(c, err)
		return
	}
	ok(c, data)
}

func (h *EcosystemHandler) ExportPackage(c *gin.Context) {
	bundle, err := h.s.ExportPackage(c, uid(c), c.Param("slug"), c.Query("version"))
	if err != nil {
		domain(c, err)
		return
	}
	ok(c, bundle)
}

func (h *EcosystemHandler) ImportPackage(c *gin.Context) {
	var bundle model.EcosystemPackageBundle
	if c.ShouldBindJSON(&bundle) != nil {
		fail(c, http.StatusBadRequest, 40205, "导入包格式不合法")
		return
	}
	item, err := h.s.ImportPackage(c, uid(c), bundle)
	if err != nil {
		domain(c, err)
		return
	}
	c.JSON(http.StatusCreated, gin.H{"code": 0, "message": "success", "data": item})
}

func (h *EcosystemHandler) ListInstallations(c *gin.Context) {
	projectID, valid := ecosystemProjectID(c)
	if !valid {
		return
	}
	items, err := h.s.ListInstallations(c, uid(c), projectID)
	if err != nil {
		domain(c, err)
		return
	}
	ok(c, items)
}

func (h *EcosystemHandler) InstallPackage(c *gin.Context) {
	projectID, valid := ecosystemProjectID(c)
	if !valid {
		return
	}
	var req struct {
		Slug    string         `json:"slug" binding:"required"`
		Version string         `json:"version"`
		Config  map[string]any `json:"config"`
	}
	if c.ShouldBindJSON(&req) != nil {
		fail(c, http.StatusBadRequest, 40206, "安装参数不合法")
		return
	}
	item, err := h.s.InstallPackage(c, uid(c), projectID, req.Slug, req.Version, req.Config)
	if err != nil {
		domain(c, err)
		return
	}
	c.JSON(http.StatusCreated, gin.H{"code": 0, "message": "success", "data": item})
}

func (h *EcosystemHandler) SetInstallationEnabled(c *gin.Context) {
	projectID, valid := ecosystemProjectID(c)
	if !valid {
		return
	}
	installationID, valid := ecosystemPositiveParam(c, "installationId", 40207, "安装记录 ID 不合法")
	if !valid {
		return
	}
	var req struct {
		Enabled *bool `json:"enabled" binding:"required"`
	}
	if c.ShouldBindJSON(&req) != nil || req.Enabled == nil {
		fail(c, http.StatusBadRequest, 40208, "启用状态不合法")
		return
	}
	item, err := h.s.SetInstallationEnabled(c, uid(c), projectID, installationID, *req.Enabled)
	if err != nil {
		domain(c, err)
		return
	}
	ok(c, item)
}

func (h *EcosystemHandler) DeleteInstallation(c *gin.Context) {
	projectID, valid := ecosystemProjectID(c)
	if !valid {
		return
	}
	installationID, valid := ecosystemPositiveParam(c, "installationId", 40209, "安装记录 ID 不合法")
	if !valid {
		return
	}
	if err := h.s.DeleteInstallation(c, uid(c), projectID, installationID); err != nil {
		domain(c, err)
		return
	}
	ok(c, nil)
}

func (h *EcosystemHandler) ListServiceAccounts(c *gin.Context) {
	projectID, valid := ecosystemProjectID(c)
	if !valid {
		return
	}
	items, err := h.s.ListServiceAccounts(c, uid(c), projectID)
	if err != nil {
		domain(c, err)
		return
	}
	ok(c, items)
}

func (h *EcosystemHandler) CreateServiceAccount(c *gin.Context) {
	projectID, valid := ecosystemProjectID(c)
	if !valid {
		return
	}
	var req struct {
		Name      string     `json:"name" binding:"required"`
		Scopes    []string   `json:"scopes" binding:"required"`
		ExpiresAt *time.Time `json:"expiresAt"`
	}
	if c.ShouldBindJSON(&req) != nil {
		fail(c, http.StatusBadRequest, 40210, "服务账号参数不合法")
		return
	}
	item, err := h.s.CreateServiceAccount(c, uid(c), projectID, req.Name, req.Scopes, req.ExpiresAt)
	if err != nil {
		domain(c, err)
		return
	}
	c.JSON(http.StatusCreated, gin.H{"code": 0, "message": "API Key 仅本次返回，请立即安全保存", "data": item})
}

func (h *EcosystemHandler) RevokeServiceAccount(c *gin.Context) {
	projectID, valid := ecosystemProjectID(c)
	if !valid {
		return
	}
	accountID, valid := ecosystemPositiveParam(c, "serviceAccountId", 40211, "服务账号 ID 不合法")
	if !valid {
		return
	}
	if err := h.s.RevokeServiceAccount(c, uid(c), projectID, accountID); err != nil {
		domain(c, err)
		return
	}
	ok(c, nil)
}

type PublicAPIHandler struct {
	s *service.EcosystemService
}

func NewPublicAPIHandler(s *service.EcosystemService) *PublicAPIHandler {
	return &PublicAPIHandler{s: s}
}

func publicAPIKey(c *gin.Context) string {
	if value := strings.TrimSpace(c.GetHeader("X-AgentMesh-Key")); value != "" {
		return value
	}
	authorization := strings.TrimSpace(c.GetHeader("Authorization"))
	if len(authorization) > 7 && strings.EqualFold(authorization[:7], "Bearer ") {
		return strings.TrimSpace(authorization[7:])
	}
	return ""
}

func publicFail(c *gin.Context, err error) {
	switch {
	case errors.Is(err, service.ErrAPIKeyInvalid):
		fail(c, http.StatusUnauthorized, 40140, "API Key 无效、已过期或已撤销")
	case errors.Is(err, service.ErrAPIScopeDenied):
		fail(c, http.StatusForbidden, 40340, "当前服务账号缺少所需 API Scope")
	case errors.Is(err, service.ErrIdempotencyConflict):
		fail(c, http.StatusConflict, 40940, "Idempotency-Key 已被其他请求占用或请求内容不一致")
	default:
		domain(c, err)
	}
}

func (h *PublicAPIHandler) authenticate(c *gin.Context) (*model.APIPrincipal, bool) {
	principal, err := h.s.AuthenticateServiceAccount(c, publicAPIKey(c))
	if err != nil {
		publicFail(c, err)
		return nil, false
	}
	return principal, true
}

func (h *PublicAPIHandler) RunTask(c *gin.Context) {
	started := time.Now()
	principal, valid := h.authenticate(c)
	if !valid {
		return
	}
	statusCode := http.StatusOK
	defer func() {
		h.s.RecordAPIUsage(c, principal, statusCode, time.Since(started).Milliseconds())
	}()

	var req service.PublicRunInput
	if c.ShouldBindJSON(&req) != nil {
		statusCode = http.StatusBadRequest
		fail(c, statusCode, 40040, "Task 参数不合法")
		return
	}
	result, replay, err := h.s.RunPublicTask(c, principal, req, c.GetHeader("Idempotency-Key"))
	if err != nil {
		switch {
		case errors.Is(err, service.ErrAPIScopeDenied):
			statusCode = http.StatusForbidden
		case errors.Is(err, service.ErrIdempotencyConflict), errors.Is(err, service.ErrConflict):
			statusCode = http.StatusConflict
		case errors.Is(err, service.ErrInvalidInput):
			statusCode = http.StatusBadRequest
		case errors.Is(err, service.ErrNotFound):
			statusCode = http.StatusNotFound
		default:
			statusCode = http.StatusInternalServerError
		}
		publicFail(c, err)
		return
	}
	if replay {
		c.Header("X-Idempotent-Replay", "true")
	}
	ok(c, result)
}

func (h *PublicAPIHandler) Task(c *gin.Context) {
	started := time.Now()
	principal, valid := h.authenticate(c)
	if !valid {
		return
	}
	statusCode := http.StatusOK
	defer func() {
		h.s.RecordAPIUsage(c, principal, statusCode, time.Since(started).Milliseconds())
	}()
	taskID, err := strconv.ParseInt(c.Param("id"), 10, 64)
	if err != nil || taskID <= 0 {
		statusCode = http.StatusBadRequest
		fail(c, statusCode, 40042, "任务 ID 不合法")
		return
	}
	item, err := h.s.PublicTask(c, principal, taskID)
	if err != nil {
		if errors.Is(err, service.ErrAPIScopeDenied) {
			statusCode = http.StatusForbidden
		} else if errors.Is(err, service.ErrNotFound) {
			statusCode = http.StatusNotFound
		} else {
			statusCode = http.StatusInternalServerError
		}
		publicFail(c, err)
		return
	}
	ok(c, item)
}

func (h *PublicAPIHandler) Marketplace(c *gin.Context) {
	started := time.Now()
	principal, valid := h.authenticate(c)
	if !valid {
		return
	}
	statusCode := http.StatusOK
	defer func() {
		h.s.RecordAPIUsage(c, principal, statusCode, time.Since(started).Milliseconds())
	}()
	limit, _ := strconv.Atoi(c.DefaultQuery("limit", "50"))
	items, err := h.s.PublicMarketplaceForPrincipal(c, principal, c.Query("q"), c.Query("kind"), limit)
	if err != nil {
		if errors.Is(err, service.ErrAPIScopeDenied) {
			statusCode = http.StatusForbidden
		} else {
			statusCode = http.StatusInternalServerError
		}
		publicFail(c, err)
		return
	}
	ok(c, items)
}

func (h *PublicAPIHandler) Package(c *gin.Context) {
	started := time.Now()
	principal, valid := h.authenticate(c)
	if !valid {
		return
	}
	statusCode := http.StatusOK
	defer func() {
		h.s.RecordAPIUsage(c, principal, statusCode, time.Since(started).Milliseconds())
	}()
	item, err := h.s.PublicPackageForPrincipal(c, principal, c.Param("slug"))
	if err != nil {
		if errors.Is(err, service.ErrAPIScopeDenied) {
			statusCode = http.StatusForbidden
		} else if errors.Is(err, service.ErrNotFound) {
			statusCode = http.StatusNotFound
		} else {
			statusCode = http.StatusInternalServerError
		}
		publicFail(c, err)
		return
	}
	ok(c, item)
}
