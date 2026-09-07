package handler

import (
	"errors"
	"io"
	"net/http"
	"strconv"

	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/service"

	"github.com/gin-gonic/gin"
)

type KnowledgeHandler struct {
	s *service.KnowledgeService

	maxUploadBytes int64
}

func NewKnowledgeHandler(
	s *service.KnowledgeService,
	maxUploadBytes int64,
) *KnowledgeHandler {
	return &KnowledgeHandler{
		s: s,

		maxUploadBytes: maxUploadBytes,
	}
}

func knowledgeBaseIDParam(
	c *gin.Context,
) (int64, bool) {
	value, err := strconv.ParseInt(
		c.Param("knowledgeBaseId"),
		10,
		64,
	)
	if err != nil || value <= 0 {
		fail(c, http.StatusBadRequest, 40084, "知识库 ID 不合法")
		return 0, false
	}
	return value, true
}

func knowledgeFileIDParam(
	c *gin.Context,
) (int64, bool) {
	value, err := strconv.ParseInt(
		c.Param("fileId"),
		10,
		64,
	)
	if err != nil || value <= 0 {
		fail(c, http.StatusBadRequest, 40080, "知识文件 ID 不合法")
		return 0, false
	}
	return value, true
}

func (h *KnowledgeHandler) ListBases(
	c *gin.Context,
) {
	bases, err := h.s.ListBases(c, uid(c))
	if err != nil {
		domain(c, err)
		return
	}
	ok(c, bases)
}

func (h *KnowledgeHandler) CreateBase(
	c *gin.Context,
) {
	var request struct {
		Name string `json:"name" binding:"required"`

		Description string `json:"description"`

		Scope model.KnowledgeBaseScope `json:"scope" binding:"required"`

		ProjectID *int64 `json:"projectId"`
	}

	if c.ShouldBindJSON(&request) != nil {
		fail(c, http.StatusBadRequest, 40085, "知识库参数不合法")
		return
	}

	base, err := h.s.CreateBase(
		c,
		uid(c),
		request.Name,
		request.Description,
		request.Scope,
		request.ProjectID,
	)
	if err != nil {
		domain(c, err)
		return
	}

	c.JSON(
		http.StatusCreated,
		gin.H{
			"code":    0,
			"message": "success",
			"data":    base,
		},
	)
}

func (h *KnowledgeHandler) UpdateBase(
	c *gin.Context,
) {
	baseID, valid := knowledgeBaseIDParam(c)
	if !valid {
		return
	}

	var request struct {
		Name string `json:"name" binding:"required"`

		Description string `json:"description"`
	}

	if c.ShouldBindJSON(&request) != nil {
		fail(c, http.StatusBadRequest, 40086, "知识库参数不合法")
		return
	}

	base, err := h.s.UpdateBase(
		c,
		uid(c),
		baseID,
		request.Name,
		request.Description,
	)
	if err != nil {
		domain(c, err)
		return
	}

	ok(c, base)
}

func (h *KnowledgeHandler) DeleteBase(
	c *gin.Context,
) {
	baseID, valid := knowledgeBaseIDParam(c)
	if !valid {
		return
	}

	err := h.s.DeleteBase(c, uid(c), baseID)
	switch {
	case errors.Is(err, service.ErrKnowledgeDefaultBase):
		fail(c, http.StatusConflict, 40921, "默认知识库不能删除")
		return
	case err != nil:
		domain(c, err)
		return
	}

	ok(c, nil)
}

func (h *KnowledgeHandler) ListAll(
	c *gin.Context,
) {
	files, err := h.s.ListAll(c, uid(c))
	if err != nil {
		domain(c, err)
		return
	}
	ok(c, files)
}

func (h *KnowledgeHandler) ListBaseFiles(
	c *gin.Context,
) {
	baseID, valid := knowledgeBaseIDParam(c)
	if !valid {
		return
	}

	files, err := h.s.ListFilesByBase(c, uid(c), baseID)
	if err != nil {
		domain(c, err)
		return
	}
	ok(c, files)
}

func (h *KnowledgeHandler) ListProjectFiles(
	c *gin.Context,
) {
	projectID, valid := idParam(c)
	if !valid {
		return
	}

	files, err := h.s.ListProjectFiles(c, uid(c), projectID)
	if err != nil {
		domain(c, err)
		return
	}
	ok(c, files)
}

func (h *KnowledgeHandler) readUpload(
	c *gin.Context,
) (string, string, func(), io.Reader) {
	c.Request.Body = http.MaxBytesReader(
		c.Writer,
		c.Request.Body,
		h.maxUploadBytes+(1<<20),
	)

	header, err := c.FormFile("file")
	if err != nil {
		fail(c, http.StatusBadRequest, 40081, "请选择要上传的文件")
		return "", "", func() {}, nil
	}
	if header.Size <= 0 {
		fail(c, http.StatusBadRequest, 40082, "不能上传空文件")
		return "", "", func() {}, nil
	}
	if header.Size > h.maxUploadBytes {
		fail(c, http.StatusRequestEntityTooLarge, 41301, "文件大小超过限制")
		return "", "", func() {}, nil
	}

	source, err := header.Open()
	if err != nil {
		fail(c, http.StatusBadRequest, 40083, "无法读取上传文件")
		return "", "", func() {}, nil
	}

	return header.Filename,
		header.Header.Get("Content-Type"),
		func() { _ = source.Close() },
		source
}

func (h *KnowledgeHandler) uploadError(
	c *gin.Context,
	err error,
) bool {
	switch {
	case errors.Is(err, service.ErrKnowledgeUnsupportedType):
		fail(c, http.StatusUnsupportedMediaType, 41501, "暂时只支持 PDF、DOCX、TXT、Markdown")
		return true
	case errors.Is(err, service.ErrKnowledgeTooLarge):
		fail(c, http.StatusRequestEntityTooLarge, 41301, "文件大小超过限制")
		return true
	case err != nil:
		domain(c, err)
		return true
	default:
		return false
	}
}

func (h *KnowledgeHandler) UploadBaseFile(
	c *gin.Context,
) {
	baseID, valid := knowledgeBaseIDParam(c)
	if !valid {
		return
	}

	filename, mediaType, closeSource, rawSource := h.readUpload(c)
	if rawSource == nil {
		return
	}
	defer closeSource()

	source := rawSource

	file, err := h.s.UploadToBase(
		c,
		uid(c),
		baseID,
		filename,
		mediaType,
		source,
	)
	if h.uploadError(c, err) {
		return
	}

	c.JSON(http.StatusCreated, gin.H{"code": 0, "message": "success", "data": file})
}

func (h *KnowledgeHandler) UploadProjectFile(
	c *gin.Context,
) {
	projectID, valid := idParam(c)
	if !valid {
		return
	}

	filename, mediaType, closeSource, rawSource := h.readUpload(c)
	if rawSource == nil {
		return
	}
	defer closeSource()

	source := rawSource

	file, err := h.s.UploadProject(
		c,
		uid(c),
		projectID,
		filename,
		mediaType,
		source,
	)
	if h.uploadError(c, err) {
		return
	}

	c.JSON(http.StatusCreated, gin.H{"code": 0, "message": "success", "data": file})
}

func (h *KnowledgeHandler) DeleteBaseFile(
	c *gin.Context,
) {
	baseID, valid := knowledgeBaseIDParam(c)
	if !valid {
		return
	}
	fileID, valid := knowledgeFileIDParam(c)
	if !valid {
		return
	}

	files, err := h.s.ListFilesByBase(c, uid(c), baseID)
	if err != nil {
		domain(c, err)
		return
	}
	found := false
	for _, file := range files {
		if file.ID == fileID {
			found = true
			break
		}
	}
	if !found {
		domain(c, service.ErrNotFound)
		return
	}

	if err = h.s.DeleteFile(c, uid(c), fileID); err != nil {
		domain(c, err)
		return
	}
	ok(c, nil)
}

func (h *KnowledgeHandler) DeleteProjectFile(
	c *gin.Context,
) {
	projectID, valid := idParam(c)
	if !valid {
		return
	}
	fileID, valid := knowledgeFileIDParam(c)
	if !valid {
		return
	}

	if err := h.s.DeleteProjectFile(c, uid(c), projectID, fileID); err != nil {
		domain(c, err)
		return
	}
	ok(c, nil)
}

func (h *KnowledgeHandler) ListGlobalBindings(
	c *gin.Context,
) {
	projectID, valid := idParam(c)
	if !valid {
		return
	}

	bases, err := h.s.ListGlobalBindings(c, uid(c), projectID)
	if err != nil {
		domain(c, err)
		return
	}
	ok(c, bases)
}

func (h *KnowledgeHandler) BindGlobal(
	c *gin.Context,
) {
	projectID, valid := idParam(c)
	if !valid {
		return
	}
	baseID, valid := knowledgeBaseIDParam(c)
	if !valid {
		return
	}

	if err := h.s.BindGlobal(c, uid(c), projectID, baseID); err != nil {
		domain(c, err)
		return
	}
	ok(c, nil)
}

func (h *KnowledgeHandler) UnbindGlobal(
	c *gin.Context,
) {
	projectID, valid := idParam(c)
	if !valid {
		return
	}
	baseID, valid := knowledgeBaseIDParam(c)
	if !valid {
		return
	}

	if err := h.s.UnbindGlobal(c, uid(c), projectID, baseID); err != nil {
		domain(c, err)
		return
	}
	ok(c, nil)
}

func (h *KnowledgeHandler) ReindexFile(
	c *gin.Context,
) {
	fileID, valid := knowledgeFileIDParam(c)
	if !valid {
		return
	}

	file, err := h.s.ReindexFile(
		c,
		uid(c),
		fileID,
	)
	if err != nil {
		domain(c, err)
		return
	}

	ok(c, file)
}

// ResolveRuntimeScope is an internal Control Plane endpoint used only by the
// Python Runtime. Authentication is enforced by the router's internal token
// middleware, not by the user JWT middleware.
func (h *KnowledgeHandler) ResolveRuntimeScope(
	c *gin.Context,
) {
	userID, err := strconv.ParseInt(
		c.Query("userId"),
		10,
		64,
	)
	if err != nil || userID <= 0 {
		fail(c, http.StatusBadRequest, 40090, "userId 不合法")
		return
	}

	var conversationID *int64
	if raw := c.Query("conversationId"); raw != "" {
		value, parseErr := strconv.ParseInt(raw, 10, 64)
		if parseErr != nil || value <= 0 {
			fail(c, http.StatusBadRequest, 40091, "conversationId 不合法")
			return
		}
		conversationID = &value
	}

	scope, err := h.s.RuntimeScope(
		c,
		userID,
		conversationID,
	)
	if err != nil {
		domain(c, err)
		return
	}

	ok(c, scope)
}
