import type {
  TraceEvent,
} from "../../types";
import {
  Icon,
} from "../../components/common/Icon";

type JsonRecord = Record<
  string,
  unknown
>;

function isRecord(
  value: unknown,
): value is JsonRecord {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value)
  );
}

function parseDetail(
  value: string,
): JsonRecord | null {
  try {
    const parsed: unknown =
      JSON.parse(value);

    return isRecord(parsed)
      ? parsed
      : null;
  } catch {
    return null;
  }
}

function numberValue(
  value: unknown,
) {
  return typeof value ===
    "number"
    ? value
    : null;
}

function stringValue(
  value: unknown,
) {
  return typeof value ===
    "string"
    ? value
    : null;
}

function boolValue(
  value: unknown,
) {
  return typeof value ===
    "boolean"
    ? value
    : null;
}

function arrayOfRecords(
  value: unknown,
) {
  return Array.isArray(value)
    ? value.filter(isRecord)
    : [];
}

function statusLabel(
  status: TraceEvent["status"],
) {
  switch (status) {
    case "completed":
      return "完成";
    case "error":
      return "异常";
    case "skipped":
      return "跳过";
    default:
      return "运行中";
  }
}

function memoryKind(
  event: TraceEvent,
) {
  if (
    event.kind ===
    "memory_retrieval"
  ) {
    return "retrieval";
  }

  if (
    event.kind ===
    "memory_write"
  ) {
    return "write";
  }

  if (
    event.kind ===
    "memory_forget"
  ) {
    return "forget";
  }

  return "other";
}

function metric(
  label: string,
  value: string | number,
) {
  return (
    <div className="memory-trace-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function RetrievalDetail({
  detail,
}: {
  detail: JsonRecord;
}) {
  const memories =
    arrayOfRecords(
      detail.memories,
    );

  const candidateCount =
    numberValue(
      detail.candidateCount,
    ) ?? 0;

  const selectedCount =
    numberValue(
      detail.selectedCount,
    ) ?? memories.length;

  const unsafeSkippedCount =
    numberValue(
      detail.unsafeSkippedCount,
    ) ?? 0;

  const semanticUsed =
    boolValue(
      detail.semanticUsed,
    );

  return (
    <>
      <div className="memory-trace-metrics">
        {metric(
          "候选",
          candidateCount,
        )}
        {metric(
          "召回",
          selectedCount,
        )}
        {metric(
          "安全过滤",
          unsafeSkippedCount,
        )}
        {metric(
          "语义检索",
          semanticUsed === null
            ? "-"
            : semanticUsed
              ? "是"
              : "否",
        )}
      </div>

      {memories.length > 0 && (
        <div className="memory-trace-records">
          {memories.map(
            (memory, index) => {
              const key =
                stringValue(
                  memory.memoryKey,
                ) ??
                `memory-${index + 1}`;

              const score =
                numberValue(
                  memory.score,
                );

              return (
                <div
                  key={`${key}-${index}`}
                  className="memory-trace-record"
                >
                  <div>
                    <code>{key}</code>
                    <span>
                      {stringValue(
                        memory.category,
                      ) ?? "-"}
                      {" · "}
                      {stringValue(
                        memory.sourceType,
                      ) ?? "-"}
                    </span>
                  </div>

                  <strong>
                    {score == null
                      ? "-"
                      : score.toFixed(
                          3,
                        )}
                  </strong>
                </div>
              );
            },
          )}
        </div>
      )}
    </>
  );
}

function WriteDetail({
  detail,
}: {
  detail: JsonRecord;
}) {
  const writes =
    arrayOfRecords(
      detail.writes,
    );

  const candidateCount =
    numberValue(
      detail.candidateCount,
    ) ?? 0;

  const extractor =
    stringValue(
      detail.extractor,
    ) ?? "-";

  return (
    <>
      <div className="memory-trace-metrics memory-trace-metrics-write">
        {metric(
          "候选",
          candidateCount,
        )}
        {metric(
          "Extractor",
          extractor,
        )}
      </div>

      {writes.length > 0 && (
        <div className="memory-trace-records">
          {writes.map(
            (write, index) => {
              const key =
                stringValue(
                  write.memoryKey,
                ) ??
                `memory-${index + 1}`;

              return (
                <div
                  key={`${key}-${index}`}
                  className="memory-trace-record"
                >
                  <div>
                    <code>{key}</code>
                    <span>
                      {stringValue(
                        write.category,
                      ) ?? "-"}
                    </span>
                  </div>

                  <strong className="memory-write-action">
                    {stringValue(
                      write.action,
                    ) ?? "-"}
                  </strong>
                </div>
              );
            },
          )}
        </div>
      )}
    </>
  );
}

function ForgetDetail({
  detail,
}: {
  detail: JsonRecord;
}) {
  const deletes =
    arrayOfRecords(
      detail.deletes,
    );

  const deletedCount =
    numberValue(
      detail.deletedCount,
    ) ?? deletes.length;

  return (
    <>
      <div className="memory-trace-metrics memory-trace-metrics-write">
        {metric(
          "已忘记",
          deletedCount,
        )}
      </div>

      {deletes.length > 0 && (
        <div className="memory-trace-records">
          {deletes.map(
            (item, index) => {
              const key =
                stringValue(
                  item.memoryKey,
                ) ??
                `memory-${index + 1}`;

              return (
                <div
                  key={`${key}-${index}`}
                  className="memory-trace-record"
                >
                  <div>
                    <code>{key}</code>
                    <span>
                      {stringValue(
                        item.category,
                      ) ?? "-"}
                    </span>
                  </div>

                  <strong className="memory-write-action">
                    DELETED
                  </strong>
                </div>
              );
            },
          )}
        </div>
      )}
    </>
  );
}

export function MemoryTracePanel({
  trace,
}: {
  trace: TraceEvent[];
}) {
  const memoryEvents =
    trace.filter(
      (event) =>
        event.kind ===
          "memory_retrieval" ||
        event.kind ===
          "memory_write" ||
        event.kind ===
          "memory_forget",
    );

  return (
    <section className="memory-trace-panel-shell">
      <div className="section-title">
        <div>
          <h3>
            Memory Observability
          </h3>

          <p>
            查看本次运行的 Memory 召回、写入与忘记决策。这里只展示必要元数据，不展示完整记忆内容。
          </p>
        </div>

        <span className="detail-count-badge">
          {memoryEvents.length} events
        </span>
      </div>

      {memoryEvents.length === 0 ? (
        <div className="memory-trace-empty">
          <div>
            <Icon
              name="memory"
              size={21}
            />
          </div>

          <strong>
            本次运行没有 Memory 事件
          </strong>

          <p>
            可能是 Memory 能力被关闭，或者这是不经过 Memory 管线的 Resume / 特殊执行路径。
          </p>
        </div>
      ) : (
        <div className="memory-trace-event-list">
          {memoryEvents.map(
            (event, index) => {
              const detail =
                parseDetail(
                  event.detail,
                );

              const kind =
                memoryKind(event);

              const reason =
                detail
                  ? stringValue(
                      detail.reason,
                    )
                  : null;

              return (
                <article
                  key={`${event.kind}-${index}`}
                  className={`memory-trace-event ${kind} ${event.status}`}
                >
                  <header>
                    <div className="memory-trace-event-heading">
                      <span className="memory-trace-kind-icon">
                        <Icon
                          name={
                            kind === "write"
                              ? "sparkles"
                              : "memory"
                          }
                          size={16}
                        />
                      </span>

                      <div>
                        <strong>
                          {event.title}
                        </strong>
                        <small>
                          {kind === "write"
                            ? "Automatic Write"
                            : kind === "forget"
                              ? "Forget"
                              : "Retrieval"}
                        </small>
                      </div>
                    </div>

                    <span className={`memory-trace-status ${event.status}`}>
                      {statusLabel(
                        event.status,
                      )}
                    </span>
                  </header>

                  {reason && (
                    <p className="memory-trace-reason">
                      reason: {reason}
                    </p>
                  )}

                  {detail ? (
                    kind === "retrieval" ? (
                      <RetrievalDetail
                        detail={detail}
                      />
                    ) : kind === "forget" ? (
                      <ForgetDetail
                        detail={detail}
                      />
                    ) : (
                      <WriteDetail
                        detail={detail}
                      />
                    )
                  ) : (
                    <p className="memory-trace-raw-note">
                      Runtime 返回了非结构化 Memory Trace，本页面不展开原始内容以避免意外泄露敏感信息。
                    </p>
                  )}

                  <footer>
                    <span>
                      {event.kind}
                    </span>
                    <span>
                      {event.elapsedMs} ms
                    </span>
                  </footer>
                </article>
              );
            },
          )}
        </div>
      )}
    </section>
  );
}
