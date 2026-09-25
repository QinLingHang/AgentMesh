import type {
  AgentFeedback,
  DynamicDAG,
  Message,
  ObservabilitySummary,
  RunResult,
  RunScorecard,
  RuntimeCitation,
  RuntimeStatus,
  Task,
  TraceEvent,
} from "../../types";

// =========================================================
// Historical Run Reconstruction
//
// Fresh execution:
//   /api/tasks/run -> RunResult
//
// Historical execution after refresh:
//   Message.metadata + Task history -> RunResult
//
// This keeps Run Details available after F5 / conversation reload.
// =========================================================

const EMPTY_OBSERVABILITY: ObservabilitySummary = {
  modelCalls: 0,
  modelProvider: "",
  modelName: "",
  modelInputTokens: 0,
  modelOutputTokens: 0,
  modelTotalTokens: 0,
  modelLatencyMs: 0,
  toolCalls: 0,
  mcpEvents: 0,
  agentAttempts: 0,
  agentSuccesses: 0,
  agentFailures: 0,
  reschedules: 0,
  dagCompletedNodes: 0,
  dagSkippedNodes: 0,
  qualityEvaluations: 0,
  averageQuality: 0,
  modelEstimatedCost: 0,
  modelCostKnown: false,
  toolSuccesses: 0,
  toolFailures: 0,
  retrievalMode: "",
  ragLatencyMs: 0,
  ragRawHits: 0,
  ragHits: 0,
  ragContextHits: 0,
  ragTextCandidates: 0,
  ragVisualCandidates: 0,
};

function asRecord(
  value: unknown,
): Record<string, unknown> | null {
  if (
    value == null ||
    typeof value !== "object" ||
    Array.isArray(value)
  ) {
    return null;
  }

  return value as Record<string, unknown>;
}

function asString(
  value: unknown,
  fallback = "",
) {
  return typeof value === "string"
    ? value
    : fallback;
}

function asNumber(
  value: unknown,
  fallback = 0,
) {
  return typeof value === "number" &&
    Number.isFinite(value)
    ? value
    : fallback;
}

function asStringArray(
  value: unknown,
): string[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value.filter(
    (item): item is string =>
      typeof item === "string",
  );
}

function normalizeStatus(
  value: unknown,
): RuntimeStatus {
  const status = asString(
    value,
    "COMPLETED",
  ).toUpperCase();

  switch (status) {
    case "QUEUED":
    case "RUNNING":
    case "INPUT_REQUIRED":
    case "AUTH_REQUIRED":
    case "COMPLETED":
    case "ERROR":
    case "CANCELED":
      return status;

    default:
      return "COMPLETED";
  }
}

function normalizeTrace(
  value: unknown,
): TraceEvent[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .map((item) => {
      const record = asRecord(
        item,
      );

      if (!record) {
        return null;
      }

      const rawStatus = asString(
        record.status,
        "completed",
      ).toLowerCase();

      const status =
        rawStatus === "running" ||
        rawStatus === "completed" ||
        rawStatus === "error" ||
        rawStatus === "skipped"
          ? rawStatus
          : "completed";

      return {
        kind: asString(
          record.kind,
        ),
        title: asString(
          record.title,
          "Runtime Event",
        ),
        status,
        detail: asString(
          record.detail,
        ),
        elapsedMs: asNumber(
          record.elapsedMs,
        ),
      } satisfies TraceEvent;
    })
    .filter(
      (
        item,
      ): item is TraceEvent =>
        item !== null,
    );
}

function normalizeDAG(
  value: unknown,
): DynamicDAG {
  const record = asRecord(
    value,
  );

  const nodes = Array.isArray(
    record?.nodes,
  )
    ? record.nodes
        .map((item) => {
          const node = asRecord(
            item,
          );

          if (!node) {
            return null;
          }

          return {
            id: asString(
              node.id,
            ),
            label: asString(
              node.label,
            ),
            kind: asString(
              node.kind,
            ),
            status: asString(
              node.status,
            ),
          };
        })
        .filter(
          (
            item,
          ): item is DynamicDAG["nodes"][number] =>
            item !== null,
        )
    : [];

  const edges = Array.isArray(
    record?.edges,
  )
    ? record.edges
        .map((item) => {
          const edge = asRecord(
            item,
          );

          if (!edge) {
            return null;
          }

          return {
            source: asString(
              edge.source,
            ),
            target: asString(
              edge.target,
            ),
          };
        })
        .filter(
          (
            item,
          ): item is DynamicDAG["edges"][number] =>
            item !== null,
        )
    : [];

  return {
    nodes,
    edges,
  };
}

function normalizeObservability(
  value: unknown,
): ObservabilitySummary {
  const record = asRecord(
    value,
  );

  if (!record) {
    return {
      ...EMPTY_OBSERVABILITY,
    };
  }

  return {
    modelCalls: asNumber(
      record.modelCalls,
    ),
    modelProvider: asString(record.modelProvider),
    modelName: asString(record.modelName),
    modelInputTokens: asNumber(
      record.modelInputTokens,
    ),
    modelOutputTokens: asNumber(
      record.modelOutputTokens,
    ),
    modelTotalTokens: asNumber(
      record.modelTotalTokens,
    ),
    modelLatencyMs: asNumber(
      record.modelLatencyMs,
    ),
    toolCalls: asNumber(
      record.toolCalls,
    ),
    mcpEvents: asNumber(
      record.mcpEvents,
    ),
    agentAttempts: asNumber(
      record.agentAttempts,
    ),
    agentSuccesses: asNumber(
      record.agentSuccesses,
    ),
    agentFailures: asNumber(
      record.agentFailures,
    ),
    reschedules: asNumber(
      record.reschedules,
    ),
    dagCompletedNodes: asNumber(
      record.dagCompletedNodes,
    ),
    dagSkippedNodes: asNumber(
      record.dagSkippedNodes,
    ),
    qualityEvaluations: asNumber(
      record.qualityEvaluations,
    ),
    averageQuality: asNumber(
      record.averageQuality,
    ),
    modelEstimatedCost: asNumber(
      record.modelEstimatedCost,
    ),
    modelCostKnown: record.modelCostKnown === true,
    toolSuccesses: asNumber(
      record.toolSuccesses,
    ),
    toolFailures: asNumber(
      record.toolFailures,
    ),
    retrievalMode: asString(record.retrievalMode),
    ragLatencyMs: asNumber(record.ragLatencyMs),
    ragRawHits: asNumber(record.ragRawHits),
    ragHits: asNumber(record.ragHits),
    ragContextHits: asNumber(record.ragContextHits),
    ragTextCandidates: asNumber(record.ragTextCandidates),
    ragVisualCandidates: asNumber(record.ragVisualCandidates),
  };
}

function normalizeCitations(
  value: unknown,
): RuntimeCitation[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .map((item) => {
      const record = asRecord(
        item,
      );

      if (!record) {
        return null;
      }

      const citationId = asNumber(
        record.citationId,
        -1,
      );

      if (citationId < 0) {
        return null;
      }

      return {
        citationId,
        label: asString(
          record.label,
          `[${citationId}]`,
        ),
        documentId: asString(
          record.documentId,
        ),
        source: asString(
          record.source,
        ),
        score: asNumber(
          record.score,
        ),
        documentType:
          typeof record.documentType ===
          "string"
            ? record.documentType
            : null,
        chunkIndex:
          typeof record.chunkIndex ===
          "number"
            ? record.chunkIndex
            : null,
        start:
          typeof record.start ===
          "number"
            ? record.start
            : null,
        end:
          typeof record.end ===
          "number"
            ? record.end
            : null,
        pageNumber:
          typeof record.pageNumber === "number" ? record.pageNumber : null,
        assetId:
          typeof record.assetId === "string" ? record.assetId : null,
        modality:
          typeof record.modality === "string" ? record.modality : null,
        visualType:
          typeof record.visualType === "string" ? record.visualType : null,
      } satisfies RuntimeCitation;
    })
    .filter(
      (
        item,
      ): item is RuntimeCitation =>
        item !== null,
    );
}

function normalizeAgentFeedback(
  value: unknown,
): AgentFeedback[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .map((item) => {
      const record = asRecord(
        item,
      );

      if (!record) {
        return null;
      }

      return {
        agentId: asNumber(
          record.agentId,
        ),
        capability: asString(
          record.capability,
        ),
        success:
          record.success === true,
        latencyMs: asNumber(
          record.latencyMs,
        ),
        cost: asNumber(
          record.cost,
        ),
        qualityScore:
          typeof record.qualityScore ===
          "number"
            ? record.qualityScore
            : null,
        errorType: asString(
          record.errorType,
        ),
      } satisfies AgentFeedback;
    })
    .filter(
      (
        item,
      ): item is AgentFeedback =>
        item !== null,
    );
}

function normalizeTaskProfile(
  value: unknown,
): Record<string, unknown> {
  return (
    asRecord(
      value,
    ) ?? {}
  );
}

function normalizeScorecard(
  value: unknown,
): RunScorecard | null {
  const record = asRecord(value);

  if (!record) {
    return null;
  }

  const rawStatus = asString(
    record.status,
    "unavailable",
  );

  const status =
    rawStatus === "pass" ||
    rawStatus === "warning" ||
    rawStatus === "fail"
      ? rawStatus
      : "unavailable";

  return {
    evaluator: asString(
      record.evaluator,
      "deterministic_scorecard_v1",
    ),
    status,
    overallScore: asNumber(record.overallScore),
    taskSuccess: asNumber(record.taskSuccess),
    answerQuality: asNumber(record.answerQuality),
    groundedness: asNumber(record.groundedness),
    correctness: asNumber(record.correctness, asNumber(record.answerQuality)),
    citationQuality: asNumber(record.citationQuality, asNumber(record.groundedness)),
    taskCompletion: asNumber(record.taskCompletion, asNumber(record.taskSuccess)),
    judgeReason: asString(record.judgeReason),
    toolReliability: asNumber(record.toolReliability),
    ragQuality: asNumber(record.ragQuality),
    memoryContribution: asNumber(record.memoryContribution),
    budgetCompliance: asNumber(record.budgetCompliance),
    latencyMs: asNumber(record.latencyMs),
    estimatedCost: asNumber(record.estimatedCost),
    modelEstimatedCost: asNumber(record.modelEstimatedCost),
    modelTokens: asNumber(record.modelTokens),
    failureCategory: asString(record.failureCategory, "none"),
    violations: asStringArray(record.violations),
    signals: asRecord(record.signals) ?? {},
  };
}


function taskFromHistory(
  message: Message,
  tasks: Task[],
  taskId: number | null,
) {
  if (taskId != null) {
    const byId = tasks.find(
      (task) =>
        task.id === taskId,
    );

    if (byId) {
      return byId;
    }
  }

  if (message.requestId) {
    const byRequest = tasks.find(
      (task) =>
        task.requestId ===
        message.requestId,
    );

    if (byRequest) {
      return byRequest;
    }
  }

  return null;
}

export function reconstructHistoricalRun(
  message: Message,
  tasks: Task[],
): RunResult | null {
  if (
    message.role !== "assistant"
  ) {
    return null;
  }

  const metadata = asRecord(
    message.metadata,
  );

  if (!metadata) {
    return null;
  }

  const rawTaskId =
    metadata.taskId;

  const taskId =
    typeof rawTaskId === "number"
      ? rawTaskId
      : null;

  const task = taskFromHistory(
    message,
    tasks,
    taskId,
  );

  const hasRuntimeMetadata =
    taskId != null ||
    metadata.trace != null ||
    metadata.dag != null ||
    metadata.observability != null ||
    metadata.runtimePhase != null;

  if (
    !task &&
    !hasRuntimeMetadata
  ) {
    return null;
  }

  const scheduler = asString(
    metadata.scheduler,
    task?.scheduler ?? "greedy",
  );

  const planner = asString(
    metadata.planner,
    task?.planner ?? "heuristic",
  );

  const executionMode = asString(
    metadata.executionMode,
    task?.executionMode ?? "auto",
  );

  const synthesisMode = asString(
    metadata.synthesisMode,
    task?.synthesisMode ?? "auto",
  );

  const trace = normalizeTrace(
    metadata.trace ??
      task?.trace ??
      [],
  );

  const dag = normalizeDAG(
    metadata.dag ??
      task?.dag ??
      {},
  );

  const selectedAgents =
    asStringArray(
      metadata.selectedAgents,
    ).length > 0
      ? asStringArray(
          metadata.selectedAgents,
        )
      : task?.selectedAgents ?? [];

  const status = normalizeStatus(
    task?.status ??
      message.status,
  );

  const requestId =
    task?.requestId ??
    message.requestId ??
    `message-${message.id}`;

  const stableTask: Task =
    task ?? {
      id:
        taskId ??
        -message.id,
      conversationId:
        message.conversationId,
      requestId,
      taskText: "",
      scheduler,
      planner,
      executionMode,
      synthesisMode,
      status,
      resultText:
        message.content,
      selectedAgents,
      trace,
      dag,
      latencyMs:
        asNumber(
          metadata.elapsedMs,
        ),
      estimatedCost:
        asNumber(
          metadata.estimatedCost,
        ),
    };

  return {
    task: stableTask,
    status,
    answer: message.content,
    citations: normalizeCitations(
      metadata.citations,
    ),
    scheduler,
    planner,
    executionMode,
    synthesisMode,
    taskProfile:
      normalizeTaskProfile(
        metadata.taskProfile,
      ),
    selectedAgents,
    estimatedCost:
      task?.estimatedCost ??
      asNumber(
        metadata.estimatedCost,
      ),
    elapsedMs:
      task?.latencyMs ??
      asNumber(
        metadata.elapsedMs,
      ),
    trace,
    dag,
    agentFeedback:
      normalizeAgentFeedback(
        metadata.agentFeedback,
      ),
    observability:
      normalizeObservability(
        metadata.observability,
      ),
    scorecard:
      normalizeScorecard(
        metadata.scorecard,
      ),
  };
}
