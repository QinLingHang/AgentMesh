package router

import "github.com/gin-gonic/gin"

func registerMemoryRoutes(
	group *gin.RouterGroup,
	dependencies Dependencies,
) {
	group.POST(
		"/memories",
		dependencies.MemoryHandler.Create,
	)

	group.GET(
		"/memories",
		dependencies.MemoryHandler.List,
	)

	group.GET(
		"/memories/:id",
		dependencies.MemoryHandler.Get,
	)

	group.PATCH(
		"/memories/:id",
		dependencies.MemoryHandler.Update,
	)

	group.DELETE(
		"/memories/:id",
		dependencies.MemoryHandler.Delete,
	)
}
