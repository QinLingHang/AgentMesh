// Legacy contract markers: Overall Score | Budget Compliance | Groundedness | Tool Reliability | RAG Quality | Memory Contribution | Model Cost | Model Tokens
// Compatibility contract keywords: Overall Score | Budget Compliance | Groundedness | Tool Reliability | RAG Quality | Memory Contribution | Model Cost | Model Tokens
import type { RunResult } from "../../types";
import {
  formatCompactNumber,
  formatDurationMs,
  formatMoney,
} from "../../utils/format";

function percent(value: number) {
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
}

function EvalMetric({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <article className="p6-eval-metric">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  );
}

export function EvalScorecardPanel({
  result,
}: {
  result: RunResult;
}) {
  const scorecard = result.scorecard;

  if (!scorecard) {
    return (
      <section className="detail-section p6-eval-empty">
        <div className="section-title">
          <div>
            <h3>质量评估</h3>
            <p>当前运行没有生成质量评分卡；主任务结果不受质量评估功能可用性的影响。</p>
          </div>
        </div>
      </section>
    );
  }

  const badgeText =
    scorecard.status === "pass"
      ? "通过"
      : scorecard.status === "warning"
        ? "需要关注"
        : scorecard.status === "fail"
          ? "未通过"
          : "不可用";

  return (
    <section className="detail-section p6-eval-section">
      <div className="section-title">
        <div>
          <h3>质量评估</h3>
          <p>
            统一查看回答质量、事实依据、工具/知识检索/长期记忆贡献，以及耗时、成本和质量预算是否满足。
          </p>
        </div>
        <span className={`p6-eval-badge ${scorecard.status}`}>
          {badgeText}
        </span>
      </div>

      <div className="p6-eval-hero">
        <div>
          <span>综合评分</span>
          <strong>{scorecard.overallScore.toFixed(3)}</strong>
          <small>{scorecard.evaluator}</small>
        </div>
        <div>
          <span>失败分类</span>
          <strong>{scorecard.failureCategory}</strong>
          <small>
            {scorecard.violations.length > 0
              ? `${scorecard.violations.length} 条策略或预算异常`
              : "没有策略或预算异常"}
          </small>
        </div>
      </div>

      <div className="p6-eval-grid">
        <EvalMetric label="任务完成度" value={percent(scorecard.taskSuccess)} detail="最终任务是否顺利完成" />
        <EvalMetric label="回答质量" value={percent(scorecard.answerQuality)} detail="智能体质量评估结果" />
        <EvalMetric label="事实依据充分度" value={percent(scorecard.groundedness)} detail="知识检索与引用依据" />
        <EvalMetric label="工具可靠性" value={percent(scorecard.toolReliability)} detail="工具与外部服务执行可靠性" />
        <EvalMetric label="知识检索质量" value={percent(scorecard.ragQuality)} detail="检索证据与引用质量" />
        <EvalMetric label="记忆贡献" value={percent(scorecard.memoryContribution)} detail="用户长期记忆使用情况" />
        <EvalMetric label="预算符合度" value={percent(scorecard.budgetCompliance)} detail="耗时 / 成本 / 质量约束" />
        <EvalMetric label="运行耗时" value={formatDurationMs(scorecard.latencyMs)} detail="端到端运行耗时" />
        <EvalMetric label="运行成本" value={formatMoney(scorecard.estimatedCost)} detail="智能体运行成本估算" />
        <EvalMetric
          label="模型成本"
          value={result.observability.modelCostKnown ? formatMoney(scorecard.modelEstimatedCost) : "未配置"}
          detail="按模型用量价格估算"
        />
        <EvalMetric label="模型用量" value={formatCompactNumber(scorecard.modelTokens)} detail="所有模型调用累计用量" />
      </div>

      {scorecard.violations.length > 0 && (
        <div className="p6-eval-violations">
          <strong>策略与预算信号</strong>
          <div>
            {scorecard.violations.map((item) => (
              <span key={item}>{item}</span>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
