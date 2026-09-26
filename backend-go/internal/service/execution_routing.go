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

func retryRoutingNotFound[T any](ctx context.Context, fn func() (T, error)) (T, error) {
	var zero T
	value, err := fn()
	if !errors.Is(err, ErrNotFound) {
		return value, err
	}
	select {
	case <-ctx.Done():
		return zero, ctx.Err()
	case <-time.After(15 * time.Millisecond):
	}
	return fn()
}

type projectRuntimeDiagnosticResolver interface {
	ResolveForConversationWithDiagnostics(
		context.Context,
		int64,
		int64,
	) (*model.ProjectRuntimeContext, []projectRuntimeLookupDiagnostic, error)
}

func (s *TaskService) resolveProjectRuntimeForRoutingDetailed(
	ctx context.Context, uid, conversationID int64,
) (*model.ProjectRuntimeContext, []projectRuntimeLookupDiagnostic, error) {
	if s.projectRuntime == nil {
		return nil, nil, nil
	}
	resolve := func() (*model.ProjectRuntimeContext, []projectRuntimeLookupDiagnostic, error) {
		if detailed, ok := s.projectRuntime.(projectRuntimeDiagnosticResolver); ok {
			return detailed.ResolveForConversationWithDiagnostics(ctx, uid, conversationID)
		}
		resolved, err := s.projectRuntime.ResolveForConversation(ctx, uid, conversationID)
		return resolved, nil, err
	}

	resolved, diagnostics, err := resolve()
	if !errors.Is(err, ErrNotFound) {
		return resolved, diagnostics, err
	}
	select {
	case <-ctx.Done():
		return nil, diagnostics, ctx.Err()
	case <-time.After(15 * time.Millisecond):
	}
	// Only persist the final lookup attempt. The short retry exists to absorb
	// commit-visibility races and should not create a false failure diagnosis.
	return resolve()
}

func (s *TaskService) resolveProjectRuntimeForRouting(
	ctx context.Context, uid, conversationID int64,
) (*model.ProjectRuntimeContext, error) {
	resolved, _, err := s.resolveProjectRuntimeForRoutingDetailed(ctx, uid, conversationID)
	return resolved, err
}

// Delivery (direct/durable) is independent of execution strategy.
type ExecutionRouteDecision struct {
	SchemaVersion               string                         `json:"schemaVersion"`
	Strategy                    string                         `json:"strategy"`
	Disposition                 string                         `json:"disposition"`
	RuntimePath                 string                         `json:"runtimePath"`
	DeliveryMode                string                         `json:"deliveryMode"`
	ReasonCodes                 []string                       `json:"reasonCodes"`
	UnresolvedRequirements      []string                       `json:"unresolvedRequirements"`
	AnalysisSource              string                         `json:"analysisSource"`
	AnalysisLatencyMS           int64                          `json:"analysisLatencyMs"`
	PreflightModelCalls         int                            `json:"preflightModelCalls"`
	PreflightModelTokens        int                            `json:"preflightModelTokens"`
	PreflightModelEstimatedCost float64                        `json:"preflightModelEstimatedCost"`
	PreflightModelCostKnown     bool                           `json:"preflightModelCostKnown"`
	ExecutionIntent             *runtimeclient.ExecutionIntent `json:"executionIntent,omitempty"`
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
	ledgerOutcome := "MISS"
	if prior != nil {
		ledgerOutcome = "FOUND"
	}
	if err != nil {
		ledgerOutcome = "ERROR"
	}
	s.recordExecutionRoutingLookup(ctx, uid, in, "SUBMISSION_LEDGER", ledgerOutcome, err)
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
		resolved, lookupDiagnostics, resolveErr := s.resolveProjectRuntimeForRoutingDetailed(ctx, uid, *prior.ConversationID)
		s.recordProjectRuntimeLookupDiagnostics(ctx, uid, in, "PRIOR_", lookupDiagnostics)
		outcome := "MISS"
		if resolved != nil {
			outcome = "FOUND"
		}
		if resolveErr != nil {
			outcome = "ERROR"
		}
		s.recordExecutionRoutingLookup(ctx, uid, in, "PRIOR_CONVERSATION_REVALIDATION", outcome, resolveErr)
		if resolveErr != nil {
			return nil, resolveErr
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

// settleReferencedPreviousTurnBeforeRouting closes the same-conversation
// streaming/finalization race before semantic preflight derives continuation
// and previous-turn facts. The trigger is only the user's explicit reference
// to prior conversation context; it does not depend on any concrete Tool, MCP,
// Agent or Knowledge identity and therefore cannot pre-authorize execution.
//
// When the latest durable user request has not yet acquired its paired
// assistant message, wait boundedly on the authoritative MySQL conversation
// history. On timeout nothing is fabricated: routing continues with the latest
// durable state and the semantic/runtime layers remain fail-closed.
func (s *TaskService) settleReferencedPreviousTurnBeforeRouting(
	ctx context.Context,
	uid int64,
	in RunTaskInput,
) error {
	if !referencesPriorContext(in.Task) || in.ConversationID == nil {
		return nil
	}
	if s.messages == nil {
		return errors.New("trusted continuation repository unavailable")
	}

	initial, err := s.messages.ListMessages(ctx, uid, *in.ConversationID, 48)
	if err != nil {
		s.recordExecutionRoutingLookup(ctx, uid, in, "PREFLIGHT_HISTORY_SETTLEMENT", "ERROR", err)
		return err
	}
	requestID := latestUserRequestID(initial)
	if requestID == "" {
		s.recordExecutionRoutingLookup(ctx, uid, in, "PREFLIGHT_HISTORY_SETTLEMENT", "NO_PRIOR_REQUEST", nil)
		return nil
	}
	if historyHasAssistantRequest(initial, requestID) {
		s.recordExecutionRoutingLookup(ctx, uid, in, "PREFLIGHT_HISTORY_SETTLEMENT", "ALREADY_SETTLED", nil)
		return nil
	}

	settled, err := s.waitForTrustedHistoryAssistant(
		ctx, uid, *in.ConversationID, initial, taskFinalizationTimeout,
	)
	if err != nil {
		s.recordExecutionRoutingLookup(ctx, uid, in, "PREFLIGHT_HISTORY_SETTLEMENT", "ERROR", err)
		return err
	}
	outcome := "TIMEOUT"
	if historyHasAssistantRequest(settled, requestID) {
		outcome = "SETTLED"
	}
	s.recordExecutionRoutingLookup(ctx, uid, in, "PREFLIGHT_HISTORY_SETTLEMENT", outcome, nil)
	return nil
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
	s.recordExecutionRoutingLookup(ctx, uid, in, "CONTINUATION_TASKS", executionRoutingOutcome(err), err)
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
	s.recordExecutionRoutingLookup(ctx, uid, in, "CONTINUATION_HISTORY", executionRoutingOutcome(err), err)
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

func metadataString(metadata map[string]any, key string) string {
	if metadata == nil {
		return ""
	}
	value, _ := metadata[key].(string)
	return strings.TrimSpace(value)
}

func metadataNumber(metadata map[string]any, key string) float64 {
	if metadata == nil {
		return 0
	}
	switch value := metadata[key].(type) {
	case float64:
		return value
	case float32:
		return float64(value)
	case int:
		return float64(value)
	case int64:
		return float64(value)
	case json.Number:
		parsed, _ := value.Float64()
		return parsed
	}
	return 0
}

func metadataSliceNonEmpty(metadata map[string]any, key string) bool {
	if metadata == nil {
		return false
	}
	switch value := metadata[key].(type) {
	case []any:
		return len(value) > 0
	case []map[string]any:
		return len(value) > 0
	case []string:
		return len(value) > 0
	}
	return false
}

func previousTurnFromAssistant(message model.Message) runtimeclient.PreviousTurnContext {
	context := runtimeclient.PreviousTurnContext{
		Exists: true, Status: strings.TrimSpace(message.Status), ExecutionRoute: "NONE",
	}
	metadata := message.Metadata
	context.RuntimePhase = metadataString(metadata, "runtimePhase")
	if route := metadataString(metadata, "executionRoute"); route == "FAST_PATH" || route == "RUNTIME" {
		context.ExecutionRoute = route
	}

	// Assistant messages intentionally contain only sanitized execution
	// metadata. InteractiveFastPath is authoritative for a completed fast-path
	// answer; all other persisted runtime phases are treated as Runtime.
	if context.ExecutionRoute == "NONE" {
		if selected, ok := metadata["selectedAgents"].([]any); ok {
			for _, item := range selected {
				if name, ok := item.(string); ok && name == "InteractiveFastPath" {
					context.ExecutionRoute = "FAST_PATH"
					break
				}
			}
		}
	}
	if context.ExecutionRoute == "NONE" {
		if selected, ok := metadata["selectedAgents"].([]string); ok {
			for _, name := range selected {
				if name == "InteractiveFastPath" {
					context.ExecutionRoute = "FAST_PATH"
					break
				}
			}
		}
	}
	if context.ExecutionRoute == "NONE" && context.RuntimePhase != "" {
		context.ExecutionRoute = "RUNTIME"
	}

	context.KnowledgeUsed = metadataSliceNonEmpty(metadata, "citations")
	if observability, ok := metadata["observability"].(map[string]any); ok {
		context.KnowledgeUsed = context.KnowledgeUsed || metadataNumber(observability, "ragHits") > 0
		context.ToolUsed = metadataNumber(observability, "toolCalls") > 0
		context.MCPUsed = metadataNumber(observability, "mcpEvents") > 0
	}
	return context
}

// resolvePreviousTurnContext returns privacy-safe execution metadata only. The
// assistant text itself never crosses the preflight boundary; normal execution
// receives bounded history separately after routing.
func (s *TaskService) resolvePreviousTurnContext(ctx context.Context, uid int64, in RunTaskInput) (runtimeclient.PreviousTurnContext, error) {
	if in.ConversationID == nil || s.messages == nil {
		return runtimeclient.PreviousTurnContext{ExecutionRoute: "NONE"}, nil
	}
	messages, err := s.messages.ListMessages(ctx, uid, *in.ConversationID, 8)
	s.recordExecutionRoutingLookup(ctx, uid, in, "PREVIOUS_TURN_HISTORY", executionRoutingOutcome(err), err)
	if err != nil {
		return runtimeclient.PreviousTurnContext{}, err
	}
	for i := len(messages) - 1; i >= 0; i-- {
		if messages[i].Role == "assistant" && strings.TrimSpace(messages[i].Content) != "" {
			return previousTurnFromAssistant(messages[i]), nil
		}
	}
	return runtimeclient.PreviousTurnContext{ExecutionRoute: "NONE"}, nil
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
		var lookupDiagnostics []projectRuntimeLookupDiagnostic
		project, lookupDiagnostics, err = s.resolveProjectRuntimeForRoutingDetailed(ctx, uid, *in.ConversationID)
		s.recordProjectRuntimeLookupDiagnostics(ctx, uid, in, "", lookupDiagnostics)
		projectOutcome := "MISS"
		if project != nil {
			projectOutcome = "FOUND"
		}
		if err != nil {
			projectOutcome = "ERROR"
		}
		s.recordExecutionRoutingLookup(ctx, uid, in, "CONVERSATION_PROJECT_RUNTIME", projectOutcome, err)
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
	s.recordExecutionRoutingLookup(ctx, uid, in, "RAG_POLICY", executionRoutingOutcome(err), err)
	if err != nil {
		return nil, err
	}
	if err := s.settleReferencedPreviousTurnBeforeRouting(ctx, uid, in); err != nil {
		return nil, err
	}
	continuation, err := s.resolveContinuationState(ctx, uid, in)
	if err != nil {
		return nil, err
	}
	previousTurn, err := s.resolvePreviousTurnContext(ctx, uid, in)
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
			s.recordExecutionRoutingLookup(ctx, uid, in, "MODEL_POOL", executionRoutingOutcome(modelErr), modelErr)
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
		PreviousTurn: previousTurn,
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
		ExecutionIntent:         proposal.ExecutionIntent,
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
	if proposal.ExecutionIntent == nil || proposal.ExecutionIntent.Version != "execution-intent.v1" {
		return errors.New("missing or invalid execution intent")
	}
	if proposal.ExecutionIntent.Dependencies.Knowledge != proposal.KnowledgeDependency {
		return errors.New("route knowledge dependency diverges from execution intent")
	}
	if proposal.ExecutionIntent.SemanticSource != "RULE" && proposal.ExecutionIntent.SemanticSource != "MODEL" {
		return errors.New("invalid execution intent source")
	}
	if len(proposal.ExecutionIntent.Capabilities.RequiredCapabilities) > 32 || len(proposal.ExecutionIntent.Capabilities.ForbiddenCapabilities) > 32 || len(proposal.ExecutionIntent.RequestedEffects) > 4 {
		return errors.New("execution intent contract size exceeded")
	}
	intentDeps := proposal.ExecutionIntent.Dependencies
	intentRuntimeDependency := intentDeps.Knowledge != "NONE" || intentDeps.Memory || intentDeps.FreshData ||
		intentDeps.ExternalSystem || intentDeps.Tool || intentDeps.MCP || intentDeps.Agent || intentDeps.MultiStep || intentDeps.SideEffect
	if proposal.ExecutionIntent.Clarification.Required && proposal.Disposition != "CLARIFY" {
		return errors.New("execution intent clarification diverges from route disposition")
	}
	if proposal.Disposition == "CLARIFY" && !proposal.ExecutionIntent.Clarification.Required {
		return errors.New("route clarification missing from execution intent")
	}
	if proposal.ExecutionIntent.Reference.RequiresExternalResolution && proposal.ExecutionIntent.Reference.ResolvableFromTrustedHistory {
		return errors.New("invalid execution intent reference resolution")
	}
	refResolution := proposal.ExecutionIntent.Reference.TrustedHistoryResolution
	if refResolution != "NONE" && refResolution != "REQUIRED" && refResolution != "RESOLVED" {
		return errors.New("invalid trusted history resolution state")
	}
	if refResolution == "REQUIRED" {
		if proposal.ExecutionIntent.Reference.ResolvableFromTrustedHistory ||
			proposal.ExecutionIntent.Reference.RequiresExternalResolution ||
			proposal.ExecutionIntent.Reference.TargetScope != "HISTORY" {
			return errors.New("invalid pending trusted history resolution")
		}
	}
	if refResolution == "RESOLVED" && !proposal.ExecutionIntent.Reference.ResolvableFromTrustedHistory {
		return errors.New("resolved trusted history reference is not marked resolvable")
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
		if decision.RuntimePath != "FAST_PATH" || proposal.CapabilityRequired || proposal.KnowledgeDependency != "NONE" || intentRuntimeDependency || policy.Mode == model.RagModeOn {
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
	if in.ExecutionIntent != nil && in.ExecutionIntent.Version == "execution-intent.v1" {
		details["intentVersion"] = in.ExecutionIntent.Version
		details["taskType"] = in.ExecutionIntent.TaskType
		details["continuation"] = in.ExecutionIntent.Continuation.Relation
		details["reference"] = in.ExecutionIntent.Reference.Type
		details["requiredCapabilities"] = append([]string(nil), in.ExecutionIntent.Capabilities.RequiredCapabilities...)
		details["knowledgeDependency"] = in.ExecutionIntent.Dependencies.Knowledge
		details["toolRequired"] = in.ExecutionIntent.Dependencies.Tool
		details["mcpRequired"] = in.ExecutionIntent.Dependencies.MCP
		details["sideEffect"] = in.ExecutionIntent.Dependencies.SideEffect
		details["clarificationRequired"] = in.ExecutionIntent.Clarification.Required
	}
	detail, _ := json.Marshal(details)
	return []map[string]any{{
		"kind": "routing", "title": "Execution Route Decision",
		"status": "completed", "detail": string(detail), "elapsedMs": int64(0),
	}}
}
