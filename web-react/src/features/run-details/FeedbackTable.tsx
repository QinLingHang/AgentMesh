import type { AgentFeedback } from "../../types";
import { formatMoney } from "../../utils/format";

export function FeedbackTable({
  feedback,
}: {
  feedback: AgentFeedback[];
}) {
  if (
    feedback.length === 0
  ) {
    return (
      <div className="empty-state">
        本次运行没有产生 Agent
        Feedback。
      </div>
    );
  }

  return (
    <div className="table-shell">
      <table className="data-table">
        <thead>
          <tr>
            <th>
              Agent
            </th>

            <th>
              Capability
            </th>

            <th>
              结果
            </th>

            <th>
              Quality
            </th>

            <th>
              Latency
            </th>

            <th>
              Cost
            </th>
          </tr>
        </thead>

        <tbody>
          {feedback.map(
            (
              item,
              index,
            ) => (
              <tr
                key={`${item.agentId}-${item.capability}-${index}`}
              >
                <td>
                  Agent #
                  {
                    item.agentId
                  }
                </td>

                <td>
                  <span className="tag">
                    {
                      item.capability
                    }
                  </span>
                </td>

                <td>
                  <span
                    className={
                      item.success
                        ? "success-text"
                        : "danger-text"
                    }
                  >
                    {item.success
                      ? "成功"
                      : "失败"}
                  </span>
                </td>

                <td>
                  {item.qualityScore ==
                  null
                    ? "—"
                    : item.qualityScore.toFixed(
                        3,
                      )}
                </td>

                <td>
                  {
                    item.latencyMs
                  }{" "}
                  ms
                </td>

                <td>
                  {formatMoney(
                    item.cost,
                  )}
                </td>
              </tr>
            ),
          )}
        </tbody>
      </table>
    </div>
  );
}

