package router

import "github.com/gin-gonic/gin"

func registerProjectRoutes(
	protected *gin.RouterGroup,
	deps Dependencies,
) {
	protected.POST(
		"/projects",
		deps.ProjectHandler.Create,
	)

	protected.GET(
		"/projects",
		deps.ProjectHandler.List,
	)

	protected.PATCH(
		"/projects/:id",
		deps.ProjectHandler.Update,
	)

	protected.DELETE(
		"/projects/:id",
		deps.ProjectHandler.Delete,
	)

	protected.PUT(
		"/projects/:id/conversations/:conversationId",
		deps.ProjectHandler.AssignConversation,
	)

	protected.DELETE(
		"/projects/conversations/:conversationId",
		deps.ProjectHandler.RemoveConversation,
	)
}
