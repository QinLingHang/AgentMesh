package handler

import (
	"net/http"
	"strconv"

	"example.com/agentmesh-control-plane/internal/service"

	"github.com/gin-gonic/gin"
)

type ProjectHandler struct {
	s *service.ProjectService
}

func NewProjectHandler(
	s *service.ProjectService,
) *ProjectHandler {
	return &ProjectHandler{
		s: s,
	}
}

func (h *ProjectHandler) Create(
	c *gin.Context,
) {
	var request struct {
		Name string `json:"name" binding:"required"`

		Description string `json:"description"`
	}

	if c.ShouldBindJSON(
		&request,
	) != nil {
		fail(
			c,
			http.StatusBadRequest,
			40070,
			"项目参数不合法",
		)

		return
	}

	project, err :=
		h.s.Create(
			c,
			uid(
				c,
			),
			request.Name,
			request.Description,
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
			"code": 0,

			"message": "success",

			"data": project,
		},
	)
}

func (h *ProjectHandler) List(
	c *gin.Context,
) {
	projects, err :=
		h.s.List(
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
		projects,
	)
}

func (h *ProjectHandler) Update(
	c *gin.Context,
) {
	projectID, valid :=
		idParam(
			c,
		)

	if !valid {
		return
	}

	var request struct {
		Name string `json:"name" binding:"required"`

		Description string `json:"description"`
	}

	if c.ShouldBindJSON(
		&request,
	) != nil {
		fail(
			c,
			http.StatusBadRequest,
			40071,
			"项目参数不合法",
		)

		return
	}

	project, err :=
		h.s.Update(
			c,
			uid(
				c,
			),
			projectID,
			request.Name,
			request.Description,
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
		project,
	)
}

func (h *ProjectHandler) Delete(
	c *gin.Context,
) {
	projectID, valid :=
		idParam(
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
		projectID,
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

func conversationIDParam(
	c *gin.Context,
) (int64, bool) {
	value, err := strconv.ParseInt(
		c.Param(
			"conversationId",
		),
		10,
		64,
	)

	if err != nil ||
		value <= 0 {
		fail(
			c,
			http.StatusBadRequest,
			40072,
			"会话 ID 不合法",
		)

		return 0,
			false
	}

	return value,
		true
}

func (h *ProjectHandler) AssignConversation(
	c *gin.Context,
) {
	projectID, valid :=
		idParam(
			c,
		)

	if !valid {
		return
	}

	conversationID, valid :=
		conversationIDParam(
			c,
		)

	if !valid {
		return
	}

	if err :=
		h.s.AssignConversation(
			c,
			uid(
				c,
			),
			projectID,
			conversationID,
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

func (h *ProjectHandler) RemoveConversation(
	c *gin.Context,
) {
	conversationID, valid :=
		conversationIDParam(
			c,
		)

	if !valid {
		return
	}

	if err :=
		h.s.RemoveConversation(
			c,
			uid(
				c,
			),
			conversationID,
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
