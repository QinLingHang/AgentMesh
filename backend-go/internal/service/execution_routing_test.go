package service

import (
	"encoding/json"
	"example.com/agentmesh-control-plane/internal/model"
	runtimeclient "example.com/agentmesh-control-plane/internal/runtime"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func routeProposal(route string) runtimeclient.ExecutionRoutingResponse {
	return runtimeclient.ExecutionRoutingResponse{
		SchemaVersion: executionRoutingVersion, ExecutionRoute: route, Disposition: "EXECUTE", KnowledgeDependency: "NONE", ReasonCodes: []string{"CONTRACT_TEST"},
	}
}
func routeDecision(route string) ExecutionRouteDecision {
	path := "FULL_RUNTIME"
	if route == "FAST_PATH" {
		path = "FAST_PATH"
	}
	return ExecutionRouteDecision{SchemaVersion: executionRoutingVersion, Strategy: route, Disposition: "EXECUTE", RuntimePath: path, DeliveryMode: "direct", AnalysisSource: "RULE", ReasonCodes: []string{"CONTRACT_TEST"}}
}
func TestBinaryRouteAllowsModelOnly(t *testing.T) {
	p := routeProposal("FAST_PATH")
	d := routeDecision("FAST_PATH")
	if err := ValidateExecutionRouteDecision(d, p, model.RagPolicy{}); err != nil {
		t.Fatal(err)
	}
}
func TestBinaryRouteAllowsRuntimeWithoutChoosingCapabilities(t *testing.T) {
	p := routeProposal("RUNTIME")
	p.CapabilityRequired = true
	p.KnowledgeDependency = "REQUIRED"
	d := routeDecision("RUNTIME")
	if err := ValidateExecutionRouteDecision(d, p, model.RagPolicy{Mode: model.RagModeAuto}); err != nil {
		t.Fatal(err)
	}
}
func TestRuntimeDependencyCannotBecomeFastPath(t *testing.T) {
	p := routeProposal("FAST_PATH")
	p.CapabilityRequired = true
	if err := ValidateExecutionRouteDecision(routeDecision("FAST_PATH"), p, model.RagPolicy{}); err == nil {
		t.Fatal("tool dependency must not bypass Runtime")
	}
	p.CapabilityRequired = false
	p.KnowledgeDependency = "REQUIRED"
	if err := ValidateExecutionRouteDecision(routeDecision("FAST_PATH"), p, model.RagPolicy{}); err == nil {
		t.Fatal("implicit Knowledge must not bypass Runtime")
	}
	p.KnowledgeDependency = "NONE"
	if err := ValidateExecutionRouteDecision(routeDecision("FAST_PATH"), p, model.RagPolicy{Mode: model.RagModeOn}); err == nil {
		t.Fatal("RAG ON must not bypass Runtime")
	}
}
func TestRouterRemainsBinaryAndHasNoCapabilitySelector(t *testing.T) {
	p := routeProposal("RUNTIME")
	d := routeDecision("RUNTIME")
	if err := ValidateExecutionRouteDecision(d, p, model.RagPolicy{}); err != nil {
		t.Fatal(err)
	}
	raw, err := json.Marshal(d)
	if err != nil {
		t.Fatal(err)
	}
	for _, forbidden := range []string{"capabilityKind", "matchedCapabilityRefs", "catalogVersion", "needsPlanner", "requiresApproval"} {
		if strings.Contains(string(raw), forbidden) {
			t.Fatalf("Go binary route leaked specific capability field: %s", forbidden)
		}
	}
	d.Strategy = "FAST_PATH"
	if err := ValidateExecutionRouteDecision(d, p, model.RagPolicy{}); err == nil {
		t.Fatal("route proposal mismatch must fail closed")
	}
}

func TestClarificationCannotCreateRuntimeExecution(t *testing.T) {
	p := routeProposal("RUNTIME")
	p.Disposition = "CLARIFY"
	p.UnresolvedRequirements = []string{"missing target"}
	d := routeDecision("RUNTIME")
	d.RuntimePath = "NONE"
	d.Disposition = "CLARIFY"
	d.UnresolvedRequirements = p.UnresolvedRequirements
	if err := ValidateExecutionRouteDecision(d, p, model.RagPolicy{}); err != nil {
		t.Fatal(err)
	}
	d.RuntimePath = "FULL_RUNTIME"
	if err := ValidateExecutionRouteDecision(d, p, model.RagPolicy{}); err == nil {
		t.Fatal("clarification cannot start Runtime")
	}
}
func TestInvalidModelOutputAndBudgetFailClosed(t *testing.T) {
	p := routeProposal("LIGHT_RUNTIME")
	d := routeDecision("LIGHT_RUNTIME")
	if err := ValidateExecutionRouteDecision(d, p, model.RagPolicy{}); err == nil {
		t.Fatal("third route must be rejected")
	}
	p = routeProposal("RUNTIME")
	d = routeDecision("RUNTIME")
	p.ModelCalls = 2
	if err := ValidateExecutionRouteDecision(d, p, model.RagPolicy{}); err == nil {
		t.Fatal("unbounded model call metadata")
	}
	p.ModelCalls = 0
	p.SchemaVersion = "legacy-routing.v1"
	if err := ValidateExecutionRouteDecision(d, p, model.RagPolicy{}); err == nil {
		t.Fatal("schema mismatch")
	}
}
func TestRagOffKnowledgeCannotExecute(t *testing.T) {
	p := routeProposal("RUNTIME")
	p.KnowledgeDependency = "REQUIRED"
	p.CapabilityRequired = true
	if err := ValidateExecutionRouteDecision(routeDecision("RUNTIME"), p, model.RagPolicy{Mode: model.RagModeOff}); err == nil {
		t.Fatal("RAG OFF is a hard boundary")
	}
}
func TestModeDefaultsOffAndShadowAvailable(t *testing.T) {
	t.Setenv("EXECUTION_ROUTING_MODE", "unexpected")
	if ExecutionRoutingMode() != "OFF" {
		t.Fatal("unsafe default")
	}
	t.Setenv("EXECUTION_ROUTING_MODE", "SHADOW")
	if ExecutionRoutingMode() != "SHADOW" {
		t.Fatal("shadow missing")
	}
	t.Setenv("EXECUTION_ROUTING_MODE", "ENABLED")
	if ExecutionRoutingMode() != "ENABLED" {
		t.Fatal("enabled missing")
	}
}
func TestRouteTraceDoesNotLeakTaskOrCatalog(t *testing.T) {
	events := executionRoutingTrace(RunTaskInput{ExecutionRoute: "RUNTIME", Task: "PRIVATE_PROMPT", RoutingReasonCodes: []string{"RUNTIME_DEPENDENCY_OR_UNCERTAINTY", "private secret"}}, "durable")
	if len(events) != 1 {
		t.Fatal("missing routing trace")
	}
	detail, _ := events[0]["detail"].(string)
	for _, s := range []string{"PRIVATE", "private", "secret", "PROMPT"} {
		if strings.Contains(detail, s) {
			t.Fatal("private text leaked")
		}
	}
}

func TestDiagnosticMetadataCannotInjectPrivateContent(t *testing.T) {
	p := routeProposal("RUNTIME")
	for _, invalid := range []string{"free form private text", "TOOL:SECRET", "bad\nline", ""} {
		d := routeDecision("RUNTIME")
		d.ReasonCodes = []string{invalid}
		if err := ValidateExecutionRouteDecision(d, p, model.RagPolicy{}); err == nil {
			t.Fatalf("invalid diagnostic reason passed: %q", invalid)
		}
	}
	d := routeDecision("RUNTIME")
	d.AnalysisSource = "injected content"
	if err := ValidateExecutionRouteDecision(d, p, model.RagPolicy{}); err == nil {
		t.Fatal("invalid model source must fail")
	}
}

func TestTaskControlOperationsAreExactNotSubstringMatches(t *testing.T) {
	for command, want := range map[string]string{
		"查询任务状态": "GET_TASK_STATUS", "恢复任务": "RESUME_TASK", "取消当前任务": "CANCEL_TASK",
	} {
		if got := TaskControlOperation(command); got != want {
			t.Fatalf("%q: %s != %s", command, got, want)
		}
	}
	for _, command := range []string{"解释取消任务的概念", "说明取消任务的流程", "查询我的订单状态", "继续解释这个", "取消一下订单"} {
		if got := TaskControlOperation(command); got != "" {
			t.Fatalf("unexpected task operation for %q: %s", command, got)
		}
	}
}

func TestSharedPythonGoBinaryRouteFixture(t *testing.T) {
	data, err := os.ReadFile(filepath.Join("..", "..", "..", "runtime-python", "tests", "fixtures", "execution_route_contract.json"))
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		Request  runtimeclient.ExecutionRoutingRequest  `json:"request"`
		Response runtimeclient.ExecutionRoutingResponse `json:"response"`
	}
	if err := json.Unmarshal(data, &fixture); err != nil {
		t.Fatal(err)
	}
	if fixture.Request.SchemaVersion != executionRoutingVersion || fixture.Response.SchemaVersion != executionRoutingVersion {
		t.Fatal("binary route contract version mismatch")
	}
	if fixture.Request.AllowModel || fixture.Request.Task == "" {
		t.Fatal("invalid fixture")
	}
	d := routeDecision(fixture.Response.ExecutionRoute)
	if err := ValidateExecutionRouteDecision(d, fixture.Response, model.RagPolicy{Mode: model.RagModeAuto}); err != nil {
		t.Fatal(err)
	}
}

func TestExecutionRoutingModelOnlyClarificationIsNotThirdExecutionRoute(t *testing.T) {
	p := routeProposal("FAST_PATH")
	p.Disposition = "CLARIFY"
	p.ReasonCodes = []string{"MISSING_MODEL_INPUT"}
	p.UnresolvedRequirements = []string{"请提供原文"}
	d := routeDecision("FAST_PATH")
	d.Disposition = "CLARIFY"
	d.RuntimePath = "NONE"
	d.UnresolvedRequirements = p.UnresolvedRequirements
	if err := ValidateExecutionRouteDecision(d, p, model.RagPolicy{Mode: model.RagModeAuto}); err != nil {
		t.Fatal(err)
	}
	p.CapabilityRequired = true
	if err := ValidateExecutionRouteDecision(d, p, model.RagPolicy{}); err == nil {
		t.Fatal("clarification must not erase capability requirements")
	}
}

func TestExecutionRoutingPolicyRejectionCannotLaunchRuntime(t *testing.T) {
	p := routeProposal("RUNTIME")
	p.Disposition = "REJECT"
	p.UnresolvedRequirements = []string{"该请求违反安全策略"}
	d := routeDecision("RUNTIME")
	d.Disposition = "REJECT"
	d.RuntimePath = "NONE"
	d.UnresolvedRequirements = p.UnresolvedRequirements
	if err := ValidateExecutionRouteDecision(d, p, model.RagPolicy{}); err != nil {
		t.Fatal(err)
	}
	d.RuntimePath = "FULL_RUNTIME"
	if err := ValidateExecutionRouteDecision(d, p, model.RagPolicy{}); err == nil {
		t.Fatal("rejection must not execute")
	}
}

func TestExecutionRoutingApprovalRejectionAndTaskStatusAreStrictCommands(t *testing.T) {
	cases := map[string]string{
		"上一轮审批我不同意，别继续写入。": "APPROVAL_REJECT",
		"拒绝当前审批":         "APPROVAL_REJECT",
		"刚才那个任务运行到哪一步了？": "GET_TASK_STATUS",
		"停止我当前正在运行的任务。":  "CANCEL_TASK",
	}
	for text, expected := range cases {
		if got := TaskControlOperation(text); got != expected {
			t.Fatalf("%q: got %q want %q", text, got, expected)
		}
	}
	for _, text := range []string{"解释拒绝审批的步骤", "介绍审批拒绝机制", "如何停止任务", "拒绝审批后帮我删除文件", "把订单状态改成取消"} {
		if got := TaskControlOperation(text); got != "" {
			t.Fatalf("non-control task misidentified: %q => %q", text, got)
		}
	}
}

// A conversational reference needs trusted history, but is not automatically
// a request to resume a Durable task or invoke an Agent.
func TestExecutionRoutingDetectsPriorAssistantAnswerReferences(t *testing.T) {
	for _, text := range []string{
		"接着解释刚才的第二点。", "上一条回复最后一段能再解释一下吗？",
		"把我们刚才确认的文案再缩短一点。", "继续执行刚才的任务。",
	} {
		if !referencesPriorContext(text) {
			t.Fatalf("missed history reference: %s", text)
		}
	}
	for _, text := range []string{"你好。", "什么是 Go slice？", "你们的退货政策是什么？"} {
		if referencesPriorContext(text) {
			t.Fatalf("unexpected history reference: %s", text)
		}
	}
}

func TestTaskControlOperationRecognizesFrozenAuthoritativeVariantsWithoutCapturingBusinessRequests(t *testing.T) {
	positive := map[string]string{
		"把上一步没做完的测试继续跑完。":            "RESUME_TASK",
		"接着处理那个还没完成的工单。":             "RESUME_TASK",
		"重试刚才失败的那一步，但不要重复已经发送的通知。":   "RESUME_TASK",
		"先前一次执行已经发出邮件，恢复时别再发第二封。":    "RESUME_TASK",
		"关闭新路由后恢复之前的运行中任务，不要重新建任务。":  "RESUME_TASK",
		"刚才网络断开了，确认是不是已经创建过工单。":      "GET_TASK_STATUS",
		"同一个请求我又发了一遍，请返回上一次的结果。":     "GET_TASK_STATUS",
		"刚执行过一次退款，页面卡住了，帮我确认是否成功。":   "GET_TASK_STATUS",
		"工单创建接口返回未知结果，先查原单号再决定是否重试。": "GET_TASK_STATUS",
		"流式回答中断后核实任务状态，不要再提交一个任务。":   "GET_TASK_STATUS",
		"请告诉我现在排队的是哪个任务。":            "GET_TASK_STATUS",
		"上一轮审批我不同意，别继续写入。":           "APPROVAL_REJECT",
		"停止我当前正在运行的任务。":              "CANCEL_TASK",
	}
	for text, want := range positive {
		if got := TaskControlOperation(text); got != want {
			t.Errorf("TaskControlOperation(%q)=%q want=%q", text, got, want)
		}
	}

	negative := []string{
		"继续解释上一条回复。",
		"帮我解释单元测试的重试机制。",
		"查询订单状态。",
		"取消订单。",
		"恢复出厂设置怎么做？",
		"停止解释这个概念。",
		"退款成功通常是什么意思？",
	}
	for _, text := range negative {
		if got := TaskControlOperation(text); got != "" {
			t.Errorf("ordinary business/chat request %q captured as %q", text, got)
		}
	}
}
