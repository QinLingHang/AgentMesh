package router

import "github.com/gin-gonic/gin"

func registerToolRoutes(g *gin.RouterGroup, d Dependencies) {
	g.POST("/tools", d.ToolHandler.Create)
	g.GET("/tools", d.ToolHandler.List)
	g.GET("/tools/:id", d.ToolHandler.Get)
	g.PATCH("/tools/:id", d.ToolHandler.Update)
	g.DELETE("/tools/:id", d.ToolHandler.Delete)
	g.POST("/tools/seed-demo", d.ToolHandler.Seed)
	g.POST("/tools/seed-desktop", d.ToolHandler.SeedDesktop)
}
