package handler

import (
	"net/http"

	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/service"

	"github.com/gin-gonic/gin"
)

type ProjectRuntimeHandler struct {
	s *service.ProjectRuntimeService
}

func NewProjectRuntimeHandler(
	s *service.ProjectRuntimeService,
) *ProjectRuntimeHandler {
	return &ProjectRuntimeHandler{s: s}
}

func (h *ProjectRuntimeHandler) Get(
	c *gin.Context,
) {
	projectID, okID := idParam(c)
	if !okID {
		return
	}

	config, err := h.s.Get(
		c,
		uid(c),
		projectID,
	)
	if err != nil {
		domain(c, err)
		return
	}

	ok(c, config)
}

func (h *ProjectRuntimeHandler) Update(
	c *gin.Context,
) {
	projectID, okID := idParam(c)
	if !okID {
		return
	}

	var config model.ProjectRuntimeConfig
	if c.ShouldBindJSON(&config) != nil {
		fail(
			c,
			http.StatusBadRequest,
			40091,
			"项目 Runtime 配置不合法",
		)
		return
	}

	updated, err := h.s.Update(
		c,
		uid(c),
		projectID,
		config,
	)
	if err != nil {
		domain(c, err)
		return
	}

	ok(c, updated)
}
