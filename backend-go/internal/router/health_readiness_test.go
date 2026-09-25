package router

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
)

func TestP10HealthContractsWithoutDependencies(t *testing.T) {
	gin.SetMode(gin.TestMode)
	engine := gin.New()
	registerHealthRoutes(engine, nil, nil, nil)

	for _, tc := range []struct {
		path string
		want int
	}{
		{path: "/health", want: http.StatusOK},
		{path: "/livez", want: http.StatusOK},
		{path: "/readyz", want: http.StatusServiceUnavailable},
	} {
		t.Run(tc.path, func(t *testing.T) {
			recorder := httptest.NewRecorder()
			request := httptest.NewRequest(http.MethodGet, tc.path, nil)
			engine.ServeHTTP(recorder, request)
			if recorder.Code != tc.want {
				t.Fatalf("%s status = %d, want %d; body=%s", tc.path, recorder.Code, tc.want, recorder.Body.String())
			}
		})
	}
}
