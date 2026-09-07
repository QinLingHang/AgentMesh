package router

import "github.com/gin-gonic/gin"

func registerAgentRoutes(protected *gin.RouterGroup, deps Dependencies) {
	protected.POST("/agents", deps.AgentHandler.Create)
	protected.GET("/agents", deps.AgentHandler.List)
	protected.DELETE("/agents/:id", deps.AgentHandler.Delete)
	protected.POST("/agents/seed-demo", deps.AgentHandler.Seed)
}
