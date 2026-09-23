package service

import (
	"context"
	"strings"

	"example.com/agentmesh-control-plane/internal/model"
)

// P23TaskOperation recognizes only unambiguous task-control commands. Generic
// occurrences of "status", "continue", or "cancel" inside a business request
// must remain ordinary task content and pass through task understanding.
func p23TaskCommandContainsAny(command string, values ...string) bool {
	for _, value := range values {
		if strings.Contains(command, value) {
			return true
		}
	}
	return false
}

func p23NormalizeTaskCommand(text string) string {
	command := strings.ToLower(strings.TrimSpace(text))
	return strings.Trim(command, " \t\r\n。！!？?，,；;")
}

// p23TaskControlCompoundSideEffect prevents an authoritative task-control
// shortcut from swallowing a second requested business mutation. A request
// such as "拒绝审批后帮我删除文件" must return to the normal governed
// execution path so approval rejection and the new side effect are evaluated
// separately. Negative safety constraints ("后不要删除", "别再发送") are
// deliberately not treated as a second requested side effect.
func p23TaskControlCompoundSideEffect(command string) bool {
	separators := []string{"然后", "之后", "以后", "后", "再帮", "并且", "并", "同时"}
	sideEffects := []string{
		"删除", "移除", "修改", "改写", "写入", "覆盖", "保存",
		"发送", "发邮件", "发消息", "创建", "提交", "上传",
		"退款", "付款", "支付", "转账", "执行脚本", "运行命令",
	}
	negations := []string{"不要", "别", "不得", "禁止", "不能", "不再", "别再", "无需"}

	for _, separator := range separators {
		start := 0
		for {
			rel := strings.Index(command[start:], separator)
			if rel < 0 {
				break
			}
			idx := start + rel
			tail := strings.TrimSpace(command[idx+len(separator):])
			if tail == "" {
				break
			}
			requestedEffect := false
			for _, effect := range sideEffects {
				effectIdx := strings.Index(tail, effect)
				if effectIdx < 0 {
					continue
				}
				prefix := tail[:effectIdx]
				negated := false
				for _, negation := range negations {
					if strings.Contains(prefix, negation) {
						negated = true
						break
					}
				}
				if !negated {
					requestedEffect = true
					break
				}
			}
			if requestedEffect {
				return true
			}
			start = idx + len(separator)
		}
	}
	return false
}

// p23TaskControlMetaDiscussion excludes requests that discuss task-control
// concepts instead of exercising them. This check runs before exact and
// compositional command matching so phrases such as "解释取消任务的概念" or
// "解释拒绝审批的步骤" can never become authoritative state mutations.
func p23TaskControlMetaDiscussion(command string) bool {
	prefixes := []string{"解释", "说明", "介绍", "什么是", "如何", "怎么", "为何", "为什么", "explain", "what is", "how to"}
	for _, prefix := range prefixes {
		if strings.HasPrefix(command, prefix) {
			return true
		}
	}
	return p23TaskCommandContainsAny(command, "概念", "步骤", "流程", "机制", "教程") &&
		p23TaskCommandContainsAny(command, "任务", "审批", "approval", "cancel", "resume")
}

// P23TaskOperation recognizes high-confidence operations on an already-owned
// Task. It deliberately does not classify ordinary business verbs such as
// "取消订单" or "查询订单状态" as task control. Ambiguous language stays in the
// normal P23 understanding path instead of guessing a Task ID or side effect.
func P23TaskOperation(text string) string {
	command := p23NormalizeTaskCommand(text)
	if p23TaskControlMetaDiscussion(command) || p23TaskControlCompoundSideEffect(command) {
		return ""
	}
	switch command {
	case "上一轮审批我不同意，别继续写入", "上一轮审批我不同意", "拒绝上一次审批", "拒绝当前审批", "拒绝审批", "我拒绝这次审批", "reject approval", "deny approval":
		return "APPROVAL_REJECT"
	case "查看任务进度", "查询任务进度", "任务进度", "当前任务进度", "查看当前任务进度",
		"查看上一个任务进度", "查看任务状态", "查询任务状态", "当前任务状态",
		"查看当前任务状态", "任务执行到哪了", "刚才那个任务运行到哪一步了", "现在排队的是哪个任务", "请告诉我现在排队的是哪个任务", "task status", "task progress":
		return "GET_TASK_STATUS"
	case "继续任务", "继续执行任务", "恢复任务", "继续当前任务", "恢复当前任务",
		"继续执行刚才的任务", "resume task", "continue task":
		return "RESUME_TASK"
	case "取消任务", "取消当前任务", "终止任务", "停止当前任务", "停止我当前正在运行的任务", "cancel task", "stop task":
		return "CANCEL_TASK"
	}

	// Approval rejection is allowed only when the utterance explicitly refers
	// to an approval/authorization decision; generic "不同意" remains content.
	if p23TaskCommandContainsAny(command, "审批", "approval") &&
		p23TaskCommandContainsAny(command, "拒绝", "不同意", "不批准", "别继续写入", "reject", "deny") {
		return "APPROVAL_REJECT"
	}

	// Unknown-outcome recovery must query authoritative state before retrying.
	// These pairs intentionally require both a prior/interrupted execution cue
	// and an outcome/status cue so a normal order-status query is not captured.
	priorExecution := p23TaskCommandContainsAny(command,
		"网络断开", "页面卡住", "未知结果", "同一个请求", "流式回答中断",
		"刚执行过一次", "工单创建接口", "上一次的结果", "刚才的任务")
	statusCheck := p23TaskCommandContainsAny(command,
		"确认是不是已经", "确认是否成功", "核实任务状态", "返回上一次的结果",
		"先查原单号", "是否已经创建", "运行到哪", "排队的是哪个任务")
	if (priorExecution && statusCheck) ||
		(p23TaskCommandContainsAny(command, "任务", "工单") && p23TaskCommandContainsAny(command, "进度", "任务状态", "运行到哪", "排队")) {
		return "GET_TASK_STATUS"
	}

	// Cancellation requires an explicit Task/execution target. Product/order
	// cancellation remains a Runtime business action, not Task cancellation.
	if p23TaskCommandContainsAny(command, "取消", "终止", "停止", "cancel", "stop") &&
		p23TaskCommandContainsAny(command, "任务", "当前正在运行", "当前执行", "运行中的任务") {
		return "CANCEL_TASK"
	}

	// Resume requires both a resume/retry verb and evidence that the user means
	// previously unfinished execution. This keeps chat follow-ups ("继续解释")
	// and general concepts ("重试机制") out of the authoritative Task branch.
	resumeVerb := p23TaskCommandContainsAny(command,
		"恢复", "重试", "继续跑完", "继续处理", "接着处理", "继续执行", "resume", "retry")
	priorWork := p23TaskCommandContainsAny(command,
		"没做完", "还没完成", "失败的那一步", "刚才失败", "先前一次执行", "之前的运行中任务",
		"已经发出邮件", "不要重复已经", "别再发第二", "没完成的工单", "未完成的工单")
	if resumeVerb && priorWork {
		return "RESUME_TASK"
	}
	return ""
}

// P23PendingTask resolves exactly one currently actionable task in the owned
// conversation. It never guesses the newest task when two candidates exist.
func (s *TaskService) P23PendingTask(ctx context.Context, uid int64, in RunTaskInput) (*model.Task, error) {
	if in.ConversationID == nil || s.tasks == nil {
		return nil, ErrInvalidInput
	}
	if s.projectRuntime != nil {
		if _, err := s.projectRuntime.ResolveForConversation(ctx, uid, *in.ConversationID); err != nil {
			return nil, err
		}
	}
	tasks, err := s.tasks.ListTasks(ctx, uid, 50)
	if err != nil {
		return nil, err
	}
	var selected *model.Task
	for i := range tasks {
		task := &tasks[i]
		if task.ConversationID == nil || *task.ConversationID != *in.ConversationID {
			continue
		}
		switch task.Status {
		case "RUNNING", "QUEUED", "DISPATCHING", "RESULT_PENDING", "COMPLETING", "INPUT_REQUIRED", "AUTH_REQUIRED":
			if selected != nil {
				return nil, ErrConflict
			}
			selected = task
		}
	}
	if selected == nil {
		return nil, ErrNotFound
	}
	return selected, nil
}

func (s *TaskService) P23StatusTask(ctx context.Context, uid int64, in RunTaskInput) (*model.Task, error) {
	return s.P23PendingTask(ctx, uid, in)
}

// P23ResumeCurrentTask is a safe task-state response, NOT an automatic replay.
// A bare "continue task" supplies neither missing input nor tool approval;
// re-executing with a made-up "continue" argument could cause side effects.
// The caller must use the existing task-id resume/approval endpoint with the
// real supplement or an explicit approve/reject decision.
func (s *TaskService) P23ResumeCurrentTask(ctx context.Context, uid int64, in RunTaskInput) (*RunTaskResult, error) {
	task, err := s.P23PendingTask(ctx, uid, in)
	if err != nil {
		return nil, err
	}
	if task.Status != "INPUT_REQUIRED" || task.Continuation == nil {
		return nil, ErrConflict
	}
	return replayDirectTask(task), nil
}

// P23RejectCurrentApproval resolves an owned, unique AUTH_REQUIRED approval
// and delegates to the existing CAS-protected TaskService.Resume rejection.
// This endpoint never approves, invents an approval ID, or submits a new job.
func (s *TaskService) P23RejectCurrentApproval(ctx context.Context, uid int64, in RunTaskInput) (*RunTaskResult, error) {
	if in.ConversationID == nil || s.tasks == nil {
		return nil, ErrInvalidInput
	}
	if s.projectRuntime != nil {
		if _, err := s.projectRuntime.ResolveForConversation(ctx, uid, *in.ConversationID); err != nil {
			return nil, err
		}
	}
	items, err := s.tasks.ListTasks(ctx, uid, 50)
	if err != nil {
		return nil, err
	}
	var approval *model.Task
	for i := range items {
		candidate := &items[i]
		if candidate.ConversationID == nil || *candidate.ConversationID != *in.ConversationID ||
			candidate.Status != "AUTH_REQUIRED" || candidate.Continuation == nil ||
			(candidate.Continuation.Kind != "tool_approval" && candidate.Continuation.Protocol != "tool_approval") {
			continue
		}
		if approval != nil {
			return nil, ErrConflict // Never select an arbitrary approval.
		}
		approval = candidate
	}
	if approval == nil {
		return nil, ErrNotFound
	}
	return s.Resume(ctx, uid, approval.ID, "reject")
}
