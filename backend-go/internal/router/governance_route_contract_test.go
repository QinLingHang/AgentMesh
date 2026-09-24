package router

import (
	"testing"

	"example.com/agentmesh-control-plane/internal/handler"
	"github.com/gin-gonic/gin"
)

func TestP9GovernanceRoutesCoexistWithExistingProjectWildcard(t *testing.T) {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	protected := r.Group("/api")
	deps := Dependencies{
		ProjectHandler:    handler.NewProjectHandler(nil),
		GovernanceHandler: handler.NewGovernanceHandler(nil),
	}

	// This combination used to panic because Project routes used :id while
	// Governance routes used :projectId at the same wildcard position.
	registerProjectRoutes(protected, deps)
	registerGovernanceRoutes(protected, deps)

	want := map[string]bool{
		"GET /api/projects/:id/governance":                           false,
		"GET /api/organizations":                                     false,
		"POST /api/organizations":                                    false,
		"POST /api/organizations/:organizationId/members":            false,
		"PUT /api/organizations/:organizationId/projects/:projectId": false,
	}
	for _, route := range r.Routes() {
		key := route.Method + " " + route.Path
		if _, ok := want[key]; ok {
			want[key] = true
		}
	}
	for route, seen := range want {
		if !seen {
			t.Fatalf("missing Governance route %s", route)
		}
	}
}
