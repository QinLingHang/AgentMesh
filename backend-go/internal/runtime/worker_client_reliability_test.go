package runtime

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func p8Envelope() DurableExecutionEnvelope {
	return DurableExecutionEnvelope{
		JobID:       7,
		ExecutionID: "exec-durable",
		LeaseToken:  "lease-durable",
		CallbackURL: "http://control-plane.invalid/internal/v1/runtime/jobs/7/result",
		Request: ExecuteRequest{
			UserID:    1,
			RequestID: "request-durable",
			Task:      "durable worker transport",
		},
	}
}

func TestDurableRuntimeWorkerAcceptanceBoundary(t *testing.T) {
	t.Run("202 establishes acceptance", func(t *testing.T) {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.Header.Get("X-Internal-Token") != "internal-test-token" {
				t.Fatalf("internal token missing")
			}
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusAccepted)
			_ = json.NewEncoder(w).Encode(DurableExecutionAccepted{Accepted: true, WorkerID: "worker-durable"})
		}))
		defer server.Close()

		client := NewClient("http://unused.invalid", "internal-test-token", time.Second)
		accepted, err := client.SubmitDurableExecution(context.Background(), server.URL, p8Envelope())
		if err != nil {
			t.Fatal(err)
		}
		if accepted == nil || !accepted.Accepted || accepted.WorkerID != "worker-durable" {
			t.Fatalf("unexpected acceptance: %#v", accepted)
		}
	})

	t.Run("explicit preaccept overload is retryable", func(t *testing.T) {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
			w.Header().Set("X-AgentMesh-Accepted", "false")
			w.WriteHeader(http.StatusTooManyRequests)
		}))
		defer server.Close()

		client := NewClient("http://unused.invalid", "internal-test-token", time.Second)
		_, err := client.SubmitDurableExecution(context.Background(), server.URL, p8Envelope())
		var dispatchErr *WorkerDispatchError
		if !errors.As(err, &dispatchErr) || !dispatchErr.SafeToRetry || dispatchErr.Ambiguous {
			t.Fatalf("expected safe preaccept retry, got %#v", err)
		}
	})

	t.Run("server failure without explicit rejection is ambiguous", func(t *testing.T) {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
			w.WriteHeader(http.StatusInternalServerError)
		}))
		defer server.Close()

		client := NewClient("http://unused.invalid", "internal-test-token", time.Second)
		_, err := client.SubmitDurableExecution(context.Background(), server.URL, p8Envelope())
		var dispatchErr *WorkerDispatchError
		if !errors.As(err, &dispatchErr) || dispatchErr.SafeToRetry || !dispatchErr.Ambiguous {
			t.Fatalf("expected ambiguous fail-closed outcome, got %#v", err)
		}
	})

	t.Run("malformed 202 is ambiguous", func(t *testing.T) {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
			w.WriteHeader(http.StatusAccepted)
			_, _ = w.Write([]byte("not-json"))
		}))
		defer server.Close()

		client := NewClient("http://unused.invalid", "internal-test-token", time.Second)
		_, err := client.SubmitDurableExecution(context.Background(), server.URL, p8Envelope())
		var dispatchErr *WorkerDispatchError
		if !errors.As(err, &dispatchErr) || !dispatchErr.Ambiguous {
			t.Fatalf("expected ambiguous malformed acceptance, got %#v", err)
		}
	})
}

func TestDurableRuntimeWorkerCancelContract(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodDelete || r.URL.Path != "/internal/v1/runtime/executions/exec-durable" {
			t.Fatalf("unexpected cancel request %s %s", r.Method, r.URL.Path)
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	client := NewClient("http://unused.invalid", "internal-test-token", time.Second)
	if err := client.CancelDurableExecution(context.Background(), server.URL, "exec-durable"); err != nil {
		t.Fatal(err)
	}
}

func TestEventDeliveryDuplicateAcceptanceMustCarryExactFence(t *testing.T) {
	for _, tc := range []struct {
		name      string
		ackFence  int64
		wantError bool
	}{
		{name: "same-fence", ackFence: 9},
		{name: "stale-fence", ackFence: 8, wantError: true},
		{name: "legacy-omits-fence", ackFence: 0, wantError: true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				w.WriteHeader(http.StatusAccepted)
				_ = json.NewEncoder(w).Encode(DurableExecutionAccepted{
					Accepted: true, Duplicate: true, WorkerID: "worker", FenceEpoch: tc.ackFence,
				})
			}))
			defer server.Close()
			input := p8Envelope()
			input.FenceEpoch = 9
			client := NewClient("http://unused.invalid", "internal-test-token", time.Second)
			ack, err := client.SubmitDurableExecution(context.Background(), server.URL, input)
			if tc.wantError {
				var dispatchErr *WorkerDispatchError
				if !errors.As(err, &dispatchErr) || !dispatchErr.Ambiguous || dispatchErr.SafeToRetry {
					t.Fatalf("mismatched duplicate fence must fail closed: ack=%#v err=%v", ack, err)
				}
				return
			}
			if err != nil || ack == nil || !ack.Duplicate {
				t.Fatalf("exact-fence duplicate must be accepted: ack=%#v err=%v", ack, err)
			}
		})
	}
}
