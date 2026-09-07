import type { TraceEvent } from "../types";

type JsonRecord = Record<string, unknown>;

const MEMORY_TRACE_KINDS = new Set([
  "memory_retrieval",
  "memory_write",
  "memory_forget",
]);

const MEMORY_TRACE_HIDDEN_MESSAGE =
  "[Memory Trace detail hidden: only approved metadata is shown for privacy.]";

function isRecord(
  value: unknown,
): value is JsonRecord {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value)
  );
}

function safeString(
  value: unknown,
) {
  return typeof value === "string"
    ? value
    : undefined;
}

function safeNumber(
  value: unknown,
) {
  return typeof value === "number" &&
    Number.isFinite(value)
    ? value
    : undefined;
}

function safeBoolean(
  value: unknown,
) {
  return typeof value === "boolean"
    ? value
    : undefined;
}

function compactRecord(
  value: JsonRecord,
) {
  return Object.fromEntries(
    Object.entries(value).filter(
      ([, item]) => item !== undefined,
    ),
  );
}

function sanitizeRetrievalMemory(
  value: unknown,
) {
  if (!isRecord(value)) {
    return null;
  }

  return compactRecord({
    memoryId: safeNumber(
      value.memoryId,
    ),
    memoryKey: safeString(
      value.memoryKey,
    ),
    category: safeString(
      value.category,
    ),
    sourceType: safeString(
      value.sourceType,
    ),
    score: safeNumber(
      value.score,
    ),
  });
}

function sanitizeWriteRecord(
  value: unknown,
) {
  if (!isRecord(value)) {
    return null;
  }

  return compactRecord({
    action: safeString(
      value.action,
    ),
    memoryId: safeNumber(
      value.memoryId,
    ),
    memoryKey: safeString(
      value.memoryKey,
    ),
    category: safeString(
      value.category,
    ),
  });
}

function sanitizeForgetRecord(
  value: unknown,
) {
  if (!isRecord(value)) {
    return null;
  }

  return compactRecord({
    memoryId: safeNumber(
      value.memoryId,
    ),
    memoryKey: safeString(
      value.memoryKey,
    ),
    category: safeString(
      value.category,
    ),
  });
}

function sanitizeMemoryTraceDetail(
  event: TraceEvent,
  parsed: unknown,
) {
  if (!isRecord(parsed)) {
    return null;
  }

  const common = {
    reason: safeString(
      parsed.reason,
    ),
    errorType: safeString(
      parsed.errorType,
    ),
    candidateCount: safeNumber(
      parsed.candidateCount,
    ),
  };

  if (
    event.kind ===
    "memory_retrieval"
  ) {
    const memories = Array.isArray(
      parsed.memories,
    )
      ? parsed.memories
          .map(
            sanitizeRetrievalMemory,
          )
          .filter(
            (
              value,
            ): value is JsonRecord =>
              value !== null,
          )
      : undefined;

    return compactRecord({
      ...common,
      selectedCount: safeNumber(
        parsed.selectedCount,
      ),
      unsafeSkippedCount:
        safeNumber(
          parsed.unsafeSkippedCount,
        ),
      semanticUsed: safeBoolean(
        parsed.semanticUsed,
      ),
      memories,
    });
  }

  if (
    event.kind ===
    "memory_forget"
  ) {
    const deletes = Array.isArray(
      parsed.deletes,
    )
      ? parsed.deletes
          .map(sanitizeForgetRecord)
          .filter(
            (
              value,
            ): value is JsonRecord =>
              value !== null,
          )
      : undefined;

    return compactRecord({
      ...common,
      requested: safeBoolean(
        parsed.requested,
      ),
      deletedCount: safeNumber(
        parsed.deletedCount,
      ),
      deletes,
    });
  }

  const writes = Array.isArray(
    parsed.writes,
  )
    ? parsed.writes
        .map(sanitizeWriteRecord)
        .filter(
          (
            value,
          ): value is JsonRecord =>
            value !== null,
        )
    : undefined;

  return compactRecord({
    ...common,
    extractor: safeString(
      parsed.extractor,
    ),
    writes,
  });
}

export function formatMoney(
  value: number,
) {
  return `$${value.toFixed(4)}`;
}

export function formatPercent(
  value: number,
) {
  return `${(
    value * 100
  ).toFixed(1)}%`;
}

export function formatDurationMs(
  value: number,
) {
  if (!Number.isFinite(value)) {
    return "-";
  }

  if (value < 1000) {
    return `${Math.round(value)} ms`;
  }

  const seconds = value / 1000;

  if (seconds < 60) {
    return `${seconds.toFixed(
      seconds >= 10 ? 1 : 2,
    )} s`;
  }

  const minutes = Math.floor(
    seconds / 60,
  );

  const remainSeconds = Math.round(
    seconds % 60,
  );

  return `${minutes}m ${remainSeconds}s`;
}

export function formatCompactNumber(
  value: number,
) {
  if (!Number.isFinite(value)) {
    return "-";
  }

  return new Intl.NumberFormat(
    "zh-CN",
    {
      notation: "compact",
      maximumFractionDigits: 1,
    },
  ).format(value);
}

export function formatDate(
  value: string,
) {
  try {
    return new Intl.DateTimeFormat(
      "zh-CN",
      {
        month: "numeric",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      },
    ).format(
      new Date(value),
    );
  } catch {
    return value;
  }
}

export function prettyTraceDetail(
  event: TraceEvent,
) {
  if (!event.detail) {
    return "";
  }

  if (
    MEMORY_TRACE_KINDS.has(
      event.kind,
    )
  ) {
    try {
      const parsed: unknown =
        JSON.parse(event.detail);

      const safeDetail =
        sanitizeMemoryTraceDetail(
          event,
          parsed,
        );

      if (!safeDetail) {
        return MEMORY_TRACE_HIDDEN_MESSAGE;
      }

      return JSON.stringify(
        safeDetail,
        null,
        2,
      );
    } catch {
      // Never echo malformed Memory Trace detail. It may contain raw secrets.
      return MEMORY_TRACE_HIDDEN_MESSAGE;
    }
  }

  try {
    const parsed = JSON.parse(
      event.detail,
    );

    return JSON.stringify(
      parsed,
      null,
      2,
    );
  } catch {
    return event.detail;
  }
}
