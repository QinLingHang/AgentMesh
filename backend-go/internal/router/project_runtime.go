package router

import "github.com/gin-gonic/gin"

func registerProjectRuntimeRoutes(
	protected *gin.RouterGroup,
	deps Dependencies,
) {
	protected.GET(
		"/projects/:id/runtime",
		deps.ProjectRuntimeHandler.Get,
	)

	protected.PUT(
		"/projects/:id/runtime",
		deps.ProjectRuntimeHandler.Update,
	)
}
