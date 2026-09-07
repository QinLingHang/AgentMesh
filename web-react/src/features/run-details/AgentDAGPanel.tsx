import type { RunResult } from "../../types";
import { DAGPanel } from "./DAGPanel";

export function AgentDAGPanel({
  result,
}: {
  result: RunResult;
}) {
  return (
    <div>
      <section className="detail-section run-detail-section-first">
        <div className="section-title">
          <div>
            <h3>
              协作策略
            </h3>

            <p>
              本次任务实际采用的调度、规划、执行与合成策略。
            </p>
          </div>
        </div>

        <div className="policy-grid">
          <div>
            <span>
              Scheduler
            </span>

            <strong>
              {result.scheduler}
            </strong>
          </div>

          <div>
            <span>
              Planner
            </span>

            <strong>
              {result.planner}
            </strong>
          </div>

          <div>
            <span>
              Execution
            </span>

            <strong>
              {result.executionMode}
            </strong>
          </div>

          <div>
            <span>
              Synthesis
            </span>

            <strong>
              {result.synthesisMode}
            </strong>
          </div>
        </div>
      </section>

      <section className="detail-section">
        <div className="section-title">
          <div>
            <h3>
              参与智能体
            </h3>

            <p>
              Runtime 最终选择并参与执行的 Agent。
            </p>
          </div>
        </div>

        <div className="selected-agent-list">
          {result.selectedAgents.length > 0 ? (
            result.selectedAgents.map(
              (agent) => (
                <div
                  className="selected-agent"
                  key={agent}
                >
                  <span className="agent-avatar">
                    {agent
                      .slice(0, 2)
                      .toUpperCase()}
                  </span>

                  <span>
                    {agent}
                  </span>
                </div>
              ),
            )
          ) : (
            <span className="muted-text">
              暂无
            </span>
          )}
        </div>
      </section>

      <section className="detail-section">
        <div className="section-title">
          <div>
            <h3>
              Dynamic DAG
            </h3>

            <p>
              查看节点状态与实际依赖关系。
            </p>
          </div>
        </div>

        <DAGPanel
          result={result}
        />
      </section>
    </div>
  );
}
