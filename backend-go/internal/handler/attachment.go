package handler

import (
	"errors"
	"net/http"
	"strconv"

	"example.com/agentmesh-control-plane/internal/service"
	"github.com/gin-gonic/gin"
)

type AttachmentHandler struct {
	s *service.AttachmentService
}

func NewAttachmentHandler(s *service.AttachmentService) *AttachmentHandler {
	return &AttachmentHandler{s: s}
}

func attachmentConversationIDParam(c *gin.Context) (int64, bool) {
	value, err := strconv.ParseInt(c.Param("id"), 10, 64)
	if err != nil || value <= 0 {
		fail(c, http.StatusBadRequest, 40091, "\u4f1a\u8bdd ID \u4e0d\u5408\u6cd5")
		return 0, false
	}
	return value, true
}

func attachmentIDParam(c *gin.Context) (int64, bool) {
	value, err := strconv.ParseInt(c.Param("attachmentId"), 10, 64)
	if err != nil || value <= 0 {
		fail(c, http.StatusBadRequest, 40092, "\u9644\u4ef6 ID \u4e0d\u5408\u6cd5")
		return 0, false
	}
	return value, true
}

func (h *AttachmentHandler) Upload(c *gin.Context) {
	conversationID, okID := attachmentConversationIDParam(c)
	if !okID {
		return
	}

	c.Request.Body = http.MaxBytesReader(
		c.Writer,
		c.Request.Body,
		h.s.MaxUploadBytes()+(1<<20),
	)

	header, err := c.FormFile("file")
	if err != nil {
		fail(c, http.StatusBadRequest, 40093, "\u8bf7\u9009\u62e9\u8981\u4e0a\u4f20\u7684\u6587\u4ef6")
		return
	}

	if header.Size <= 0 {
		fail(c, http.StatusBadRequest, 40094, "\u4e0d\u80fd\u4e0a\u4f20\u7a7a\u6587\u4ef6")
		return
	}

	if header.Size > h.s.MaxUploadBytes() {
		fail(c, http.StatusRequestEntityTooLarge, 41311, "\u9644\u4ef6\u5927\u5c0f\u8d85\u8fc7 10 MB \u9650\u5236")
		return
	}

	source, err := header.Open()
	if err != nil {
		fail(c, http.StatusBadRequest, 40095, "\u65e0\u6cd5\u8bfb\u53d6\u4e0a\u4f20\u6587\u4ef6")
		return
	}
	defer source.Close()

	item, err := h.s.Upload(
		c,
		uid(c),
		conversationID,
		header.Filename,
		header.Header.Get("Content-Type"),
		source,
	)

	switch {
	case errors.Is(err, service.ErrAttachmentUnsupportedType):
		fail(
			c,
			http.StatusUnsupportedMediaType,
			41511,
			"\u652f\u6301 PNG\u3001JPG\u3001WebP\u3001PDF\u3001DOCX\u3001TXT\u3001Markdown\u3001CSV\u3001JSON",
		)
	case errors.Is(err, service.ErrAttachmentTooLarge):
		fail(c, http.StatusRequestEntityTooLarge, 41311, "\u9644\u4ef6\u5927\u5c0f\u8d85\u8fc7\u9650\u5236")
	case err != nil:
		domain(c, err)
	default:
		c.JSON(
			http.StatusCreated,
			gin.H{
				"code":    0,
				"message": "success",
				"data":    item,
			},
		)
	}
}

func (h *AttachmentHandler) List(c *gin.Context) {
	conversationID, okID := attachmentConversationIDParam(c)
	if !okID {
		return
	}

	items, err := h.s.List(c, uid(c), conversationID)
	if err != nil {
		domain(c, err)
		return
	}

	ok(c, items)
}

func (h *AttachmentHandler) Delete(c *gin.Context) {
	conversationID, okID := attachmentConversationIDParam(c)
	if !okID {
		return
	}

	attachmentID, okAttachment := attachmentIDParam(c)
	if !okAttachment {
		return
	}

	if err := h.s.Delete(
		c,
		uid(c),
		conversationID,
		attachmentID,
	); err != nil {
		domain(c, err)
		return
	}

	ok(c, nil)
}
