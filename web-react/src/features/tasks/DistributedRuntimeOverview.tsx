import type { RuntimeTopologySnapshot } from "../../types";

function percent(value: number | undefined) {
  if (value == null || Number.isNaN(value)) return "0%";
  return `${Math.max(0, Math.min(100, value)).toFixed(value >= 10 ? 0 : 1)}%`;
}

function compactId(value: string) {
  return value.length <= 22 ? value : `${value.slice(0, 12)}…${value.slice(-6)}`;
}

export function DistributedRuntimeOverview({ topology }: { topology: RuntimeTopologySnapshot }) {
  const reliability = topology.reliability;
  const activeNodes = topology.nodes.filter((node) => node.status === "ACTIVE" && !node.draining);

  return (
    <details className="distributed-runtime-overview">
      <summary>
        <div>
          <span className="calm-kicker">Distributed Runtime</span>
          <strong>多节点执行拓扑</strong>
          <small>查看 Node、Worker、队列和 HA Dispatcher 状态。内部 Endpoint 与凭据不会展示。</small>
        </div>
        <span className="runtime-topology-health">
          {activeNodes.length > 0 ? `${activeNodes.length} 个节点在线` : "暂无在线节点"}
        </span>
      </summary>

      <div className="runtime-topology-metrics" aria-label="分布式 Runtime 指标">
        <div><span>节点</span><strong>{reliability.availableNodes ?? 0}/{reliability.nodes ?? 0}</strong></div>
        <div><span>Worker</span><strong>{reliability.availableWorkers}/{reliability.workers}</strong></div>
        <div><span>容量</span><strong>{reliability.activeExecutions ?? 0}/{reliability.totalCapacity ?? 0}</strong></div>
        <div><span>利用率</span><strong>{percent(reliability.utilizationPercent)}</strong></div>
        <div><span>Dispatcher</span><strong>{reliability.dispatcherLeader ? "当前实例主调度" : `Epoch ${reliability.dispatcherEpoch ?? 0}`}</strong></div>
        <div><span>等待队列</span><strong>{reliability.queueDepth}</strong></div>
      </div>

      <div className="runtime-node-list">
        {topology.nodes.length === 0 ? (
          <div className="empty-detail-state">暂无 Runtime Node 心跳。</div>
        ) : topology.nodes.map((node) => (
          <article className="runtime-node-card" key={node.nodeId}>
            <header>
              <div>
                <strong title={node.nodeId}>{compactId(node.nodeId)}</strong>
                <span>{node.zone || "default-zone"}</span>
              </div>
              <em className={`runtime-node-status ${node.status.toLowerCase()}`}>
                {node.draining ? "DRAINING" : node.status}
              </em>
            </header>
            <div className="runtime-node-meta">
              <span>Worker <b>{node.workerCount}</b></span>
              <span>负载 <b>{node.activeExecutions}/{node.capacity}</b></span>
              <span>版本 <b>{node.version || "—"}</b></span>
            </div>
          </article>
        ))}
      </div>

      <div className="runtime-worker-table" role="table" aria-label="Runtime Worker 调度状态">
        <div className="runtime-worker-row head" role="row">
          <span>Worker</span><span>Node</span><span>执行</span><span>Score</span><span>状态</span>
        </div>
        {topology.workers.map((worker) => (
          <div className="runtime-worker-row" role="row" key={worker.workerId}>
            <span title={worker.workerId}>{compactId(worker.workerId)}</span>
            <span title={worker.nodeId}>{compactId(worker.nodeId)}</span>
            <span>{worker.authoritativeActive}/{worker.capacity}</span>
            <span>{worker.schedulingScore.toFixed(3)}</span>
            <span>{worker.draining ? "DRAINING" : worker.status}</span>
          </div>
        ))}
      </div>
    </details>
  );
}
