package runtime

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestP22RuntimeValidationDiagnosticsAreRedacted(t *testing.T) {
	const secret = "PRIVATE_API_KEY_SHOULD_NOT_LEAK"
	for _, stream := range []bool{false, true} {
		t.Run(map[bool]string{false: "execute", true: "execute-stream"}[stream], func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if stream != strings.HasSuffix(r.URL.Path, "/execute-stream") {
					t.Errorf("wrong endpoint: %s", r.URL.Path)
				}
				w.Header().Set("Content-Type", "application/json")
				w.WriteHeader(http.StatusUnprocessableEntity)
				_, _ = w.Write([]byte(`{"detail":[{"loc":["body","effectiveRagPolicy","allowedScopes"],"type":"list_type","input":"` + secret + `"},{"loc":["body","tools",0,"` + secret + `"],"type":"value_error","input":"` + secret + `"}]}`))
			}))
			defer server.Close()
			client := NewClient(server.URL, "test-token", 5*time.Second)
			ctx := context.Background()
			if stream {
				ctx = WithStreamEventSink(ctx, func(map[string]any) {})
			}
			_, err := client.Execute(ctx, ExecuteRequest{UserID: 1, RequestID: "test", Task: "hello"})
			if err == nil || !strings.Contains(err.Error(), "effectiveRagPolicy.allowedScopes:list_type") {
				t.Fatalf("422 validation path missing: %v", err)
			}
			if strings.Contains(err.Error(), secret) {
				t.Fatal("upstream request input or user-controlled location leaked to Go error")
			}
		})
	}
}

func TestP22RuntimeValidationDiagnosticsMalformedResponseIsSafe(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusUnprocessableEntity)
		_, _ = w.Write([]byte(`not-json PRIVATE_SECRET`))
	}))
	defer server.Close()
	client := NewClient(server.URL, "token", time.Second)
	_, err := client.Execute(context.Background(), ExecuteRequest{UserID: 1, RequestID: "t", Task: "hi"})
	if err == nil || !strings.Contains(err.Error(), "422") || strings.Contains(err.Error(), "PRIVATE_SECRET") {
		t.Fatalf("malformed response was not redacted: %v", err)
	}
}
