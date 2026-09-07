package router

import "github.com/gin-gonic/gin"

func registerMCPServerRoutes(g *gin.RouterGroup, d Dependencies) {
	g.POST("/mcp-servers", d.MCPServerHandler.Create)
	g.GET("/mcp-servers", d.MCPServerHandler.List)
	g.POST("/mcp-servers/seed-demo", d.MCPServerHandler.Seed)
	g.GET("/mcp-servers/:id", d.MCPServerHandler.Get)
	g.PATCH("/mcp-servers/:id", d.MCPServerHandler.Update)
	g.DELETE("/mcp-servers/:id", d.MCPServerHandler.Delete)
	g.POST("/mcp-servers/:id/discover", d.MCPServerHandler.Discover)
}
