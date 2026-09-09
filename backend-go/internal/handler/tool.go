package handler

import (
	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/service"
	"github.com/gin-gonic/gin"
)

type ToolHandler struct{ s *service.ToolService }

func NewToolHandler(s *service.ToolService) *ToolHandler { return &ToolHandler{s} }
func (h *ToolHandler) Create(c *gin.Context) {
	var q model.Tool
	if c.ShouldBindJSON(&q) != nil {
		fail(c, 400, 40050, "invalid tool")
		return
	}
	v, e := h.s.Create(c, uid(c), q)
	if e != nil {
		domain(c, e)
		return
	}
	c.JSON(201, gin.H{"code": 0, "message": "success", "data": v})
}
func (h *ToolHandler) List(c *gin.Context) {
	v, e := h.s.List(c, uid(c), c.Query("enabled") == "true")
	if e != nil {
		domain(c, e)
		return
	}
	ok(c, v)
}
func (h *ToolHandler) Get(c *gin.Context) {
	id, x := idParam(c)
	if !x {
		return
	}
	v, e := h.s.Get(c, uid(c), id)
	if e != nil {
		domain(c, e)
		return
	}
	ok(c, v)
}
func (h *ToolHandler) Update(c *gin.Context) {
	id, x := idParam(c)
	if !x {
		return
	}
	var q model.Tool
	if c.ShouldBindJSON(&q) != nil {
		fail(c, 400, 40050, "invalid tool")
		return
	}
	v, e := h.s.Update(c, uid(c), id, q)
	if e != nil {
		domain(c, e)
		return
	}
	ok(c, v)
}
func (h *ToolHandler) Delete(c *gin.Context) {
	id, x := idParam(c)
	if !x {
		return
	}
	if e := h.s.Delete(c, uid(c), id); e != nil {
		domain(c, e)
		return
	}
	ok(c, nil)
}
func (h *ToolHandler) Seed(c *gin.Context) {
	v, e := h.s.SeedDemo(c, uid(c))
	if e != nil {
		domain(c, e)
		return
	}
	ok(c, v)
}

func (h *ToolHandler) SeedDesktop(c *gin.Context) {
	v, e := h.s.SeedDesktop(c, uid(c))
	if e != nil {
		domain(c, e)
		return
	}
	ok(c, v)
}
