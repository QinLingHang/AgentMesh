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

type EvidenceRow = {
  id?: string;
  source?: string;
  score?: number;
  modality?: string;
  pageNumber?: number | null;
  visualType?: string | null;
  assetId?: string | null;
};

function evidenceRows(
  value: unknown,
): EvidenceRow[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value.filter(
    (item): item is EvidenceRow =>
      typeof item === "object" &&
      item !== null,
  );
}

function retrievalModeLabel(
  value: unknown,
) {
  switch (String(value ?? "").toLowerCase()) {
    case "visual":
      return "VISUAL";
    case "hybrid":
      return "HYBRID";
    case "text":
      return "TEXT";
    default:
      return "—";
  }
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

  const selectedEvidence =
    evidenceRows(
      retrieval.documents,
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
          <span>Retrieval Mode</span>
          <strong>
            {retrievalModeLabel(
              retrieval.retrievalMode ??
                result.observability.retrievalMode,
            )}
          </strong>
          <small>
            Text {numberValue(
              retrieval.textCandidates,
              result.observability.ragTextCandidates,
            )} · Visual {numberValue(
              retrieval.visualCandidates,
              result.observability.ragVisualCandidates,
            )}
          </small>
        </div>

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
            Raw {numberValue(
              retrieval.rawHits,
            )} · Context {numberValue(
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

      {selectedEvidence.length > 0 && (
        <section className="detail-section run-detail-section-tight">
          <div className="section-title">
            <div>
              <h3>已选多模态证据</h3>
              <p>展示本次检索最终进入回答上下文的文本、页面与视觉证据。</p>
            </div>
          </div>

          <div className="run-v2-evidence-list">
            {selectedEvidence.map((item, index) => (
              <article className="run-v2-evidence-card" key={`${item.id ?? item.assetId ?? "evidence"}-${index}`}>
                <div>
                  <strong>{item.source || item.id || `Evidence ${index + 1}`}</strong>
                  <span>{String(item.modality || "text").toUpperCase()}</span>
                </div>
                <small>
                  {item.pageNumber != null ? `第 ${item.pageNumber} 页 · ` : ""}
                  {item.visualType ? `${item.visualType} · ` : ""}
                  score={typeof item.score === "number" ? item.score.toFixed(3) : "—"}
                </small>
              </article>
            ))}
          </div>
        </section>
      )}

      <section className="detail-section run-detail-section-tight">
        <div className="section-title">
          <div>
            <h3>
              RAG 执行事件
            </h3>

            <p>
              记录 Query Intelligence、TEXT / VISUAL / HYBRID 检索、Grounding 与 Citation 的完整执行轨迹。
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
