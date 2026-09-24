package service

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"strings"
	"time"

	"example.com/agentmesh-control-plane/internal/model"
	"example.com/agentmesh-control-plane/internal/repository"
	runtimeclient "example.com/agentmesh-control-plane/internal/runtime"
)

const executionRoutingVersion = "execution-routing.v1"

// Delivery (direct/durable) is independent of execution strategy.
type ExecutionRouteDecision struct {
	SchemaVersion               string   `json:"schemaVersion"`
	Strategy                    string   `json:"strategy"`
	Disposition                 string   `json:"disposition"`
	RuntimePath                 string   `json:"runtimePath"`
	DeliveryMode                string   `json:"deliveryMode"`
	ReasonCodes                 []string `json:"reasonCodes"`
	UnresolvedRequirements      []string `json:"unresolvedRequirements"`
	AnalysisSource              string   `json:"analysisSource"`
	AnalysisLatencyMS           int64    `json:"analysisLatencyMs"`
	PreflightModelCalls         int      `json:"preflightModelCalls"`
	PreflightModelTokens        int      `json:"preflightModelTokens"`
	PreflightModelEstimatedCost float64  `json:"preflightModelEstimatedCost"`
	PreflightModelCostKnown     bool     `json:"preflightModelCostKnown"`
}

func ExecutionRoutingMode() string {
	value := strings.ToUpper(strings.TrimSpace(os.Getenv("EXECUTION_ROUTING_MODE")))
	switch value {
	case "SHADOW", "ENABLED":
		return value
	}
	return "OFF"
}

func executionRoutingFingerprint(in RunTaskInput, delivery string) (string, error) {
	if delivery == "direct" {
		// Match both legacy direct entry points: they trim the task before
		// computing its persisted request fingerprint.
		in.Task = strings.TrimSpace(in.Task)
		_, digest, err := directRequestIdentity(in)
		return digest, err
	}
	normalized, err := normalizeDurableRunInput(in)
	if err != nil {
		return "", err
	}
	normalized.ClientRequestID = ""
	raw, err := json.Marshal(normalized)
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:]), nil
}

// Resolve an existing submission before invoking any new model, catalog read or
// route classifier. The same user key plus different intent is a hard conflict.
// This lookup does not re-grant rights to a removed project/conversation.
func (s *TaskService) ResolveExistingSubmission(ctx context.Context, uid int64, in RunTaskInput) (*model.Task, error) {
	key := strings.TrimSpace(in.ClientRequestID)
	if !validClientRequestID(key) {
		return nil, ErrInvalidInput
	}
	if key == "" {
		return nil, nil
	}
	store, ok := s.tasks.(repository.DirectSubmissionRepository)
	if !ok {
		return nil, errors.New("execution routing submission ledger unavailable")
	}
	prior, recorded, err := store.LookupDurableSubmission(ctx, uid, key)
	if errors.Is(err, repository.ErrSubmissionConflict) {
		return nil, ErrIdempotencyConflict
	}
	if err != nil || prior == nil {
		return prior, err
	}
	// The Knowledge Runtime modes used different canonicalization. Compare the fingerprint
	// for the ORIGINAL mode so a feature-flag change cannot change the identity.
	digest, err := executionRoutingFingerprint(in, prior.DeliveryMode)
	if err != nil {
		return nil, err
	}
	if digest != recorded {
		return nil, ErrIdempotencyConflict
	}
	if s.projectRuntime != nil && prior.ConversationID != nil {
		if _, err = s.projectRuntime.ResolveForConversation(ctx, uid, *prior.ConversationID); err != nil {
			return nil, err
		}
	}
	return prior, nil
}

// referencesPriorContext only indicates that trusted conversation state
// should be checked; it does not authorize resuming or selecting any Task.
// Include references to assistant answers ("上一条"), not just executable tasks.
func referencesPriorContext(task string) bool {
	q := strings.ToLower(strings.TrimSpace(task))
	for _, token := range []string{"继续", "接着", "刚才", "上一个", "上一条", "上一轮", "上条", "上一步", "昨天那个", "进度", "状态如何", "取消任务", "continue", "go on", "progress", "status"} {
		if strings.Contains(q, token) {
			return true
		}
	}
	return false
}

// Resolve conversation references from owned records only. Never forward
// message bodies or task identifiers to a preflight model or private catalog.
// Task status and chat continuation are not interchangeable operations.
func (s *TaskService) resolveContinuationState(ctx context.Context, uid int64, in RunTaskInput) (string, error) {
	if !referencesPriorContext(in.Task) {
		return "NONE", nil
	}
	if in.ConversationID == nil {
		return "NONE", nil
	}
	if s.tasks == nil || s.messages == nil {
		return "NONE", errors.New("trusted continuation repository unavailable")
	}
	tasks, err := s.tasks.ListTasks(ctx, uid, 50)
	if err != nil {
		return "NONE", err
	}
	pending := 0
	for _, task := range tasks {
		if task.ConversationID == nil || *task.ConversationID != *in.ConversationID {
			continue
		}
		switch task.Status {
		case "RUNNING", "QUEUED", "DISPATCHING", "RESULT_PENDING", "COMPLETING", "INPUT_REQUIRED", "AUTH_REQUIRED":
			pending++
		}
		if pending > 1 {
			return "AMBIGUOUS", nil
		}
	}
	if pending == 1 {
		return "ONE_PENDING", nil
	}
	messages, err := s.messages.ListMessages(ctx, uid, *in.ConversationID, 8)
	if err != nil {
		return "NONE", err
	}
	for i := len(messages) - 1; i >= 0; i-- {
		if messages[i].Role == "assistant" && strings.TrimSpace(messages[i].Content) != "" {
			return "CHAT", nil
		}
	}
	return "NONE", nil
}

// DecideExecutionRoute decides only the execution boundary. Python Runtime owns all
// concrete Tool/MCP/Agent/Knowledge discovery, selection, planner and ToolLoop.
// This preflight never copies a capability catalog, schema or knowledge body.
func (s *TaskService) DecideExecutionRoute(ctx context.Context, uid int64, in RunTaskInput) (*ExecutionRouteDecision, error) {
	return s.decideExecutionRoute(ctx, uid, in, true)
}

// Shadow may observe a read-only routing suggestion but never pays for an
// extra LLM call or creates a task, message, tool invocation or Knowledge read.
func (s *TaskService) DecideExecutionRouteShadow(ctx context.Context, uid int64, in RunTaskInput) (*ExecutionRouteDecision, error) {
	return s.decideExecutionRoute(ctx, uid, in, false)
}

func (s *TaskService) decideExecutionRoute(ctx context.Context, uid int64, in RunTaskInput, allowModel bool) (*ExecutionRouteDecision, error) {
	if strings.TrimSpace(in.Task) == "" {
		return nil, ErrInvalidInput
	}
	var project *model.ProjectRuntimeContext
	var err error
	if s.projectRuntime != nil && in.ConversationID != nil {
		project, err = s.projectRuntime.ResolveForConversation(ctx, uid, *in.ConversationID)
		if err != nil {
			return nil, err
		}
		explicitRetry := in.Constraints.RetryOnWorkerLoss
		applyProjectRuntimePolicy(&in, project)
		if explicitRetry {
			in.Constraints.RetryOnWorkerLoss = true
		}
	}
	delivery := s.DecideDeliveryMode(in)
	policy, _, _, err := s.resolveEffectiveRagPolicy(ctx, uid, in.ConversationID, in.RagPolicy)
	if err != nil {
		return nil, err
	}
	continuation, err := s.resolveContinuationState(ctx, uid, in)
	if err != nil {
		return nil, err
	}
	if s.runtime == nil {
		return nil, errors.New("route preflight runtime unavailable")
	}

	// Use the existing request model policy; no platform-owned routing key.
	// Explicitly simple requests may still use zero model calls (Python rules).
	var modelPool []runtimeclient.ProjectModelRuntime
	var projectModel *runtimeclient.ProjectModelRuntime
	selection := in.ModelSelection
	if strings.TrimSpace(selection.Mode) == "" {
		selection.Mode = "auto"
	}
	if allowModel {
		if s.governance != nil && project != nil {
			if quotaErr := s.governance.CheckQuota(ctx, uid, project.ProjectID); quotaErr != nil {
				allowModel = false
			}
		}
		if allowModel {
			pool, configured, normalized, modelErr := s.resolveRequestModelRuntimePool(ctx, uid, project, selection)
			if modelErr == nil {
				modelPool, projectModel, selection = pool, configured, normalized
			} else {
				// Routing is advisory. A broken/expired BYOK configuration must not
				// turn a clearly model-only request into a preflight 503. The actual
				// execution path still independently enforces its model policy.
				allowModel = false
			}
		}
	}
	analysisStarted := time.Now()
	proposal, err := s.runtime.UnderstandExecutionRoute(ctx, runtimeclient.ExecutionRoutingRequest{
		SchemaVersion: executionRoutingVersion, Task: in.Task, RagMode: string(policy.Mode),
		HasAttachments:           len(in.AttachmentIDs) != 0,
		ModelReadableAttachments: s.modelReadableAttachments(ctx, uid, in), ContinuationState: continuation,
		AllowModel:   allowModel && (len(modelPool) != 0 || projectModel != nil),
		ProjectModel: projectModel, ModelPool: modelPool,
		ModelSelection: runtimeclient.ModelSelection{Mode: selection.Mode, ServiceID: selection.ServiceID},
		Constraints:    in.Constraints,
	})
	if err != nil {
		return nil, err
	}
	// Durable is orthogonal to route classification, but the existing
	// reliable transport executes through Runtime; do not downgrade delivery.
	if delivery.Mode == "durable" && proposal.ExecutionRoute == "FAST_PATH" && proposal.Disposition == "EXECUTE" {
		proposal.ExecutionRoute = "RUNTIME"
		proposal.ReasonCodes = append(proposal.ReasonCodes, "DURABLE_REQUIRES_RUNTIME")
	}
	decision := &ExecutionRouteDecision{
		SchemaVersion: executionRoutingVersion, Strategy: proposal.ExecutionRoute, Disposition: proposal.Disposition,
		DeliveryMode: delivery.Mode, ReasonCodes: append([]string(nil), proposal.ReasonCodes...),
		UnresolvedRequirements: append([]string(nil), proposal.UnresolvedRequirements...),
		AnalysisSource:         proposal.AnalysisSource, AnalysisLatencyMS: time.Since(analysisStarted).Milliseconds(), PreflightModelCalls: proposal.ModelCalls,
		PreflightModelTokens: proposal.ModelTokens, PreflightModelEstimatedCost: proposal.ModelEstimatedCost,
		PreflightModelCostKnown: proposal.ModelCostKnown,
	}
	switch proposal.Disposition {
	case "EXECUTE":
		if proposal.ExecutionRoute == "FAST_PATH" {
			decision.RuntimePath = "FAST_PATH"
		} else {
			decision.RuntimePath = "FULL_RUNTIME"
		}
	case "CLARIFY", "REJECT":
		decision.RuntimePath = "NONE" // no third executable route; no side effects
	default:
		return nil, errors.New("invalid route disposition")
	}
	if err := ValidateExecutionRouteDecision(*decision, *proposal, policy); err != nil {
		return nil, err
	}
	return decision, nil
}

// ValidateExecutionRouteDecision is a pure, fail-closed boundary. A model never chooses
// capability IDs or overrides RAG restrictions, auth, durability or task state.
func ValidateExecutionRouteDecision(decision ExecutionRouteDecision, proposal runtimeclient.ExecutionRoutingResponse, policy model.RagPolicy) error {
	if decision.SchemaVersion != executionRoutingVersion || proposal.SchemaVersion != executionRoutingVersion {
		return errors.New("invalid route contract version")
	}
	if decision.DeliveryMode != "direct" && decision.DeliveryMode != "durable" {
		return errors.New("invalid delivery mode")
	}
	if proposal.ExecutionRoute != "FAST_PATH" && proposal.ExecutionRoute != "RUNTIME" {
		return errors.New("invalid execution route")
	}
	if decision.Strategy != proposal.ExecutionRoute {
		return errors.New("route proposal and decision mismatch")
	}
	if proposal.ModelCalls < 0 || proposal.ModelCalls > 1 || proposal.ModelTokens < 0 || proposal.ModelTokens > 100000 ||
		proposal.ModelEstimatedCost < 0 || proposal.ModelEstimatedCost > 100000 ||
		(decision.AnalysisSource != "RULE" && decision.AnalysisSource != "MODEL" && decision.AnalysisSource != "INDETERMINATE") {
		return errors.New("invalid preflight source or budget metadata")
	}
	if len(decision.ReasonCodes) > 8 || len(decision.UnresolvedRequirements) > 4 {
		return errors.New("preflight diagnostic size exceeded")
	}
	for _, reason := range decision.ReasonCodes {
		if len(reason) < 1 || len(reason) > 64 {
			return errors.New("invalid diagnostic reason length")
		}
		for _, c := range reason {
			if !((c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_') {
				return errors.New("invalid diagnostic reason")
			}
		}
	}
	for _, item := range decision.UnresolvedRequirements {
		if strings.TrimSpace(item) == "" || len(item) > 640 {
			return errors.New("invalid clarification requirement")
		}
	}
	if decision.Disposition != "" && decision.Disposition != proposal.Disposition {
		return errors.New("route disposition and decision mismatch")
	}
	if proposal.Disposition == "CLARIFY" {
		if decision.RuntimePath != "NONE" || len(decision.UnresolvedRequirements) == 0 {
			return errors.New("invalid clarification route")
		}
		if proposal.ExecutionRoute == "FAST_PATH" && (proposal.CapabilityRequired || proposal.KnowledgeDependency != "NONE" || policy.Mode == model.RagModeOn) {
			return errors.New("capability-dependent clarification cannot use model-only route")
		}
		return nil
	}
	if proposal.Disposition == "REJECT" {
		if decision.RuntimePath != "NONE" || proposal.ExecutionRoute != "RUNTIME" || len(decision.UnresolvedRequirements) == 0 {
			return errors.New("invalid rejection route")
		}
		return nil
	}
	if proposal.Disposition != "EXECUTE" || len(decision.UnresolvedRequirements) != 0 {
		return errors.New("invalid execution disposition")
	}
	if proposal.ExecutionRoute == "FAST_PATH" {
		if decision.RuntimePath != "FAST_PATH" || proposal.CapabilityRequired || proposal.KnowledgeDependency != "NONE" || policy.Mode == model.RagModeOn {
			return errors.New("capability-dependent request cannot bypass runtime")
		}
	} else if decision.RuntimePath != "FULL_RUNTIME" {
		return errors.New("runtime route must use existing full runtime")
	}
	if policy.Mode == model.RagModeOff && proposal.KnowledgeDependency == "REQUIRED" {
		return errors.New("required knowledge is disabled by policy")
	}
	return nil
}

// An idempotent replay is a projection of the original authoritative task.
// Neither the current route flag nor its new policy is consulted.
func ReplaySubmissionResult(task *model.Task) *RunTaskResult {
	if task.DeliveryMode == "durable" {
		return durableSubmissionResult(task)
	}
	return replayDirectTask(task)
}

// Persist a minimal decision fingerprint together with the message/task
// submission transaction. OFF preserves the old exact metadata shape.
func executionRoutingMetadata(in RunTaskInput, metadata map[string]any) map[string]any {
	if in.ExecutionRoute != "" {
		metadata["executionRoutingVersion"] = executionRoutingVersion
		metadata["executionRoute"] = in.ExecutionRoute
		metadata["routingReasonCodes"] = append([]string(nil), in.RoutingReasonCodes...)
		metadata["routingAnalysisSource"] = in.RoutingAnalysisSource
		metadata["routingAnalysisLatencyMs"] = in.RoutingAnalysisLatencyMS
		metadata["routingModelCalls"] = in.RoutingModelCalls
		metadata["routingModelTokens"] = in.RoutingModelTokens
		if in.RoutingModelCostKnown {
			metadata["routingModelEstimatedCost"] = in.RoutingModelEstimatedCost
		}
	}
	return metadata
}

// executionRoutingTrace only includes bounded enumerated metadata. It never logs
// the user prompt, private catalog, authorization refs, or knowledge contents.
func executionRoutingTrace(in RunTaskInput, delivery string) []map[string]any {
	if in.ExecutionRoute == "" {
		return nil
	}
	allowed := map[string]bool{"FAST_PATH": true, "RUNTIME": true}
	if !allowed[in.ExecutionRoute] {
		return nil
	}
	reasonCodes := make([]string, 0, 12)
	for _, reason := range in.RoutingReasonCodes {
		if len(reasonCodes) >= 12 {
			break
		}
		if len(reason) > 64 {
			continue
		}
		safe := true
		for _, ch := range reason {
			if !((ch >= 'A' && ch <= 'Z') || (ch >= '0' && ch <= '9') || ch == '_') {
				safe = false
				break
			}
		}
		if safe {
			reasonCodes = append(reasonCodes, reason)
		}
	}
	details := map[string]any{
		"decisionVersion":         executionRoutingVersion,
		"strategy":                in.ExecutionRoute,
		"deliveryMode":            delivery,
		"reasonCodes":             reasonCodes,
		"analysisSource":          in.RoutingAnalysisSource,
		"analysisLatencyMs":       in.RoutingAnalysisLatencyMS,
		"preflightModelCalls":     in.RoutingModelCalls,
		"preflightModelTokens":    in.RoutingModelTokens,
		"preflightModelCostKnown": in.RoutingModelCostKnown,
	}
	if in.RoutingModelCostKnown {
		details["preflightModelEstimatedCost"] = in.RoutingModelEstimatedCost
	}
	detail, _ := json.Marshal(details)
	return []map[string]any{{
		"kind": "routing", "title": "Execution Route Decision",
		"status": "completed", "detail": string(detail), "elapsedMs": int64(0),
	}}
}
