package router

import "github.com/gin-gonic/gin"

func registerDurableRuntimeRoutes(protected *gin.RouterGroup, deps Dependencies) {
	if deps.DurableRuntimeHandler == nil {
		return
	}
	protected.GET("/runtime/reliability", deps.DurableRuntimeHandler.Reliability)
	protected.GET("/runtime/topology", deps.DurableRuntimeHandler.Topology)
	protected.POST("/tasks/:id/cancel", deps.DurableRuntimeHandler.Cancel)
}

func registerRateLimitedDurableRuntimeRoutes(rateLimited *gin.RouterGroup, deps Dependencies) {
	if deps.DurableRuntimeHandler == nil {
		return
	}
	rateLimited.POST("/tasks/run-durable", deps.DurableRuntimeHandler.Run)
}

func registerInternalDurableRuntimeRoutes(internal *gin.RouterGroup, deps Dependencies) {
	if deps.DurableRuntimeHandler == nil {
		return
	}
	internal.POST("/runtime/workers/heartbeat", deps.DurableRuntimeHandler.Heartbeat)
	internal.POST("/runtime/jobs/:jobId/result", deps.DurableRuntimeHandler.Callback)
}
