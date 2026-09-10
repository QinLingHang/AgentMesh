package router

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestP20ConversationMemoryInternalRoutesRequireInternalToken(t *testing.T) {
	const internalToken = "p20-conversation-memory-internal-token"
	engine := New(Dependencies{InternalToken: internalToken})
	path := "/internal/v1/users/1/conversations/1/memory-capsules"

	for _, tc := range []struct {
		name  string
		token string
	}{
		{name: "missing token", token: ""},
		{name: "wrong token", token: "wrong-token"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodGet, path, nil)
			if tc.token != "" {
				req.Header.Set("X-Internal-Token", tc.token)
			}
			res := httptest.NewRecorder()
			engine.ServeHTTP(res, req)
			if res.Code != http.StatusUnauthorized {
				t.Fatalf("expected 401 for %s, got %d body=%s", tc.name, res.Code, res.Body.String())
			}
		})
	}
}
