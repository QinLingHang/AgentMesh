package handler

import (
	"net/http"
	"strconv"

	"example.com/agentmesh-control-plane/internal/service"

	"github.com/gin-gonic/gin"
)

type MemoryHandler struct {
	s *service.MemoryService
}

func NewMemoryHandler(
	s *service.MemoryService,
) *MemoryHandler {
	return &MemoryHandler{
		s: s,
	}
}

type createMemoryRequest struct {
	Category string `json:"category" binding:"required"`

	MemoryKey string `json:"memoryKey" binding:"required"`

	Content string `json:"content" binding:"required"`

	SourceType string `json:"sourceType"`

	Confidence *float64 `json:"confidence"`

	Status string `json:"status"`
}

type internalUpsertMemoryRequest struct {
	Category string `json:"category" binding:"required"`

	MemoryKey string `json:"memoryKey" binding:"required"`

	Content string `json:"content" binding:"required"`

	SourceType string `json:"sourceType" binding:"required"`

	Confidence *float64 `json:"confidence"`
}

type updateMemoryRequest struct {
	Category *string `json:"category"`

	MemoryKey *string `json:"memoryKey"`

	Content *string `json:"content"`

	SourceType *string `json:"sourceType"`

	Confidence *float64 `json:"confidence"`

	Status *string `json:"status"`
}

func memoryLimit(
	c *gin.Context,
) (int, bool) {
	value := c.Query(
		"limit",
	)

	if value == "" {
		return 0, true
	}

	limit, err := strconv.Atoi(
		value,
	)

	if err != nil ||
		limit <= 0 {
		fail(
			c,
			http.StatusBadRequest,
			40090,
			"Memory limit 不合法",
		)
		return 0, false
	}

	return limit, true
}

func (h *MemoryHandler) Create(
	c *gin.Context,
) {
	var request createMemoryRequest

	if c.ShouldBindJSON(
		&request,
	) != nil {
		fail(
			c,
			http.StatusBadRequest,
			40091,
			"Memory 参数不合法",
		)
		return
	}

	memory, err := h.s.Create(
		c,
		uid(
			c,
		),
		service.CreateMemoryInput{
			Category:   request.Category,
			MemoryKey:  request.MemoryKey,
			Content:    request.Content,
			SourceType: request.SourceType,
			Confidence: request.Confidence,
			Status:     request.Status,
		},
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
			"data":    memory,
		},
	)
}

func (h *MemoryHandler) List(
	c *gin.Context,
) {
	limit, valid := memoryLimit(
		c,
	)
	if !valid {
		return
	}

	memories, err := h.s.List(
		c,
		uid(
			c,
		),
		service.MemoryListInput{
			Category: c.Query(
				"category",
			),
			Status: c.Query(
				"status",
			),
			Keyword: c.Query(
				"keyword",
			),
			Limit: limit,
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
		memories,
	)
}

func (h *MemoryHandler) Get(
	c *gin.Context,
) {
	id, valid := idParam(
		c,
	)
	if !valid {
		return
	}

	memory, err := h.s.Get(
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
		memory,
	)
}

func (h *MemoryHandler) Update(
	c *gin.Context,
) {
	id, valid := idParam(
		c,
	)
	if !valid {
		return
	}

	var request updateMemoryRequest
	if c.ShouldBindJSON(
		&request,
	) != nil {
		fail(
			c,
			http.StatusBadRequest,
			40092,
			"Memory 参数不合法",
		)
		return
	}

	memory, err := h.s.Update(
		c,
		uid(
			c,
		),
		id,
		service.UpdateMemoryInput{
			Category:   request.Category,
			MemoryKey:  request.MemoryKey,
			Content:    request.Content,
			SourceType: request.SourceType,
			Confidence: request.Confidence,
			Status:     request.Status,
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
		memory,
	)
}

func (h *MemoryHandler) Delete(
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

func (h *MemoryHandler) InternalListActive(
	c *gin.Context,
) {
	userID, err := strconv.ParseInt(
		c.Param(
			"userId",
		),
		10,
		64,
	)

	if err != nil ||
		userID <= 0 {
		fail(
			c,
			http.StatusBadRequest,
			40093,
			"User ID 不合法",
		)
		return
	}

	limit, valid := memoryLimit(
		c,
	)
	if !valid {
		return
	}

	memories, err := h.s.ListActiveForUser(
		c,
		userID,
		limit,
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
		memories,
	)
}

// InternalUpsert is used only by the trusted Python Runtime after memory write policy has
// extracted a durable candidate from the direct user message. The internal
// token middleware protects the route; user_id remains explicit so persistence
// stays inside the Go ownership boundary rather than allowing Python to query
// MySQL directly.
func (h *MemoryHandler) InternalUpsert(
	c *gin.Context,
) {
	userID, err := strconv.ParseInt(
		c.Param("userId"),
		10,
		64,
	)
	if err != nil || userID <= 0 {
		fail(
			c,
			http.StatusBadRequest,
			40094,
			"User ID 不合法",
		)
		return
	}

	var request internalUpsertMemoryRequest
	if c.ShouldBindJSON(&request) != nil {
		fail(
			c,
			http.StatusBadRequest,
			40095,
			"Automatic Memory 参数不合法",
		)
		return
	}

	result, err := h.s.UpsertAutomatic(
		c,
		userID,
		service.CreateMemoryInput{
			Category:   request.Category,
			MemoryKey:  request.MemoryKey,
			Content:    request.Content,
			SourceType: request.SourceType,
			Confidence: request.Confidence,
			Status:     "active",
		},
	)
	if err != nil {
		domain(c, err)
		return
	}

	ok(c, result)
}

// InternalDelete is used by the trusted Python Runtime for explicit user
// "forget" requests. The internal token authenticates Runtime, while the
// service still deletes by both user_id and memory_id so ownership remains
// enforced by Go rather than delegated to Python.
func (h *MemoryHandler) InternalDelete(c *gin.Context) {
	userID, err := strconv.ParseInt(c.Param("userId"), 10, 64)
	if err != nil || userID <= 0 {
		fail(c, http.StatusBadRequest, 40096, "User ID 不合法")
		return
	}

	memoryID, err := strconv.ParseInt(c.Param("id"), 10, 64)
	if err != nil || memoryID <= 0 {
		fail(c, http.StatusBadRequest, 40097, "Memory ID 不合法")
		return
	}

	if err := h.s.Delete(c, userID, memoryID); err != nil {
		domain(c, err)
		return
	}

	ok(c, nil)
}
