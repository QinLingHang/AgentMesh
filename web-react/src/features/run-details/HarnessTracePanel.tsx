// P37 Agent Harness run detail panel.
// 呈现模式、最终状态、校验、诊断、恢复、预算消耗与状态时间线。
// 旧任务没有 harness 数据时不渲染本页签（见 RunDetailsTabs）。
import type {
  HarnessDiagnosis,
  HarnessEvent,
  HarnessRecovery,
  HarnessReport,
  HarnessValidationResult,
  RunResult,
} from "../../types";

const severityLabels: Record<string, string> = {
  info: "信息",
  warning: "警告",
  error: "错误",
};

const stateLabels: Record<string, string> = {
  CREATED: "已创建",
  PRECHECK: "前置校验",
  EXECUTING: "执行中",
  TOOL_GUARD: "工具防护",
  STEP_VALIDATING: "步骤校验",
  RESULT_VALIDATING: "结果校验",
  DIAGNOSING: "失败诊断",
  RECOVERING: "恢复中",
  COMPLETED: "已完成",
  TERMINATED: "已终止",
};

const outcomeLabels: Record<string, string> = {
  COMPLETED: "业务成功",
  TERMINATED: "已终止",
  OBSERVED_ISSUES: "成功（观察到问题）",
};

const actionLabels: Record<string, string> = {
  REPAIR_ARGS: "参数修复",
  RETRY: "重试",
  FALLBACK: "显式回退",
  REPLAN: "重规划",
  TERMINATE: "终止",
};

const categoryLabels: Record<string, string> = {
  INPUT: "输入",
  OUTPUT: "输出",
  TOOL: "工具",
  STEP: "步骤",
  RESULT: "结果",
  LOOP: "循环",
  TIMEOUT: "超时",
  AUTHORIZATION: "授权",
  UNKNOWN: "未知",
};

function MetricRow({ label, value }: { label: string; value: string | number }) {
  return (
    <span>
      {label} <strong>{value}</strong>
    </span>
  );
}

function ValidationCard({ validation }: { validation: HarnessValidationResult }) {
  return (
    <article className="harness-validation-card">
      <header>
        <strong>{validation.validator}</strong>
        <span
          className={`harness-status-badge harness-status-${validation.status.toLowerCase()}`}
        >
          {validation.status === "PASS"
            ? "通过"
            : validation.status === "FAIL"
              ? "失败"
              : "未配置"}
        </span>
      </header>
      {validation.code && validation.code !== "OK" && (
        <code>{validation.code}</code>
      )}
      {validation.message && <p>{validation.message}</p>}
      {validation.fieldPaths && validation.fieldPaths.length > 0 && (
        <p className="harness-field-paths">
          字段：{validation.fieldPaths.join("、")}
        </p>
      )}
    </article>
  );
}

function DiagnosisCard({ diagnosis }: { diagnosis: HarnessDiagnosis }) {
  return (
    <article className="harness-diagnosis-card">
      <header>
        <strong>
          {categoryLabels[diagnosis.category] ?? diagnosis.category}
          {" · "}
          <code>{diagnosis.rootCauseCode}</code>
        </strong>
        <span>
          建议：
          {actionLabels[diagnosis.recommendedAction ?? "TERMINATE"] ??
            diagnosis.recommendedAction}
        </span>
      </header>
      {diagnosis.sideEffectRisk && (
        <p>
          副作用风险：
          {diagnosis.sideEffectRisk}
          {diagnosis.retryable ? " · 可重试" : " · 不可自动重试"}
        </p>
      )}
    </article>
  );
}

function RecoveryCard({ recovery }: { recovery: HarnessRecovery }) {
  return (
    <article className="harness-recovery-card">
      <header>
        <strong>{actionLabels[recovery.action] ?? recovery.action}</strong>
        <span className={recovery.success ? "harness-recovery-ok" : "harness-recovery-pending"}>
          {recovery.success ? "已执行" : "未完成"}
        </span>
      </header>
      {recovery.tool && <p>工具：{recovery.tool}</p>}
      {recovery.reason && <p>{recovery.reason}</p>}
    </article>
  );
}

function EventCard({ event }: { event: HarnessEvent }) {
  return (
    <article className="harness-event-card">
      <header>
        <strong>
          #{event.sequence} {event.type}
        </strong>
        <span>
          {stateLabels[event.state] ?? event.state}
          {event.severity && event.severity !== "info"
            ? ` · ${severityLabels[event.severity] ?? event.severity}`
            : ""}
        </span>
      </header>
      {event.subject && <p>{event.subject}</p>}
      {event.validation && (
        <p>
          <code>{event.validation.status}</code> {event.validation.code}
          {event.validation.message ? ` · ${event.validation.message}` : ""}
        </p>
      )}
      {event.recovery && (
        <p>
          恢复：<code>{event.recovery.action}</code>
        </p>
      )}
    </article>
  );
}

export function HarnessTracePanel({ result }: { result: RunResult }) {
  const report: HarnessReport | null | undefined = result.harnessReport;
  const summary = result.harnessSummary;

  if (!report && !summary) {
    return (
      <section className="trace-panel-shell harness-panel-shell">
        <div className="empty-detail-state">本次运行没有 Harness 数据。</div>
      </section>
    );
  }

  const events = report?.events ?? [];
  const diagnoses = report?.diagnoses ?? [];
  const recoveries = report?.recoveries ?? [];
  const timeline = report?.stateTimeline ?? [];
  const metrics = report?.metrics;
  const budget = metrics?.budget;
  const finalValidation = report?.finalValidation;

  const failingValidations = events
    .filter((event) => event.validation?.status === "FAIL")
    .map((event) => event.validation as HarnessValidationResult);

  return (
    <section className="trace-panel-shell harness-panel-shell">
      <div className="section-title">
        <div>
          <h3>Agent Harness</h3>
          <p>
            监督层判定与恢复过程：确定性校验、结构化诊断、白名单恢复与统一预算。
            证据仅包含字段路径、错误码与摘要，不含凭据或完整响应。
          </p>
        </div>
        <span className="detail-count-badge">{events.length} events</span>
      </div>

      <div className="harness-summary-strip">
        <MetricRow label="模式" value={summary?.mode ?? "—"} />
        <MetricRow
          label="Harness 结论"
          value={outcomeLabels[summary?.outcome ?? ""] ?? summary?.outcome ?? "—"}
        />
        <MetricRow label="校验失败" value={summary?.validationFailures ?? metrics?.validationFailures ?? 0} />
        <MetricRow label="修复" value={summary?.repairs ?? 0} />
        <MetricRow label="重试" value={summary?.retries ?? 0} />
        <MetricRow label="重调度" value={summary?.reschedules ?? 0} />
        <MetricRow label="监督开销" value={`${summary?.overheadMs ?? 0} ms`} />
      </div>

      {summary?.terminationReason && (
        <div className="harness-termination">
          终止原因：<code>{summary.terminationReason}</code>
        </div>
      )}

      {budget && (
        <div className="harness-budget">
          <h4>预算消耗</h4>
          <div className="harness-budget-grid">
            <MetricRow label="步骤" value={`${budget.usedSteps ?? 0}/${budget.maxSteps ?? "—"}`} />
            <MetricRow label="修复" value={`${budget.usedRepairs ?? 0}/${budget.maxRepairs ?? "—"}`} />
            <MetricRow label="工具重试" value={`${budget.usedToolRetries ?? 0}/${budget.maxRetriesPerTool ?? "—"}`} />
            <MetricRow label="重调度" value={`${budget.usedReschedules ?? 0}/${budget.maxReschedules ?? "—"}`} />
            <MetricRow label="循环阈值" value={budget.loopRepeatThreshold ?? "—"} />
          </div>
        </div>
      )}

      {timeline.length > 0 && (
        <div className="harness-timeline">
          <h4>状态时间线</h4>
          <ol>
            {timeline.map((entry, index) => (
              <li key={`${entry.state}-${index}`}>
                <strong>{stateLabels[entry.state] ?? entry.state}</strong>
                <span>{entry.elapsedMs} ms</span>
              </li>
            ))}
          </ol>
        </div>
      )}

      {finalValidation && (
        <div className="harness-final-validation">
          <h4>最终结果校验</h4>
          <ValidationCard validation={finalValidation} />
        </div>
      )}

      {failingValidations.length > 0 && (
        <div className="harness-section">
          <h4>校验失败</h4>
          <div className="harness-card-list">
            {failingValidations.map((validation, index) => (
              <ValidationCard key={`validation-${index}`} validation={validation} />
            ))}
          </div>
        </div>
      )}

      {diagnoses.length > 0 && (
        <div className="harness-section">
          <h4>失败诊断</h4>
          <div className="harness-card-list">
            {diagnoses.map((diagnosis, index) => (
              <DiagnosisCard key={`diagnosis-${index}`} diagnosis={diagnosis} />
            ))}
          </div>
        </div>
      )}

      {recoveries.length > 0 && (
        <div className="harness-section">
          <h4>恢复动作</h4>
          <div className="harness-card-list">
            {recoveries.map((recovery, index) => (
              <RecoveryCard key={`recovery-${index}`} recovery={recovery} />
            ))}
          </div>
        </div>
      )}

      {events.length > 0 && (
        <div className="harness-section">
          <h4>Harness 事件</h4>
          <div className="harness-card-list">
            {events.map((event) => (
              <EventCard key={event.eventId} event={event} />
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
