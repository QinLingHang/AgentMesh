import type { DeliveryMode, ExecutionMode, Planner, Scheduler, SynthesisMode } from "../../types";
import { Icon } from "../../components/common/Icon";

export function RunConfiguration({
  scheduler,
  setScheduler,
  planner,
  setPlanner,
  executionMode,
  setExecutionMode,
  synthesisMode,
  setSynthesisMode,
  deliveryMode,
  setDeliveryMode,
  latency,
  setLatency,
  cost,
  setCost,
  quality,
  setQuality,
  retryOnWorkerLoss,
  setRetryOnWorkerLoss,
}: {
  scheduler: Scheduler;

  setScheduler: (
    value: Scheduler,
  ) => void;

  planner: Planner;

  setPlanner: (
    value: Planner,
  ) => void;

  executionMode:
    ExecutionMode;

  setExecutionMode: (
    value:
      ExecutionMode,
  ) => void;

  synthesisMode:
    SynthesisMode;

  setSynthesisMode: (
    value:
      SynthesisMode,
  ) => void;

  deliveryMode:
    DeliveryMode;

  setDeliveryMode: (
    value:
      DeliveryMode,
  ) => void;

  latency: number;

  setLatency: (
    value: number,
  ) => void;

  cost: number;

  setCost: (
    value: number,
  ) => void;

  quality: number;

  setQuality: (
    value: number,
  ) => void;

  retryOnWorkerLoss: boolean;

  setRetryOnWorkerLoss: (
    value: boolean,
  ) => void;
}) {
  return (
    <div className="run-config">
      <div className="config-main">
        <label>
          <span>
            调度
          </span>

          <select
            value={
              scheduler
            }
            onChange={(e) =>
              setScheduler(
                e.target
                  .value as Scheduler,
              )
            }
          >
            <option value="fixed">
              Fixed
            </option>

            <option value="capability">
              Capability
            </option>

            <option value="greedy">
              Greedy
            </option>

            <option value="adaptive">
              Adaptive
            </option>
          </select>
        </label>

        <label>
          <span>
            协作规划
          </span>

          <select
            value={planner}
            onChange={(e) =>
              setPlanner(
                e.target
                  .value as Planner,
              )
            }
          >
            <option value="heuristic">
              Heuristic
            </option>

            <option value="multi_objective">
              Multi-objective
            </option>
          </select>
        </label>

        <label>
          <span>
            执行
          </span>

          <select
            value={
              executionMode
            }
            onChange={(e) =>
              setExecutionMode(
                e.target
                  .value as ExecutionMode,
              )
            }
          >
            <option value="auto">
              Auto
            </option>

            <option value="parallel">
              Parallel
            </option>

            <option value="sequential">
              Sequential
            </option>
          </select>
        </label>

        <label>
          <span>
            投递
          </span>

          <select
            value={deliveryMode}
            onChange={(e) =>
              setDeliveryMode(
                e.target.value as DeliveryMode,
              )
            }
          >
            <option value="direct">
              互动模式 · 更快响应
            </option>

            <option value="durable">
              可靠队列 · 长任务
            </option>
          </select>
        </label>

        <label>
          <span>
            合成
          </span>

          <select
            value={
              synthesisMode
            }
            onChange={(e) =>
              setSynthesisMode(
                e.target
                  .value as SynthesisMode,
              )
            }
          >
            <option value="auto">
              Auto
            </option>

            <option value="always">
              Always
            </option>

            <option value="never">
              Never
            </option>
          </select>
        </label>
      </div>

      <details className="advanced-config">
        <summary>
          <span>
            高级约束
          </span>

          <Icon
            name="chevron"
            size={14}
          />
        </summary>

        <div className="advanced-fields">
          <label>
            <span>
              SLA
            </span>

            <div className="input-with-unit">
              <input
                type="number"
                value={
                  latency
                }
                onChange={(e) =>
                  setLatency(
                    Number(
                      e.target
                        .value,
                    ),
                  )
                }
              />

              <small>
                ms
              </small>
            </div>
          </label>

          <label>
            <span>
              最大成本
            </span>

            <div className="input-with-unit">
              <small>
                $
              </small>

              <input
                type="number"
                step="0.01"
                value={cost}
                onChange={(e) =>
                  setCost(
                    Number(
                      e.target
                        .value,
                    ),
                  )
                }
              />
            </div>
          </label>

          <label>
            <span>
              最低质量
            </span>

            <input
              type="number"
              min="0"
              max="1"
              step="0.05"
              value={quality}
              onChange={(e) =>
                setQuality(
                  Number(
                    e.target
                      .value,
                  ),
                )
              }
            />
          </label>

          {deliveryMode === "durable" && (
            <label className="failover-retry-toggle">
              <span>
                节点故障重试
              </span>

              <div className="failover-retry-control">
                <input
                  type="checkbox"
                  checked={retryOnWorkerLoss}
                  onChange={(e) => setRetryOnWorkerLoss(e.target.checked)}
                />
                <small>
                  仅对无副作用或幂等任务开启。Worker 丢失后允许跨节点重新分配，并使用 Fence 防止旧结果写回。
                </small>
              </div>
            </label>
          )}
        </div>
      </details>
    </div>
  );
}

