package service

import (
	"context"
	"errors"

	runtimeclient "example.com/agentmesh-control-plane/internal/runtime"
)

// runtimeFailureDiagnosticsRepository is intentionally optional so existing
// TaskRepository test doubles do not need to implement diagnostic persistence.
// The MySQL repository implements it in production.
type runtimeFailureDiagnosticsRepository interface {
	FailTaskWithDiagnostics(
		context.Context,
		int64,
		int64,
		string,
		int64,
		[]map[string]any,
	) error
}

func (s *TaskService) failTaskAfterRuntimeError(
	ctx context.Context,
	uid int64,
	taskID int64,
	err error,
	latencyMS int64,
) {
	if s == nil || s.tasks == nil || taskID <= 0 || err == nil {
		return
	}

	// A browser disconnect can cancel the request context after Runtime has
	// already progressed. Use a short independent finalization context so the
	// task does not remain RUNNING solely because its caller disappeared.
	cleanupCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), taskFinalizationTimeout)
	defer cancel()

	var streamErr *runtimeclient.RuntimeStreamError
	if errors.As(err, &streamErr) {
		if trace := streamErr.PartialTrace(); len(trace) != 0 {
			if repo, ok := s.tasks.(runtimeFailureDiagnosticsRepository); ok {
				if persistErr := repo.FailTaskWithDiagnostics(
					cleanupCtx, uid, taskID, err.Error(), latencyMS, trace,
				); persistErr == nil {
					return
				}
			}
		}
	}

	_ = s.tasks.FailTask(cleanupCtx, uid, taskID, err.Error(), latencyMS)
}
