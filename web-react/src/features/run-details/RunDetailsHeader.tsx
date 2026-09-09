import type { RunResult } from "../../types";
import { Icon } from "../../components/common/Icon";
import { RuntimeStatusBadge } from "../../components/common/RuntimeStatusBadge";

export function RunDetailsHeader({
  result,
  onBack,
  display = "page",
}: {
  result: RunResult;
  onBack: () => void;
  display?: "page" | "drawer";
}) {
  if (display === "drawer") {
    return (
      <header className="run-details-shell-head run-details-drawer-head">
        <div className="run-details-drawer-titlebar">
          <div>
            <span className="eyebrow">
              RUN DETAILS
            </span>

            <h2>
              运行详情
            </h2>
          </div>

          <div className="run-details-drawer-actions">
            <RuntimeStatusBadge
              status={result.status}
            />

            <button
              aria-label="关闭运行详情"
              className="icon-button"
              data-testid="run-details-close"
              onClick={onBack}
              type="button"
            >
              <Icon
                name="close"
                size={17}
              />
            </button>
          </div>
        </div>

        <p>
          将 RAG、Agent 调度、DAG、Trace 与反馈独立于最终回答查看。
        </p>

        <div className="run-identity-row">
          <span>
            Task #{result.task.id}
          </span>

          <code>
            {result.task.requestId}
          </code>

          <span>
            {result.selectedAgents.length} Agents
          </span>

          <span>
            {result.citations.length} Citations
          </span>
        </div>
      </header>
    );
  }

  return (
    <header className="run-details-shell-head">
      <button
        className="plain-button back-link"
        onClick={onBack}
        type="button"
      >
        <Icon
          name="back"
          size={16}
        />

        返回工作台
      </button>

      <div className="run-details-title-row">
        <div>
          <div className="eyebrow">
            RUN DETAILS
          </div>

          <h1>
            运行详情
          </h1>

          <p>
            查看一次 Agent Runtime 执行的策略、RAG、DAG、Trace 与反馈。
          </p>
        </div>

        <RuntimeStatusBadge
          status={result.status}
        />
      </div>

      <div className="run-identity-row">
        <span>
          Task #{result.task.id}
        </span>

        <code>
          {result.task.requestId}
        </code>

        <span>
          {result.selectedAgents.length} Agents
        </span>

        <span>
          {result.citations.length} Citations
        </span>
      </div>
    </header>
  );
}
