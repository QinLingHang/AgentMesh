package runtime

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// The HTTP transport is real; only the upstream model is simulated. This
// regression prevents a truncated upstream body from persisting a task as
// COMPLETED, without requiring an external provider or changing user data.
func TestP22InteractiveStreamRequiresMatchingTerminalDone(t *testing.T) {
	cases := []struct {
		name          string
		body          string
		wantError     string
		wantCallbacks int
	}{
		{name: "native token stream", body: "{\"type\":\"delta\",\"delta\":\"真\"}\n{\"type\":\"delta\",\"delta\":\"流式\"}\n{\"type\":\"done\",\"content\":\"真流式\"}\n", wantCallbacks: 3},
		{name: "completed without native deltas", body: "{\"type\":\"done\",\"content\":\"one-shot result\"}\n", wantCallbacks: 1},
		{name: "no events", body: "", wantError: "without a done event"},
		{name: "partial token stream", body: "{\"type\":\"delta\",\"delta\":\"partial\"}\n", wantError: "without a done event", wantCallbacks: 1},
		{name: "mismatched provider final", body: "{\"type\":\"delta\",\"delta\":\"visible\"}\n{\"type\":\"done\",\"content\":\"different\"}\n", wantError: "does not match deltas", wantCallbacks: 1},
		{name: "event after terminal", body: "{\"type\":\"done\",\"content\":\"complete\"}\n{\"type\":\"delta\",\"delta\":\"unexpected\"}\n", wantError: "after done", wantCallbacks: 1},
		{name: "upstream failure", body: "{\"type\":\"delta\",\"delta\":\"partial\"}\n{\"type\":\"error\",\"message\":\"upstream unavailable\"}\n", wantError: "upstream unavailable", wantCallbacks: 2},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.URL.Path != "/internal/v1/runtime/interactive-stream" || r.Header.Get("X-Internal-Token") != "test-token" {
					t.Errorf("unexpected upstream request: %s token=%q", r.URL.Path, r.Header.Get("X-Internal-Token"))
					w.WriteHeader(http.StatusUnauthorized)
					return
				}
				w.Header().Set("Content-Type", "application/x-ndjson")
				_, _ = w.Write([]byte(tc.body))
			}))
			defer server.Close()
			client := NewClient(server.URL, "test-token", time.Second)
			callbacks := 0
			err := client.StreamInteractive(context.Background(), InteractiveStreamRequest{}, func(event InteractiveStreamEvent) error {
				callbacks++
				return nil
			})
			if tc.wantError == "" && err != nil {
				t.Fatalf("unexpected stream error: %v", err)
			}
			if tc.wantError != "" && (err == nil || !strings.Contains(err.Error(), tc.wantError)) {
				t.Fatalf("stream error=%v, want substring %q", err, tc.wantError)
			}
			if callbacks != tc.wantCallbacks {
				t.Fatalf("callbacks=%d, want %d", callbacks, tc.wantCallbacks)
			}
		})
	}
}
