import type {
  RunResult,
  TraceEvent,
} from "../../types";
import { ExecutionTimeline } from "./ExecutionTimeline";

function isRAGEvent(
  event: TraceEvent,
) {
  return (
    event.kind === "rag" ||
    /rag|retrieval|grounding|citation|evidence/i.test(
      event.title,
    )
  );
}

function parseDetail(
  event?: TraceEvent,
): Record<string, unknown> {
  if (!event?.detail) {
    return {};
  }

  try {
    const value = JSON.parse(
      event.detail,
    ) as unknown;

    if (
      typeof value === "object" &&
      value !== null &&
      !Array.isArray(value)
    ) {
      return value as Record<
        string,
        unknown
      >;
    }
  } catch {
    // Trace detail may be plain text.
  }

  return {};
}

function numberValue(
  value: unknown,
  fallback = 0,
) {
  return typeof value === "number"
    ? value
    : fallback;
}

function textValue(
  value: unknown,
  fallback = "—",
) {
  if (
    typeof value === "string" &&
    value.trim()
  ) {
    return value;
  }

  if (typeof value === "boolean") {
    return value
      ? "是"
      : "否";
  }

  return fallback;
}

export function RAGTracePanel({
  result,
}: {
  result: RunResult;
}) {
  const ragEvents =
    result.trace.filter(
      isRAGEvent,
    );

  const agentic = parseDetail(
    ragEvents.find(
      (event) =>
        event.title ===
        "Agentic RAG Completed",
    ),
  );

  const retrieval = parseDetail(
    ragEvents.find(
      (event) =>
        event.title ===
        "RAG Retrieval Completed",
    ),
  );

  const grounding = parseDetail(
    ragEvents.find(
      (event) =>
        event.title ===
        "RAG Grounding Guard",
    ),
  );

  const projection = parseDetail(
    ragEvents.find(
      (event) =>
        event.title ===
        "Citation Provenance Projected",
    ),
  );

  if (ragEvents.length === 0) {
    return (
      <div className="empty-state run-detail-empty">
        本次运行没有产生 RAG Trace。
      </div>
    );
  }

  return (
    <div>
      <div className="rag-summary-grid">
        <div>
          <span>
            Agentic Rounds
          </span>

          <strong>
            {numberValue(
              agentic.rounds,
            )}
          </strong>

          <small>
            {textValue(
              agentic.stoppedReason,
            )}
          </small>
        </div>

        <div>
          <span>
            Retrieval Hits
          </span>

          <strong>
            {numberValue(
              retrieval.hits,
            )}
          </strong>

          <small>
            Context {numberValue(
              retrieval.contextHits,
            )}
          </small>
        </div>

        <div>
          <span>
            Grounding
          </span>

          <strong>
            {textValue(
              grounding.policy,
            )}
          </strong>

          <small>
            sufficient={textValue(
              grounding.sufficient,
            )}
          </small>
        </div>

        <div>
          <span>
            Used Citations
          </span>

          <strong>
            {numberValue(
              projection.usedCount,
              result.citations.length,
            )}
          </strong>

          <small>
            available {numberValue(
              projection.availableCount,
            )}
          </small>
        </div>
      </div>

      <section className="detail-section run-detail-section-tight">
        <div className="section-title">
          <div>
            <h3>
              RAG 执行事件
            </h3>

            <p>
              v2.2A 先按领域筛出 RAG Trace；后续会继续结构化 Query Rewrite、Rerank 与 Evidence Grade。
            </p>
          </div>
        </div>

        <ExecutionTimeline
          trace={ragEvents}
        />
      </section>
    </div>
  );
}
