package service

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"strconv"
	"strings"

	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/repository"
)

const executionRoutingDiagnosticAction = "execution.routing.preflight.lookup"

func executionRoutingOutcome(err error) string {
	if err != nil {
		return "ERROR"
	}
	return "SUCCESS"
}

func (s *TaskService) recordProjectRuntimeLookupDiagnostics(
	ctx context.Context,
	uid int64,
	in RunTaskInput,
	prefix string,
	diagnostics []projectRuntimeLookupDiagnostic,
) {
	for _, item := range diagnostics {
		s.recordExecutionRoutingLookup(ctx, uid, in, prefix+item.Stage, item.Outcome, item.Err)
	}
}

type executionRoutingAuditRepository interface {
	AppendAudit(context.Context, model.AuditEvent) error
}

func executionRoutingCorrelationID(uid int64, in RunTaskInput) string {
	seed := strings.TrimSpace(in.ClientRequestID)
	if seed == "" && in.ConversationID != nil && *in.ConversationID > 0 {
		seed = "conversation:" + strconv.FormatInt(*in.ConversationID, 10)
	}
	if seed == "" || uid <= 0 {
		return ""
	}
	sum := sha256.Sum256([]byte(strconv.FormatInt(uid, 10) + ":" + seed))
	return hex.EncodeToString(sum[:8])
}

func executionRoutingErrorCode(err error) string {
	switch {
	case err == nil:
		return "NONE"
	case errors.Is(err, ErrNotFound), errors.Is(err, repository.ErrNotOwned):
		return "NOT_FOUND"
	case errors.Is(err, ErrForbidden):
		return "FORBIDDEN"
	case errors.Is(err, ErrInvalidInput):
		return "INVALID_INPUT"
	case errors.Is(err, ErrIdempotencyConflict), errors.Is(err, repository.ErrSubmissionConflict):
		return "SUBMISSION_CONFLICT"
	case errors.Is(err, context.Canceled):
		return "CANCELED"
	case errors.Is(err, context.DeadlineExceeded):
		return "DEADLINE"
	default:
		return "INTERNAL"
	}
}

func (s *TaskService) recordExecutionRoutingLookup(
	ctx context.Context,
	uid int64,
	in RunTaskInput,
	stage string,
	outcome string,
	err error,
) {
	if s == nil || s.tasks == nil || uid <= 0 {
		return
	}
	repo, ok := s.tasks.(executionRoutingAuditRepository)
	if !ok {
		return
	}
	stage = strings.ToUpper(strings.TrimSpace(stage))
	outcome = strings.ToUpper(strings.TrimSpace(outcome))
	if stage == "" || outcome == "" {
		return
	}
	metadata := map[string]any{
		"stage":     stage,
		"outcome":   outcome,
		"errorCode": executionRoutingErrorCode(err),
	}
	if correlation := executionRoutingCorrelationID(uid, in); correlation != "" {
		metadata["correlationId"] = correlation
	}
	_ = repo.AppendAudit(ctx, model.AuditEvent{
		ProjectID:    nil,
		ActorUserID:  uid,
		Action:       executionRoutingDiagnosticAction,
		ResourceType: "execution_routing",
		ResourceID:   executionRoutingCorrelationID(uid, in),
		Result:       outcome,
		Metadata:     safeAuditMetadata(metadata),
	})
}
