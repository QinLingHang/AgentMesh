from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
)

from app.mcp.contracts import (
    MCPServerDefinition,
)
from app.tools.contracts import (
    ToolDefinition,
)


class AgentCapabilityProfile(
    BaseModel
):
    model_config = ConfigDict(
        populate_by_name=True
    )

    capability: str

    quality_score: float = Field(
        default=0.8,
        alias="qualityScore",
    )

    avg_latency_ms: int = Field(
        default=1000,
        alias="avgLatencyMs",
    )

    avg_cost: float = Field(
        default=0.0,
        alias="avgCost",
    )

    success_rate: float = Field(
        default=1.0,
        alias="successRate",
    )

    failure_rate: float = Field(
        default=0.0,
        alias="failureRate",
    )

    sample_count: int = Field(
        default=0,
        alias="sampleCount",
    )


class AgentProfile(
    BaseModel
):
    model_config = ConfigDict(
        populate_by_name=True
    )

    id: int
    name: str
    description: str = ""
    endpoint: str
    protocol: str = "http"

    capabilities: list[str]

    capability_profiles: list[
        AgentCapabilityProfile
    ] = Field(
        default_factory=list,
        alias="capabilityProfiles",
    )

    provider: str = "internal"

    model_name: str = Field(
        default="",
        alias="modelName",
    )

    model_runtime: str = Field(
        default="default",
        alias="modelRuntime",
    )

    quality_score: float = Field(
        default=0.8,
        alias="qualityScore",
    )

    avg_latency_ms: int = Field(
        default=1000,
        alias="avgLatencyMs",
    )

    avg_cost: float = Field(
        default=0.0,
        alias="avgCost",
    )

    success_rate: float = Field(
        default=1.0,
        alias="successRate",
    )

    failure_rate: float = Field(
        default=0.0,
        alias="failureRate",
    )

    current_load: float = Field(
        default=0.0,
        alias="currentLoad",
    )

    status: str = "ACTIVE"


class TaskConstraints(
    BaseModel
):
    model_config = ConfigDict(
        populate_by_name=True
    )

    max_latency_ms: int = Field(
        default=8000,
        alias="maxLatencyMs",
    )

    max_cost: float = Field(
        default=0.15,
        alias="maxCost",
    )

    min_quality: float = Field(
        default=0.8,
        alias="minQuality",
    )

    retry_on_worker_loss: bool = Field(
        default=False,
        alias="retryOnWorkerLoss",
    )

RuntimeStatus = Literal[
    "SUBMITTED",
    "RUNNING",
    "COMPLETED",
    "INPUT_REQUIRED",
    "AUTH_REQUIRED",
    "FAILED",
    "CANCELED",
]


class RuntimeContinuation(
    BaseModel
):
    model_config = ConfigDict(
        populate_by_name=True
    )

    protocol: str

    agent_id: int = Field(
        alias="agentId"
    )

    capability: str

    task_id: str = Field(
        alias="taskId",
        min_length=1,
    )

    context_id: str = Field(
        alias="contextId",
        min_length=1,
    )

    state: Literal[
        "INPUT_REQUIRED",
        "AUTH_REQUIRED",
    ]

    # P5 tool approval continuation. These fields are persisted only on the
    # trusted Go side; browsers never submit authoritative tool arguments.
    kind: Literal[
        "agent",
        "tool_approval",
    ] = "agent"

    approval_id: str | None = Field(
        default=None,
        alias="approvalId",
    )

    tool_name: str | None = Field(
        default=None,
        alias="toolName",
    )

    tool_protocol: str | None = Field(
        default=None,
        alias="toolProtocol",
    )

    risk_level: str | None = Field(
        default=None,
        alias="riskLevel",
    )

    requires_confirmation: bool = Field(
        default=False,
        alias="requiresConfirmation",
    )

    arguments: dict[str, Any] = Field(
        default_factory=dict,
    )

    fingerprint: str | None = None
    summary: str | None = None



class ProjectModelRuntime(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    provider: str = "openai-compatible"
    base_url: str = Field(alias="baseUrl")
    model_name: str = Field(alias="modelName")
    vision_model_name: str | None = Field(default=None, alias="visionModelName")
    api_key: SecretStr = Field(alias="apiKey")

class RuntimeAttachment(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    name: str = Field(min_length=1, max_length=255)
    media_type: str = Field(alias="mediaType", min_length=1, max_length=128)
    extension: str = Field(min_length=1, max_length=32)
    size_bytes: int = Field(alias="sizeBytes", gt=0)
    content_base64: str = Field(alias="contentBase64", min_length=1)


class InteractiveMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=6000)


class InteractiveStreamRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    user_id: int
    request_id: str
    conversation_id: int | None = Field(default=None, alias="conversationId")
    task: str = Field(min_length=1, max_length=20000)
    history: list[InteractiveMessage] = Field(default_factory=list, max_length=10)
    project_model: ProjectModelRuntime | None = Field(default=None, alias="projectModel")
    attachments: list[RuntimeAttachment] = Field(default_factory=list, max_length=6)


class RuntimeRequest(
    BaseModel
):
    model_config = ConfigDict(
        populate_by_name=True
    )

    user_id: int
    request_id: str

    conversation_id: int | None = Field(
        default=None,
        alias="conversationId",
    )

    continuation: (
        RuntimeContinuation
        | None
    ) = None

    project_model: ProjectModelRuntime | None = Field(
        default=None,
        alias="projectModel",
    )

    task: str = Field(
        min_length=1,
        max_length=20000,
    )

    scheduler: Literal[
        "fixed",
        "capability",
        "greedy",
        "adaptive",
    ] = "greedy"

    planner: Literal[
    "heuristic",
    "multi_objective",
    ] = "heuristic"

    execution_mode: Literal[
        "auto",
        "parallel",
        "sequential",
    ] = Field(
        default="auto",
        alias="executionMode",
    )

    synthesis_mode: Literal[
        "auto",
        "always",
        "never",
    ] = Field(
        default="auto",
        alias="synthesisMode",
    )

    constraints: TaskConstraints = Field(
        default_factory=TaskConstraints
    )

    agents: list[AgentProfile]

    tools: list[ToolDefinition] = Field(
        default_factory=list
    )

    mcp_servers: list[
        MCPServerDefinition
    ] = Field(
        default_factory=list
    )

    attachments: list[RuntimeAttachment] = Field(
        default_factory=list
    )


class TaskProfile(
    BaseModel
):
    required_capabilities: list[str]

    complexity: Literal[
        "low",
        "medium",
        "high",
    ]

    risk_level: Literal[
        "low",
        "medium",
        "high",
    ]

    modality: list[str]

    parallelizable: bool


class Assignment(
    BaseModel
):
    capability: str
    agent_id: int
    agent_name: str


class DAGNode(
    BaseModel
):
    model_config = ConfigDict(
        populate_by_name=True
    )

    id: str
    label: str
    kind: str

    status: Literal[
        "pending",
        "running",
        "completed",
        "error",
        "skipped",
    ] = "pending"

    capability: str | None = None

    agent_id: int | None = Field(
        default=None,
        alias="agentId",
    )

    agent_name: str | None = Field(
        default=None,
        alias="agentName",
    )
    optional: bool = False
    condition: str | None = None


class DAGEdge(
    BaseModel
):
    source: str
    target: str


class DynamicDAG(
    BaseModel
):
    nodes: list[
        DAGNode
    ]

    edges: list[
        DAGEdge
    ]


class TraceEvent(
    BaseModel
):
    model_config = ConfigDict(
        populate_by_name=True
    )

    kind: str
    title: str

    status: Literal[
        "running",
        "completed",
        "error",
        "skipped",
    ]

    detail: str = ""

    elapsed_ms: int = Field(
        default=0,
        alias="elapsedMs",
    )


class AgentFeedback(
    BaseModel
):
    model_config = ConfigDict(
        populate_by_name=True
    )

    agent_id: int = Field(
        alias="agentId"
    )

    capability: str

    success: bool

    latency_ms: int = Field(
        alias="latencyMs"
    )

    cost: float

    quality_score: float | None = Field(
    default=None,
    alias="qualityScore",)

    error_type: str = Field(
        default="",
        alias="errorType",
    )

class ObservabilitySummary(
    BaseModel
):
    model_config = ConfigDict(
        populate_by_name=True
    )

    model_calls: int = Field(
        default=0,
        alias="modelCalls",
    )

    model_input_tokens: int = Field(
        default=0,
        alias="modelInputTokens",
    )

    model_output_tokens: int = Field(
        default=0,
        alias="modelOutputTokens",
    )

    model_total_tokens: int = Field(
        default=0,
        alias="modelTotalTokens",
    )

    model_latency_ms: int = Field(
        default=0,
        alias="modelLatencyMs",
    )

    tool_calls: int = Field(
        default=0,
        alias="toolCalls",
    )

    mcp_events: int = Field(
        default=0,
        alias="mcpEvents",
    )

    agent_attempts: int = Field(
        default=0,
        alias="agentAttempts",
    )

    agent_successes: int = Field(
        default=0,
        alias="agentSuccesses",
    )

    agent_failures: int = Field(
        default=0,
        alias="agentFailures",
    )

    reschedules: int = 0

    dag_completed_nodes: int = Field(
        default=0,
        alias="dagCompletedNodes",
    )

    dag_skipped_nodes: int = Field(
        default=0,
        alias="dagSkippedNodes",
    )

    quality_evaluations: int = Field(
        default=0,
        alias="qualityEvaluations",
    )

    average_quality: float = Field(
        default=0.0,
        alias="averageQuality",
    )

    model_estimated_cost: float = Field(
        default=0.0,
        alias="modelEstimatedCost",
    )

    model_cost_known: bool = Field(
        default=False,
        alias="modelCostKnown",
    )

    model_provider: str = Field(
        default="",
        alias="modelProvider",
    )

    model_name: str = Field(
        default="",
        alias="modelName",
    )

    retrieval_mode: str = Field(
        default="",
        alias="retrievalMode",
    )

    rag_latency_ms: int = Field(
        default=0,
        alias="ragLatencyMs",
    )

    rag_raw_hits: int = Field(
        default=0,
        alias="ragRawHits",
    )

    rag_hits: int = Field(
        default=0,
        alias="ragHits",
    )

    rag_context_hits: int = Field(
        default=0,
        alias="ragContextHits",
    )

    rag_text_candidates: int = Field(
        default=0,
        alias="ragTextCandidates",
    )

    rag_visual_candidates: int = Field(
        default=0,
        alias="ragVisualCandidates",
    )

    tool_successes: int = Field(
        default=0,
        alias="toolSuccesses",
    )

    tool_failures: int = Field(
        default=0,
        alias="toolFailures",
    )


class RunScorecard(
    BaseModel
):
    """P6 per-run evaluation and governance scorecard.

    This is developer-facing observability metadata. It intentionally stores
    scores/counters only and never raw Memory, Tool, RAG, or user-secret text.
    """

    model_config = ConfigDict(
        populate_by_name=True
    )

    evaluator: str = "p6_deterministic_v1"

    status: Literal[
        "pass",
        "warning",
        "fail",
        "unavailable",
    ] = "unavailable"

    overall_score: float = Field(
        default=0.0,
        alias="overallScore",
    )

    task_success: float = Field(
        default=0.0,
        alias="taskSuccess",
    )

    answer_quality: float = Field(
        default=0.0,
        alias="answerQuality",
    )

    groundedness: float = 0.0

    correctness: float = 0.0

    citation_quality: float = Field(
        default=0.0,
        alias="citationQuality",
    )

    task_completion: float = Field(
        default=0.0,
        alias="taskCompletion",
    )

    judge_reason: str = Field(
        default="",
        alias="judgeReason",
    )

    tool_reliability: float = Field(
        default=0.0,
        alias="toolReliability",
    )

    rag_quality: float = Field(
        default=0.0,
        alias="ragQuality",
    )

    memory_contribution: float = Field(
        default=0.0,
        alias="memoryContribution",
    )

    budget_compliance: float = Field(
        default=0.0,
        alias="budgetCompliance",
    )

    latency_ms: int = Field(
        default=0,
        alias="latencyMs",
    )

    estimated_cost: float = Field(
        default=0.0,
        alias="estimatedCost",
    )

    model_estimated_cost: float = Field(
        default=0.0,
        alias="modelEstimatedCost",
    )

    model_tokens: int = Field(
        default=0,
        alias="modelTokens",
    )

    failure_category: str = Field(
        default="none",
        alias="failureCategory",
    )

    violations: list[str] = Field(
        default_factory=list,
    )

    signals: dict[str, Any] = Field(
        default_factory=dict,
    )


class RuntimeCitation(
    BaseModel
):
    """
    User-facing structured citation metadata.

    This is intentionally different from
    EvidenceProvenance:

        EvidenceProvenance
            Internal RAG/runtime domain contract.

        RuntimeCitation
            External API response contract.

    Only stable, user-facing provenance fields belong here.

    Retrieval diagnostics such as:

        userId
        rrfScore
        reranker
        ragDiagnostics

    must remain in Trace / Observability and must not leak
    into this response model.
    """

    model_config = ConfigDict(
        populate_by_name=True
    )

    citation_id: int = Field(
        alias="citationId",
    )

    label: str

    document_id: str = Field(
        alias="documentId",
    )

    source: str

    score: float

    document_type: (
        str
        | None
    ) = Field(
        default=None,
        alias="documentType",
    )

    chunk_index: (
        int
        | None
    ) = Field(
        default=None,
        alias="chunkIndex",
    )

    start: (
        int
        | None
    ) = None

    end: (
        int
        | None
    ) = None

    page_number: (
        int
        | None
    ) = Field(
        default=None,
        alias="pageNumber",
        exclude_if=lambda value: value is None,
    )

    asset_id: (
        str
        | None
    ) = Field(
        default=None,
        alias="assetId",
        exclude_if=lambda value: value is None,
    )

    modality: (
        str
        | None
    ) = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )

    visual_type: (
        str
        | None
    ) = Field(
        default=None,
        alias="visualType",
        exclude_if=lambda value: value is None,
    )

class RuntimeResponse(
    BaseModel
):
    model_config = ConfigDict(
        populate_by_name=True
    )

    request_id: str

    status: RuntimeStatus = (
        "COMPLETED"
    )

    answer: str

    citations: list[
        RuntimeCitation
    ] = Field(
        default_factory=list
    )

    continuation: (
        RuntimeContinuation
        | None
    ) = None

    scheduler: str

    task_profile: TaskProfile

    selected_agents: list[str]

    estimated_cost: float
    elapsed_ms: int

    trace: list[
        TraceEvent
    ]

    dag: DynamicDAG

    agent_feedback: list[
        AgentFeedback
    ]

    observability: ObservabilitySummary = Field(
        default_factory=ObservabilitySummary
    )

    scorecard: RunScorecard | None = None
