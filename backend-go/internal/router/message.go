package router

import "github.com/gin-gonic/gin"

func registerMessageRoutes(protected *gin.RouterGroup, deps Dependencies) {
	// Legacy newest-window endpoint remains for backward compatibility.
	protected.GET("/conversations/:id/messages", deps.ConversationHandler.Messages)
	// Cursor history endpoint is used by the Workspace to make every durable
	// message in a long conversation reachable without unbounded payloads.
	protected.GET("/conversations/:id/messages/page", deps.ConversationHandler.MessagePage)
}
