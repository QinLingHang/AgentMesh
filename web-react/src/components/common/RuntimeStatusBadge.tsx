export function isWaitingStatus(
  status?: string | null,
) {
  return (
    status === "INPUT_REQUIRED" ||
    status === "AUTH_REQUIRED"
  );
}

export function runtimeStatusText(
  status?: string | null,
) {
  switch (status) {
    case "QUEUED":
      return "排队中";

    case "RUNNING":
      return "运行中";

    case "INPUT_REQUIRED":
      return "等待补充信息";

    case "AUTH_REQUIRED":
      return "等待授权";

    case "COMPLETED":
      return "已完成";

    case "ERROR":
      return "执行失败";

    case "CANCELED":
      return "已取消";

    default:
      return status || "未知";
  }
}

function runtimeStatusClass(
  status?: string | null,
) {
  if (
    status === "ERROR" ||
    status === "CANCELED"
  ) {
    return "error-status";
  }

  return "";
}

export function RuntimeStatusBadge({
  status,
}: {
  status?: string | null;
}) {
  return (
    <span
      className={`status-label ${runtimeStatusClass(
        status,
      )}`}
    >
      <span className="status-dot" />

      {runtimeStatusText(
        status,
      )}
    </span>
  );
}

// =========================================================
// Auth
// =========================================================

