import type { RunResult } from "../../types";
import { runtimeStatusText } from "../../components/common/RuntimeStatusBadge";
import {
  formatCompactNumber,
  formatDurationMs,
  formatMoney,
} from "../../utils/format";

function SummaryItem({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="run-summary-item">
      <span>
        {label}
      </span>

      <strong>
        {value}
      </strong>

      {hint && (
        <small>
          {hint}
        </small>
      )}
    </div>
  );
}

export function RunSummaryStrip({
  result,
}: {
  result: RunResult;
}) {
  const observability =
    result.observability;

  const quality =
    result.scorecard
      ? result.scorecard.overallScore.toFixed(3)
      : observability.qualityEvaluations > 0
        ? observability.averageQuality.toFixed(3)
        : "-";

  return (
    <section className="run-summary-strip">
      <SummaryItem
        label="状态"
        value={runtimeStatusText(
          result.status,
        )}
        hint={`Task #${result.task.id}`}
      />

      <SummaryItem
        label="总耗时"
        value={formatDurationMs(
          result.elapsedMs,
        )}
        hint="端到端 Runtime"
      />

      <SummaryItem
        label="Agent 执行成本估算"
        value={formatMoney(
          result.estimatedCost,
        )}
        hint="基于 Agent 能力画像，不等于模型 Token 费用"
      />

      <SummaryItem
        label={result.scorecard ? "质量评分" : "质量"}
        value={quality}
        hint={result.scorecard ? result.scorecard.status : `${observability.qualityEvaluations} 次 Eval`}
      />

      <SummaryItem
        label="模型用量"
        value={formatCompactNumber(
          observability.modelTotalTokens,
        )}
        hint={`${observability.modelCalls} 次模型调用`}
      />
    </section>
  );
}
