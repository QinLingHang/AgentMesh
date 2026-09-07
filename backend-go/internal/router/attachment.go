package router

import "github.com/gin-gonic/gin"

func registerAttachmentRoutes(protected *gin.RouterGroup, deps Dependencies) {
	if deps.AttachmentHandler == nil {
		return
	}
	protected.POST("/conversations/:id/attachments", deps.AttachmentHandler.Upload)
	protected.GET("/conversations/:id/attachments", deps.AttachmentHandler.List)
	protected.DELETE("/conversations/:id/attachments/:attachmentId", deps.AttachmentHandler.Delete)
}
