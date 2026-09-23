import type { RunResult, Task } from "../../types";
import { Icon } from "../../components/common/Icon";
import { runtimeStatusText } from "../../components/common/RuntimeStatusBadge";

export function ResumePanel({
  task,
  latestRun,
  value,
  setValue,
  busy,
  error,
  onResume,
  onApprovalDecision,
  openDetails,
}: {
  task: Task;
  latestRun: RunResult | null;
  value: string;
  setValue: (value: string) => void;
  busy: boolean;
  error: string;
  onResume: () => Promise<void>;
  onApprovalDecision: (decision: "approve" | "reject") => Promise<void>;
  openDetails: () => void;
}) {
  // Never let a RunResult from another task override the persisted waiting
  // task. During submit -> task-list refresh there is a short window where the
  // newest AUTH_REQUIRED task exists only in latestRun; after refresh, Task is
  // authoritative for lifecycle state. Matching latestRun is only a safe
  // fallback for answer/approval projection of that exact same task id.
  const matchingLatestRun =
    latestRun?.task.id === task.id
      ? latestRun
      : null;

  const status = task.status;

  const prompt =
    matchingLatestRun?.answer ||
    task.resultText ||
    "Agent 正在等待补充信息。";

  const authRequired = status === "AUTH_REQUIRED";
  const approval =
    task.approval ??
    matchingLatestRun?.task.approval ??
    null;

  if (authRequired && approval) {
    return (
      <div className="composer approval-composer">
        <section className="approval-card" data-testid="approval-card">
          <div className="approval-card-head">
            <div>
              <span className="approval-kicker">
                需要你的确认
              </span>

              <h3>{approval.toolName}</h3>

              <p>
                {approval.summary ||
                  "此操作会调用外部工具并产生实际影响。"}
              </p>
            </div>

            <span
              className={`approval-risk risk-${
                approval.riskLevel || "high"
              }`}
            >
              {approval.riskLevel || "high"} risk
            </span>
          </div>

          {approval.argumentsPreview &&
            Object.keys(approval.argumentsPreview).length >
              0 && (
              <div className="approval-arguments">
                <span>本次将使用</span>

                <pre>
                  {JSON.stringify(
                    approval.argumentsPreview,
                    null,
                    2
                  )}
                </pre>
              </div>
            )}

          <div className="approval-safety-note">
            <Icon name="shield" size={15} />

            <span>
              确认只对上面这一次具体操作有效。
              若工具配置或参数发生变化，
              系统会拒绝执行并要求重新确认。
            </span>
          </div>

          <small>
            Go Task #{task.id} ·{" "}
            {runtimeStatusText(status)}
          </small>
        </section>

        {error && (
          <div className="error-box">
            {error}
          </div>
        )}

        <footer className="composer-footer approval-actions">
          <button
            className="secondary-button"
            disabled={!latestRun}
            onClick={openDetails}
          >
            <Icon
              name="activity"
              size={15}
            />

            查看执行详情
          </button>

          <div className="approval-action-group">
            <button
              className="secondary-button"
              data-testid="approval-reject"
              disabled={busy}
              onClick={() => void onApprovalDecision("reject")}
            >
              取消操作
            </button>

            <button
              className="primary-button run-button"
              data-testid="approval-approve"
              disabled={busy}
              onClick={() => void onApprovalDecision("approve")}
            >
              {busy ? (
                <span className="spinner" />
              ) : (
                <Icon
                  name="check"
                  size={15}
                />
              )}

              确认执行
            </button>
          </div>
        </footer>
      </div>
    );
  }

  return (
    <div className="composer">
      <section className="warning-box">
        <strong>
          {authRequired
            ? "任务等待授权"
            : "任务等待补充信息"}
        </strong>

        <p>{prompt}</p>

        <small>
          Go Task #{task.id} ·{" "}
          {runtimeStatusText(status)}
        </small>
      </section>

      <label className="field">
        <span>
          {authRequired
            ? "授权信息"
            : "补充信息"}
        </span>

        <textarea
          rows={3}
          value={value}
          disabled={busy}
          placeholder={
            authRequired
              ? "输入完成授权所需的信息..."
              : "输入 Agent 需要的补充信息..."
          }
          onChange={(e) =>
            setValue(e.target.value)
          }
        />
      </label>

      {error && (
        <div className="error-box">
          {error}
        </div>
      )}

      <footer className="composer-footer">
        <button
          className="secondary-button"
          disabled={!latestRun}
          onClick={openDetails}
        >
          <Icon
            name="activity"
            size={15}
          />

          查看暂停详情
        </button>

        <button
          className="primary-button run-button"
          disabled={
            busy || !value.trim()
          }
          onClick={() =>
            void onResume()
          }
        >
          {busy ? (
            <>
              <span className="spinner" />
              正在继续任务
            </>
          ) : (
            <>
              继续任务
              <Icon
                name="arrow"
                size={15}
              />
            </>
          )}
        </button>
      </footer>
    </div>
  );
}