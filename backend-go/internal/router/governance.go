package router

import "github.com/gin-gonic/gin"

func registerGovernanceRoutes(protected *gin.RouterGroup, deps Dependencies) {
	if deps.GovernanceHandler == nil {
		return
	}
	protected.GET("/me/model-provider", deps.GovernanceHandler.GetUserModelProvider)
	protected.PUT("/me/model-provider", deps.GovernanceHandler.UpsertUserModelProvider)
	protected.DELETE("/me/model-provider", deps.GovernanceHandler.DeleteUserModelProvider)
	protected.GET("/costs/summary", deps.GovernanceHandler.UserCostSummary)
	protected.GET("/tasks/:taskId/cost", deps.GovernanceHandler.RunCost)
	protected.GET("/projects/:id/governance", deps.GovernanceHandler.Overview)
	protected.GET("/projects/:id/costs", deps.GovernanceHandler.ProjectCostSummary)
	protected.POST("/projects/:id/members", deps.GovernanceHandler.AddMember)
	protected.DELETE("/projects/:id/members/:userId", deps.GovernanceHandler.RemoveMember)
	protected.PUT("/projects/:id/quota", deps.GovernanceHandler.UpdateQuota)
	protected.POST("/projects/:id/secrets", deps.GovernanceHandler.CreateSecret)
	protected.DELETE("/projects/:id/secrets/:secretId", deps.GovernanceHandler.DeleteSecret)
	protected.PUT("/projects/:id/model-provider", deps.GovernanceHandler.UpsertProvider)
	protected.GET("/projects/:id/audit", deps.GovernanceHandler.Audit)
	protected.GET("/organizations", deps.GovernanceHandler.ListOrganizations)
	protected.POST("/organizations", deps.GovernanceHandler.CreateOrganization)
	protected.POST("/organizations/:organizationId/members", deps.GovernanceHandler.AddOrganizationMember)
	protected.PUT("/organizations/:organizationId/projects/:projectId", deps.GovernanceHandler.BindOrganizationProject)
}
