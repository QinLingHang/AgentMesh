package handler

import (
	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/service"
	"github.com/gin-gonic/gin"
)

type MCPServerHandler struct{ s *service.MCPServerService }

func NewMCPServerHandler(s *service.MCPServerService) *MCPServerHandler { return &MCPServerHandler{s} }
func (h *MCPServerHandler) Create(c *gin.Context) {
	var q model.MCPServer
	if c.ShouldBindJSON(&q) != nil {
		fail(c, 400, 40060, "invalid MCP server")
		return
	}
	v, e := h.s.Create(c, uid(c), q)
	if e != nil {
		domain(c, e)
		return
	}
	c.JSON(201, gin.H{"code": 0, "message": "success", "data": v})
}
func (h *MCPServerHandler) List(c *gin.Context) {
	v, e := h.s.List(c, uid(c), c.Query("enabled") == "true")
	if e != nil {
		domain(c, e)
		return
	}
	ok(c, v)
}
func (h *MCPServerHandler) Get(c *gin.Context) {
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
func (h *MCPServerHandler) Update(c *gin.Context) {
	id, x := idParam(c)
	if !x {
		return
	}
	var q model.MCPServer
	if c.ShouldBindJSON(&q) != nil {
		fail(c, 400, 40060, "invalid MCP server")
		return
	}
	v, e := h.s.Update(c, uid(c), id, q)
	if e != nil {
		domain(c, e)
		return
	}
	ok(c, v)
}
func (h *MCPServerHandler) Delete(c *gin.Context) {
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
func (h *MCPServerHandler) Discover(c *gin.Context) {
	id, x := idParam(c)
	if !x {
		return
	}
	v, e := h.s.Discover(c, uid(c), id)
	if e != nil {
		domain(c, e)
		return
	}
	ok(c, v)
}
func (h *MCPServerHandler) Seed(c *gin.Context) {
	v, e := h.s.SeedDemo(c, uid(c))
	if e != nil {
		domain(c, e)
		return
	}
	ok(c, v)
}
