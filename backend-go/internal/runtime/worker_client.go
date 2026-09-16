package runtime

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// DurableExecutionEnvelope is sent only between the trusted Go control plane
// and a Python worker. The callback is authenticated with the same internal
// token; browsers never see this object.
type DurableExecutionEnvelope struct {
	JobID           int64          `json:"jobId"`
	ExecutionID     string         `json:"executionId"`
	LeaseToken      string         `json:"leaseToken"`
	FenceEpoch      int64          `json:"fenceEpoch"`
	DispatcherEpoch int64          `json:"dispatcherEpoch"`
	CallbackURL     string         `json:"callbackUrl"`
	Request         ExecuteRequest `json:"request"`
}

type DurableExecutionAccepted struct {
	Accepted   bool   `json:"accepted"`
	Duplicate  bool   `json:"duplicate"`
	WorkerID   string `json:"workerId"`
	FenceEpoch int64  `json:"fenceEpoch"`
}

type WorkerDispatchError struct {
	Err         error
	SafeToRetry bool
	Ambiguous   bool
	StatusCode  int
}

func (e *WorkerDispatchError) Error() string {
	if e == nil || e.Err == nil {
		return "worker dispatch failed"
	}
	return e.Err.Error()
}

func (e *WorkerDispatchError) Unwrap() error { return e.Err }

// SubmitDurableExecution uses a short request that only acknowledges acceptance.
// Once 202 is received, execution outcome is delivered asynchronously through
// the control-plane callback. This acceptance boundary makes retry semantics
// explicit: connect failures or explicit pre-accept 429/503 may retry; anything
// else is treated as ambiguous/fail-closed.
func (c *Client) SubmitDurableExecution(
	ctx context.Context,
	workerEndpoint string,
	envelope DurableExecutionEnvelope,
) (*DurableExecutionAccepted, error) {
	body, err := json.Marshal(envelope)
	if err != nil {
		return nil, err
	}
	endpoint := strings.TrimRight(workerEndpoint, "/") + "/internal/v1/runtime/executions"
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Internal-Token", c.token)

	resp, err := c.http.Do(req)
	if err != nil {
		safe := isPreConnectFailure(err)
		return nil, &WorkerDispatchError{
			Err:         err,
			SafeToRetry: safe,
			Ambiguous:   !safe,
		}
	}
	defer resp.Body.Close()

	var accepted DurableExecutionAccepted
	if resp.StatusCode == http.StatusAccepted {
		if err := json.NewDecoder(resp.Body).Decode(&accepted); err != nil {
			return nil, &WorkerDispatchError{Err: err, Ambiguous: true, StatusCode: resp.StatusCode}
		}
		if !accepted.Accepted {
			return nil, &WorkerDispatchError{Err: errors.New("worker returned 202 without acceptance"), Ambiguous: true, StatusCode: resp.StatusCode}
		}
		// An older worker can reply duplicate=202 for execution_id even when the
		// new assignment carries a higher fence. Never treat an unverified
		// duplicate as acceptance of the current attempt.
		if accepted.Duplicate && accepted.FenceEpoch != envelope.FenceEpoch {
			return nil, &WorkerDispatchError{
				Err:       errors.New("worker duplicate acknowledgement has mismatched fence"),
				Ambiguous: true, StatusCode: resp.StatusCode,
			}
		}
		return &accepted, nil
	}

	// Worker must mark overload/draining responses as explicitly not accepted.
	preAccept := strings.EqualFold(resp.Header.Get("X-AgentMesh-Accepted"), "false")
	if preAccept && (resp.StatusCode == http.StatusTooManyRequests || resp.StatusCode == http.StatusServiceUnavailable) {
		return nil, &WorkerDispatchError{
			Err:         fmt.Errorf("worker unavailable before acceptance: %s", resp.Status),
			SafeToRetry: true,
			StatusCode:  resp.StatusCode,
		}
	}

	return nil, &WorkerDispatchError{
		Err:        fmt.Errorf("worker dispatch failed: %s", resp.Status),
		Ambiguous:  true,
		StatusCode: resp.StatusCode,
	}
}

func (c *Client) CancelDurableExecution(
	ctx context.Context,
	workerEndpoint string,
	executionID string,
) error {
	endpoint := strings.TrimRight(workerEndpoint, "/") + "/internal/v1/runtime/executions/" + url.PathEscape(executionID)
	req, err := http.NewRequestWithContext(ctx, http.MethodDelete, endpoint, nil)
	if err != nil {
		return err
	}
	req.Header.Set("X-Internal-Token", c.token)
	resp, err := c.http.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode == http.StatusOK || resp.StatusCode == http.StatusAccepted || resp.StatusCode == http.StatusNotFound {
		return nil
	}
	return fmt.Errorf("worker cancel failed: %s", resp.Status)
}

func isPreConnectFailure(err error) bool {
	var urlErr *url.Error
	if errors.As(err, &urlErr) {
		err = urlErr.Err
	}
	var opErr *net.OpError
	if errors.As(err, &opErr) {
		op := strings.ToLower(strings.TrimSpace(opErr.Op))
		return op == "dial" || op == "connect"
	}
	return false
}

// Dedicated acceptance calls should be short even when the synchronous Runtime
// timeout is large. The caller controls a stricter context deadline.
func AcceptanceTimeout(parent context.Context, timeout time.Duration) (context.Context, context.CancelFunc) {
	if timeout <= 0 {
		timeout = 5 * time.Second
	}
	return context.WithTimeout(parent, timeout)
}
