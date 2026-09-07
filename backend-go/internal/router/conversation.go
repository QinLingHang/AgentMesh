package router

import "github.com/gin-gonic/gin"

func registerConversationRoutes(
	protected *gin.RouterGroup,
	deps Dependencies,
) {
	protected.POST(
		"/conversations",
		deps.ConversationHandler.Create,
	)

	protected.GET(
		"/conversations",
		deps.ConversationHandler.List,
	)

	protected.PATCH(
		"/conversations/:id",
		deps.ConversationHandler.Rename,
	)

	protected.DELETE(
		"/conversations/:id",
		deps.ConversationHandler.Delete,
	)
}
