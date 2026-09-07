package router

import "github.com/gin-gonic/gin"

func registerKnowledgeRoutes(
	protected *gin.RouterGroup,
	deps Dependencies,
) {
	protected.GET(
		"/knowledge/bases",
		deps.KnowledgeHandler.ListBases,
	)

	protected.POST(
		"/knowledge/bases",
		deps.KnowledgeHandler.CreateBase,
	)

	protected.PATCH(
		"/knowledge/bases/:knowledgeBaseId",
		deps.KnowledgeHandler.UpdateBase,
	)

	protected.DELETE(
		"/knowledge/bases/:knowledgeBaseId",
		deps.KnowledgeHandler.DeleteBase,
	)

	protected.GET(
		"/knowledge/files",
		deps.KnowledgeHandler.ListAll,
	)

	protected.GET(
		"/knowledge/bases/:knowledgeBaseId/files",
		deps.KnowledgeHandler.ListBaseFiles,
	)

	protected.POST(
		"/knowledge/bases/:knowledgeBaseId/files",
		deps.KnowledgeHandler.UploadBaseFile,
	)

	protected.DELETE(
		"/knowledge/bases/:knowledgeBaseId/files/:fileId",
		deps.KnowledgeHandler.DeleteBaseFile,
	)

	protected.POST(
		"/knowledge/files/:fileId/reindex",
		deps.KnowledgeHandler.ReindexFile,
	)

	// Compatibility / Project Home API: resolves the Project's default PROJECT KB.
	protected.GET(
		"/projects/:id/knowledge/files",
		deps.KnowledgeHandler.ListProjectFiles,
	)

	protected.POST(
		"/projects/:id/knowledge/files",
		deps.KnowledgeHandler.UploadProjectFile,
	)

	protected.DELETE(
		"/projects/:id/knowledge/files/:fileId",
		deps.KnowledgeHandler.DeleteProjectFile,
	)

	protected.GET(
		"/projects/:id/knowledge/global-bindings",
		deps.KnowledgeHandler.ListGlobalBindings,
	)

	protected.PUT(
		"/projects/:id/knowledge/global-bindings/:knowledgeBaseId",
		deps.KnowledgeHandler.BindGlobal,
	)

	protected.DELETE(
		"/projects/:id/knowledge/global-bindings/:knowledgeBaseId",
		deps.KnowledgeHandler.UnbindGlobal,
	)
}
