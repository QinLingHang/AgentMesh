package router

import "github.com/gin-gonic/gin"

func registerEcosystemRoutes(protected *gin.RouterGroup, deps Dependencies) {
	if deps.EcosystemHandler == nil {
		return
	}

	protected.GET("/ecosystem/overview", deps.EcosystemHandler.Overview)
	protected.GET("/ecosystem/marketplace", deps.EcosystemHandler.SearchPackages)
	protected.GET("/ecosystem/packages/:slug", deps.EcosystemHandler.PackageDetail)
	protected.POST("/ecosystem/packages", deps.EcosystemHandler.CreatePackage)
	protected.POST("/ecosystem/packages/validate", deps.EcosystemHandler.ValidatePackage)
	protected.POST("/ecosystem/packages/:slug/versions", deps.EcosystemHandler.AddPackageVersion)
	protected.POST("/ecosystem/packages/:slug/publish", deps.EcosystemHandler.PublishPackage)
	protected.GET("/ecosystem/packages/:slug/export", deps.EcosystemHandler.ExportPackage)
	protected.POST("/ecosystem/import", deps.EcosystemHandler.ImportPackage)

	protected.GET("/projects/:id/ecosystem/installations", deps.EcosystemHandler.ListInstallations)
	protected.POST("/projects/:id/ecosystem/installations", deps.EcosystemHandler.InstallPackage)
	protected.PATCH("/projects/:id/ecosystem/installations/:installationId", deps.EcosystemHandler.SetInstallationEnabled)
	protected.DELETE("/projects/:id/ecosystem/installations/:installationId", deps.EcosystemHandler.DeleteInstallation)

	protected.GET("/projects/:id/service-accounts", deps.EcosystemHandler.ListServiceAccounts)
	protected.POST("/projects/:id/service-accounts", deps.EcosystemHandler.CreateServiceAccount)
	protected.DELETE("/projects/:id/service-accounts/:serviceAccountId", deps.EcosystemHandler.RevokeServiceAccount)
}

func registerPublicAPIRoutes(r *gin.Engine, deps Dependencies) {
	if deps.PublicAPIHandler == nil {
		return
	}
	public := r.Group("/openapi/v1")
	public.POST("/tasks/run", deps.PublicAPIHandler.RunTask)
	public.GET("/tasks/:id", deps.PublicAPIHandler.Task)
	public.GET("/marketplace", deps.PublicAPIHandler.Marketplace)
	public.GET("/marketplace/:slug", deps.PublicAPIHandler.Package)
}
