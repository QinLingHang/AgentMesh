import type { RuntimeTopologySnapshot } from "../../types";

function percent(value: number | undefined) {
  if (value == null || Number.isNaN(value)) {
    return "0%";
  }

  return `${Math.max(0, Math.min(100, value)).toFixed(
    value >= 10 ? 0 : 1,
  )}%`;
}

function compactId(value: string) {
  return value.length <= 22
    ? value
    : `${value.slice(0, 12)}…${value.slice(-6)}`;
}

function runtimeStatusLabel(status: string) {
  switch (status.toUpperCase()) {
    case "ACTIVE":
      return "运行中";
    case "DRAINING":
      return "排空中";
    case "INACTIVE":
      return "未运行";
    case "OFFLINE":
      return "离线";
    case "UNHEALTHY":
      return "异常";
    case "READY":
      return "就绪";
    default:
      return status;
  }
}

function zoneLabel(zone?: string | null) {
  if (!zone || zone === "default-zone") {
    return "默认区域";
  }

  if (zone.toLowerCase() === "local") {
    return "本地";
  }

  return zone;
}

export function DistributedRuntimeOverview({
  topology,
}: {
  topology: RuntimeTopologySnapshot;
}) {
  const reliability = topology.reliability;

  const activeNodes = topology.nodes.filter(
    (node) =>
      node.status === "ACTIVE" &&
      !node.draining,
  );

  return (
    <details className="distributed-runtime-overview">
      <summary>
        <div>
          <span className="calm-kicker">
            分布式运行时
          </span>

          <strong>
            多节点执行拓扑
          </strong>

          <small>
            查看节点、工作节点、队列和高可用调度器状态。
            内部端点与凭据不会展示。
          </small>
        </div>

        <span className="runtime-topology-health">
          {activeNodes.length > 0
            ? `${activeNodes.length} 个节点在线`
            : "暂无在线节点"}
        </span>
      </summary>

      <div
        className="runtime-topology-metrics"
        aria-label="分布式运行时指标"
      >
        <div>
          <span>节点</span>
          <strong>
            {reliability.availableNodes ?? 0}/
            {reliability.nodes ?? 0}
          </strong>
        </div>

        <div>
          <span>工作节点</span>
          <strong>
            {reliability.availableWorkers}/
            {reliability.workers}
          </strong>
        </div>

        <div>
          <span>容量</span>
          <strong>
            {reliability.activeExecutions ?? 0}/
            {reliability.totalCapacity ?? 0}
          </strong>
        </div>

        <div>
          <span>利用率</span>
          <strong>
            {percent(
              reliability.utilizationPercent,
            )}
          </strong>
        </div>

        <div>
          <span>调度器</span>
          <strong>
            {reliability.dispatcherLeader
              ? "当前实例主调度"
              : `调度纪元 ${
                  reliability.dispatcherEpoch ?? 0
                }`}
          </strong>
        </div>

        <div>
          <span>等待队列</span>
          <strong>
            {reliability.queueDepth}
          </strong>
        </div>
      </div>

      <div className="runtime-node-list">
        {topology.nodes.length === 0 ? (
          <div className="empty-detail-state">
            暂无运行时节点心跳。
          </div>
        ) : (
          topology.nodes.map((node) => (
            <article
              className="runtime-node-card"
              key={node.nodeId}
            >
              <header>
                <div>
                  <strong title={node.nodeId}>
                    {compactId(node.nodeId)}
                  </strong>

                  <span>
                    {zoneLabel(node.zone)}
                  </span>
                </div>

                <em
                  className={`runtime-node-status ${node.status.toLowerCase()}`}
                >
                  {node.draining
                    ? "排空中"
                    : runtimeStatusLabel(
                        node.status,
                      )}
                </em>
              </header>

              <div className="runtime-node-meta">
                <span>
                  工作节点{" "}
                  <b>{node.workerCount}</b>
                </span>

                <span>
                  负载{" "}
                  <b>
                    {node.activeExecutions}/
                    {node.capacity}
                  </b>
                </span>

                <span>
                  版本{" "}
                  <b>
                    {node.version || "—"}
                  </b>
                </span>
              </div>
            </article>
          ))
        )}
      </div>

      <div
        className="runtime-worker-table"
        role="table"
        aria-label="运行时工作节点调度状态"
      >
        <div
          className="runtime-worker-row head"
          role="row"
        >
          <span>工作节点</span>
          <span>所属节点</span>
          <span>执行</span>
          <span>调度评分</span>
          <span>状态</span>
        </div>

        {topology.workers.map((worker) => (
          <div
            className="runtime-worker-row"
            role="row"
            key={worker.workerId}
          >
            <span title={worker.workerId}>
              {compactId(worker.workerId)}
            </span>

            <span title={worker.nodeId}>
              {compactId(worker.nodeId)}
            </span>

            <span>
              {worker.authoritativeActive}/
              {worker.capacity}
            </span>

            <span>
              {worker.schedulingScore.toFixed(3)}
            </span>

            <span>
              {worker.draining
                ? "排空中"
                : runtimeStatusLabel(
                    worker.status,
                  )}
            </span>
          </div>
        ))}
      </div>
    </details>
  );
}