import type { RunResult } from "../../types";
import { Icon } from "../../components/common/Icon";

export function LatestRunMeta({
  result,
  openDetails,
  historical = false,
}: {
  result: RunResult;
  openDetails: () => void;
  historical?: boolean;
}) {
  const elapsedSeconds = Math.max(1, Math.round(result.elapsedMs / 1000));

  return (
    <div className="result-meta result-meta-compact">
      <div className="result-meta-hint">
        <span className="result-meta-dot" />

        <span>
          {historical
            ? "历史结果已恢复"
            : "本次任务已完成"}
        </span>

        <small>
          约 {elapsedSeconds} 秒完成 · 执行过程可按需查看
        </small>
      </div>

      <button
        className="run-detail-link"
        onClick={openDetails}
        type="button"
      >
        运行详情
        <Icon name="arrow" size={14} />
      </button>
    </div>
  );
}
