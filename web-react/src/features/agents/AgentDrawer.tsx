import type { Agent } from "../../types";
import { Icon } from "../../components/common/Icon";
import {
  formatMoney,
  formatPercent,
} from "../../utils/format";

export function AgentDrawer({
  agent,
  close,
}: {
  agent: Agent;
  close: () => void;
}) {
  return (
    <div
      className="drawer-backdrop"
      onClick={close}
    >
      <aside
        className="agent-drawer"
        onClick={(e) =>
          e.stopPropagation()
        }
      >
        <header className="drawer-head">
          <div className="drawer-agent">
            <span className="drawer-avatar">
              {agent.name
                .slice(0, 2)
                .toUpperCase()}
            </span>

            <div>
              <h2>{agent.name}</h2>

              <p>
                {agent.provider} ·{" "}
                {agent.protocol}
              </p>
            </div>
          </div>

          <button
            className="icon-button"
            onClick={close}
            aria-label="关闭智能体详情"
            title="关闭"
          >
            <Icon
              name="close"
              size={18}
            />
          </button>
        </header>

        <div className="drawer-body">
          <section>
            <span className="drawer-label">
              描述
            </span>

            <p className="drawer-description">
              {agent.description ||
                "暂无描述"}
            </p>
          </section>

          <section>
            <span className="drawer-label">
              运行环境
            </span>

            <div className="drawer-kv">
              <div>
                <span>服务地址</span>

                <code>
                  {agent.endpoint}
                </code>
              </div>

              <div>
                <span>模型</span>

                <strong>
                  {agent.modelName ||
                    "默认"}
                </strong>
              </div>

              <div>
                <span>当前负载</span>

                <strong>
                  {agent.currentLoad.toFixed(
                    2,
                  )}
                </strong>
              </div>
            </div>
          </section>

          <section>
            <span className="drawer-label">
              全局指标
            </span>

            <div className="drawer-metrics">
              <div>
                <span>质量</span>

                <strong>
                  {agent.qualityScore.toFixed(
                    3,
                  )}
                </strong>
              </div>

              <div>
                <span>成功率</span>

                <strong>
                  {formatPercent(
                    agent.successRate,
                  )}
                </strong>
              </div>

              <div>
                <span>响应耗时</span>

                <strong>
                  {agent.avgLatencyMs}{" "}
                  ms
                </strong>
              </div>

              <div>
                <span>平均成本</span>

                <strong>
                  {formatMoney(
                    agent.avgCost,
                  )}
                </strong>
              </div>
            </div>
          </section>

          <section>
            <span className="drawer-label">
              能力画像
            </span>

            {agent.capabilityProfiles
              ?.length ? (
              <div className="capability-profile-list">
                {agent.capabilityProfiles.map(
                  (profile) => (
                    <article
                      key={
                        profile.capability
                      }
                    >
                      <header>
                        <strong>
                          {
                            profile.capability
                          }
                        </strong>

                        <span>
                          {
                            profile.sampleCount
                          }{" "}
                          个样本
                        </span>
                      </header>

                      <div>
                        <span>
                          质量
                          <b>
                            {profile.qualityScore.toFixed(
                              3,
                            )}
                          </b>
                        </span>

                        <span>
                          成功率
                          <b>
                            {formatPercent(
                              profile.successRate,
                            )}
                          </b>
                        </span>

                        <span>
                          响应耗时
                          <b>
                            {
                              profile.avgLatencyMs
                            }{" "}
                            ms
                          </b>
                        </span>

                        <span>
                          平均成本
                          <b>
                            {formatMoney(
                              profile.avgCost,
                            )}
                          </b>
                        </span>
                      </div>
                    </article>
                  ),
                )}
              </div>
            ) : (
              <div className="drawer-empty">
                暂无长期能力经验
              </div>
            )}
          </section>
        </div>
      </aside>
    </div>
  );
}