import { useEffect, useMemo, useState } from "react";
import type { RuntimeReliabilitySnapshot, Task } from "../../types";
import { getRuntimeReliability } from "../../api";
import { RuntimeStatusBadge } from "../../components/common/RuntimeStatusBadge";
import { Icon } from "../../components/common/Icon";
import { formatMoney } from "../../utils/format";

type DeleteState = { task: Task; phase: "confirm" | "deleting" } | null;

function canDeleteTask(task: Task) {
  return ["COMPLETED", "ERROR", "CANCELED"].includes(String(task.status).toUpperCase());
}

function taskDeleteHint(task: Task) {
  const status = String(task.status).toUpperCase();
  if (status === "QUEUED" || status === "RUNNING") return "任务仍在执行，暂时不能删除。";
  if (status === "INPUT_REQUIRED" || status === "AUTH_REQUIRED") return "任务仍在等待你的操作，暂时不能删除。";
  return "删除任务记录";
}

function compactTaskText(value: string) {
  const text = value.trim();
  return text.length <= 76 ? text : `${text.slice(0, 76)}…`;
}

function formatLatency(value: number | null | undefined) {
  if (value == null) return "—";
  if (value < 1000) return `${value} ms`;
  return `${(value / 1000).toFixed(value >= 10000 ? 0 : 1)} 秒`;
}

export function Tasks({
  tasks,
  onDeleteTask,
  onCancelTask,
}: {
  tasks: Task[];
  onDeleteTask: (taskId: number) => Promise<void>;
  onCancelTask: (taskId: number) => Promise<void>;
}) {
  const [deleteState, setDeleteState] = useState<DeleteState>(null);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; message: string } | null>(null);
  const [cancelingId, setCancelingId] = useState<number | null>(null);
  const [reliability, setReliability] = useState<RuntimeReliabilitySnapshot | null>(null);
  const [expandedTaskId, setExpandedTaskId] = useState<number | null>(null);

  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const snapshot = await getRuntimeReliability();
        if (active) setReliability(snapshot);
      } catch {
        // Runtime telemetry is optional for the user-facing history page.
      }
    };
    void refresh();
    const timer = window.setInterval(refresh, 3000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  const deleting = deleteState?.phase === "deleting";
  const deletableCount = useMemo(() => tasks.filter(canDeleteTask).length, [tasks]);
  const runningCount = useMemo(
    () => tasks.filter((task) => ["QUEUED", "RUNNING"].includes(String(task.status).toUpperCase())).length,
    [tasks],
  );

  // P8 reliability remains available for developer diagnostics in Run Details.
  // The product-facing task list intentionally does not surface worker/circuit internals.
  // reliability.availableWorkers
  // reliability.circuitOpenWorkers

  const cancelRunningTask = async (task: Task) => {
    try {
      setCancelingId(task.id);
      setFeedback(null);
      await onCancelTask(task.id);
      setFeedback({ type: "success", message: `任务 #${task.id} 已请求取消。` });
    } catch {
      setFeedback({ type: "error", message: "取消失败，任务可能已经完成或进入不可撤销阶段。" });
    } finally {
      setCancelingId(null);
    }
  };

  const deleteTask = async () => {
    if (!deleteState) return;
    const target = deleteState.task;
    try {
      setFeedback(null);
      setDeleteState({ task: target, phase: "deleting" });
      await onDeleteTask(target.id);
      setDeleteState(null);
      setFeedback({ type: "success", message: `任务 #${target.id} 已从记录中删除。` });
    } catch (error) {
      setDeleteState({ task: target, phase: "confirm" });
      setFeedback({
        type: "error",
        message:
          error instanceof Error && error.message.includes("409")
            ? "该任务仍在运行或等待操作，暂时不能删除。"
            : "删除失败，请稍后重试。",
      });
    }
  };

  return (
    <div className="page calm-page tasks-calm-page">
      <header className="calm-page-head">
        <div className="calm-page-copy">
          <span className="calm-kicker">执行记录</span>
          <h1>任务</h1>
          <p>回顾最近的任务、结果状态与耗时。调度策略、请求标识等工程信息默认收起。</p>
        </div>
      </header>

      <section className="calm-overview-strip" aria-label="任务概览">
        <div>
          <span>全部任务</span>
          <strong>{tasks.length}</strong>
        </div>
        <div>
          <span>正在处理</span>
          <strong>{runningCount}</strong>
        </div>
        <div>
          <span>可清理记录</span>
          <strong>{deletableCount}</strong>
        </div>
        <div className="calm-overview-grow">
          <span>执行服务</span>
          <strong>{reliability?.enabled ? "运行正常" : "状态已隐藏"}</strong>
          {reliability?.enabled && (
            <small>{reliability.queueDepth > 0 ? `${reliability.queueDepth} 个任务等待中` : "当前没有排队任务"}</small>
          )}
        </div>
      </section>

      {feedback && (
        <div className={`calm-feedback ${feedback.type}`} role={feedback.type === "error" ? "alert" : "status"}>
          <span>{feedback.message}</span>
          <button type="button" onClick={() => setFeedback(null)}>
            <Icon name="close" size={14} />
          </button>
        </div>
      )}

      {tasks.length === 0 ? (
        <div className="calm-empty-card large">
          <Icon name="tasks" size={22} />
          <strong>还没有任务记录</strong>
          <span>在工作台运行一个任务后，这里会自动保留结果与状态。</span>
        </div>
      ) : (
        <div className="task-calm-list">
          {tasks.map((task) => {
            const allowed = canDeleteTask(task);
            const expanded = expandedTaskId === task.id;
            const running =
              task.status === "QUEUED" || task.status === "RUNNING";
            return (
              <article className={`task-calm-card ${expanded ? "expanded" : ""}`} key={task.id}>
                <div className="task-calm-main">
                  <div className="task-calm-copy">
                    <div className="task-calm-title-row">
                      <strong title={task.taskText}>{compactTaskText(task.taskText)}</strong>
                      <RuntimeStatusBadge status={task.status} />
                    </div>
                    <div className="task-calm-meta">
                      <span>任务 #{task.id}</span>
                      <i />
                      <span>{formatLatency(task.latencyMs)}</span>
                      <i />
                      <span>{formatMoney(task.estimatedCost ?? 0)}</span>
                    </div>
                  </div>

                  <div className="task-calm-actions">
                    {task.deliveryMode === "durable" && running && (
                      <button
                        type="button"
                        className="calm-button subtle danger-soft"
                        disabled={cancelingId === task.id}
                        onClick={() => void cancelRunningTask(task)}
                      >
                        {cancelingId === task.id ? "取消中" : "取消任务"}
                      </button>
                    )}
                    <button
                      type="button"
                      className="calm-button ghost"
                      onClick={() => setExpandedTaskId(expanded ? null : task.id)}
                    >
                      {expanded ? "收起详情" : "查看详情"}
                      <Icon name="chevron" size={13} />
                    </button>
                  </div>
                </div>

                {expanded && (
                  <div className="task-calm-detail">
                    <div>
                      <span>执行方式</span>
                      <strong>{task.deliveryMode === "durable" ? "可靠执行" : "即时执行"}</strong>
                    </div>
                    <div>
                      <span>调度策略</span>
                      <strong>{task.scheduler}</strong>
                    </div>
                    <div>
                      <span>规划策略</span>
                      <strong>{task.planner || "heuristic"}</strong>
                    </div>
                    <div>
                      <span>请求标识</span>
                      <code>{task.requestId.slice(0, 12)}</code>
                    </div>
                    <div className="task-calm-detail-actions">
                      <button
                        type="button"
                        className={`calm-button ghost ${allowed ? "" : "disabled"}`}
                        disabled={!allowed}
                        title={taskDeleteHint(task)}
                        onClick={() => {
                          setFeedback(null);
                          setDeleteState({ task, phase: "confirm" });
                        }}
                      >
                        <Icon name="trash" size={14} />
                        删除记录
                      </button>
                    </div>
                  </div>
                )}
              </article>
            );
          })}
        </div>
      )}

      {deleteState && (
        <div
          className="task-delete-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !deleting) setDeleteState(null);
          }}
        >
          <div className="task-delete-dialog calm-dialog" role="dialog" aria-modal="true" aria-labelledby="task-delete-title">
            <div className="task-delete-dialog-icon">
              <Icon name="trash" size={18} />
            </div>
            <div className="task-delete-dialog-copy">
              <h2 id="task-delete-title">删除这条任务记录？</h2>
              <p>Task #{deleteState.task.id} · {compactTaskText(deleteState.task.taskText)}</p>
              <div className="task-delete-note">
                只删除任务记录，不会删除工作台中的会话消息和回答。删除后不可恢复。
              </div>
            </div>
            <div className="task-delete-dialog-actions">
              <button type="button" className="calm-button subtle" disabled={deleting} onClick={() => setDeleteState(null)}>
                取消
              </button>
              <button type="button" className="task-confirm-delete" disabled={deleting} onClick={() => void deleteTask()}>
                {deleting ? "删除中…" : "确认删除"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
