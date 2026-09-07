import type { RunResult } from "../../types";
import { Icon } from "../../components/common/Icon";

export function DAGPanel({
  result,
}: {
  result: RunResult;
}) {
  const nodes =
    result.dag?.nodes ??
    [];

  const edges =
    result.dag?.edges ??
    [];

  return (
    <div>
      <div className="dag-summary">
        <span>
          {nodes.length} 节点
        </span>

        <span>
          {edges.length} 条依赖
        </span>

        <span>
          {
            result
              .observability
              .dagCompletedNodes
          }{" "}
          已完成
        </span>

        <span>
          {
            result
              .observability
              .dagSkippedNodes
          }{" "}
          已跳过
        </span>
      </div>

      <div className="dag-grid">
        {nodes.map(
          (node) => (
            <div
              className={`dag-node ${node.status}`}
              key={node.id}
            >
              <div className="dag-node-top">
                <span>
                  {node.kind}
                </span>

                <small>
                  {
                    node.status
                  }
                </small>
              </div>

              <strong>
                {node.label ||
                  node.id}
              </strong>
            </div>
          ),
        )}
      </div>

      {edges.length > 0 && (
        <section className="detail-section">
          <div className="section-title">
            <div>
              <h3>
                DAG 依赖关系
              </h3>

              <p>
                当前运行图的实际依赖边
              </p>
            </div>
          </div>

          <div className="edge-list">
            {edges.map(
              (
                edge,
                index,
              ) => (
                <div
                  className="edge-row"
                  key={`${edge.source}-${edge.target}-${index}`}
                >
                  <code>
                    {
                      edge.source
                    }
                  </code>

                  <Icon
                    name="arrow"
                    size={14}
                  />

                  <code>
                    {
                      edge.target
                    }
                  </code>
                </div>
              ),
            )}
          </div>
        </section>
      )}
    </div>
  );
}

