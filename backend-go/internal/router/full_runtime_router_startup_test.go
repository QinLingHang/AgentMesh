package router

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"example.com/agentmesh-control-plane/internal/handler"
	"github.com/gin-gonic/gin"
)

// Register EVERY route in the production router, not merely a synthetic task
// group. In particular the governance cost endpoint has to coexist with the
// durable task subtree, task deletion and rate-limited task endpoints.
func TestKnowledgeRuntimeFullRouterRegistersAllTaskRoutesWithoutPanic(t *testing.T) {
	gin.SetMode(gin.TestMode)
	engine := New(Dependencies{
		GovernanceHandler:     handler.NewGovernanceHandler(nil),
		DurableRuntimeHandler: handler.NewDurableRuntimeHandler(nil),
		InternalToken:         "knowledge-runtime-router-test-token",
	})
	want := map[string]bool{
		"GET /api/tasks/:id/cost":       false,
		"GET /api/tasks/:id/events":     false,
		"POST /api/tasks/:id/cancel":    false,
		"POST /api/tasks/:id/resume":    false,
		"DELETE /api/tasks/:id":         false,
		"POST /api/tasks/submit-stream": false,
		"POST /api/tasks/run-durable":   false,
		"GET /livez":                    false,
		"GET /readyz":                   false,
	}
	for _, route := range engine.Routes() {
		key := route.Method + " " + route.Path
		if _, ok := want[key]; ok {
			want[key] = true
		}
	}
	for path, seen := range want {
		if !seen {
			t.Errorf("full router missing %s", path)
		}
	}
	for _, tc := range []struct {
		path string
		want int
	}{
		{path: "/livez", want: http.StatusOK},
		{path: "/readyz", want: http.StatusServiceUnavailable},
		{path: "/api/tasks/1/cost", want: http.StatusUnauthorized},
		{path: "/api/tasks/1/events", want: http.StatusUnauthorized},
	} {
		response := httptest.NewRecorder()
		engine.ServeHTTP(response, httptest.NewRequest(http.MethodGet, tc.path, nil))
		if response.Code != tc.want {
			t.Errorf("GET %s returned %d (want %d): %s", tc.path, response.Code, tc.want, response.Body.String())
		}
	}
}
