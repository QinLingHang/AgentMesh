package router

import (
	"testing"

	"example.com/agentmesh-control-plane/internal/handler"
	"github.com/gin-gonic/gin"
)

// The task subtree must use ONE wildcard name. Gin panics at startup if cost
// uses :taskId while task state, cancellation and replay use :id.
func TestP22TaskCostRouteCoexistsWithTaskWildcard(t *testing.T) {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	protected := r.Group("/api")
	protected.GET("/tasks/:id/events", func(c *gin.Context) {})
	protected.POST("/tasks/:id/cancel", func(c *gin.Context) {})
	registerGovernanceRoutes(protected, Dependencies{
		GovernanceHandler: handler.NewGovernanceHandler(nil),
	})

	want := "GET /api/tasks/:id/cost"
	for _, route := range r.Routes() {
		if route.Method+" "+route.Path == want {
			return
		}
	}
	t.Fatalf("missing compatible route %s", want)
}
