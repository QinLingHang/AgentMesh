package router

import (
	"database/sql"
	"time"

	"example.com/agentmesh-control-plane/internal/handler"
	"example.com/agentmesh-control-plane/internal/middleware"
	"example.com/agentmesh-control-plane/internal/security"

	"github.com/gin-gonic/gin"
	"github.com/redis/go-redis/v9"
)

type Dependencies struct {
	AuthHandler *handler.AuthHandler

	VerificationAuthHandler *handler.VerificationAuthHandler

	ConversationHandler *handler.ConversationHandler

	ProjectHandler *handler.ProjectHandler

	ProjectRuntimeHandler *handler.ProjectRuntimeHandler

	MemoryHandler *handler.MemoryHandler

	KnowledgeHandler *handler.KnowledgeHandler

	AttachmentHandler *handler.AttachmentHandler

	AgentHandler *handler.AgentHandler

	TaskHandler *handler.TaskHandler

	DurableRuntimeHandler *handler.DurableRuntimeHandler

	ToolHandler *handler.ToolHandler

	MCPServerHandler *handler.MCPServerHandler

	GovernanceHandler *handler.GovernanceHandler

	EcosystemHandler *handler.EcosystemHandler

	PublicAPIHandler *handler.PublicAPIHandler

	JWT *security.JWTManager

	DB *sql.DB

	Redis *redis.Client

	AllowedOrigins []string

	TaskRateLimit int

	InternalToken string
}

func New(
	deps Dependencies,
) *gin.Engine {
	r := gin.Default()

	r.Use(
		middleware.CORS(
			deps.AllowedOrigins,
		),
	)

	registerHealthRoutes(
		r,
		deps.DB,
		deps.Redis,
	)

	internal := r.Group(
		"/internal/v1",
	)
	internal.Use(
		func(c *gin.Context) {
			if deps.InternalToken == "" ||
				c.GetHeader("X-Internal-Token") != deps.InternalToken {
				c.AbortWithStatusJSON(
					401,
					gin.H{
						"code":    40101,
						"message": "invalid internal token",
					},
				)
				return
			}
			c.Next()
		},
	)
	internal.GET(
		"/knowledge/scope",
		deps.KnowledgeHandler.ResolveRuntimeScope,
	)
	internal.GET(
		"/users/:userId/memories",
		deps.MemoryHandler.InternalListActive,
	)
	internal.POST(
		"/users/:userId/memories/upsert",
		deps.MemoryHandler.InternalUpsert,
	)
	internal.DELETE(
		"/users/:userId/memories/:id",
		deps.MemoryHandler.InternalDelete,
	)

	registerInternalDurableRuntimeRoutes(internal, deps)

	registerPublicAPIRoutes(r, deps)

	api := r.Group(
		"/api",
	)

	registerAuthRoutes(
		api,
		deps,
	)

	protected := api.Group(
		"",
	)

	protected.Use(
		middleware.Auth(
			deps.JWT,
		),
	)

	registerCurrentUserRoutes(
		protected,
		deps,
	)

	registerConversationRoutes(
		protected,
		deps,
	)

	registerAttachmentRoutes(
		protected,
		deps,
	)

	registerProjectRoutes(
		protected,
		deps,
	)

	registerProjectRuntimeRoutes(
		protected,
		deps,
	)

	registerMemoryRoutes(
		protected,
		deps,
	)

	registerKnowledgeRoutes(
		protected,
		deps,
	)

	registerMessageRoutes(
		protected,
		deps,
	)

	registerAgentRoutes(
		protected,
		deps,
	)

	registerToolRoutes(
		protected,
		deps,
	)

	registerMCPServerRoutes(
		protected,
		deps,
	)

	registerTaskRoutes(
		protected,
		deps,
	)

	registerDurableRuntimeRoutes(protected, deps)

	registerGovernanceRoutes(protected, deps)

	registerEcosystemRoutes(protected, deps)

	// Task history deletion is not rate-limited as task execution.
	// It still passes JWT tenant authentication.
	protected.DELETE(
		"/tasks/:id",
		deps.TaskHandler.Delete,
	)

	rateLimited :=
		protected.Group(
			"",
		)

	rateLimited.Use(
		middleware.FixedWindowRateLimit(
			deps.Redis,
			deps.TaskRateLimit,
			time.Minute,
		),
	)

	registerRateLimitedTaskRoutes(
		rateLimited,
		deps,
	)

	registerRateLimitedDurableRuntimeRoutes(rateLimited, deps)

	return r
}
