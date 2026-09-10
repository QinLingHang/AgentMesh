package handler

import (
	"net/http"
	"strconv"
	"strings"

	"example.com/agentmesh-control-plane/internal/model"

	"github.com/gin-gonic/gin"
)

func parsePositivePathInt64(c *gin.Context, name string, code int) (int64, bool) {
	value, err := strconv.ParseInt(strings.TrimSpace(c.Param(name)), 10, 64)
	if err != nil || value <= 0 {
		fail(c, http.StatusBadRequest, code, "参数不合法")
		return 0, false
	}
	return value, true
}

func (h *ConversationHandler) InternalMemoryCapsules(c *gin.Context) {
	userID, ok := parsePositivePathInt64(c, "userId", 40120)
	if !ok {
		return
	}
	conversationID, ok := parsePositivePathInt64(c, "conversationId", 40121)
	if !ok {
		return
	}

	limit := 80
	if raw := strings.TrimSpace(c.Query("limit")); raw != "" {
		parsed, err := strconv.Atoi(raw)
		if err != nil || parsed <= 0 || parsed > 200 {
			fail(c, http.StatusBadRequest, 40122, "Memory Capsule limit 不合法")
			return
		}
		limit = parsed
	}

	items, err := h.s.MemoryCapsules(c, userID, conversationID, limit)
	if err != nil {
		domain(c, err)
		return
	}
	okResponse(c, items)
}

func (h *ConversationHandler) InternalUpsertMemoryCapsule(c *gin.Context) {
	userID, ok := parsePositivePathInt64(c, "userId", 40123)
	if !ok {
		return
	}
	conversationID, ok := parsePositivePathInt64(c, "conversationId", 40124)
	if !ok {
		return
	}

	var input model.ConversationMemoryCapsuleWrite
	if c.ShouldBindJSON(&input) != nil {
		fail(c, http.StatusBadRequest, 40125, "Memory Capsule 参数不合法")
		return
	}

	item, err := h.s.UpsertMemoryCapsule(c, userID, conversationID, input)
	if err != nil {
		domain(c, err)
		return
	}
	okResponse(c, item)
}

func (h *ConversationHandler) InternalCompactionWindow(c *gin.Context) {
	userID, ok := parsePositivePathInt64(c, "userId", 40126)
	if !ok {
		return
	}
	conversationID, ok := parsePositivePathInt64(c, "conversationId", 40127)
	if !ok {
		return
	}

	parse := func(name string, defaultValue int, minValue int, maxValue int) (int, bool) {
		raw := strings.TrimSpace(c.Query(name))
		if raw == "" {
			return defaultValue, true
		}
		value, err := strconv.Atoi(raw)
		if err != nil || value < minValue || value > maxValue {
			fail(c, http.StatusBadRequest, 40128, "Memory compaction 参数不合法")
			return 0, false
		}
		return value, true
	}

	afterID := int64(0)
	if raw := strings.TrimSpace(c.Query("afterId")); raw != "" {
		parsed, err := strconv.ParseInt(raw, 10, 64)
		if err != nil || parsed < 0 {
			fail(c, http.StatusBadRequest, 40129, "Memory compaction cursor 不合法")
			return
		}
		afterID = parsed
	}
	minMessages, ok := parse("minMessages", 12, 4, 40)
	if !ok {
		return
	}
	maxMessages, ok := parse("maxMessages", 18, 4, 40)
	if !ok {
		return
	}
	reserveRecent, ok := parse("reserveRecent", 8, 4, 40)
	if !ok {
		return
	}

	window, err := h.s.CompactionWindow(
		c,
		userID,
		conversationID,
		afterID,
		minMessages,
		maxMessages,
		reserveRecent,
	)
	if err != nil {
		domain(c, err)
		return
	}
	okResponse(c, window)
}

// okResponse is kept local to this file to avoid changing the long-standing
// public handler helper names while making internal memory handlers explicit.
func okResponse(c *gin.Context, data any) {
	ok(c, data)
}
