package router

import "github.com/gin-gonic/gin"

func registerMessageRoutes(protected *gin.RouterGroup, deps Dependencies) {
	protected.GET("/conversations/:id/messages", deps.ConversationHandler.Messages)
}
