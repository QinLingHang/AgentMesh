package router

import "github.com/gin-gonic/gin"

func registerTaskRoutes(
	protected *gin.RouterGroup,
	deps Dependencies,
) {
	protected.GET(
		"/tasks",
		deps.TaskHandler.List,
	)

	protected.GET(
		"/runtime/plugins",
		deps.TaskHandler.Plugins,
	)
}

func registerRateLimitedTaskRoutes(
	rateLimited *gin.RouterGroup,
	deps Dependencies,
) {
	rateLimited.POST(
		"/tasks/run",
		deps.TaskHandler.Run,
	)

	rateLimited.POST(
		"/tasks/run-stream",
		deps.TaskHandler.RunStream,
	)

	rateLimited.POST(
		"/tasks/:id/resume",
		deps.TaskHandler.Resume,
	)
}
