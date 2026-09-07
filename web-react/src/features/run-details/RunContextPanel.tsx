import type {
  RunResult,
} from "../../types";

function formatProfileValue(
  value: unknown,
) {
  if (
    value == null ||
    value === ""
  ) {
    return "-";
  }

  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return String(value);
  }

  if (Array.isArray(value)) {
    return value
      .slice(0, 4)
      .map(String)
      .join(", ");
  }

  return "structured";
}

export function RunContextPanel({
  result,
}: {
  result: RunResult;
}) {
  const taskProfileEntries =
    Object.entries(
      result.taskProfile ?? {},
    ).slice(0, 6);

  return (
    <section className="detail-section run-context-section">
      <div className="section-title">
        <div>
          <h3>
            运行上下文
          </h3>

          <p>
            本次执行冻结的策略、参与 Agent 与对外可见的运行资产。
          </p>
        </div>
      </div>

      <div className="run-context-grid">
        <article className="run-context-card">
          <div className="run-context-card-head">
            <span>
              Runtime Policy
            </span>

            <small>
              frozen for this run
            </small>
          </div>

          <div className="run-context-policy-list">
            <div>
              <span>
                调度
              </span>
              <strong>
                {result.scheduler}
              </strong>
            </div>

            <div>
              <span>
                协作规划
              </span>
              <strong>
                {result.planner}
              </strong>
            </div>

            <div>
              <span>
                执行
              </span>
              <strong>
                {result.executionMode}
              </strong>
            </div>

            <div>
              <span>
                合成
              </span>
              <strong>
                {result.synthesisMode}
              </strong>
            </div>
          </div>
        </article>

        <article className="run-context-card">
          <div className="run-context-card-head">
            <span>
              Runtime Assets
            </span>

            <small>
              user-facing result
            </small>
          </div>

          <div className="run-context-asset-grid">
            <div>
              <strong>
                {result.selectedAgents.length}
              </strong>
              <span>
                Agents
              </span>
            </div>

            <div>
              <strong>
                {result.citations.length}
              </strong>
              <span>
                Citations
              </span>
            </div>

            <div>
              <strong>
                {result.trace.length}
              </strong>
              <span>
                Trace Events
              </span>
            </div>

            <div>
              <strong>
                {result.agentFeedback.length}
              </strong>
              <span>
                Feedback
              </span>
            </div>
          </div>
        </article>
      </div>

      <div className="run-context-subgrid">
        <article className="run-context-subcard">
          <div className="run-context-card-head">
            <span>
              Selected Agents
            </span>

            <small>
              {result.selectedAgents.length} selected
            </small>
          </div>

          {result.selectedAgents.length > 0 ? (
            <div className="overview-agent-list">
              {result.selectedAgents.map(
                (agent) => (
                  <span
                    key={agent}
                  >
                    {agent}
                  </span>
                ),
              )}
            </div>
          ) : (
            <p className="overview-muted-copy">
              本次运行没有记录选中的 Agent。
            </p>
          )}
        </article>

        <article className="run-context-subcard">
          <div className="run-context-card-head">
            <span>
              Task Profile
            </span>

            <small>
              runtime classification
            </small>
          </div>

          {taskProfileEntries.length > 0 ? (
            <div className="task-profile-list">
              {taskProfileEntries.map(
                ([key, value]) => (
                  <div key={key}>
                    <span>
                      {key}
                    </span>

                    <strong>
                      {formatProfileValue(
                        value,
                      )}
                    </strong>
                  </div>
                ),
              )}
            </div>
          ) : (
            <p className="overview-muted-copy">
              Runtime 没有返回额外的 Task Profile 字段。
            </p>
          )}
        </article>
      </div>
    </section>
  );
}
