from __future__ import annotations

import asyncio
import base64
import json
import time
from dataclasses import replace
from typing import Any, Callable


from app.rag.agentic_retrieval import (
    AgenticRetrievalExecutor,
    HeuristicEvidenceGrader,
)

from app.rag.model_intelligence import (
    ModelBackedEvidenceGrader,
    ModelBackedQueryTransformer,
)

from app.agents import (
    A2AAgentInterruptedError,
    A2ACapabilityDiscovery,
    AgentExecutionRequest,
    AgentExecutorResolver,
)
from app.agents.capability import (
    apply_capability_feedback,
    effective_capability_profile,
)
from app.config import settings
from app.capabilities import (
    contextualize_discovery_task,
    continuation_subject_task,
    discover_capabilities,
    discover_mcp_tools,
    discovery_context,
)
from app.eval import (
    EvaluationRequest,
    HeuristicEvaluator,
)
from app.eval.scorecard import (
    ScorecardInputs,
    build_run_scorecard,
)
from app.kernel import (
    PluginRegistry,
)
from app.mcp import (
    MCPFailureBackoff,
    MCPManager,
    MCPToolAdapter,
)
from app.memory import (
    AutomaticLongTermMemoryForgetter,
    AutomaticLongTermMemoryWriter,
    ControlPlaneLongTermMemoryDeleteSink,
    ControlPlaneLongTermMemorySink,
    ControlPlaneLongTermMemorySource,
    ConversationMemory,
    HybridLongTermMemoryRetriever,
    InMemoryConversationMemory,
    LongTermMemoryRetriever,
    MemoryMessage,
    ModelBackedMemoryExtractor,
    RedisConversationMemory,
    RetrievedLongTermMemory,
    is_memory_overview_query,
)
from app.memory.conversation_context import (
    ControlPlaneConversationMemoryStore,
    ConversationMemoryRetriever,
    ModelBackedConversationCompactor,
    RetrievedConversationMemory,
)
from app.models.runtime import (
    ModelRuntimeResolver,
)
from app.models.contracts import ModelInputAttachment
from app.knowledge.parser import parse_document_bytes
from app.knowledge import (
    KnowledgeDiscoveryResult,
    discover_knowledge_bases,
    set_candidate_knowledge_ids,
)
from app.semantics import (
    KnowledgeDependency,
    RagPreference,
    analyze_task_semantics,
)
from app.multimodal.retrieval import (
    classify_retrieval_mode,
    diversify_multimodal_hits,
    filter_hits_for_mode,
)
from app.rag import (
    AdaptiveRAGRouter,
    RAGMode,
    HashEmbeddingProvider,
    HeuristicReranker,
    HybridMilvusRetriever,
    InMemoryRetriever,
    MilvusRetriever,
    OpenAICompatibleEmbeddingProvider,
    QwenReranker,
    RetrievalHit,
    Retriever,
    build_evidence_provenance,
)
from app.schemas import (
    AgentFeedback,
    AgentProfile,
    Assignment,
    RuntimeCitation,
    RuntimeContinuation,
    RuntimeRequest,
    RuntimeResponse,
    TraceEvent,
)
from app.services.collaboration_planner import (
    CollaborationPlan,
    CollaborationPlanner,
    MultiObjectiveCollaborationPlanner,
)
from app.services.knowledge_step_gate import partition_knowledge_steps
from app.services.context_builder import (
    build_agent_context,
)
from app.services.synthesis_context import (
    build_synthesis_context,
    select_synthesis_evidence,
)
from app.services.citation_validator import (
    guard_answer_citations,
)
from app.services.citation_projection import (
    project_used_citations,
)
from app.services.grounded_answer_guard import (
    guard_grounded_answer,
)
from app.services.platform_capability_grounding import (
    build_platform_capability_context,
    guard_platform_capability_answer,
)
from app.services.dag import (
    build_dag,
)
from app.planning import (
    ExecutionPlan,
    PlanStep,
    PlanValidator,
    SemanticReplanner,
    SemanticTaskPlanner,
)
from app.services.plan_compiler import (
    PlanCompiler,
)
from app.services.quality_gate import (
    QualityGate,
    QualityGateError,
)
from app.eval.repair import (
    RepairPromptBuilder,
)
from app.services.dag_executor import (
    DAGExecutionError,
    DAGExecutor,
)
from app.services.observability import (
    build_observability_summary,
)
from app.services.profiler import (
    profile_task,
)
from app.services.rescheduler import (
    RuntimeRescheduler,
)
from app.services.request_policy import (
    should_retrieve_long_term_memory,
)
from app.tools import (
    ToolApprovalRequest,
    ToolApprovalRequired,
    ToolRegistry,
    register_builtin_tools,
    register_demo_tools,
    register_desktop_tools,
    tool_call_fingerprint,
)
from app.tools.loop import safe as safe_tool_payload


# ============================================================
# Runtime Control-flow Signal
# ============================================================


class RuntimeTaskInterrupted(
    RuntimeError
):
    """
    AgentMesh Runtime 层的“暂停”控制信号。

    它和普通 Exception 的语义不同。

    普通异常：
        Agent 真正失败
            ↓
        Failed Feedback
            ↓
        Capability Profile 降低
            ↓
        Runtime Rescheduler

    RuntimeTaskInterrupted：
        INPUT_REQUIRED / AUTH_REQUIRED
            ↓
        Agent 没失败
            ↓
        Suspend
            ↓
        保存 task_id / context_id
            ↓
        等待用户继续输入
    """

    def __init__(
        self,
        *,
        agent: AgentProfile,
        capability: str,
        state: str,
        task_id: str,
        context_id: str,
        message: str,
        estimated_cost: float = 0.0,
        continuation_protocol: str | None = None,
        approval: ToolApprovalRequest | None = None,
    ) -> None:
        super().__init__(
            message
        )

        self.agent = (
            agent
        )

        self.capability = (
            capability
        )

        self.state = (
            state
        )

        self.task_id = (
            task_id
        )

        self.context_id = (
            context_id
        )

        self.message = (
            message
        )

        self.estimated_cost = (
            estimated_cost
        )

        self.continuation_protocol = (
            continuation_protocol
            or agent.protocol
        )

        self.approval = approval


def find_runtime_interruption(
    exc: BaseException,
) -> RuntimeTaskInterrupted | None:
    """
    从异常链中找到 RuntimeTaskInterrupted。

    DAGExecutor 会把节点异常包装成 DAGExecutionError：

        RuntimeTaskInterrupted
                ↓
        DAGExecutionError

    Runtime 层需要把这种控制流异常重新识别出来，
    而不能把 INPUT_REQUIRED 当成真正的 DAG Failure。
    """

    current: BaseException | None = (
        exc
    )

    visited: set[int] = set()

    while current is not None:

        current_id = id(
            current
        )

        if (
            current_id
            in visited
        ):
            break

        visited.add(
            current_id
        )

        if isinstance(
            current,
            RuntimeTaskInterrupted,
        ):

            return current

        if (
            current.__cause__
            is not None
        ):

            current = (
                current.__cause__
            )

        else:

            current = (
                current.__context__
            )

    return None

# ============================================================
# Runtime Engine
# ============================================================


class RuntimeEngine:
    def __init__(
        self,
        registry: PluginRegistry,
        *,
        retriever: Retriever | None = None,
        memory: ConversationMemory | None = None,
        long_term_memory_retriever: LongTermMemoryRetriever | None = None,
        mcp_targets: dict[int, Any] | None = None,
    ) -> None:
        self.registry = (
            registry
        )

        # Test/development injection for in-process MCP targets.
        # Production normally leaves this empty and uses the configured HTTP endpoint.
        self.mcp_targets = dict(mcp_targets or {})

        # ====================================================
        # Agent Executor Resolver
        #
        # AgentProfile.protocol
        #       ↓
        # agent.<protocol>
        #
        # internal
        # http
        # langgraph
        # a2a
        # ====================================================

        self.executor_resolver = (
            AgentExecutorResolver(
                registry
            )
        )

        # ====================================================
        # A2A Capability Discovery
        #
        # Agent Card
        #    ↓
        # Skills
        #    ↓
        # AgentProfile.capabilities
        #    ↓
        # Capability Profile
        #    ↓
        # Scheduler
        # ====================================================

        self.a2a_discovery = (
            A2ACapabilityDiscovery(
                timeout_seconds=(
                    settings
                    .a2a_timeout_seconds
                ),
                trust_env=(
                    settings
                    .a2a_http_trust_env
                ),
                cache_ttl_seconds=(
                    settings
                    .a2a_discovery_cache_ttl_seconds
                ),
            )
        )

        # ====================================================
        # Model Runtime Resolver
        # ====================================================

        self.model_runtime_resolver = (
            ModelRuntimeResolver(
                registry.context
            )
        )

                # ====================================================
        # Agentic RAG Intelligence Model
        #
        # 直接复用 Kernel 中已经注册的 Model Gateway。
        #
        # 不重新创建：
        # Qwen Client / OpenAI Client / HTTP Client
        #
        # 所以仍然继承：
        # Provider abstraction
        # Timeout
        # Retry
        # Model events
        # ====================================================

        try:

            self.rag_intelligence_model = (
                registry
                .context
                .get(
                    "model.default"
                )
            )

        except KeyError:

            self.rag_intelligence_model = (
                None
            )
        # ====================================================
        # Runtime Rescheduler
        # ====================================================

        self.runtime_rescheduler = (
            RuntimeRescheduler()
        )

        # ====================================================
        # Dynamic DAG Executor
        # ====================================================

        self.dag_executor = (
            DAGExecutor()
        )

        # ====================================================
        # Collaboration Planner
        # ====================================================

        self.collaboration_planners = {
            "heuristic":
                CollaborationPlanner(),

            "multi_objective":
                MultiObjectiveCollaborationPlanner(),
        }

        # ====================================================
        # Adaptive Workflow Orchestration
        # ====================================================

        self.plan_validator = PlanValidator(
            max_steps=settings.semantic_planner_max_steps
        )
        self.semantic_planner = SemanticTaskPlanner(
            validator=self.plan_validator,
            timeout_seconds=settings.semantic_planner_timeout_seconds,
        )
        self.semantic_replanner = SemanticReplanner(
            validator=self.plan_validator,
            timeout_seconds=settings.semantic_planner_timeout_seconds,
        )
        self.plan_compiler = PlanCompiler()

        # ====================================================
        # Evaluator / Quality Gate
        # ====================================================

        self.evaluator = (
            HeuristicEvaluator()
        )
        self.quality_gate = QualityGate(
            enabled=settings.quality_gate_enabled,
            pass_threshold=settings.quality_gate_pass_threshold,
            hard_fail_threshold=settings.quality_gate_hard_fail_threshold,
            max_repair_attempts=settings.max_quality_repair_attempts,
        )
        self.repair_prompt_builder = RepairPromptBuilder()

        # ====================================================
        # MCP Discovery Failure Backoff
        # ====================================================

        self.mcp_failure_backoff = (
            MCPFailureBackoff(
                base_seconds=30.0,
                max_seconds=300.0,
            )
        )
                # ====================================================
        # Adaptive RAG Router
        #
        # Query
        #   ↓
        # Query Intelligence
        #   ↓
        #
        # NO_RAG
        # FAST_RAG
        # AGENTIC_RAG
        #
        # Retriever 只是“怎么检索”。
        # Router 决定“要不要检索”。
        # ====================================================

        self.rag_router = (
            AdaptiveRAGRouter()
        )
        # ====================================================
        # RAG Retriever
        #
        # Priority:
        #
        # injected
        #    ↓
        # hybrid_milvus
        #    ↓
        # milvus
        #    ↓
        # inmemory
        # ====================================================

        self._owns_retriever = (
            retriever is None
        )

        if retriever is not None:

            self.retriever = (
                retriever
            )

        # ====================================================
        # Hybrid Milvus RAG
        # ====================================================

        elif (
            settings
            .rag_backend
            .strip()
            .lower()
            == "hybrid_milvus"
        ):

            embedding_backend = (
                settings
                .embedding_backend
                .strip()
                .lower()
            )

            # ------------------------------------------------
            # Embedding Provider
            # ------------------------------------------------

            if (
                embedding_backend
                == "openai_compatible"
            ):

                embedding = (
                    OpenAICompatibleEmbeddingProvider(
                        api_key=(
                            settings
                            .embedding_api_key
                        ),
                        base_url=(
                            settings
                            .embedding_base_url
                        ),
                        model=(
                            settings
                            .embedding_model
                        ),
                        dimension=(
                            settings
                            .embedding_dimension
                        ),
                        trust_env=(
                            settings
                            .embedding_http_trust_env
                        ),
                    )
                )

            else:

                embedding = (
                    HashEmbeddingProvider(
                        dimension=(
                            settings
                            .embedding_dimension
                        )
                    )
                )

            # ------------------------------------------------
            # Reranker
            # ------------------------------------------------

            reranker = (
                HeuristicReranker()
            )

            if (
                settings
                .reranker_backend
                .strip()
                .lower()
                == "qwen"
            ):

                reranker_api_key = (
                    settings
                    .reranker_api_key
                    .strip()
                    or
                    settings
                    .embedding_api_key
                    .strip()
                )

                if reranker_api_key:

                    reranker = (
                        QwenReranker(
                            api_key=(
                                reranker_api_key
                            ),
                            base_url=(
                                settings
                                .reranker_base_url
                            ),
                            model=(
                                settings
                                .reranker_model
                            ),
                            timeout_seconds=(
                                settings
                                .reranker_timeout_seconds
                            ),
                            trust_env=(
                                settings
                                .reranker_http_trust_env
                            ),
                            instruct=(
                                settings
                                .reranker_instruct
                            ),
                        )
                    )

            self.retriever = (
                HybridMilvusRetriever(
                    uri=(
                        settings
                        .milvus_uri
                    ),
                    collection_name=(
                        settings
                        .milvus_hybrid_collection
                    ),
                    embedding=(
                        embedding
                    ),
                    candidate_k=(
                        settings
                        .rag_candidate_k
                    ),
                    rrf_k=(
                        settings
                        .rag_rrf_k
                    ),
                    reranker=(
                        reranker
                    ),
                    fallback_reranker=(
                        HeuristicReranker()
                    ),
                )
            )

        # ====================================================
        # Standard Milvus
        # ====================================================

        elif (
            settings
            .rag_backend
            .strip()
            .lower()
            == "milvus"
        ):

            embedding_backend = (
                settings
                .embedding_backend
                .strip()
                .lower()
            )

            if (
                embedding_backend
                == "openai_compatible"
            ):

                embedding = (
                    OpenAICompatibleEmbeddingProvider(
                        api_key=(
                            settings
                            .embedding_api_key
                        ),
                        base_url=(
                            settings
                            .embedding_base_url
                        ),
                        model=(
                            settings
                            .embedding_model
                        ),
                        dimension=(
                            settings
                            .embedding_dimension
                        ),
                        trust_env=(
                            settings
                            .embedding_http_trust_env
                        ),
                    )
                )

            else:

                embedding = (
                    HashEmbeddingProvider(
                        dimension=(
                            settings
                            .embedding_dimension
                        )
                    )
                )

            self.retriever = (
                MilvusRetriever(
                    uri=(
                        settings
                        .milvus_uri
                    ),
                    collection_name=(
                        settings
                        .milvus_collection
                    ),
                    embedding=(
                        embedding
                    ),
                )
            )

        # ====================================================
        # InMemory Retriever
        # ====================================================

        else:

            self.retriever = (
                InMemoryRetriever()
            )

                # ====================================================
        # Agentic Retrieval Executor
        #
        # AdaptiveRAGRouter:
        #   decides whether/how to retrieve
        #
        # AgenticRetrievalExecutor:
        #   executes multi-round adaptive retrieval
        # ====================================================

        self.agentic_retrieval = (
            AgenticRetrievalExecutor(
                retriever=(
                    self.retriever
                )
            )
        )
        # ====================================================
        # Conversation Memory
        #
        # injected
        #   ↓
        # Redis
        #   ↓
        # InMemory
        # ====================================================

        self._owns_memory = (
            memory is None
        )

        if memory is not None:

            self.memory = (
                memory
            )

        elif (
            settings
            .memory_backend
            .strip()
            .lower()
            == "redis"
        ):

            self.memory = (
                RedisConversationMemory(
                    redis_url=(
                        settings
                        .redis_url
                    ),
                    max_messages=(
                        settings
                        .memory_max_messages
                    ),
                    ttl_seconds=(
                        settings
                        .memory_ttl_seconds
                    ),
                    key_prefix=(
                        settings
                        .memory_key_prefix
                    ),
                )
            )

        else:

            self.memory = (
                InMemoryConversationMemory(
                    max_messages=(
                        settings
                        .memory_max_messages
                    )
                )
            )

        # ====================================================
        # User-global Long-term Memory Automatic Writer (P3.2)
        #
        # Source boundary:
        #   ONLY req.task (direct user text) is passed in.
        #
        # Never passed in:
        #   Project Knowledge / RAG evidence / citations /
        #   tool results / MCP results / assistant output.
        #
        # Go Control Plane remains the ownership/persistence
        # boundary. Python does not access MySQL directly.
        # ====================================================

        model_extractor = None

        if (
            settings
            .memory_auto_inference_enabled
            and self.rag_intelligence_model
            is not None
        ):
            model_extractor = (
                ModelBackedMemoryExtractor(
                    self.rag_intelligence_model,
                    model_name=(
                        settings.model_name
                    ),
                    max_items=(
                        settings
                        .memory_auto_write_max_items
                    ),
                )
            )

        self.long_term_memory_writer = (
            AutomaticLongTermMemoryWriter(
                sink=(
                    ControlPlaneLongTermMemorySink(
                        internal_token=(
                            settings.internal_token
                        ),
                        timeout_seconds=(
                            settings
                            .memory_auto_write_timeout_seconds
                        ),
                    )
                ),
                model_extractor=(
                    model_extractor
                ),
                enabled=(
                    settings
                    .memory_auto_write_enabled
                ),
            )
        )

        # ====================================================
        # User-global Long-term Memory Retrieval (P3.3)
        #
        # Retrieval reads ONLY user-owned Memory through Go.
        # It is independent from Project Knowledge RAG and does
        # not receive project_id, RAG evidence, tool/MCP output,
        # citations, or assistant output.
        # ====================================================

        self._owns_long_term_memory_retriever = (
            long_term_memory_retriever is None
        )

        if long_term_memory_retriever is not None:
            self.long_term_memory_retriever = long_term_memory_retriever
        else:
            memory_retrieval_embedding = None
            memory_embedding_backend = (
                settings
                .memory_retrieval_embedding_backend
                .strip()
                .lower()
            )

            if memory_embedding_backend == "openai_compatible":
                if settings.embedding_api_key.strip():
                    memory_retrieval_embedding = (
                        OpenAICompatibleEmbeddingProvider(
                            api_key=settings.embedding_api_key,
                            base_url=settings.embedding_base_url,
                            model=settings.embedding_model,
                            dimension=settings.embedding_dimension,
                            trust_env=settings.embedding_http_trust_env,
                        )
                    )
            elif memory_embedding_backend != "none":
                memory_retrieval_embedding = (
                    HashEmbeddingProvider(
                        dimension=settings.embedding_dimension
                    )
                )

            self.long_term_memory_retriever = (
                HybridLongTermMemoryRetriever(
                    source=(
                        ControlPlaneLongTermMemorySource(
                            internal_token=settings.internal_token,
                            timeout_seconds=(
                                settings
                                .memory_retrieval_timeout_seconds
                            ),
                        )
                    ),
                    embedding=memory_retrieval_embedding,
                    enabled=settings.memory_retrieval_enabled,
                    candidate_limit=(
                        settings
                        .memory_retrieval_candidate_limit
                    ),
                    top_k=settings.memory_retrieval_top_k,
                    min_score=settings.memory_retrieval_min_score,
                    semantic_weight=(
                        settings
                        .memory_retrieval_semantic_weight
                    ),
                    lexical_weight=(
                        settings
                        .memory_retrieval_lexical_weight
                    ),
                    confidence_weight=(
                        settings
                        .memory_retrieval_confidence_weight
                    ),
                    authority_weight=(
                        settings
                        .memory_retrieval_authority_weight
                    ),
                    relevance_weight=(
                        settings
                        .memory_retrieval_relevance_weight
                    ),
                )
            )


        # ====================================================
        # Conversation Memory Capsules (P20)
        #
        # Raw conversation history remains durable in MySQL. Redis keeps only
        # a small working window; older ranges are compressed asynchronously
        # and retrieved selectively without a paid model call per request.
        # ====================================================

        self.conversation_memory_store = ControlPlaneConversationMemoryStore(
            internal_token=settings.internal_token,
            base_url=settings.control_plane_internal_base_url,
            timeout_seconds=settings.memory_retrieval_timeout_seconds,
        )
        self.conversation_memory_retriever = ConversationMemoryRetriever(
            store=self.conversation_memory_store,
            enabled=settings.conversation_memory_retrieval_enabled,
            candidate_limit=settings.conversation_memory_retrieval_candidate_limit,
            top_k=settings.conversation_memory_retrieval_top_k,
            min_score=settings.conversation_memory_retrieval_min_score,
            max_chars=settings.conversation_memory_retrieval_max_chars,
        )
        self.conversation_memory_compactor = ModelBackedConversationCompactor(
            store=self.conversation_memory_store,
            enabled=settings.conversation_memory_compaction_enabled,
            min_messages=settings.conversation_memory_compaction_min_messages,
            max_messages=settings.conversation_memory_compaction_max_messages,
            reserve_recent=settings.conversation_memory_compaction_reserve_recent,
            min_input_chars=settings.conversation_memory_compaction_min_input_chars,
            max_input_chars=settings.conversation_memory_compaction_max_input_chars,
            max_output_tokens=settings.conversation_memory_compaction_max_output_tokens,
            timeout_seconds=settings.conversation_memory_compaction_timeout_seconds,
            failure_backoff_seconds=settings.conversation_memory_compaction_failure_backoff_seconds,
            redis_url=settings.redis_url,
            lock_prefix=settings.conversation_memory_compaction_lock_prefix,
            lock_ttl_seconds=settings.conversation_memory_compaction_lock_ttl_seconds,
        )


        # Explicit conversational forget is the user-facing management path.
        # It reuses the same user-global retriever to resolve a target, but
        # deletion still crosses the trusted Go ownership boundary.
        self.long_term_memory_forgetter = (
            AutomaticLongTermMemoryForgetter(
                retriever=self.long_term_memory_retriever,
                sink=ControlPlaneLongTermMemoryDeleteSink(
                    internal_token=settings.internal_token,
                    timeout_seconds=settings.memory_retrieval_timeout_seconds,
                ),
            )
        )

    # ========================================================
    # Lifecycle
    # ========================================================

    async def close(
        self,
    ) -> None:

        # ====================================================
        # Long-term Memory Retrieval lifecycle
        # ====================================================

        if self._owns_long_term_memory_retriever:
            close_long_term_retriever = getattr(
                self.long_term_memory_retriever,
                "aclose",
                None,
            )
            if close_long_term_retriever is not None:
                await close_long_term_retriever()

        # ====================================================
        # Memory lifecycle
        # ====================================================

        if self._owns_memory:

            close_memory = (
                getattr(
                    self.memory,
                    "aclose",
                    None,
                )
            )

            if close_memory is not None:

                await close_memory()

        # ====================================================
        # Retriever lifecycle
        # ====================================================

        if self._owns_retriever:

            close_retriever = (
                getattr(
                    self.retriever,
                    "aclose",
                    None,
                )
            )

            if close_retriever is not None:

                await close_retriever()

    # ========================================================
    # P5 Human-in-the-loop Tool Approval Resume
    # ========================================================

    async def _resume_tool_approval(
        self,
        *,
        req: RuntimeRequest,
        trace: list[TraceEvent],
        feedback: list[AgentFeedback],
        selected_names: list[str],
        started: float,
        event,
    ) -> RuntimeResponse:
        continuation = req.continuation
        if continuation is None:
            raise RuntimeError("tool approval resume requires continuation")

        decision = req.task.strip().lower()
        if decision not in {"approve", "reject"}:
            raise RuntimeError("tool approval decision must be approve or reject")

        agent = next(
            (item for item in req.agents if item.id == continuation.agent_id),
            None,
        )
        if agent is None:
            raise RuntimeError("approval agent is no longer available")

        selected_names.append(agent.name)
        profile = profile_task("human approval for tool action")
        dag = build_dag(
            [
                Assignment(
                    capability=continuation.capability,
                    agent_id=agent.id,
                    agent_name=agent.name,
                )
            ],
            execution_mode="sequential",
        )
        for node in dag.nodes:
            if node.kind == "agent":
                node.status = "skipped"
            elif node.id == "synthesize":
                node.status = "skipped"

        approval_id = continuation.approval_id or continuation.task_id
        tool_name = continuation.tool_name or ""

        if decision == "reject":
            event(
                "approval",
                "Approval Rejected",
                "completed",
                json.dumps(
                    {
                        "approvalId": approval_id,
                        "tool": tool_name,
                        "fingerprint": continuation.fingerprint,
                    },
                    ensure_ascii=False,
                ),
            )
            event("task", "Task Completed", "completed", "action rejected by user")
            observability = build_observability_summary(
                trace=trace,
                feedback=feedback,
                dag=dag,
            )
            scorecard = None
            if settings.eval_scorecard_enabled:
                try:
                    scorecard = build_run_scorecard(
                        ScorecardInputs(
                            answer="好的，这次操作已取消，没有执行。",
                            trace=trace,
                            feedback=feedback,
                            citations=[],
                            constraints=req.constraints,
                            elapsed_ms=int((time.perf_counter() - started) * 1000),
                            estimated_cost=0.0,
                            observability=observability,
                        )
                    )
                    event(
                        "eval",
                        "Run Scorecard",
                        "completed",
                        json.dumps(scorecard.model_dump(by_alias=True), ensure_ascii=False),
                    )
                except Exception as exc:
                    event(
                        "eval",
                        "Run Scorecard",
                        "error",
                        json.dumps({"reason": "scorecard_unavailable", "errorType": type(exc).__name__}),
                    )
            return RuntimeResponse(
                request_id=req.request_id,
                status="COMPLETED",
                answer="好的，这次操作已取消，没有执行。",
                continuation=None,
                scheduler=req.scheduler,
                task_profile=profile,
                selected_agents=selected_names,
                estimated_cost=0.0,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                trace=trace,
                dag=dag,
                agent_feedback=feedback,
                observability=observability,
                scorecard=scorecard,
            )

        if not tool_name or not continuation.fingerprint:
            raise RuntimeError("invalid persisted tool approval continuation")

        registry = ToolRegistry(timeout=settings.tool_timeout_seconds)
        demo_registry = ToolRegistry(timeout=settings.tool_timeout_seconds)
        register_builtin_tools(demo_registry)
        register_demo_tools(demo_registry)
        register_desktop_tools(demo_registry)
        demo_handlers = {
            tool.name: demo_registry._adapters[tool.name].handler
            for tool in demo_registry.list()
        }

        for tool in req.tools:
            if tool.protocol == "internal" and tool.name in demo_handlers:
                registry.register(tool, demo_handlers[tool.name])
            elif tool.protocol == "http":
                registry.register(tool)

        def approval_mcp_event(payload: dict[str, Any]) -> None:
            data = dict(payload)
            title = str(data.pop("title", "MCP Event"))
            status = str(data.pop("status", "completed"))
            event("mcp", title, status, json.dumps(data, ensure_ascii=False))

        async def execute_exact_action() -> Any:
            current_tool = registry.get(tool_name)
            actual_fingerprint = tool_call_fingerprint(
                current_tool,
                continuation.arguments,
            )
            if actual_fingerprint != continuation.fingerprint:
                event(
                    "approval",
                    "Approval Invalidated",
                    "error",
                    json.dumps(
                        {
                            "approvalId": approval_id,
                            "tool": tool_name,
                            "reason": "tool_or_arguments_changed",
                        },
                        ensure_ascii=False,
                    ),
                )
                raise RuntimeError(
                    "approved action no longer matches current tool configuration"
                )

            event(
                "approval",
                "Approval Granted",
                "completed",
                json.dumps(
                    {
                        "approvalId": approval_id,
                        "tool": tool_name,
                        "riskLevel": continuation.risk_level,
                        "fingerprint": continuation.fingerprint,
                    },
                    ensure_ascii=False,
                ),
            )
            event(
                "tool",
                "Tool Started",
                "running",
                json.dumps(
                    {
                        "tool": tool_name,
                        "protocol": current_tool.protocol,
                        "approved": True,
                    },
                    ensure_ascii=False,
                ),
            )
            call_started = time.perf_counter()
            try:
                # Approved high-impact actions deliberately do not use the P4
                # automatic retry loop. Ambiguous network failures must fail
                # closed instead of risking a duplicate side effect.
                result = await registry.execute(
                    tool_name,
                    continuation.arguments,
                    approved_tools={tool_name},
                )
            except Exception as exc:
                event(
                    "tool",
                    "Tool Failed",
                    "error",
                    json.dumps(
                        {
                            "tool": tool_name,
                            "latencyMs": int((time.perf_counter() - call_started) * 1000),
                            "errorType": type(exc).__name__,
                        },
                        ensure_ascii=False,
                    ),
                )
                raise

            event(
                "tool",
                "Tool Completed",
                "completed",
                json.dumps(
                    {
                        "tool": tool_name,
                        "latencyMs": int((time.perf_counter() - call_started) * 1000),
                        "result": safe_tool_payload(result),
                    },
                    ensure_ascii=False,
                ),
            )
            return result

        if continuation.tool_protocol == "mcp":
            async with MCPManager(
                req.mcp_servers,
                approval_mcp_event,
                self.mcp_targets,
            ) as mcp_manager:
                for tool in await mcp_manager.discover_all():
                    registry.register(tool, adapter=MCPToolAdapter(mcp_manager))
                result = await execute_exact_action()
        else:
            result = await execute_exact_action()

        # Tool output is already the authoritative observation. We avoid a
        # second model decision that could mutate/reissue the action.
        rendered = json.dumps(
            safe_tool_payload(result),
            ensure_ascii=False,
            default=str,
        )
        answer = f"操作已执行完成。结果：{rendered}"

        if req.conversation_id is not None:
            try:
                await self.memory.append(
                    user_id=req.user_id,
                    conversation_id=req.conversation_id,
                    message=MemoryMessage(role="user", content="确认执行"),
                )
                await self.memory.append(
                    user_id=req.user_id,
                    conversation_id=req.conversation_id,
                    message=MemoryMessage(role="assistant", content=answer),
                )
            except Exception as exc:
                event("memory", "Memory Context Save Failed", "error", str(exc))

        event("task", "Task Completed", "completed")
        observability = build_observability_summary(
            trace=trace,
            feedback=feedback,
            dag=dag,
        )
        event(
            "observability",
            "Runtime Metrics Aggregated",
            "completed",
            json.dumps(observability.model_dump(by_alias=True), ensure_ascii=False),
        )
        scorecard = None
        if settings.eval_scorecard_enabled:
            try:
                scorecard = build_run_scorecard(
                    ScorecardInputs(
                        answer=answer,
                        trace=trace,
                        feedback=feedback,
                        citations=[],
                        constraints=req.constraints,
                        elapsed_ms=int((time.perf_counter() - started) * 1000),
                        estimated_cost=0.0,
                        observability=observability,
                    )
                )
                event(
                    "eval",
                    "Run Scorecard",
                    "completed",
                    json.dumps(scorecard.model_dump(by_alias=True), ensure_ascii=False),
                )
            except Exception as exc:
                event(
                    "eval",
                    "Run Scorecard",
                    "error",
                    json.dumps({"reason": "scorecard_unavailable", "errorType": type(exc).__name__}),
                )
        return RuntimeResponse(
            request_id=req.request_id,
            status="COMPLETED",
            answer=answer,
            continuation=None,
            scheduler=req.scheduler,
            task_profile=profile,
            selected_agents=selected_names,
            estimated_cost=0.0,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            trace=trace,
            dag=dag,
            agent_feedback=feedback,
            observability=observability,
            scorecard=scorecard,
        )

    # ========================================================
    # Resume Existing Runtime Task
    # ========================================================

    async def _resume_task(
        self,
        *,
        req: RuntimeRequest,
        trace: list[TraceEvent],
        feedback: list[AgentFeedback],
        selected_names: list[str],
        started: float,
        event,
        runtime_event,
    ) -> RuntimeResponse:

        continuation = (
            req.continuation
        )

        if continuation is None:

            raise RuntimeError(
                (
                    "resume requested "
                    "without continuation"
                )
            )

        if continuation.protocol.strip().lower() == "tool_approval":
            return await self._resume_tool_approval(
                req=req,
                trace=trace,
                feedback=feedback,
                selected_names=selected_names,
                started=started,
                event=event,
            )

        # ====================================================
        # 1. Continuation Protocol Validation
        # ====================================================

        if (
            continuation
            .protocol
            .strip()
            .lower()
            != "a2a"
        ):

            raise RuntimeError(
                (
                    "unsupported runtime "
                    "continuation protocol: "
                    f"{continuation.protocol}"
                )
            )

        # ====================================================
        # 2. Find Original Agent
        #
        # Resume 必须继续原 Agent。
        #
        # 不能：
        #
        # 用户补一个订单号
        #      ↓
        # Scheduler 重新选择 Agent
        #
        # 因为 remote task_id/context_id 属于原 Agent。
        # ====================================================

        agent = next(
            (
                item
                for item
                in req.agents
                if (
                    item.id
                    == continuation.agent_id
                )
            ),
            None,
        )

        if agent is None:

            raise RuntimeError(
                (
                    "continuation agent "
                    f"{continuation.agent_id} "
                    "not found in request"
                )
            )

        if (
            agent.protocol
            .strip()
            .lower()
            != "a2a"
        ):

            raise RuntimeError(
                (
                    "continuation agent "
                    "is not an A2A agent"
                )
            )

        selected_names.append(
            agent.name
        )

        # ====================================================
        # 3. Resume Task Profile
        #
        # profiler 可以继续分析用户新输入，
        # 但是 capability 必须保持原来的 capability。
        # ====================================================

        raw_profile = (
            profile_task(
                req.task
            )
        )

        profile = (
            raw_profile
            .model_copy(
                update={
                    "required_capabilities": [
                        continuation
                        .capability
                    ]
                }
            )
        )

        event(
            "task",
            "Task Resume Accepted",
            "completed",
            json.dumps(
                {
                    "agent":
                        agent.name,

                    "capability":
                        continuation
                        .capability,

                    "taskId":
                        continuation
                        .task_id,

                    "contextId":
                        continuation
                        .context_id,

                    "previousState":
                        continuation
                        .state,
                },
                ensure_ascii=False,
            ),
        )

        # ====================================================
        # 4. Resolve Same A2A Executor
        # ====================================================

        executor = (
            self
            .executor_resolver
            .resolve(
                agent.protocol
            )
        )

        resume_method = (
            getattr(
                executor,
                "resume",
                None,
            )
        )

        if resume_method is None:

            raise RuntimeError(
                (
                    "resolved executor "
                    "does not support resume"
                )
            )

        # ====================================================
        # 5. Minimal Resume DAG
        #
        # Resume ≠ New Collaboration Plan
        #
        # 所以这里只保留原来的一个 Agent 节点。
        # ====================================================

        assignment = (
            Assignment(
                capability=(
                    continuation
                    .capability
                ),
                agent_id=(
                    agent.id
                ),
                agent_name=(
                    agent.name
                ),
            )
        )

        dag = (
            build_dag(
                [
                    assignment
                ],
                execution_mode=(
                    "sequential"
                ),
            )
        )

        agent_node = next(
            (
                node
                for node
                in dag.nodes
                if (
                    node.id
                    == "agent-1"
                )
            ),
            None,
        )

        synthesis_node = next(
            (
                node
                for node
                in dag.nodes
                if (
                    node.id
                    == "synthesize"
                )
            ),
            None,
        )

        if agent_node is not None:

            agent_node.status = (
                "running"
            )

        event(
            "agent",
            (
                f"{agent.name} "
                "resume started"
            ),
            "running",
            continuation
            .capability,
        )

        # ====================================================
        # 6. Resume Request
        #
        # IMPORTANT:
        #
        # Resume 只发送用户“新补充的信息”。
        #
        # 不重新塞：
        #
        # RAG
        # Redis Conversation Memory
        # 原 Task Prompt
        #
        # 因为 Remote A2A Agent 已经有：
        #
        # task_id
        # context_id
        # ====================================================

        execution_request = (
            AgentExecutionRequest(
                agent=(
                    agent
                ),
                capability=(
                    continuation
                    .capability
                ),
                task=(
                    req.task
                ),
                on_runtime_event=(
                    runtime_event
                ),
            )
        )

        execution_started = (
            time.perf_counter()
        )

        # ====================================================
        # 7. Real Resume
        # ====================================================

        try:

            result = (
                await resume_method(
                    execution_request,
                    task_id=(
                        continuation
                        .task_id
                    ),
                    context_id=(
                        continuation
                        .context_id
                    ),
                )
            )

        # ====================================================
        # Resume 后仍然可能继续要求输入
        # ====================================================

        except (
            A2AAgentInterruptedError
        ) as exc:

            if (
                exc.task_state
                == (
                    "TASK_STATE_"
                    "AUTH_REQUIRED"
                )
            ):

                state = (
                    "AUTH_REQUIRED"
                )

            else:

                state = (
                    "INPUT_REQUIRED"
                )

            new_continuation = (
                RuntimeContinuation(
                    protocol="a2a",
                    agentId=(
                        agent.id
                    ),
                    capability=(
                        continuation
                        .capability
                    ),
                    taskId=(
                        exc.task_id
                    ),
                    contextId=(
                        exc.context_id
                    ),
                    state=(
                        state
                    ),
                )
            )

            if agent_node is not None:

                # 当前 DAGNode 还没有 suspended 状态。
                # 暂停表示“尚未完成”，因此重置为 pending，
                # 而不是 error。
                agent_node.status = (
                    "pending"
                )

            if synthesis_node is not None:

                synthesis_node.status = (
                    "pending"
                )

            event(
                "agent",
                (
                    f"{agent.name} "
                    "suspended"
                ),
                "completed",
                json.dumps(
                    {
                        "state":
                            state,

                        "taskId":
                            exc.task_id,

                        "contextId":
                            exc.context_id,

                        "message":
                            (
                                exc.status_message
                                or str(exc)
                            ),
                    },
                    ensure_ascii=False,
                ),
            )

            event(
                "task",
                "Task Suspended",
                "completed",
                json.dumps(
                    {
                        "status":
                            state,

                        "agent":
                            agent.name,

                        "capability":
                            continuation
                            .capability,

                        "taskId":
                            exc.task_id,

                        "contextId":
                            exc.context_id,
                    },
                    ensure_ascii=False,
                ),
            )

            observability = (
                build_observability_summary(
                    trace=(
                        trace
                    ),
                    feedback=(
                        feedback
                    ),
                    dag=(
                        dag
                    ),
                )
            )

            event(
                "observability",
                (
                    "Runtime Metrics "
                    "Aggregated"
                ),
                "completed",
                json.dumps(
                    observability
                    .model_dump(
                        by_alias=True
                    ),
                    ensure_ascii=False,
                ),
            )

            return RuntimeResponse(
                request_id=(
                    req.request_id
                ),
                status=(
                    state
                ),
                answer=(
                    exc.status_message
                    or str(exc)
                ),
                continuation=(
                    new_continuation
                ),
                scheduler=(
                    req.scheduler
                ),
                task_profile=(
                    profile
                ),
                selected_agents=(
                    selected_names
                ),
                estimated_cost=0.0,
                elapsed_ms=int(
                    (
                        time.perf_counter()
                        - started
                    )
                    * 1000
                ),
                trace=(
                    trace
                ),
                dag=(
                    dag
                ),
                agent_feedback=(
                    feedback
                ),
                observability=(
                    observability
                ),
            )

        # ====================================================
        # 8. Resume Completed
        # ====================================================

        latency_ms = int(
            (
                time.perf_counter()
                - execution_started
            )
            * 1000
        )

        if agent_node is not None:

            agent_node.status = (
                "completed"
            )

        if synthesis_node is not None:

            synthesis_node.status = (
                "skipped"
            )

        # ====================================================
        # 9. Evaluation
        # ====================================================

        evaluation = (
            await self
            .evaluator
            .evaluate(
                EvaluationRequest(
                    task=(
                        req.task
                    ),
                    capability=(
                        continuation
                        .capability
                    ),
                    result=(
                        result.content
                    ),
                    agent_name=(
                        agent.name
                    ),
                )
            )
        )

        event(
            "evaluation",
            (
                "Agent Result "
                "Evaluated"
            ),
            "completed",
            json.dumps(
                {
                    "agent":
                        agent.name,

                    "capability":
                        continuation
                        .capability,

                    "evaluator":
                        evaluation
                        .evaluator,

                    "quality_score":
                        evaluation
                        .quality_score,

                    "signals":
                        evaluation
                        .signals,
                },
                ensure_ascii=False,
            ),
        )

        # ====================================================
        # 10. Capability Feedback
        # ====================================================

        metrics = (
            effective_capability_profile(
                agent,
                continuation
                .capability,
            )
        )

        success_feedback = (
            AgentFeedback(
                agentId=(
                    agent.id
                ),
                capability=(
                    continuation
                    .capability
                ),
                success=True,
                latencyMs=(
                    latency_ms
                ),
                cost=(
                    metrics
                    .avg_cost
                ),
                qualityScore=(
                    evaluation
                    .quality_score
                ),
            )
        )

        feedback.append(
            success_feedback
        )

        updated = (
            apply_capability_feedback(
                agent,
                success_feedback,
            )
        )

        event(
            "profile_update",
            (
                "Capability Profile "
                "Updated"
            ),
            "completed",
            json.dumps(
                {
                    "agent":
                        agent.name,

                    "capability":
                        updated
                        .capability,

                    "success_rate":
                        updated
                        .success_rate,

                    "failure_rate":
                        updated
                        .failure_rate,

                    "avg_latency_ms":
                        updated
                        .avg_latency_ms,

                    "avg_cost":
                        updated
                        .avg_cost,

                    "quality_score":
                        updated
                        .quality_score,

                    "sample_count":
                        updated
                        .sample_count,
                },
                ensure_ascii=False,
            ),
        )

        event(
            "agent",
            (
                f"{agent.name} "
                "resume completed"
            ),
            "completed",
            (
                f"{latency_ms} ms"
            ),
        )

        # ====================================================
        # 11. Resume Conversation Memory Write-back
        # ====================================================

        if (
            req.conversation_id
            is not None
        ):

            try:

                await self.memory.append(
                    user_id=(
                        req.user_id
                    ),
                    conversation_id=(
                        req
                        .conversation_id
                    ),
                    message=(
                        MemoryMessage(
                            role="user",
                            content=(
                                req.task
                            ),
                        )
                    ),
                )

                await self.memory.append(
                    user_id=(
                        req.user_id
                    ),
                    conversation_id=(
                        req
                        .conversation_id
                    ),
                    message=(
                        MemoryMessage(
                            role="assistant",
                            content=(
                                result.content
                            ),
                        )
                    ),
                )

                event(
                    "memory",
                    (
                        "Memory Context "
                        "Saved"
                    ),
                    "completed",
                    json.dumps(
                        {
                            "conversation_id":
                                req
                                .conversation_id,

                            "messages_saved":
                                2,
                        },
                        ensure_ascii=False,
                    ),
                )

            except Exception as exc:

                event(
                    "memory",
                    (
                        "Memory Context "
                        "Save Failed"
                    ),
                    "error",
                    str(exc),
                )

        # ====================================================
        # 12. Completed
        # ====================================================

        event(
            "task",
            "Task Completed",
            "completed",
        )

        observability = (
            build_observability_summary(
                trace=(
                    trace
                ),
                feedback=(
                    feedback
                ),
                dag=(
                    dag
                ),
            )
        )

        event(
            "observability",
            (
                "Runtime Metrics "
                "Aggregated"
            ),
            "completed",
            json.dumps(
                observability
                .model_dump(
                    by_alias=True
                ),
                ensure_ascii=False,
            ),
        )

        scorecard = None
        if settings.eval_scorecard_enabled:
            try:
                resume_cost = round(metrics.avg_cost, 6)
                scorecard = build_run_scorecard(
                    ScorecardInputs(
                        answer=result.content,
                        trace=trace,
                        feedback=feedback,
                        citations=[],
                        constraints=req.constraints,
                        elapsed_ms=int((time.perf_counter() - started) * 1000),
                        estimated_cost=resume_cost,
                        observability=observability,
                    )
                )
                event(
                    "eval",
                    "Run Scorecard",
                    "completed",
                    json.dumps(scorecard.model_dump(by_alias=True), ensure_ascii=False),
                )
            except Exception as exc:
                event(
                    "eval",
                    "Run Scorecard",
                    "error",
                    json.dumps({"reason": "scorecard_unavailable", "errorType": type(exc).__name__}),
                )

        return RuntimeResponse(
            request_id=(
                req.request_id
            ),
            status=(
                "COMPLETED"
            ),
            answer=(
                result.content
            ),
            continuation=None,
            scheduler=(
                req.scheduler
            ),
            task_profile=(
                profile
            ),
            selected_agents=(
                selected_names
            ),
            estimated_cost=round(
                metrics.avg_cost,
                6,
            ),
            elapsed_ms=int(
                (
                    time.perf_counter()
                    - started
                )
                * 1000
            ),
            trace=(
                trace
            ),
            dag=(
                dag
            ),
            agent_feedback=(
                feedback
            ),
            observability=(
                observability
            ),
            scorecard=scorecard,
        )

    # ========================================================
    # New Runtime Execution
    # ========================================================

    async def run(
        self,
        req: RuntimeRequest,
        event_sink: Callable[[TraceEvent], None] | None = None,
        delta_sink: Callable[[str], None] | None = None,
    ) -> RuntimeResponse:

        started = (
            time.perf_counter()
        )

        trace: list[
            TraceEvent
        ] = []

        feedback: list[
            AgentFeedback
        ] = []

        selected_names: list[
            str
        ] = []

        # ====================================================
        # Trace Helpers
        # ====================================================

        def elapsed() -> int:

            return int(
                (
                    time.perf_counter()
                    - started
                )
                * 1000
            )

        def event(
            kind: str,
            title: str,
            status: str,
            detail: str = "",
        ) -> None:

            trace_event = TraceEvent(
                kind=(
                    kind
                ),
                title=(
                    title
                ),
                status=(
                    status
                ),
                detail=(
                    detail
                ),
                elapsedMs=(
                    elapsed()
                ),
            )
            trace.append(trace_event)
            if event_sink is not None:
                try:
                    event_sink(trace_event)
                except Exception:
                    # Streaming observability is fail-open: a disconnected UI
                    # must never change the authoritative task execution.
                    pass

        # ====================================================
        # Model Event Adapter
        # ====================================================

        def model_event(
            payload: dict[
                str,
                Any,
            ],
        ) -> None:

            kind = str(
                payload.get(
                    "kind",
                    "model_event",
                )
            )

            titles = {
                "model_call_started":
                    "Model Call Started",

                "model_call_completed":
                    "Model Call Completed",

                "model_call_retry":
                    "Model Call Retry",

                "model_call_failed":
                    "Model Call Failed",
            }

            if (
                kind
                == "model_call_failed"
            ):

                status = (
                    "error"
                )

            elif (
                kind
                == "model_call_completed"
            ):

                status = (
                    "completed"
                )

            else:

                status = (
                    "running"
                )

            detail = {
                key:
                    value

                for key, value
                in payload.items()

                if (
                    key
                    != "kind"
                )
            }

            event(
                "model",
                titles.get(
                    kind,
                    kind,
                ),
                status,
                json.dumps(
                    detail,
                    ensure_ascii=False,
                ),
            )

        # ====================================================
        # Tool Event Adapter
        # ====================================================

        def tool_event(
            payload: dict[
                str,
                Any,
            ],
        ) -> None:

            data = dict(
                payload
            )

            title = str(
                data.pop(
                    "title",
                    "Tool Event",
                )
            )

            status = str(
                data.pop(
                    "status",
                    "completed",
                )
            )

            event(
                "tool",
                title,
                status,
                json.dumps(
                    data,
                    ensure_ascii=False,
                ),
            )

        # ====================================================
        # Runtime Event Adapter
        # ====================================================

        def runtime_event(
            payload: dict[
                str,
                Any,
            ],
        ) -> None:

            detail = {
                key:
                    value

                for key, value
                in payload.items()

                if key not in {
                    "kind",
                    "title",
                    "status",
                }
            }

            event(
                str(
                    payload.get(
                        "kind",
                        "agent_runtime",
                    )
                ),
                str(
                    payload.get(
                        "title",
                        (
                            "Agent Runtime "
                            "Event"
                        ),
                    )
                ),
                str(
                    payload.get(
                        "status",
                        "completed",
                    )
                ),
                json.dumps(
                    detail,
                    ensure_ascii=False,
                ),
            )

        # ====================================================
        # MCP Event Adapter
        # ====================================================

        mcp_discovery_failures: dict[
            str,
            dict[str, Any],
        ] = {}

        def mcp_event(
            payload: dict[
                str,
                Any,
            ],
        ) -> None:

            data = dict(
                payload
            )

            title = str(
                data.pop(
                    "title",
                    "MCP Event",
                )
            )

            status = str(
                data.pop(
                    "status",
                    "completed",
                )
            )

            if (
                title
                == (
                    "MCP Discovery "
                    "Failed"
                )
            ):

                server_name = str(
                    data.get(
                        "server",
                        "",
                    )
                )

                if server_name:

                    mcp_discovery_failures[
                        server_name
                    ] = dict(
                        data
                    )

            event(
                "mcp",
                title,
                status,
                json.dumps(
                    data,
                    ensure_ascii=False,
                ),
            )

        # ====================================================
        # RESUME SHORT-CIRCUIT
        #
        # Resume 不再进入：
        #
        # Tool
        # MCP
        # RAG
        # Discovery
        # Scheduler
        # Planner
        #
        # 因为它是在继续已经存在的 Task。
        # ====================================================

        if (
            req.continuation
            is not None
        ):

            return (
                await self
                ._resume_task(
                    req=(
                        req
                    ),
                    trace=(
                        trace
                    ),
                    feedback=(
                        feedback
                    ),
                    selected_names=(
                        selected_names
                    ),
                    started=(
                        started
                    ),
                    event=(
                        event
                    ),
                    runtime_event=(
                        runtime_event
                    ),
                )
            )

                # ====================================================
                # Request pre-profile
                #
                # This lightweight local classification is intentionally performed
                # before MCP / Memory / RAG work so ordinary chat turns can avoid
                # expensive subsystems they do not need.  The same profile is reused
                # later for Scheduler / Planner observability.
                # ====================================================

        # ====================================================
        # 1. Task Accepted
        #
        # The task event is the stable trace boundary for every new runtime
        # execution. Capability discovery is work performed *after* the task
        # has been accepted, so keep this event first for P3.x trace contracts
        # and downstream consumers that rely on trace[0] being the task.
        # Resume requests short-circuit above and preserve their own lifecycle.
        # ====================================================

        event(
            "task",
            "Task Accepted",
            "completed",
            req.request_id,
        )

        pre_profile = profile_task(req.task)

        # ====================================================
        # RAG V1.1 Shared Semantic Intent
        #
        # One request may require multiple capability families at the same
        # time (for example Tool + Knowledge). This contract is descriptive
        # only; it cannot grant access to any resource.
        # ====================================================
        semantic_intent = analyze_task_semantics(
            req.task,
            has_attachments=bool(req.attachments),
            profiler_capabilities=pre_profile.required_capabilities,
        )
        merged_capabilities = list(
            dict.fromkeys(
                [*pre_profile.required_capabilities, *semantic_intent.required_capabilities]
            )
        )
        if merged_capabilities != list(pre_profile.required_capabilities):
            pre_profile = pre_profile.model_copy(
                update={"required_capabilities": merged_capabilities}
            )

        event(
            "semantic",
            "Shared Task Semantics",
            "completed",
            semantic_intent.model_dump_json(by_alias=True),
        )

        # ====================================================
        # V4.1 Autonomous Capability Discovery
        #
        # Users express goals; Runtime discovers request-relevant Tool / MCP /
        # Skill / Knowledge capabilities before expensive execution work.
        # ====================================================

        capability_query, capability_used_history, capability_history_turns = (
            contextualize_discovery_task(
                req.task,
                req.history,
            )
        )

        capability_plan = discover_capabilities(
            capability_query,
            tools=req.tools,
            mcp_servers=req.mcp_servers,
            agents=req.agents,
            has_attachments=bool(req.attachments),
            semantic_intent=semantic_intent,
        )

        knowledge_query = continuation_subject_task(
            req.task,
            req.history,
        )

        effective_rag_policy = req.effective_rag_policy
        allowed_knowledge_ids = (
            list(effective_rag_policy.allowed_knowledge_base_ids)
            if effective_rag_policy is not None
            else [item.knowledge_base_id for item in req.knowledge_catalog if item.accessible]
        )
        allowed_knowledge_set = {int(value) for value in allowed_knowledge_ids if int(value) > 0}
        authorized_catalog = [
            item
            for item in req.knowledge_catalog
            if item.accessible and item.knowledge_base_id in allowed_knowledge_set
        ]
        explicit_knowledge_ids = (
            list(effective_rag_policy.explicitly_selected_ids)
            if effective_rag_policy is not None
            else list(req.rag_policy.selected_knowledge_base_ids)
        )
        knowledge_policy_mode = (
            effective_rag_policy.mode
            if effective_rag_policy is not None
            else req.rag_policy.mode
        )
        if (
            knowledge_policy_mode == "OFF"
            or semantic_intent.rag_preference == RagPreference.DISABLE
        ):
            # OFF must skip discovery itself, not merely suppress its retrieval
            # result later. A user prohibition also wins over AUTO/ON.
            knowledge_discovery = KnowledgeDiscoveryResult(
                needed=False, reason_code="DISABLED",
            )
        else:
            knowledge_discovery = discover_knowledge_bases(
                knowledge_query,
                semantic=semantic_intent,
                catalog=authorized_catalog,
                explicitly_selected_ids=explicit_knowledge_ids,
                force_needed=knowledge_policy_mode == "ON",
            )
        set_candidate_knowledge_ids(knowledge_discovery.selected_knowledge_base_ids)

        event(
            "knowledge_discovery",
            "Knowledge Discovery",
            "skipped" if knowledge_discovery.reason_code == "DISABLED" else "completed",
            json.dumps(
                {
                    **knowledge_discovery.trace_dict(),
                    "policyMode": (
                        effective_rag_policy.mode
                        if effective_rag_policy is not None
                        else req.rag_policy.mode
                    ),
                    "allowedScopes": (
                        list(effective_rag_policy.allowed_scopes)
                        if effective_rag_policy is not None
                        else list(req.rag_policy.scopes)
                    ),
                    "allowedKnowledgeBaseIds": sorted(allowed_knowledge_set),
                    "knowledgeDependency": semantic_intent.knowledge_dependency.value,
                    "ragPreference": semantic_intent.rag_preference.value,
                },
                ensure_ascii=False,
            ),
        )

        capability_trace = capability_plan.trace_detail()
        capability_trace.update(
            {
                "contextualized": capability_used_history,
                "historyTurns": capability_history_turns,
            }
        )
        event(
            "capability_discovery",
            "Autonomous Capability Discovery",
            "completed",
            json.dumps(
                capability_trace,
                ensure_ascii=False,
            ),
        )

        selected_tool_names = {
            name.casefold()
            for name in capability_plan.selected_tool_names
        }
        selected_mcp_server_ids = set(
            capability_plan.selected_mcp_server_ids
        )

        tool_execution_enabled = bool(
            selected_tool_names
            or selected_mcp_server_ids
        )

        # ====================================================
        # Request-local attachment preprocessing
        #
        # Documents become bounded execution-only context. Images remain binary
        # multimodal inputs and are never persisted into Memory or Knowledge.
        # ====================================================

        attachment_text_parts: list[str] = []
        model_attachments: list[ModelInputAttachment] = []
        attachment_text_chars = 0
        attachment_text_limit = 60_000

        for attachment in req.attachments:
            try:
                raw = base64.b64decode(attachment.content_base64, validate=True)
            except Exception as exc:
                raise ValueError(f"invalid attachment encoding: {attachment.name}") from exc

            if len(raw) != attachment.size_bytes:
                raise ValueError(f"attachment size mismatch: {attachment.name}")

            if attachment.media_type.startswith("image/"):
                model_attachments.append(
                    ModelInputAttachment(
                        name=attachment.name,
                        media_type=attachment.media_type,
                        content_base64=attachment.content_base64,
                    )
                )
                continue

            text = parse_document_bytes(
                extension=attachment.extension,
                content=raw,
            )
            remaining = max(0, attachment_text_limit - attachment_text_chars)
            if remaining <= 0:
                break
            bounded = text[:remaining]
            attachment_text_chars += len(bounded)
            attachment_text_parts.append(
                f"[Attached document: {attachment.name}]\n{bounded}"
            )

        attachment_text_context = "\n\n".join(attachment_text_parts)
        if req.attachments:
            event(
                "attachment",
                "Request Attachments Prepared",
                "completed",
                json.dumps(
                    {
                        "count": len(req.attachments),
                        "images": len(model_attachments),
                        "documents": len(attachment_text_parts),
                        "names": [item.name for item in req.attachments],
                        "documentContextChars": attachment_text_chars,
                    },
                    ensure_ascii=False,
                ),
            )

        # ====================================================
        # Task-scoped Tool Registry
        # ====================================================

        tool_registry = (
            ToolRegistry(
                timeout=(
                    settings
                    .tool_timeout_seconds
                )
            )
        )

        # ====================================================
        # Demo Internal Tools
        # ====================================================

        demo_registry = (
            ToolRegistry(
                timeout=(
                    settings
                    .tool_timeout_seconds
                )
            )
        )

        register_builtin_tools(
            demo_registry
        )

        register_demo_tools(
            demo_registry
        )

        register_desktop_tools(
            demo_registry
        )

        demo_handlers = {
            tool.name:
                demo_registry
                ._adapters[
                    tool.name
                ]
                .handler

            for tool
            in demo_registry.list()
        }

        for tool in req.tools:

            if tool.name.casefold() not in selected_tool_names:
                continue

            if (
                tool.protocol
                == "internal"
                and
                tool.name
                in demo_handlers
            ):

                tool_registry.register(
                    tool,
                    demo_handlers[
                        tool.name
                    ],
                )

            elif (
                tool.protocol
                == "http"
            ):

                tool_registry.register(
                    tool
                )

        # ====================================================
        # MCP Failure Backoff
        # ====================================================

        eligible_mcp_servers = []

        if req.mcp_servers and not selected_mcp_server_ids:
            event(
                "mcp",
                "MCP Discovery Skipped",
                "completed",
                json.dumps(
                    {
                        "reason": "capability discovery found no relevant MCP connector",
                        "configuredServers": len(req.mcp_servers),
                    },
                    ensure_ascii=False,
                ),
            )

        for server in (
            server
            for server in req.mcp_servers
            if server.id in selected_mcp_server_ids
        ):

            decision = (
                self
                .mcp_failure_backoff
                .decision(
                    server
                )
            )

            if decision.blocked:

                event(
                    "mcp",
                    (
                        "MCP Discovery "
                        "Backoff"
                    ),
                    "skipped",
                    json.dumps(
                        {
                            "server":
                                server.name,

                            "transport":
                                server.transport,

                            "remaining_ms":
                                decision
                                .remaining_ms,

                            "consecutive_failures":
                                decision
                                .consecutive_failures,

                            "last_error_type":
                                decision
                                .error_type,

                            "last_error":
                                decision
                                .message,
                        },
                        ensure_ascii=False,
                    ),
                )

                continue

            eligible_mcp_servers.append(
                server
            )

        # ====================================================
        # MCP Lifecycle
        # ====================================================

        async with MCPManager(
            eligible_mcp_servers,
            mcp_event,
            self.mcp_targets,
        ) as mcp_manager:

            discovered_tools = (
                await mcp_manager
                .discover_all()
            )

            discovered_server_ids = {
                tool.mcp_server_id

                for tool
                in discovered_tools
            }

            # =================================================
            # MCP Backoff Feedback
            # =================================================

            for server in (
                eligible_mcp_servers
            ):

                failure = (
                    mcp_discovery_failures
                    .get(
                        server.name
                    )
                )

                if failure is not None:

                    error_payload = (
                        failure.get(
                            "error"
                        )
                        or {}
                    )

                    if not isinstance(
                        error_payload,
                        dict,
                    ):

                        error_payload = {
                            "message":
                                str(
                                    error_payload
                                )
                        }

                    self.mcp_failure_backoff.record_failure(
                        server,
                        error_type=str(
                            error_payload.get(
                                "type",
                                "",
                            )
                        ),
                        message=str(
                            error_payload.get(
                                "message",
                                "",
                            )
                        ),
                    )

                    continue

                if (
                    server.id
                    in discovered_server_ids
                ):

                    self.mcp_failure_backoff.record_success(
                        server
                    )

            # =================================================
            # V4.1 MCP Tool-level Discovery
            # =================================================

            mcp_tool_plan = discover_mcp_tools(
                capability_query,
                discovered_tools,
                semantic_intent=semantic_intent,
            )
            capability_plan.selected_mcp_tool_names = list(
                mcp_tool_plan.selected_mcp_tool_names
            )
            capability_plan.candidates.extend(
                mcp_tool_plan.candidates
            )
            capability_plan.confidence = max(
                capability_plan.confidence,
                mcp_tool_plan.confidence,
            )

            if discovered_tools:
                event(
                    "capability_discovery",
                    "MCP Capability Discovery",
                    "completed",
                    json.dumps(
                        mcp_tool_plan.trace_detail(),
                        ensure_ascii=False,
                    ),
                )

            selected_mcp_tool_names = {
                name.casefold()
                for name in mcp_tool_plan.selected_mcp_tool_names
            }

            for tool in discovered_tools:
                if tool.name.casefold() not in selected_mcp_tool_names:
                    continue

                tool_registry.register(
                    tool,
                    adapter=(
                        MCPToolAdapter(
                            mcp_manager
                        )
                    ),
                )

            tool_execution_enabled = bool(
                tool_registry.list()
            )

            # =================================================
            # 1.1 User memory control + retrieval
            #
            # A user can manage remembered information directly in chat.
            # Explicit forget commands are handled before normal retrieval so
            # a memory being deleted cannot also be injected into the same
            # request.  Non-forget requests continue through P3.3 retrieval.
            # =================================================

            long_term_memories: list[
                RetrievedLongTermMemory
            ] = []
            memory_retrieval_reason = ""
            memory_overview_query = is_memory_overview_query(req.task)
            memory_forget_outcome = None
            memory_forget_requested = False

            try:
                memory_forget_outcome = (
                    await self.long_term_memory_forgetter.process(
                        user_id=req.user_id,
                        text=req.task,
                    )
                )
                memory_forget_requested = memory_forget_outcome.requested

                if memory_forget_requested:
                    memory_retrieval_reason = "forget_request"
                    event(
                        "memory_forget",
                        "Memory Forget",
                        memory_forget_outcome.status,
                        json.dumps(
                            memory_forget_outcome.trace_detail(),
                            ensure_ascii=False,
                        ),
                    )
            except Exception as exc:
                memory_forget_requested = False
                event(
                    "memory_forget",
                    "Memory Forget",
                    "error",
                    json.dumps(
                        {
                            "reason": "unexpected_memory_forget_error",
                            "errorType": type(exc).__name__,
                        },
                        ensure_ascii=False,
                    ),
                )

            memory_retrieval_enabled_for_request = bool(
                semantic_intent.requires_memory
                or should_retrieve_long_term_memory(
                    req.task,
                    memory_overview_query=memory_overview_query,
                )
            )

            if not memory_forget_requested and memory_retrieval_enabled_for_request:
                try:
                    memory_retrieval_outcome = (
                        await self
                        .long_term_memory_retriever
                        .retrieve(
                            user_id=req.user_id,
                            query=req.task,
                        )
                    )
                    long_term_memories = list(
                        memory_retrieval_outcome.memories
                    )
                    memory_retrieval_reason = memory_retrieval_outcome.reason

                    if not (
                        memory_retrieval_outcome.status == "skipped"
                        and memory_retrieval_outcome.reason == "disabled"
                    ):
                        event(
                            "memory_retrieval",
                            "Memory Retrieval",
                            memory_retrieval_outcome.status,
                            json.dumps(
                                memory_retrieval_outcome.trace_detail(),
                                ensure_ascii=False,
                            ),
                        )
                except Exception as exc:
                    long_term_memories = []
                    memory_retrieval_reason = "unexpected_memory_retrieval_error"
                    event(
                        "memory_retrieval",
                        "Memory Retrieval",
                        "error",
                        json.dumps(
                            {
                                "reason": "unexpected_memory_retrieval_error",
                                "errorType": type(exc).__name__,
                            },
                            ensure_ascii=False,
                        ),
                    )

            if (
                not memory_forget_requested
                and not memory_retrieval_enabled_for_request
            ):
                memory_retrieval_reason = "not_relevant_to_request"
                event(
                    "memory_retrieval",
                    "Memory Retrieval",
                    "skipped",
                    json.dumps(
                        {
                            "reason": memory_retrieval_reason,
                            "selectedCount": 0,
                        },
                        ensure_ascii=False,
                    ),
                )

            # =================================================
            # 1.2 User-global Long-term Memory Auto Write
            #
            # IMPORTANT:
            # - direct user text only
            # - no RAG / tool / MCP / citation / assistant data
            # - continuation/resume is excluded because it can
            #   carry OTP/auth/ephemeral task input
            # - write failure never fails the main task
            # =================================================

            memory_write_outcome = None

            try:
                if not memory_forget_requested:
                    memory_write_outcome = (
                        await self
                        .long_term_memory_writer
                        .process(
                            user_id=req.user_id,
                            text=req.task,
                        )
                    )

                    event(
                        "memory_write",
                        "Memory Write",
                        memory_write_outcome.status,
                        json.dumps(
                            memory_write_outcome
                            .trace_detail(),
                            ensure_ascii=False,
                        ),
                    )

            except Exception as exc:
                # Defensive fail-open for the task itself.
                # Memory persistence is auxiliary and must not
                # take down Agent execution.
                event(
                    "memory_write",
                    "Long-term Memory Write",
                    "error",
                    json.dumps(
                        {
                            "reason": (
                                "unexpected_memory_write_error"
                            ),
                            "errorType": (
                                type(exc).__name__
                            ),
                        },
                        ensure_ascii=False,
                    ),
                )

            # =================================================
            # 2. Task Profiler
            # =================================================

            event(
                "profile",
                "Task Profiler",
                "running",
            )

            profile = pre_profile

            event(
                "profile",
                "Task Profiler",
                "completed",
                ", ".join(
                    profile
                    .required_capabilities
                ),
            )

            # =================================================
            # 2.1 Conversation Memory
            # =================================================

            memory_messages: list[
                MemoryMessage
            ] = []

            if (
                req.conversation_id
                is not None
            ):

                try:
                    history_source = "runtime_memory"

                    # Go/MySQL is the authoritative conversation log and spans
                    # both execution paths.  Prefer request history when present
                    # so a turn that moves from InteractiveFastPath -> full Agent
                    # Runtime still sees the immediately preceding discussion.
                    if req.history:
                        memory_messages = [
                            MemoryMessage(
                                role=item.role,
                                content=item.content,
                            )
                            for item in req.history
                            if item.content.strip()
                        ]
                        history_source = "control_plane_history"
                    else:
                        memory_messages = (
                            await self.memory
                            .recent(
                                user_id=(
                                    req.user_id
                                ),
                                conversation_id=(
                                    req
                                    .conversation_id
                                ),
                                limit=8,
                            )
                        )

                    event(
                        "memory",
                        (
                            "Memory Context "
                            "Loaded"
                        ),
                        "completed",
                        json.dumps(
                            {
                                "conversation_id":
                                    req
                                    .conversation_id,

                                "messages":
                                    len(
                                        memory_messages
                                    ),

                                "source":
                                    history_source,
                            },
                            ensure_ascii=False,
                        ),
                    )

                except Exception as exc:

                    memory_messages = []

                    event(
                        "memory",
                        (
                            "Memory Context "
                            "Load Failed"
                        ),
                        "error",
                        str(exc),
                    )

            else:

                event(
                    "memory",
                    (
                        "Memory Context "
                        "Loaded"
                    ),
                    "completed",
                    json.dumps(
                        {
                            "enabled":
                                False,

                            "messages":
                                0,
                        },
                        ensure_ascii=False,
                    ),
                )

            # =================================================
            # 2.1.1 Selective Older Conversation Recall
            # =================================================

            conversation_memories: list[RetrievedConversationMemory] = []
            if req.conversation_id is not None:
                try:
                    conversation_memories = await self.conversation_memory_retriever.retrieve(
                        user_id=req.user_id,
                        conversation_id=req.conversation_id,
                        query=req.task,
                    )
                    event(
                        "memory_retrieval",
                        "Conversation Memory Recall",
                        "completed",
                        json.dumps(
                            {
                                "selectedCount": len(conversation_memories),
                                "capsuleIds": [
                                    item.capsule.id for item in conversation_memories
                                ],
                                "scores": [
                                    round(item.score, 6) for item in conversation_memories
                                ],
                                "paidModelCall": False,
                            },
                            ensure_ascii=False,
                        ),
                    )
                except Exception as exc:
                    conversation_memories = []
                    event(
                        "memory_retrieval",
                        "Conversation Memory Recall",
                        "error",
                        json.dumps(
                            {
                                "reason": "conversation_memory_unavailable",
                                "errorType": type(exc).__name__,
                            },
                            ensure_ascii=False,
                        ),
                    )

            # =================================================
            # 2.2 Adaptive RAG Routing + Retrieval
            #
            # v2.0.1
            #
            # Task Profile
            #      ↓
            # Query Intelligence
            #      ↓
            # Adaptive RAG Router
            #
            # NO_RAG
            # FAST_RAG
            # AGENTIC_RAG
            #
            # IMPORTANT:
            #
            # AGENTIC_RAG 在 v2.0.1 只负责生成执行计划，
            # 当前 Retrieval 仍然复用现有 Hybrid Retriever。
            #
            # 真正的：
            #
            # rewrite
            # multi-query
            # decomposition
            # evidence grade
            # retry
            #
            # 会在 v2.0.2 实现。
            # =================================================

            retrieval_hits: list[
                RetrievalHit
            ] = []

            rag_context_hits: list[
                RetrievalHit
            ] = []

            rag_grounding_sufficient: (
                bool
                | None
            ) = None

            rag_grounding_reason = ""

            rag_grounding_stopped_reason = ""

            rag_grounding_policy = ""

            runtime_citations: list[
                RuntimeCitation
            ] = []

            # -------------------------------------------------
            # 2.2.1 RAG Route Decision
            #
            # Task Profiler 已经先执行，因此这里可以同时使用：
            #
            # raw query
            # +
            # profile.required_capabilities
            #
            # 例如：
            #
            # order query + business
            #     ↓
            # NO_RAG
            #
            # document query + document
            #     ↓
            # AGENTIC_RAG
            # -------------------------------------------------

            rag_decision = (
                self.rag_router.route(
                    req.task,
                    capabilities=(
                        profile
                        .required_capabilities
                    ),
                )
            )

            retrieval_mode_decision = classify_retrieval_mode(req.task, rag_decision.analysis)
            retrieval_mode = retrieval_mode_decision.mode

            policy_mode = (
                effective_rag_policy.mode
                if effective_rag_policy is not None
                else req.rag_policy.mode
            )
            explicit_rag_off = semantic_intent.rag_preference == RagPreference.DISABLE
            has_available_source = bool(knowledge_discovery.selected_knowledge_base_ids)
            needs_knowledge = knowledge_discovery.needed

            # RAG V1.1 has one authoritative gate. Policy controls whether
            # retrieval is allowed; semantic/planner signals describe need;
            # Knowledge Discovery only chooses authorized sources. No downstream
            # component may silently widen scope or turn OFF back into ON.
            if policy_mode == "OFF" or explicit_rag_off:
                rag_decision = replace(
                    rag_decision,
                    mode=RAGMode.NO_RAG,
                    reason=(
                        "RAG disabled by effective policy"
                        if policy_mode == "OFF"
                        else "RAG disabled by explicit user instruction"
                    ),
                    confidence=1.0,
                    retrieve=False,
                    inject_context=False,
                    top_k=0,
                    max_retrieval_rounds=0,
                    enable_query_rewrite=False,
                    enable_multi_query=False,
                    enable_decomposition=False,
                    enable_reranker=False,
                )
            elif not has_available_source:
                rag_decision = replace(
                    rag_decision,
                    mode=RAGMode.NO_RAG,
                    reason="no authorized knowledge source available",
                    confidence=max(rag_decision.confidence, 0.98),
                    retrieve=False,
                    inject_context=False,
                    top_k=0,
                    max_retrieval_rounds=0,
                    enable_query_rewrite=False,
                    enable_multi_query=False,
                    enable_decomposition=False,
                    enable_reranker=False,
                )
            elif policy_mode == "ON":
                if not rag_decision.retrieve:
                    rag_decision = replace(
                        rag_decision,
                        mode=RAGMode.FAST_RAG,
                        reason="RAG policy ON: attempt retrieval from authorized sources",
                        confidence=max(rag_decision.confidence, 0.96),
                        retrieve=True,
                        inject_context=True,
                        top_k=max(settings.rag_top_k, 5),
                        max_retrieval_rounds=1,
                        enable_query_rewrite=False,
                        enable_multi_query=False,
                        enable_decomposition=False,
                        enable_reranker=True,
                    )
            elif policy_mode == "AUTO" and not needs_knowledge:
                rag_decision = replace(
                    rag_decision,
                    mode=RAGMode.NO_RAG,
                    reason="AUTO policy: shared semantics determined knowledge is not needed",
                    confidence=max(rag_decision.confidence, 0.96),
                    retrieve=False,
                    inject_context=False,
                    top_k=0,
                    max_retrieval_rounds=0,
                    enable_query_rewrite=False,
                    enable_multi_query=False,
                    enable_decomposition=False,
                    enable_reranker=False,
                )
            elif policy_mode == "AUTO" and needs_knowledge and not rag_decision.retrieve:
                rag_decision = replace(
                    rag_decision,
                    mode=RAGMode.FAST_RAG,
                    reason="AUTO policy: task requires governed knowledge",
                    confidence=max(rag_decision.confidence, 0.92),
                    retrieve=True,
                    inject_context=True,
                    top_k=max(settings.rag_top_k, 5),
                    max_retrieval_rounds=1,
                    enable_query_rewrite=False,
                    enable_multi_query=False,
                    enable_decomposition=False,
                    enable_reranker=True,
                )

            event(
                "rag",
                "RAG Route",
                "completed",
                json.dumps(
                    {
                        "mode":
                            rag_decision
                            .mode
                            .value,

                        "retrievalMode":
                            retrieval_mode.value,

                        "retrievalModeReason":
                            retrieval_mode_decision.reason,

                        "intent":
                            rag_decision
                            .analysis
                            .intent
                            .value,

                        "complexity":
                            rag_decision
                            .analysis
                            .complexity
                            .value,

                        "confidence":
                            rag_decision
                            .confidence,

                        "reason":
                            rag_decision
                            .reason,

                        "retrieve":
                            rag_decision
                            .retrieve,

                        "injectContext":
                            rag_decision
                            .inject_context,

                        "topK":
                            rag_decision
                            .top_k,

                        "maxRetrievalRounds":
                            rag_decision
                            .max_retrieval_rounds,

                        "queryRewrite":
                            rag_decision
                            .enable_query_rewrite,

                        "multiQuery":
                            rag_decision
                            .enable_multi_query,

                        "decomposition":
                            rag_decision
                            .enable_decomposition,

                        "reranker":
                            rag_decision
                            .enable_reranker,

                        "backend":
                            settings
                            .rag_backend,
                    },
                    ensure_ascii=False,
                ),
            )

            # -------------------------------------------------
            # 2.2.3 NO-RAG
            #
            # 最关键的 Context Gating。
            #
            # 这里不是：
            #
            # retrieve → 丢弃结果
            #
            # 而是：
            #
            # Retriever 根本不调用。
            #
            # 因此：
            #
            # Embedding = 0
            # Milvus = 0
            # BM25 = 0
            # RRF = 0
            # Reranker = 0
            # -------------------------------------------------

            if not (
                rag_decision
                .retrieve
            ):

                event(
                    "rag",
                    (
                        "RAG Retrieval "
                        "Skipped"
                    ),
                    "completed",
                    json.dumps(
                        {
                            "mode":
                                rag_decision
                                .mode
                                .value,

                            "retrievalMode":
                                retrieval_mode.value,

                            "reason":
                                rag_decision
                                .reason,

                            "query":
                                knowledge_query,

                            "retrieverCalled":
                                False,

                            "hits":
                                0,

                            "contextHits":
                                0,
                        },
                        ensure_ascii=False,
                    ),
                )

            # -------------------------------------------------
            # 2.2.4 FAST / AGENTIC Retrieval
            # -------------------------------------------------

            else:

                event(
                    "rag",
                    (
                        "RAG Retrieval "
                        "Started"
                    ),
                    "running",
                    json.dumps(
                        {
                            "query":
                                knowledge_query,

                            "mode":
                                rag_decision
                                .mode
                                .value,

                            "retrievalMode":
                                retrieval_mode.value,

                            "top_k":
                                rag_decision
                                .top_k,

                            "backend":
                                settings
                                .rag_backend,
                        },
                        ensure_ascii=False,
                    ),
                )

                try:

                    # =========================================
                    # Adaptive Retrieval Execution
                    # =========================================

                    if (
                        rag_decision
                        .mode
                        .value
                        == "agentic_rag"
                    ):

                        # =====================================
                        # Request-scoped Agentic Intelligence
                        #
                        # 为什么 request-scoped？
                        #
                        # on_model_event / on_rag_event
                        # 都属于当前 Task Trace。
                        #
                        # 不能把某个请求的 callback
                        # 长期保存在 RuntimeEngine singleton 中。
                        # =====================================

                        agentic_executor = (
                            self.agentic_retrieval
                        )

                        if (
                            self
                            .rag_intelligence_model
                            is not None
                        ):

                            def rag_intelligence_event(
                                payload: dict[
                                    str,
                                    Any,
                                ],
                            ) -> None:

                                data = dict(
                                    payload
                                )

                                title = str(
                                    data.pop(
                                        "title",
                                        (
                                            "RAG "
                                            "Intelligence"
                                        ),
                                    )
                                )

                                status = str(
                                    data.pop(
                                        "status",
                                        "completed",
                                    )
                                )

                                event(
                                    "rag",
                                    title,
                                    status,
                                    json.dumps(
                                        data,
                                        ensure_ascii=False,
                                    ),
                                )

                            transformer = (
                                ModelBackedQueryTransformer(
                                    model=(
                                        self
                                        .rag_intelligence_model
                                    ),
                                    on_model_event=(
                                        model_event
                                    ),
                                    on_rag_event=(
                                        rag_intelligence_event
                                    ),
                                )
                            )

                            grader = (
                                ModelBackedEvidenceGrader(
                                    model=(
                                        self
                                        .rag_intelligence_model
                                    ),
                                    on_model_event=(
                                        model_event
                                    ),
                                    on_rag_event=(
                                        rag_intelligence_event
                                    ),
                                )
                            )

                            agentic_executor = (
                                AgenticRetrievalExecutor(
                                    retriever=(
                                        self.retriever
                                    ),
                                    transformer=(
                                        transformer
                                    ),
                                    grader=(
                                        grader
                                    ),
                                )
                            )

                        agentic_result = (
                            await agentic_executor
                            .retrieve(
                                knowledge_query,

                                user_id=(
                                    req.user_id
                                ),

                                top_k=(
                                    max(
                                        rag_decision.top_k,
                                        rag_decision.top_k * 3,
                                    )
                                ),

                                max_rounds=(
                                    rag_decision
                                    .max_retrieval_rounds
                                ),

                                enable_query_rewrite=(
                                    rag_decision
                                    .enable_query_rewrite
                                ),

                                enable_multi_query=(
                                    rag_decision
                                    .enable_multi_query
                                ),

                                enable_decomposition=(
                                    rag_decision
                                    .enable_decomposition
                                ),
                            )
                        )


                        retrieval_hits = list(
                            agentic_result
                            .hits
                        )

                        rag_grounding_sufficient = (
                            agentic_result
                            .sufficient
                        )

                        rag_grounding_reason = (
                            agentic_result
                            .final_grade
                            .reason
                        )

                        rag_grounding_stopped_reason = (
                            agentic_result
                            .stopped_reason
                        )
                        event(
                            "rag",
                            (
                                "Agentic RAG "
                                "Completed"
                            ),
                            "completed",
                            json.dumps(
                                {
                                    "rounds":
                                        len(
                                            agentic_result
                                            .rounds
                                        ),

                                    "sufficient":
                                        agentic_result
                                        .sufficient,

                                    "stoppedReason":
                                        agentic_result
                                        .stopped_reason,

                                    "finalGrade": {
                                        "relevance":
                                            agentic_result
                                            .final_grade
                                            .relevance,

                                        "coverage":
                                            agentic_result
                                            .final_grade
                                            .coverage,

                                        "confidence":
                                            agentic_result
                                            .final_grade
                                            .confidence,

                                        "sufficient":
                                            agentic_result
                                            .final_grade
                                            .sufficient,

                                        "reason":
                                            agentic_result
                                            .final_grade
                                            .reason,
                                    },

                                    "roundDetails": [
                                        {
                                            "round":
                                                item
                                                .round_index
                                                + 1,

                                            "queries":
                                                list(
                                                    item
                                                    .queries
                                                ),

                                            "hitCount":
                                                item
                                                .hit_count,

                                            "grade": {
                                                "relevance":
                                                    item
                                                    .grade
                                                    .relevance,

                                                "coverage":
                                                    item
                                                    .grade
                                                    .coverage,

                                                "confidence":
                                                    item
                                                    .grade
                                                    .confidence,

                                                "sufficient":
                                                    item
                                                    .grade
                                                    .sufficient,
                                            },
                                        }

                                        for item
                                        in (
                                            agentic_result
                                            .rounds
                                        )
                                    ],
                                },
                                ensure_ascii=False,
                            ),
                        )

                    else:

                        retrieval_hits = (
                            await self
                            .retriever
                            .retrieve(
                                knowledge_query,
                                top_k=(
                                    max(
                                        rag_decision.top_k,
                                        rag_decision.top_k * 3,
                                    )
                                ),
                                filters={
                                    "userId":
                                        req.user_id
                                },
                            )
                        )

                    raw_retrieval_hits = list(retrieval_hits)
                    retrieval_hits = diversify_multimodal_hits(
                        filter_hits_for_mode(
                            raw_retrieval_hits,
                            retrieval_mode,
                        ),
                        top_k=rag_decision.top_k,
                    )

                    # One bounded expansion inside the SAME Go-authorized
                    # catalog when metadata selection yielded no evidence.
                    # Never add a new scope or knowledge base from the model.
                    if rag_decision.retrieve and not retrieval_hits:
                        already_selected = set(knowledge_discovery.selected_knowledge_base_ids)
                        remaining = [
                            item.knowledge_base_id
                            for item in authorized_catalog
                            if item.knowledge_base_id not in already_selected
                        ][:2]
                        if remaining:
                            expanded_ids = sorted(already_selected | set(remaining))
                            set_candidate_knowledge_ids(expanded_ids)
                            event(
                                "knowledge_discovery", "Bounded Knowledge Expansion", "running",
                                json.dumps({
                                    "initialCount": len(already_selected),
                                    "addedCount": len(remaining),
                                    "maxAdditionalRounds": 1,
                                }, ensure_ascii=False),
                            )
                            additional_hits = await self.retriever.retrieve(
                                knowledge_query,
                                top_k=max(rag_decision.top_k, rag_decision.top_k * 3),
                                filters={"userId": req.user_id},
                            )
                            raw_retrieval_hits = list(additional_hits)
                            retrieval_hits = diversify_multimodal_hits(
                                filter_hits_for_mode(raw_retrieval_hits, retrieval_mode),
                                top_k=rag_decision.top_k,
                            )
                            event(
                                "knowledge_discovery", "Bounded Knowledge Expansion", "completed",
                                json.dumps({
                                    "candidateCount": len(expanded_ids),
                                    "hitCount": len(retrieval_hits),
                                }, ensure_ascii=False),
                            )

                    if rag_decision.retrieve and not retrieval_hits:
                        rag_grounding_sufficient = False
                        rag_grounding_reason = "no retrieval evidence matched the task"
                        rag_grounding_stopped_reason = "no_evidence"

                    if (
                        rag_decision.mode.value == "agentic_rag"
                        and raw_retrieval_hits
                        and not retrieval_hits
                    ):
                        rag_grounding_sufficient = False
                        rag_grounding_reason = (
                            "retrieval evidence did not match requested "
                            f"{retrieval_mode.value} modality"
                        )

                    rag_diagnostics: dict[
                        str,
                        Any,
                    ] = {}

                    if retrieval_hits:

                        metadata = (
                            retrieval_hits[
                                0
                            ]
                            .document
                            .metadata
                        )

                        diagnostics = (
                            metadata.get(
                                "ragDiagnostics",
                                {},
                            )
                        )

                        if isinstance(
                            diagnostics,
                            dict,
                        ):

                            rag_diagnostics = (
                                diagnostics
                            )

                    # -----------------------------------------
                    # Context Injection Gate
                    #
                    # Retrieval 和 Context Injection
                    # 是两个不同概念。
                    #
                    # 当前：
                    #
                    # FAST_RAG      → inject
                    # AGENTIC_RAG   → inject
                    # NO_RAG        → no retrieve
                    #
                    # 以后可以扩展：
                    #
                    # retrieve for evaluation
                    # but do not inject
                    # -----------------------------------------

                    if (
                        rag_decision
                        .inject_context
                    ):

                        rag_context_hits = (
                            retrieval_hits
                        )

                    else:

                        rag_context_hits = []
                    if (
                        rag_grounding_sufficient
                        is not None
                    ):
                        if (
                            rag_grounding_sufficient
                        ):
                            grounding_action = (
                                "grounded_answer"
                            )

                            rag_grounding_policy = (
                                "grounded_only"
                            )

                        elif rag_context_hits:
                            grounding_action = (
                                "answer_with_insufficiency"
                            )

                            rag_grounding_policy = (
                                "grounded_partial_only"
                            )

                        else:
                            grounding_action = (
                                "answer_without_evidence"
                            )

                            rag_grounding_policy = (
                                "insufficiency_only"
                            )

                        event(
                            "rag",
                            "RAG Grounding Guard",
                            "completed",
                            json.dumps(
                                {
                                    "sufficient":
                                        rag_grounding_sufficient,
                                    "policy":
                                         rag_grounding_policy,

                                    "action":
                                        grounding_action,

                                    "stoppedReason":
                                        (
                                            rag_grounding_stopped_reason
                                        ),

                                    "reason":
                                        rag_grounding_reason,

                                    "contextHits":
                                        len(
                                            rag_context_hits
                                        ),
                                },
                                ensure_ascii=False,
                            ),
                        )

                    event(
                        "rag",
                        (
                            "RAG Retrieval "
                            "Completed"
                        ),
                        "completed",
                        json.dumps(
                            {
                                "mode":
                                    rag_decision
                                    .mode
                                    .value,

                                "retrievalMode":
                                    retrieval_mode.value,

                                "rawHits":
                                    len(raw_retrieval_hits),

                                "hits":
                                    len(
                                        retrieval_hits
                                    ),

                                "textCandidates":
                                    sum(
                                        1 for hit in raw_retrieval_hits
                                        if str(hit.document.metadata.get("modality", "text")).lower() == "text"
                                    ),

                                "visualCandidates":
                                    sum(
                                        1 for hit in raw_retrieval_hits
                                        if str(hit.document.metadata.get("modality", "text")).lower() != "text"
                                    ),

                                "contextHits":
                                    len(
                                        rag_context_hits
                                    ),

                                "metrics":
                                    rag_diagnostics,

                                "documents": [
                                    {
                                        "id":
                                            hit
                                            .document
                                            .id,

                                        "source":
                                            hit
                                            .document
                                            .source,

                                        "score":
                                            hit.score,

                                        "modality":
                                            hit.document.metadata.get("modality", "text"),

                                        "pageNumber":
                                            hit.document.metadata.get("pageNumber"),

                                        "visualType":
                                            hit.document.metadata.get("visualType"),

                                        "assetId":
                                            hit.document.metadata.get("assetId"),

                                        "reranker":
                                            hit
                                            .document
                                            .metadata
                                            .get(
                                                "reranker"
                                            ),
                                    }

                                    for hit
                                    in retrieval_hits
                                ],
                            },
                            ensure_ascii=False,
                        ),
                    )

                    if (
                        rag_diagnostics.get(
                            "rerankFallback"
                        )
                    ):

                        event(
                            "rag",
                            (
                                "RAG Reranker "
                                "Fallback"
                            ),
                            "completed",
                            json.dumps(
                                {
                                    "requested":
                                        rag_diagnostics
                                        .get(
                                            "requestedReranker"
                                        ),

                                    "effective":
                                        rag_diagnostics
                                        .get(
                                            "effectiveReranker"
                                        ),

                                    "error":
                                        rag_diagnostics
                                        .get(
                                            "rerankError",
                                            "",
                                        ),
                                },
                                ensure_ascii=False,
                            ),
                        )

                except Exception as exc:

                    retrieval_hits = []

                    rag_context_hits = []

                    event(
                        "rag",
                        (
                            "RAG Retrieval "
                            "Failed"
                        ),
                        "error",
                        str(
                            exc
                        ),
                    )

            # =================================================
            # 2.3 A2A Capability Discovery
            # =================================================
            # 2.3 A2A Capability Discovery
            #
            # 必须在 Scheduler 前。
            # =================================================

            for agent in (
                req.agents
            ):

                if (
                    agent.protocol
                    .strip()
                    .lower()
                    != "a2a"
                ):

                    continue

                event(
                    "a2a",
                    (
                        "A2A Capability "
                        "Discovery"
                    ),
                    "running",
                    json.dumps(
                        {
                            "agent":
                                agent.name,

                            "endpoint":
                                agent.endpoint,

                            "declaredCapabilities":
                                list(
                                    agent
                                    .capabilities
                                ),
                        },
                        ensure_ascii=False,
                    ),
                )

                try:

                    discovery = (
                        await self
                        .a2a_discovery
                        .hydrate(
                            agent
                        )
                    )

                    event(
                        "a2a",
                        (
                            "A2A Capability "
                            "Discovery"
                        ),
                        "completed",
                        json.dumps(
                            {
                                "agent":
                                    agent.name,

                                "remoteAgent":
                                    discovery
                                    .remote_name,

                                "remoteVersion":
                                    discovery
                                    .remote_version,

                                "skillCount":
                                    discovery
                                    .skill_count,

                                "capabilities":
                                    list(
                                        discovery
                                        .capabilities
                                    ),

                                "addedCapabilities":
                                    list(
                                        discovery
                                        .added_capabilities
                                    ),

                                "cacheHit":
                                    discovery
                                    .cache_hit,

                                "capabilityProfiles":
                                    len(
                                        agent
                                        .capability_profiles
                                    ),
                            },
                            ensure_ascii=False,
                        ),
                    )

                except Exception as exc:

                    event(
                        "a2a",
                        (
                            "A2A Capability "
                            "Discovery Failed"
                        ),
                        "error",
                        json.dumps(
                            {
                                "agent":
                                    agent.name,

                                "endpoint":
                                    agent.endpoint,

                                "fallbackCapabilities":
                                    list(
                                        agent
                                        .capabilities
                                    ),

                                "errorType":
                                    type(exc)
                                    .__name__,

                                "error":
                                    str(exc),
                            },
                            ensure_ascii=False,
                        ),
                    )

            # =================================================
            # 2.4 Agent / A2A Skill Discovery Refinement
            # =================================================

            skill_refresh = discover_capabilities(
                capability_query,
                agents=req.agents,
                has_attachments=bool(req.attachments),
            )
            refreshed_skills = list(
                dict.fromkeys(
                    [
                        *capability_plan.selected_skill_names,
                        *skill_refresh.selected_skill_names,
                    ]
                )
            )
            capability_plan.selected_skill_names = refreshed_skills

            existing_candidate_keys = {
                (item.kind.value, item.identifier)
                for item in capability_plan.candidates
            }
            for candidate in skill_refresh.candidates:
                key = (candidate.kind.value, candidate.identifier)
                if key in existing_candidate_keys:
                    continue
                capability_plan.candidates.append(candidate)
                existing_candidate_keys.add(key)
            capability_plan.confidence = max(
                capability_plan.confidence,
                skill_refresh.confidence,
            )

            existing_profile_capabilities = {
                item.casefold()
                for item in profile.required_capabilities
            }
            for skill in refreshed_skills:
                if skill.casefold() in existing_profile_capabilities:
                    continue
                profile.required_capabilities.append(skill)
                existing_profile_capabilities.add(skill.casefold())

            if refreshed_skills:
                event(
                    "capability_discovery",
                    "Agent Skill Discovery",
                    "completed",
                    json.dumps(
                        {
                            **skill_refresh.trace_detail(),
                            "selectedSkills": refreshed_skills,
                            "requiredCapabilities": list(
                                profile.required_capabilities
                            ),
                            "source": "Agent/A2A skill catalog",
                            "contextualized": capability_used_history,
                            "historyTurns": capability_history_turns,
                        },
                        ensure_ascii=False,
                    ),
                )

            # =================================================
            # 3. Semantic Planner + Scheduler
            #
            # Planner decides WHAT work is required. Scheduler keeps its
            # existing responsibility for WHO should execute each capability.
            # Simple/explicit-topology requests stay on the legacy fast path.
            # =================================================

            semantic_plan: ExecutionPlan | None = None
            semantic_planning_used = False
            planning_model = None

            if (
                settings.semantic_planner_enabled
                and req.execution_mode == "auto"
                and self.semantic_planner.should_plan(
                    task=req.task,
                    profile=profile,
                )
            ):
                event(
                    "planning",
                    "Semantic Planner",
                    "running",
                    json.dumps(
                        {
                            "complexity": profile.complexity,
                            "baselineCapabilities": list(profile.required_capabilities),
                            "maxSteps": settings.semantic_planner_max_steps,
                        },
                        ensure_ascii=False,
                    ),
                )

                try:
                    planning_model = self.registry.context.get("model.default")
                except KeyError:
                    planning_model = None

                planning_outcome = await self.semantic_planner.plan(
                    task=req.task,
                    profile=profile,
                    agents=req.agents,
                    model=planning_model,
                    semantic=semantic_intent,
                    on_model_event=model_event,
                )
                semantic_plan = planning_outcome.plan
                semantic_planning_used = True

                planned_capabilities = [
                    step.capability
                    for step in semantic_plan.steps
                ]
                root_steps = [
                    step
                    for step in semantic_plan.steps
                    if not step.depends_on
                ]
                profile = profile.model_copy(
                    update={
                        "required_capabilities": planned_capabilities,
                        "parallelizable": len(root_steps) > 1,
                        "complexity": (
                            "high"
                            if len(semantic_plan.steps) >= 4
                            else profile.complexity
                        ),
                    }
                )

                event(
                    "planning",
                    "Semantic Planner",
                    "completed",
                    json.dumps(
                        {
                            "source": semantic_plan.source,
                            "usedModel": planning_outcome.used_model,
                            "fallbackReason": planning_outcome.fallback_reason,
                            "goal": semantic_plan.goal,
                            "requiresSynthesis": semantic_plan.requires_synthesis,
                            "steps": [
                                step.model_dump(by_alias=True)
                                for step in semantic_plan.steps
                            ],
                        },
                        ensure_ascii=False,
                    ),
                )

            # P22/RAG V1.1: a semantic plan can introduce a knowledge
            # obligation AFTER the initial low-cost RAG routing. Resolve it
            # once, inside the immutable Go-authorized catalog, BEFORE the
            # scheduler starts any potentially side-effecting Agent/Tool.
            # A final-answer-only guard is too late: a refund Tool may have
            # already executed based on an invented private policy.
            required_steps = (
                [step for step in semantic_plan.steps
                 if step.knowledge_dependency == "REQUIRED"]
                if semantic_plan is not None else []
            )
            required_knowledge = (
                semantic_intent.knowledge_dependency == KnowledgeDependency.REQUIRED
                or bool(required_steps)
            )
            blocked_step_reasons: dict[str, str] = {}
            if required_knowledge:
                evidence_query = (
                    "\n".join(step.objective for step in required_steps[:3])
                    if required_steps else knowledge_query
                )
                evidence_grader = HeuristicEvidenceGrader()
                evidence_grade = await evidence_grader.grade(
                    evidence_query, rag_context_hits,
                )
                async def unmet_required_ids(hits):
                    # The joined query is not sufficient: one relevant passage
                    # must not silently satisfy a different REQUIRED step.
                    missing = set()
                    for step in required_steps:
                        grade = await evidence_grader.grade(step.objective, hits)
                        if not hits or not grade.sufficient:
                            missing.add(step.id)
                    return missing

                unmet_step_ids = await unmet_required_ids(rag_context_hits)
                evidence_ok = (
                    bool(rag_context_hits)
                    and rag_grounding_sufficient is not False
                    and evidence_grade.sufficient
                    and not unmet_step_ids
                )

                # At most one additional lookup; OFF / a natural-language
                # refusal can NEVER be overturned by a late Planner step.
                if (
                    not evidence_ok
                    and policy_mode != "OFF"
                    and not explicit_rag_off
                    and authorized_catalog
                ):
                    late_semantic = semantic_intent.model_copy(update={
                        "knowledge_dependency": KnowledgeDependency.REQUIRED,
                    })
                    late_discovery = discover_knowledge_bases(
                        evidence_query,
                        semantic=late_semantic,
                        catalog=authorized_catalog,
                        explicitly_selected_ids=explicit_knowledge_ids,
                        max_candidates=2,
                        force_needed=True,
                    )
                    late_ids = list(late_discovery.selected_knowledge_base_ids[:2])
                    # An explicit selection is a hard upper bound; a discovery
                    # score never grants permissions or widens a named source.
                    if explicit_knowledge_ids:
                        late_ids = [
                            value for value in late_ids
                            if value in set(explicit_knowledge_ids)
                        ]
                    late_ids = [
                        value for value in late_ids
                        if value in allowed_knowledge_set
                    ]
                    if late_ids:
                        set_candidate_knowledge_ids(late_ids)
                        event(
                            "knowledge_discovery", "Planner Late Knowledge Discovery",
                            "running", json.dumps({
                                "round": 2, "candidateCount": len(late_ids),
                                "reason": "planner_required_evidence",
                            }),
                        )
                        try:
                            late_hits = await self.retriever.retrieve(
                                evidence_query,
                                top_k=max(1, settings.rag_top_k),
                                filters={"userId": req.user_id},
                            )
                        except Exception:
                            # An authorization outage is fail-closed. Never
                            # use stale evidence from the first retrieval.
                            rag_context_hits = []
                            rag_grounding_sufficient = False
                            raise RuntimeError(
                                "知识权限校验或检索不可用，无法依据指定资料完成此任务。"
                            ) from None
                        # The second retriever call performed a NEW live
                        # authorization check. Never merge first-round hits:
                        # their access may have been revoked during planning.
                        # An empty authorized result must clear stale evidence.
                        rag_context_hits = list(late_hits)
                        retrieval_hits = list(late_hits)
                        late_grade = await evidence_grader.grade(evidence_query, rag_context_hits)
                        evidence_grade = late_grade
                        unmet_step_ids = await unmet_required_ids(rag_context_hits)
                        if rag_context_hits and late_grade.sufficient and not unmet_step_ids:
                            rag_grounding_sufficient = True
                            rag_grounding_policy = "grounded_only"
                            evidence_ok = True
                        event(
                            "knowledge_discovery", "Planner Late Knowledge Discovery",
                            "completed", json.dumps({
                                "round": 2, "hitCount": len(late_hits),
                                "sufficient": bool(late_grade.sufficient),
                            }),
                        )

                if not evidence_ok:
                    rag_grounding_sufficient = False
                    rag_grounding_policy = "insufficiency_only"
                    if semantic_plan is not None:
                        # If a global obligation is unmet we cannot prove that
                        # *any* REQUIRED step is grounded, even if a heuristic
                        # gave that step a positive score. Never send uncertain
                        # project evidence to an independent sibling either.
                        missing_steps = (
                            {step.id for step in required_steps}
                            if not evidence_grade.sufficient or not rag_context_hits
                            else unmet_step_ids
                        )
                        partition = partition_knowledge_steps(
                            semantic_plan,
                            insufficient_required=missing_steps,
                            global_requirement_unresolved=(
                                semantic_intent.knowledge_dependency
                                == KnowledgeDependency.REQUIRED
                            ),
                        )
                        blocked_step_reasons = partition.blocked
                        if blocked_step_reasons:
                            # With partial execution only unrelated model-only
                            # work may proceed. Evidence on a blocked policy
                            # must never leak into its context or citations.
                            rag_context_hits = []
                            retrieval_hits = []
                    event(
                        "rag", "Required Knowledge Pre-execution Gate", "error",
                        json.dumps({
                            "status": "INSUFFICIENT_EVIDENCE",
                            "reason": "required_evidence_unavailable_before_execution",
                            "blockedSteps": sorted(blocked_step_reasons),
                        }),
                    )
                    if not blocked_step_reasons or (
                        semantic_plan is not None and
                        len(blocked_step_reasons) == len(semantic_plan.steps)
                    ):
                        raise RuntimeError(
                            "本次任务需要指定知识资料，但缺少足够的已授权证据。"
                            "已停止依赖该资料的 Agent 与工具；请提供资料后重试。"
                        )

            scheduler_id = (
                f"scheduler."
                f"{req.scheduler}"
            )

            scheduler = (
                self.registry.get(
                    scheduler_id
                )
            )

            event(
                "schedule",
                "Scheduler",
                "running",
                scheduler_id,
            )

            raw_assignments: list[Assignment] = (
                await scheduler.schedule(
                    req.agents,
                    profile,
                    req.constraints,
                )
            )

            if semantic_plan is not None:
                if len(raw_assignments) != len(semantic_plan.steps):
                    raise RuntimeError(
                        "scheduler assignment count does not match semantic plan steps"
                    )
                assignments = [
                    Assignment(
                        capability=assignment.capability,
                        agent_id=assignment.agent_id,
                        agent_name=assignment.agent_name,
                        stepId=step.id,
                        objective=step.objective,
                        dependsOn=list(step.depends_on),
                        optional=step.optional,
                        condition=step.condition,
                    )
                    for step, assignment in zip(semantic_plan.steps, raw_assignments)
                ]
            else:
                assignments = raw_assignments

            for assignment in assignments:
                if assignment.agent_name not in selected_names:
                    selected_names.append(assignment.agent_name)

            routing_decisions = getattr(
                scheduler,
                "last_routing_decisions",
                [],
            )
            if routing_decisions:
                for decision in routing_decisions:
                    event(
                        "routing",
                        "Adaptive Agent Route",
                        "completed",
                        json.dumps(
                            decision,
                            ensure_ascii=False,
                        ),
                    )

            event(
                "schedule",
                "Scheduler",
                "completed",
                " + ".join(
                    selected_names
                ),
            )

            # =================================================
            # 4. Collaboration / Plan Topology
            # =================================================

            if semantic_plan is not None:
                execution_mode = self.plan_compiler.infer_topology(semantic_plan)
                collaboration_plan = CollaborationPlan(
                    topology=execution_mode,
                    reason="semantic execution plan dependencies",
                    agent_count=len(assignments),
                    max_parallelism=self.plan_compiler.max_parallelism(semantic_plan),
                    requires_synthesis=semantic_plan.requires_synthesis,
                )
                event(
                    "planning",
                    "Plan Topology",
                    "completed",
                    json.dumps(
                        {
                            "planner": "semantic",
                            "topology": execution_mode,
                            "reason": collaboration_plan.reason,
                            "agent_count": collaboration_plan.agent_count,
                            "max_parallelism": collaboration_plan.max_parallelism,
                            "requires_synthesis": collaboration_plan.requires_synthesis,
                        },
                        ensure_ascii=False,
                    ),
                )
            else:
                event(
                    "planning",
                    "Collaboration Planner",
                    "running",
                )

                planner = (
                    self
                    .collaboration_planners[
                        req.planner
                    ]
                )

                collaboration_plan = (
                    planner.plan(
                        assignments=(
                            assignments
                        ),
                        profile=(
                            profile
                        ),
                        constraints=(
                            req.constraints
                        ),
                        requested_mode=(
                            req.execution_mode
                        ),
                        agents=(
                            req.agents
                        ),
                    )
                )

                execution_mode = (
                    collaboration_plan
                    .topology
                )

                event(
                    "planning",
                    "Collaboration Planner",
                    "completed",
                    json.dumps(
                        {
                            "planner": req.planner,
                            "topology": collaboration_plan.topology,
                            "reason": collaboration_plan.reason,
                            "agent_count": collaboration_plan.agent_count,
                            "max_parallelism": collaboration_plan.max_parallelism,
                            "requires_synthesis": collaboration_plan.requires_synthesis,
                            "estimated_quality": collaboration_plan.estimated_quality,
                            "estimated_reliability": collaboration_plan.estimated_reliability,
                            "estimated_latency_ms": collaboration_plan.estimated_latency_ms,
                            "estimated_cost": collaboration_plan.estimated_cost,
                            "estimated_load": collaboration_plan.estimated_load,
                            "constraint_violation": collaboration_plan.constraint_violation,
                            "utility_score": collaboration_plan.utility_score,
                        },
                        ensure_ascii=False,
                    ),
                )

            # =================================================
            # 5. Dynamic DAG / Semantic Plan Compiler
            # =================================================

            if semantic_plan is not None:
                dag = self.plan_compiler.compile(
                    semantic_plan,
                    assignments,
                )
            else:
                dag = build_dag(
                    assignments,
                    execution_mode=execution_mode,
                )

            event(
                "dag",
                "Dynamic DAG",
                "completed",
                json.dumps(
                    {
                        "agent_nodes": len(assignments),
                        "topology": execution_mode,
                        "edges": len(dag.edges),
                        "max_parallelism": collaboration_plan.max_parallelism,
                        "semanticPlan": semantic_planning_used,
                    },
                    ensure_ascii=False,
                ),
            )

            agents_by_id = {
                agent.id:
                    agent

                for agent
                in req.agents
            }
            if blocked_step_reasons:
                # We cannot infer read-only guarantees from names, risk labels
                # or arbitrary third-party Tool/MCP descriptions. Do not pass a
                # shared registry (or delegate to an opaque remote Agent) while
                # REQUIRED knowledge is missing. Stop if there is no safe
                # independent model-only work, rather than fabricate a lookup.
                independent = [a for a in assignments
                               if a.step_id not in blocked_step_reasons]
                if tool_execution_enabled or any(
                    agents_by_id[a.agent_id].protocol.strip().lower() != "internal"
                    for a in independent
                ):
                    event("rag", "Partial Knowledge Side Effect Gate", "error",
                          json.dumps({"status": "INSUFFICIENT_EVIDENCE",
                                      "reason": "unverified_independent_executor",
                                      "blockedSteps": sorted(blocked_step_reasons)}))
                    raise RuntimeError(
                        "知识不足时无法验证剩余外部 Agent/工具为只读操作；"
                        "为防止未经依据的写入，已暂停本次混合任务。"
                    )

            # For a single internal Agent with no Tools / external evidence,
            # its tool-free model output is the eventual answer (when synthesis
            # is bypassed). Never stream Planner/model intermediate tokens,
            # multi-agent outputs, personal Memory or unvalidated RAG evidence.
            # Claims from the stream are provisional until Go persists result.
            stream_single_agent = bool(
                delta_sink is not None
                and len(assignments) == 1
                and not rag_context_hits
                and not rag_decision.retrieve
                and not required_knowledge
                and not memory_overview_query
                and not memory_forget_requested
                and not long_term_memories
                and not conversation_memories
                and not memory_messages
                and memory_write_outcome is None
                and not model_attachments
                and req.synthesis_mode != "always"
                and not collaboration_plan.requires_synthesis
                and "agentmesh" not in req.task.casefold()
            )
            stream_single_agent_claimed = False

            # =================================================
            # Capability Feedback Helper
            # =================================================

            def record_feedback(
                agent: AgentProfile,
                item: AgentFeedback,
            ) -> None:

                updated = (
                    apply_capability_feedback(
                        agent,
                        item,
                    )
                )

                event(
                    "profile_update",
                    (
                        "Capability Profile "
                        "Updated"
                    ),
                    "completed",
                    json.dumps(
                        {
                            "agent":
                                agent.name,

                            "capability":
                                updated
                                .capability,

                            "success_rate":
                                updated
                                .success_rate,

                            "failure_rate":
                                updated
                                .failure_rate,

                            "avg_latency_ms":
                                updated
                                .avg_latency_ms,

                            "avg_cost":
                                updated
                                .avg_cost,

                            "quality_score":
                                updated
                                .quality_score,

                            "sample_count":
                                updated
                                .sample_count,
                        },
                        ensure_ascii=False,
                    ),
                )

            # =================================================
            # Execute One Agent
            # =================================================

            async def execute_once(
                agent: AgentProfile,
                capability: str,
                task_input: str,
            ) -> tuple[
                str,
                int,
                Any | None,
            ]:

                # =============================================
                # Protocol Resolver
                # =============================================

                executor = (
                    self
                    .executor_resolver
                    .resolve(
                        agent.protocol
                    )
                )

                model_runtime = (
                    None
                )

                # =============================================
                # Model Routing
                #
                # internal / langgraph:
                # AgentMesh controls model
                #
                # http / a2a:
                # Remote Agent controls model
                # =============================================

                if (
                    agent.protocol
                    .strip()
                    .lower()
                    in {
                        "internal",
                        "langgraph",
                    }
                ):

                    model_runtime = (
                        self
                        .model_runtime_resolver
                        .resolve(
                            agent,
                            adaptive=(
                                settings.model_router_enabled
                                and req.scheduler == "adaptive"
                            ),
                            constraints=req.constraints,
                            profile=profile,
                            project_model=req.project_model,
                            model_pool=req.model_pool,
                            model_selection=req.model_selection,
                            has_images=bool(model_attachments),
                        )
                    )

                    event(
                        "model_route",
                        (
                            "Model Runtime "
                            "Resolved"
                        ),
                        "completed",
                        json.dumps(
                            {
                                "agent":
                                    agent.name,

                                "runtime_id":
                                    model_runtime
                                    .runtime_id,

                                "declared_provider":
                                    model_runtime
                                    .declared_provider,

                                "gateway_provider":
                                    model_runtime
                                    .gateway_provider,

                                "model": (
                                    model_runtime.vision_model
                                    if model_attachments and model_runtime.vision_model
                                    else model_runtime.model
                                ),

                                "serviceId": model_runtime.service_id,
                                "serviceName": model_runtime.service_name,
                                "selectionMode": model_runtime.selection_mode,

                                "mode": (
                                    model_runtime.route_decision.mode
                                    if model_runtime.route_decision is not None
                                    else "declared"
                                ),

                                "reason": (
                                    model_runtime.route_decision.reason
                                    if model_runtime.route_decision is not None
                                    else "agent/default model runtime"
                                ),

                                "selectedScore": (
                                    round(model_runtime.route_decision.selected_score, 6)
                                    if model_runtime.route_decision is not None
                                    else None
                                ),

                                "degraded": (
                                    model_runtime.route_decision.degraded
                                    if model_runtime.route_decision is not None
                                    else False
                                ),

                                "candidates": (
                                    [
                                        item.as_dict()
                                        for item in model_runtime.route_decision.candidates
                                    ]
                                    if model_runtime.route_decision is not None
                                    else []
                                ),
                            },
                            ensure_ascii=False,
                        ),
                    )

                # =============================================
                # Context
                # =============================================

                execution_context = (
                    build_agent_context(
                        task=(
                            task_input
                        ),
                        memory_messages=(
                            [] if blocked_step_reasons else memory_messages
                        ),
                        conversation_memories=(
                            [] if blocked_step_reasons else conversation_memories
                        ),
                        retrieval_hits=(
                            []
                            if memory_overview_query
                            else rag_context_hits
                        ),
                        long_term_memories=(
                            [] if blocked_step_reasons else long_term_memories
                        ),
                        memory_overview_query=(
                            memory_overview_query
                        ),
                        memory_retrieval_reason=(
                            memory_retrieval_reason
                        ),
                        grounding_sufficient=(
                            None
                            if (
                                memory_overview_query
                                or (
                                    semantic_intent.knowledge_dependency == KnowledgeDependency.OPTIONAL
                                    and rag_grounding_sufficient is False
                                )
                            )
                            else rag_grounding_sufficient
                        ),
                        grounding_reason=(
                            rag_grounding_reason
                        ),
                        grounding_stopped_reason=(
                            rag_grounding_stopped_reason
                        ),
                    )
                )

                if (
                    agent.protocol.strip().lower()
                    in {"internal", "langgraph"}
                ):
                    capability_context = (
                        "" if blocked_step_reasons
                        else discovery_context(capability_plan)
                    )
                    if capability_context:
                        execution_context = (
                            execution_context
                            + "\n\n"
                            + capability_context
                        )

                    platform_capability_context = (
                        "" if blocked_step_reasons else
                        build_platform_capability_context(
                            task=req.task,
                            history=req.history,
                            tools=req.tools,
                            mcp_servers=req.mcp_servers,
                            agents=req.agents,
                            selected_tool_names=(
                                capability_plan.selected_tool_names
                            ),
                            selected_mcp_tool_names=(
                                capability_plan.selected_mcp_tool_names
                            ),
                        )
                    )
                    if platform_capability_context:
                        execution_context = (
                            execution_context
                            + "\n\n"
                            + platform_capability_context
                        )

                event(
                    "context",
                    (
                        "Agent Context "
                        "Built"
                    ),
                    "completed",
                    json.dumps(
                        {
                            "agent":
                                agent.name,

                            "capability":
                                capability,

                            "memory_messages":
                                len(
                                    memory_messages
                                ),

                            "long_term_memories":
                                len(
                                    long_term_memories
                                ),

                            "rag_hits":
                                len(
                                    rag_context_hits
                                ),

                            "context_chars":
                                len(
                                    execution_context
                                ),
                        },
                        ensure_ascii=False,
                    ),
                )

                nonlocal stream_single_agent_claimed
                stream_this_agent = (
                    stream_single_agent
                    and not stream_single_agent_claimed
                    and agent.protocol.strip().lower() == "internal"
                    and agent.id == assignments[0].agent_id
                )
                if stream_this_agent:
                    # Even a later reschedule may not emit a second stream.
                    stream_single_agent_claimed = True

                execution_request = (
                    AgentExecutionRequest(
                        agent=(
                            agent
                        ),
                        capability=(
                            capability
                        ),

                        # IMPORTANT:
                        # 使用 build 后的 context，
                        # 不是 raw task。
                        task=(
                            execution_context
                        ),

                        on_model_event=(
                            model_event
                        ),
                        on_delta=(delta_sink if stream_this_agent else None),

                        tool_registry=(
                            tool_registry
                            if tool_execution_enabled
                            else None
                        ),

                        on_tool_event=(
                            tool_event
                        ),

                        on_runtime_event=(
                            runtime_event
                        ),

                        model_runtime=(
                            model_runtime
                        ),

                        attachments=(
                            model_attachments
                        ),
                    )
                )

                execution_started = (
                    time.perf_counter()
                )

                execution_result = (
                    await executor.execute(
                        execution_request
                    )
                )

                latency_ms = int(
                    (
                        time.perf_counter()
                        - execution_started
                    )
                    * 1000
                )

                return (
                    execution_result
                    .content,

                    latency_ms,

                    model_runtime,
                )

            # =================================================
            # Execute Assignment + Reschedule
            # =================================================

            async def execute_assignment(
                assignment: Assignment,
                task_input: str,
            ) -> tuple[
                str,
                str,
                list[AgentFeedback],
                float,
            ]:

                local_feedback: list[
                    AgentFeedback
                ] = []

                current_agent = (
                    agents_by_id[
                        assignment
                        .agent_id
                    ]
                )

                attempted_agent_ids: set[
                    int
                ] = set()

                total_cost = (
                    0.0
                )

                reschedule_count = (
                    0
                )

                quality_repair_count = 0
                current_task_input = task_input

                while True:

                    attempted_agent_ids.add(
                        current_agent.id
                    )

                    metrics = (
                        effective_capability_profile(
                            current_agent,
                            assignment
                            .capability,
                        )
                    )

                    attempt_cost = (
                        metrics
                        .avg_cost
                    )

                    # P6 hard cost guard. Scheduler/Planner already prefer
                    # candidates inside constraints; this final execution gate
                    # prevents a fallback/reschedule from knowingly crossing
                    # the configured request budget.
                    if (
                        req.constraints.max_cost > 0
                        and total_cost + attempt_cost
                        > req.constraints.max_cost + 1e-12
                    ):
                        event(
                            "governance",
                            "Cost Budget Blocked",
                            "error",
                            json.dumps(
                                {
                                    "currentCost": round(total_cost, 8),
                                    "nextAttemptCost": round(attempt_cost, 8),
                                    "maxCost": req.constraints.max_cost,
                                    "agent": current_agent.name,
                                    "capability": assignment.capability,
                                },
                                ensure_ascii=False,
                            ),
                        )
                        raise RuntimeError(
                            "runtime cost budget exhausted before next agent attempt"
                        )

                    total_cost += (
                        attempt_cost
                    )

                    event(
                        "agent",
                        (
                            f"{current_agent.name} "
                            "started"
                        ),
                        "running",
                        assignment
                        .capability,
                    )

                    attempt_started = (
                        time.perf_counter()
                    )

                    try:

                        result, latency, used_model_runtime = (
                            await execute_once(
                                current_agent,
                                assignment
                                .capability,
                                current_task_input,
                            )
                        )

                        # =====================================
                        # Evaluation
                        # =====================================

                        evaluation = (
                            await self
                            .evaluator
                            .evaluate(
                                EvaluationRequest(
                                    task=(
                                        current_task_input
                                    ),
                                    capability=(
                                        assignment
                                        .capability
                                    ),
                                    result=(
                                        result
                                    ),
                                    agent_name=(
                                        current_agent
                                        .name
                                    ),
                                )
                            )
                        )

                        event(
                            "evaluation",
                            (
                                "Agent Result "
                                "Evaluated"
                            ),
                            "completed",
                            json.dumps(
                                {
                                    "agent":
                                        current_agent
                                        .name,

                                    "capability":
                                        assignment
                                        .capability,

                                    "evaluator":
                                        evaluation
                                        .evaluator,

                                    "quality_score":
                                        evaluation
                                        .quality_score,

                                    "signals":
                                        evaluation
                                        .signals,
                                },
                                ensure_ascii=False,
                            ),
                        )

                        if used_model_runtime is not None:
                            used_model_runtime.record_quality(
                                evaluation.quality_score
                            )

                            event(
                                "routing",
                                "Model Route Feedback",
                                "completed",
                                json.dumps(
                                    {
                                        "runtimeId": used_model_runtime.runtime_id,
                                        "provider": used_model_runtime.gateway_provider,
                                        "model": used_model_runtime.model,
                                        "qualityScore": evaluation.quality_score,
                                    },
                                    ensure_ascii=False,
                                ),
                            )

                        # =====================================
                        # Runtime Quality Gate
                        #
                        # Quality recovery is intentionally conservative. Model-only
                        # local workflows may be repaired/retried. Tool, high-risk,
                        # HTTP and A2A executions are never replayed solely because a
                        # heuristic quality score is low; replay could duplicate an
                        # external side effect.
                        # =====================================

                        protocol = current_agent.protocol.strip().lower()
                        quality_recovery_safe = (
                            profile.risk_level != "high"
                            and not tool_execution_enabled
                            and protocol in {"internal", "langgraph"}
                        )
                        quality_repair_safe = (
                            quality_recovery_safe
                            and protocol == "internal"
                        )

                        gate_decision = self.quality_gate.decide(
                            evaluation,
                            repair_attempts=quality_repair_count,
                            allow_repair=quality_repair_safe,
                        )

                        if gate_decision.action == "fail" and not quality_recovery_safe:
                            # Monitor-only mode for executions that must not be replayed.
                            gate_action = "degraded"
                            gate_reason = (
                                gate_decision.reason
                                + "; recovery suppressed for side-effect safety"
                            )
                        else:
                            gate_action = gate_decision.action
                            gate_reason = gate_decision.reason

                        event(
                            "quality_gate",
                            "Runtime Quality Gate",
                            (
                                "error"
                                if gate_action == "fail"
                                else "completed"
                            ),
                            json.dumps(
                                {
                                    "agent": current_agent.name,
                                    "capability": assignment.capability,
                                    "action": gate_action,
                                    "score": gate_decision.score,
                                    "reason": gate_reason,
                                    "repairAttempt": quality_repair_count,
                                    "recoverySafe": quality_recovery_safe,
                                },
                                ensure_ascii=False,
                            ),
                        )

                        if gate_action == "repair":
                            quality_repair_count += 1
                            current_task_input = self.repair_prompt_builder.build(
                                original_task=task_input,
                                previous_result=result,
                                evaluation=evaluation,
                                attempt=quality_repair_count,
                            )
                            event(
                                "repair",
                                "Agent Result Repair",
                                "running",
                                json.dumps(
                                    {
                                        "agent": current_agent.name,
                                        "capability": assignment.capability,
                                        "attempt": quality_repair_count,
                                        "qualityScore": evaluation.quality_score,
                                    },
                                    ensure_ascii=False,
                                ),
                            )
                            continue

                        if gate_action == "fail":
                            raise QualityGateError(
                                (
                                    f"quality gate rejected {assignment.capability} "
                                    f"result from {current_agent.name}"
                                ),
                                score=evaluation.quality_score,
                            )

                        # =====================================
                        # Successful Feedback
                        # =====================================

                        success_feedback = (
                            AgentFeedback(
                                agentId=(
                                    current_agent
                                    .id
                                ),
                                capability=(
                                    assignment
                                    .capability
                                ),
                                success=True,
                                latencyMs=(
                                    latency
                                ),
                                cost=(
                                    attempt_cost
                                ),
                                qualityScore=(
                                    evaluation
                                    .quality_score
                                ),
                            )
                        )

                        local_feedback.append(
                            success_feedback
                        )

                        record_feedback(
                            current_agent,
                            success_feedback,
                        )

                        completion_detail = (
                            f"{latency} ms"
                        )

                        if (
                            reschedule_count
                            > 0
                        ):

                            completion_detail = (
                                "fallback "
                                + completion_detail
                            )

                        event(
                            "agent",
                            (
                                f"{current_agent.name} "
                                "completed"
                            ),
                            "completed",
                            completion_detail,
                        )

                        fallback_suffix = (
                            "/fallback"

                            if (
                                reschedule_count
                                > 0
                            )

                            else ""
                        )

                        return (
                            assignment
                            .capability,

                            (
                                f"[{current_agent.name}/"
                                f"{assignment.capability}"
                                f"{fallback_suffix}]"
                                "\n"
                                f"{result}"
                            ),

                            local_feedback,

                            total_cost,
                        )

                    # =========================================
                    # TOOL APPROVAL REQUIRED
                    #
                    # Human approval is a normal suspend state,
                    # never an Agent failure/reschedule signal.
                    # =========================================

                    except ToolApprovalRequired as exc:

                        approval = exc.request

                        event(
                            "approval",
                            "Approval Requested",
                            "completed",
                            json.dumps(
                                {
                                    "approvalId": approval.approval_id,
                                    "tool": approval.tool_name,
                                    "protocol": approval.protocol,
                                    "riskLevel": approval.risk_level,
                                    "requiresConfirmation": approval.requires_confirmation,
                                    "fingerprint": approval.fingerprint,
                                    "arguments": approval.safe_arguments(),
                                },
                                ensure_ascii=False,
                            ),
                        )

                        raise RuntimeTaskInterrupted(
                            agent=current_agent,
                            capability=assignment.capability,
                            state="AUTH_REQUIRED",
                            task_id=approval.approval_id,
                            context_id=approval.fingerprint,
                            message=(
                                "此操作需要你的确认后才会执行。"
                            ),
                            estimated_cost=total_cost,
                            continuation_protocol="tool_approval",
                            approval=approval,
                        ) from exc

                    # =========================================
                    # A2A INTERRUPTED
                    #
                    # IMPORTANT:
                    #
                    # 这里一定必须放在
                    # except Exception 前面。
                    #
                    # INPUT_REQUIRED / AUTH_REQUIRED
                    # 不是失败。
                    # =========================================

                    except (
                        A2AAgentInterruptedError
                    ) as exc:

                        if (
                            exc.task_state
                            == (
                                "TASK_STATE_"
                                "AUTH_REQUIRED"
                            )
                        ):

                            runtime_state = (
                                "AUTH_REQUIRED"
                            )

                        else:

                            runtime_state = (
                                "INPUT_REQUIRED"
                            )

                        event(
                            "agent",
                            (
                                f"{current_agent.name} "
                                "suspended"
                            ),
                            "completed",
                            json.dumps(
                                {
                                    "capability":
                                        assignment
                                        .capability,

                                    "state":
                                        runtime_state,

                                    "taskId":
                                        exc.task_id,

                                    "contextId":
                                        exc.context_id,

                                    "message":
                                        (
                                            exc
                                            .status_message
                                            or str(exc)
                                        ),
                                },
                                ensure_ascii=False,
                            ),
                        )

                        # 不：
                        #
                        # local_feedback.append(failure)
                        #
                        # 不：
                        #
                        # record_feedback(... success=False)
                        #
                        # 不：
                        #
                        # RuntimeRescheduler

                        raise (
                            RuntimeTaskInterrupted(
                                agent=(
                                    current_agent
                                ),
                                capability=(
                                    assignment
                                    .capability
                                ),
                                state=(
                                    runtime_state
                                ),
                                task_id=(
                                    exc.task_id
                                ),
                                context_id=(
                                    exc.context_id
                                ),
                                message=(
                                    exc.status_message
                                    or str(exc)
                                ),
                                estimated_cost=(
                                    total_cost
                                ),
                            )
                        ) from exc

                    # =========================================
                    # REAL EXECUTION FAILURE
                    # =========================================

                    except Exception as exc:

                        failure_latency = max(
                            1,
                            int(
                                (
                                    time.perf_counter()
                                    - attempt_started
                                )
                                * 1000
                            ),
                        )

                        failed_feedback = (
                            AgentFeedback(
                                agentId=(
                                    current_agent
                                    .id
                                ),
                                capability=(
                                    assignment
                                    .capability
                                ),
                                success=False,
                                latencyMs=(
                                    failure_latency
                                ),
                                cost=(
                                    attempt_cost
                                ),
                                errorType=(
                                    type(exc)
                                    .__name__
                                ),
                            )
                        )

                        local_feedback.append(
                            failed_feedback
                        )

                        record_feedback(
                            current_agent,
                            failed_feedback,
                        )

                        event(
                            "agent",
                            (
                                f"{current_agent.name} "
                                "failed"
                            ),
                            "error",
                            str(exc),
                        )

                        # =====================================
                        # Bounded Reschedule
                        # =====================================

                        if (
                            reschedule_count
                            >=
                            settings
                            .max_reschedule_attempts
                        ):

                            event(
                                "reschedule",
                                (
                                    "Runtime "
                                    "Rescheduler"
                                ),
                                "error",
                                (
                                    "maximum "
                                    "reschedule "
                                    "attempts reached"
                                ),
                            )

                            raise RuntimeError(
                                (
                                    f"{assignment.capability} "
                                    "failed after "
                                    f"{reschedule_count} "
                                    "reschedule attempt(s)"
                                )
                            ) from exc

                        event(
                            "reschedule",
                            (
                                "Runtime "
                                "Rescheduler"
                            ),
                            "running",
                            assignment
                            .capability,
                        )

                        decision = (
                            self
                            .runtime_rescheduler
                            .choose_replacement(
                                agents=(
                                    req.agents
                                ),
                                capability=(
                                    assignment
                                    .capability
                                ),
                                constraints=(
                                    req.constraints
                                ),
                                attempted_agent_ids=(
                                    attempted_agent_ids
                                ),
                                profile=profile,
                            )
                        )

                        if decision is None:

                            event(
                                "reschedule",
                                (
                                    "Runtime "
                                    "Rescheduler"
                                ),
                                "error",
                                (
                                    "no replacement "
                                    "candidate"
                                ),
                            )

                            raise RuntimeError(
                                (
                                    f"{assignment.capability} "
                                    "failed and no "
                                    "replacement candidate"
                                )
                            ) from exc

                        replacement = (
                            decision.agent
                        )

                        if (
                            replacement.name
                            not in selected_names
                        ):

                            selected_names.append(
                                replacement.name
                            )

                        reschedule_count += (
                            1
                        )

                        event(
                            "reschedule",
                            (
                                "Runtime "
                                "Rescheduler"
                            ),
                            "completed",
                            json.dumps(
                                {
                                    "from":
                                        current_agent
                                        .name,

                                    "to":
                                        replacement
                                        .name,

                                    "capability":
                                        assignment
                                        .capability,

                                    "adaptive_score":
                                        round(
                                            decision
                                            .score,
                                            6,
                                        ),

                                    "constraint_fit":
                                        decision
                                        .constraint_fit,

                                    "reason":
                                        decision.reason,

                                    "candidates":
                                        decision.candidates,

                                    "attempt":
                                        reschedule_count,
                                },
                                ensure_ascii=False,
                            ),
                        )

                        current_agent = (
                            replacement
                        )
                        # Keep the mutable Assignment aligned with the latest
                        # runtime fallback so bounded replanning can correctly
                        # assess which protocol actually executed last.
                        assignment.agent_id = replacement.id
                        assignment.agent_name = replacement.name

            # =================================================
            # 6. DAG Runtime
            # =================================================

            event(
                "runtime",
                "DAG Runtime",
                "running",
                json.dumps(
                    {
                        "topology":
                            execution_mode,

                        "max_parallelism":
                            collaboration_plan
                            .max_parallelism,
                    },
                    ensure_ascii=False,
                ),
            )

            # =================================================
            # DAG Condition Evaluator
            # =================================================

            def evaluate_dag_condition(
                node,
                upstream_outputs,
            ) -> bool:

                if (
                    node.condition
                    == "always"
                ):

                    return True

                if (
                    node.condition
                    == "never"
                ):

                    return False

                if (
                    node.condition
                    == (
                        "has_upstream_output"
                    )
                ):

                    return bool(
                        upstream_outputs
                    )

                raise RuntimeError(
                    (
                        "unsupported DAG "
                        "condition: "
                        f"{node.condition}"
                    )
                )

            # =================================================
            # DAG Node Executor
            # =================================================

            async def execute_dag_node(
                node,
                upstream_outputs,
            ):

                if (
                    node.agent_id
                    is None
                    or
                    node.capability
                    is None
                    or
                    node.agent_name
                    is None
                ):

                    raise RuntimeError(
                        (
                            "invalid agent "
                            "DAG node: "
                            f"{node.id}"
                        )
                    )

                assignment = (
                    Assignment(
                        capability=(
                            node
                            .capability
                        ),
                        agent_id=(
                            node
                            .agent_id
                        ),
                        agent_name=(
                            node
                            .agent_name
                        ),
                        stepId=node.step_id,
                        objective=node.objective,
                        optional=node.optional,
                        condition=node.condition,
                    )
                )

                # =============================================
                # Assigned semantic step / legacy task
                # =============================================

                if node.objective:
                    base_task_input = (
                        ("" if blocked_step_reasons else "Overall user goal:\n" + req.task + "\n\n")
                        + "Assigned execution-plan step"
                        + (f" [{node.step_id}]" if node.step_id else "")
                        + ":\n"
                        + node.objective
                        + "\n\nComplete only this assigned step. "
                        "Use upstream results when present and do not redo completed steps."
                        + ("\nOther steps requiring unavailable knowledge are blocked. "
                           "Do not infer or perform their actions."
                           if blocked_step_reasons else "")
                    )
                else:
                    base_task_input = req.task

                task_input = (
                    base_task_input
                    + (
                        "\n\nRequest-local attachment context:\n"
                        + attachment_text_context
                        if attachment_text_context
                        else ""
                    )
                )

                # =============================================
                # Downstream Agent
                # =============================================

                if upstream_outputs:

                    upstream_parts: list[
                        str
                    ] = []

                    for (
                        upstream_node_id,
                        upstream_result,
                    ) in (
                        upstream_outputs
                        .items()
                    ):

                        upstream_text = (
                            upstream_result[
                                1
                            ]
                        )

                        upstream_parts.append(
                            (
                                "[Upstream "
                                f"{upstream_node_id}]"
                                "\n"
                                f"{upstream_text}"
                            )
                        )

                    task_input = (
                        task_input
                        + "\n\n"
                        + (
                            "Upstream Agent "
                            "Results:"
                        )
                        + "\n\n"
                        + "\n\n".join(
                            upstream_parts
                        )
                        + "\n\n"
                        + (
                            "Use the upstream "
                            "results as context "
                            "for your assigned "
                            "capability. "
                            "Do not ignore them."
                        )
                    )

                return (
                    await execute_assignment(
                        assignment,
                        task_input,
                    )
                )

            # =================================================
            # Bounded Semantic Replanning
            #
            # Replanning is allowed only for low-risk, model-only executions.
            # Tool / HTTP / A2A work may have side effects and is therefore
            # never replayed by this recovery layer. Completed semantic steps
            # are carried forward as initial DAG outputs.
            # =================================================

            async def execute_dag_with_replanning():
                nonlocal dag
                nonlocal assignments
                nonlocal semantic_plan
                nonlocal profile
                nonlocal execution_mode
                nonlocal collaboration_plan

                replan_count = 0
                carried_outputs: dict[str, Any] = {}

                while True:
                    try:
                        return await self.dag_executor.execute(
                            dag,
                            execute_dag_node,
                            runtime_event,
                            evaluate_dag_condition,
                            initial_outputs=carried_outputs,
                            blocked_node_reasons={
                                self.plan_compiler.node_id(step_id): reason
                                for step_id, reason in blocked_step_reasons.items()
                            },
                        )
                    except DAGExecutionError as dag_exc:
                        # Suspension is control flow, not a replanning trigger.
                        if find_runtime_interruption(dag_exc) is not None:
                            raise

                        if (
                            semantic_plan is None
                            or replan_count >= max(0, settings.max_replan_attempts)
                            or profile.risk_level == "high"
                            or tool_execution_enabled
                            or blocked_step_reasons
                        ):
                            raise

                        # Fail closed if any actually selected/fallback Agent is
                        # remote. Replaying HTTP/A2A execution could duplicate
                        # an external action whose effects are not observable to
                        # this process.
                        selected_protocols = {
                            agents_by_id[item.agent_id].protocol.strip().lower()
                            for item in assignments
                            if item.agent_id in agents_by_id
                        }
                        if not selected_protocols.issubset({"internal", "langgraph"}):
                            event(
                                "replan",
                                "Semantic Replanner",
                                "skipped",
                                json.dumps(
                                    {
                                        "reason": "remote_agent_replay_not_safe",
                                        "protocols": sorted(selected_protocols),
                                    },
                                    ensure_ascii=False,
                                ),
                            )
                            raise

                        partial = dag_exc.partial_result
                        if partial is None:
                            raise

                        current_nodes = {node.id: node for node in dag.nodes}
                        current_steps = {step.id: step for step in semantic_plan.steps}
                        completed_steps: dict[str, PlanStep] = {}
                        for node_id in partial.outputs:
                            node = current_nodes.get(node_id)
                            if node is None or not node.step_id:
                                continue
                            step = current_steps.get(node.step_id)
                            if step is not None:
                                completed_steps[step.id] = step

                        failed_step_id = None
                        if dag_exc.node_id:
                            failed_node = current_nodes.get(dag_exc.node_id)
                            if failed_node is not None:
                                failed_step_id = failed_node.step_id

                        event(
                            "replan",
                            "Semantic Replanner",
                            "running",
                            json.dumps(
                                {
                                    "attempt": replan_count + 1,
                                    "failedStepId": failed_step_id,
                                    "completedStepIds": sorted(completed_steps),
                                    "failureType": type(dag_exc.__cause__ or dag_exc).__name__,
                                },
                                ensure_ascii=False,
                            ),
                        )

                        available_capabilities = self.semantic_planner.available_capabilities(
                            req.agents,
                            profile,
                        )
                        revised_plan = await self.semantic_replanner.replan(
                            task=req.task,
                            current_plan=semantic_plan,
                            completed_steps=completed_steps,
                            failed_step_id=failed_step_id,
                            failure=dag_exc.__cause__ or dag_exc,
                            available_capabilities=available_capabilities,
                            baseline_capabilities=[
                                step.capability for step in semantic_plan.steps
                            ],
                            model=planning_model,
                            on_model_event=model_event,
                        )

                        if revised_plan is None:
                            event(
                                "replan",
                                "Semantic Replanner",
                                "error",
                                json.dumps(
                                    {
                                        "reason": "no_valid_revised_plan",
                                        "attempt": replan_count + 1,
                                    },
                                    ensure_ascii=False,
                                ),
                            )
                            raise

                        root_steps = [step for step in revised_plan.steps if not step.depends_on]
                        revised_profile = profile.model_copy(
                            update={
                                "required_capabilities": [
                                    step.capability for step in revised_plan.steps
                                ],
                                "parallelizable": len(root_steps) > 1,
                                "complexity": (
                                    "high"
                                    if len(revised_plan.steps) >= 4
                                    else profile.complexity
                                ),
                            }
                        )

                        # Keep assignments for completed semantic steps. They are
                        # already materialized in ``partial.outputs`` and must not
                        # become dependent on a newly available Agent merely because
                        # the unfinished plan changed. Only unfinished steps are sent
                        # back through the Scheduler.
                        current_assignments_by_step = {
                            item.step_id: item
                            for item in assignments
                            if item.step_id
                        }
                        unfinished_steps = [
                            step
                            for step in revised_plan.steps
                            if step.id not in completed_steps
                        ]

                        raw_reassignments: list[Assignment] = []
                        if unfinished_steps:
                            scheduling_profile = revised_profile.model_copy(
                                update={
                                    "required_capabilities": [
                                        step.capability for step in unfinished_steps
                                    ],
                                    "parallelizable": len(
                                        [
                                            step
                                            for step in unfinished_steps
                                            if not step.depends_on
                                            or all(
                                                dependency in completed_steps
                                                for dependency in step.depends_on
                                            )
                                        ]
                                    ) > 1,
                                }
                            )
                            raw_reassignments = await scheduler.schedule(
                                req.agents,
                                scheduling_profile,
                                req.constraints,
                            )

                        if len(raw_reassignments) != len(unfinished_steps):
                            event(
                                "replan",
                                "Semantic Replanner",
                                "error",
                                "scheduler assignment count mismatch after replanning",
                            )
                            raise RuntimeError(
                                "scheduler assignment count mismatch after replanning"
                            )

                        scheduled_iter = iter(raw_reassignments)
                        revised_assignments: list[Assignment] = []
                        for step in revised_plan.steps:
                            if step.id in completed_steps:
                                previous = current_assignments_by_step.get(step.id)
                                if previous is None:
                                    raise RuntimeError(
                                        "completed semantic step lost its assignment: "
                                        f"{step.id}"
                                    )
                                assignment = previous
                            else:
                                assignment = next(scheduled_iter)

                            revised_assignments.append(
                                Assignment(
                                    capability=step.capability,
                                    agent_id=assignment.agent_id,
                                    agent_name=assignment.agent_name,
                                    stepId=step.id,
                                    objective=step.objective,
                                    dependsOn=list(step.depends_on),
                                    optional=step.optional,
                                    condition=step.condition,
                                )
                            )

                        for assignment in revised_assignments:
                            if assignment.agent_name not in selected_names:
                                selected_names.append(assignment.agent_name)

                        semantic_plan = revised_plan
                        profile = revised_profile
                        assignments = revised_assignments
                        execution_mode = self.plan_compiler.infer_topology(revised_plan)
                        collaboration_plan = CollaborationPlan(
                            topology=execution_mode,
                            reason="bounded semantic replanning",
                            agent_count=len(assignments),
                            max_parallelism=self.plan_compiler.max_parallelism(revised_plan),
                            requires_synthesis=revised_plan.requires_synthesis,
                        )
                        dag = self.plan_compiler.compile(revised_plan, assignments)

                        new_node_ids = {node.id for node in dag.nodes}
                        carried_outputs = {
                            node_id: output
                            for node_id, output in partial.outputs.items()
                            if node_id in new_node_ids
                        }

                        replan_count += 1
                        event(
                            "replan",
                            "Semantic Replanner",
                            "completed",
                            json.dumps(
                                {
                                    "attempt": replan_count,
                                    "topology": execution_mode,
                                    "carriedCompletedNodes": sorted(carried_outputs),
                                    "steps": [
                                        step.model_dump(by_alias=True)
                                        for step in revised_plan.steps
                                    ],
                                },
                                ensure_ascii=False,
                            ),
                        )

            # =================================================
            # Execute DAG
            #
            # RuntimeTaskInterrupted 必须向 Runtime Response
            # 转换成 Suspend，而不是 failure。
            # =================================================
            try:

                dag_result = (
                    await execute_dag_with_replanning()
                )

            except (
                DAGExecutionError
            ) as dag_exc:

                interrupted = (
                    find_runtime_interruption(
                        dag_exc
                    )
                )

                # =============================================
                # 普通 DAG Failure
                #
                # 如果异常链里没有 RuntimeTaskInterrupted，
                # 说明它真的只是 DAG 执行失败。
                #
                # 原异常继续往上抛，不能误吞。
                # =============================================

                if interrupted is None:

                    raise

                # =============================================
                # Runtime Suspend
                #
                # INPUT_REQUIRED / AUTH_REQUIRED
                # 虽然穿过 DAGExecutor，
                # 但它不是 DAG Failure。
                # =============================================

                for node in dag.nodes:

                    if (
                        node.agent_id
                        == interrupted.agent.id
                        and
                        node.capability
                        == interrupted.capability
                    ):

                        # DAGExecutor 可能已经把这个节点
                        # 标记为 error。
                        #
                        # 但实际上 Agent 只是暂停，
                        # 所以恢复为 pending。
                        node.status = (
                            "pending"
                        )

                approval = interrupted.approval

                continuation = (
                    RuntimeContinuation(
                        protocol=(
                            interrupted
                            .continuation_protocol
                        ),

                        agentId=(
                            interrupted
                            .agent
                            .id
                        ),

                        capability=(
                            interrupted
                            .capability
                        ),

                        taskId=(
                            interrupted
                            .task_id
                        ),

                        contextId=(
                            interrupted
                            .context_id
                        ),

                        state=(
                            interrupted
                            .state
                        ),

                        kind=(
                            "tool_approval"
                            if approval is not None
                            else "agent"
                        ),

                        approvalId=(
                            approval.approval_id
                            if approval is not None
                            else None
                        ),

                        toolName=(
                            approval.tool_name
                            if approval is not None
                            else None
                        ),

                        toolProtocol=(
                            approval.protocol
                            if approval is not None
                            else None
                        ),

                        riskLevel=(
                            approval.risk_level
                            if approval is not None
                            else None
                        ),

                        requiresConfirmation=(
                            approval.requires_confirmation
                            if approval is not None
                            else False
                        ),

                        arguments=(
                            approval.arguments
                            if approval is not None
                            else {}
                        ),

                        fingerprint=(
                            approval.fingerprint
                            if approval is not None
                            else None
                        ),

                        summary=(
                            approval.summary
                            if approval is not None
                            else None
                        ),
                    )
                )

                event(
                    "task",
                    "Task Suspended",
                    "completed",

                    json.dumps(
                        {
                            "status":
                                interrupted
                                .state,

                            "agent":
                                interrupted
                                .agent
                                .name,

                            "capability":
                                interrupted
                                .capability,

                            "taskId":
                                interrupted
                                .task_id,

                            "contextId":
                                interrupted
                                .context_id,
                        },
                        ensure_ascii=False,
                    ),
                )

                # =============================================
                # Conversation Memory
                # =============================================

                if (
                    req.conversation_id
                    is not None
                ):

                    try:

                        await self.memory.append(
                            user_id=(
                                req.user_id
                            ),

                            conversation_id=(
                                req
                                .conversation_id
                            ),

                            message=(
                                MemoryMessage(
                                    role="user",

                                    content=(
                                        req.task
                                    ),
                                )
                            ),
                        )

                        await self.memory.append(
                            user_id=(
                                req.user_id
                            ),

                            conversation_id=(
                                req
                                .conversation_id
                            ),

                            message=(
                                MemoryMessage(
                                    role="assistant",

                                    content=(
                                        interrupted
                                        .message
                                    ),
                                )
                            ),
                        )

                        event(
                            "memory",
                            (
                                "Memory Context "
                                "Saved"
                            ),
                            "completed",

                            json.dumps(
                                {
                                    "conversation_id":
                                        req
                                        .conversation_id,

                                    "messages_saved":
                                        2,

                                    "reason":
                                        "task_suspended",
                                },
                                ensure_ascii=False,
                            ),
                        )

                    except Exception as exc:

                        event(
                            "memory",
                            (
                                "Memory Context "
                                "Save Failed"
                            ),
                            "error",
                            str(exc),
                        )

                # =============================================
                # Observability
                #
                # 注意：
                #
                # feedback 里没有 success=False。
                #
                # 所以 INPUT_REQUIRED 不应该增加
                # agentFailures。
                # =============================================

                observability = (
                    build_observability_summary(
                        trace=(
                            trace
                        ),

                        feedback=(
                            feedback
                        ),

                        dag=(
                            dag
                        ),
                    )
                )

                event(
                    "observability",
                    (
                        "Runtime Metrics "
                        "Aggregated"
                    ),
                    "completed",

                    json.dumps(
                        observability
                        .model_dump(
                            by_alias=True
                        ),
                        ensure_ascii=False,
                    ),
                )

                return RuntimeResponse(
                    request_id=(
                        req.request_id
                    ),

                    status=(
                        interrupted
                        .state
                    ),

                    answer=(
                        interrupted
                        .message
                    ),

                    continuation=(
                        continuation
                    ),

                    scheduler=(
                        req.scheduler
                    ),

                    task_profile=(
                        profile
                    ),

                    selected_agents=(
                        selected_names
                    ),

                    estimated_cost=round(
                        interrupted
                        .estimated_cost,
                        6,
                    ),

                    elapsed_ms=(
                        elapsed()
                    ),

                    trace=(
                        trace
                    ),

                    dag=(
                        dag
                    ),

                    agent_feedback=(
                        feedback
                    ),

                    observability=(
                        observability
                    ),
                )

                # =============================================
                # Reset interrupted node from error
                # =============================================

                for node in dag.nodes:

                    if (
                        node.agent_id
                        == interrupted.agent.id
                        and
                        node.capability
                        == interrupted.capability
                    ):

                        node.status = (
                            "pending"
                        )

                continuation = (
                    RuntimeContinuation(
                        protocol=(
                            interrupted
                            .agent
                            .protocol
                        ),
                        agentId=(
                            interrupted
                            .agent
                            .id
                        ),
                        capability=(
                            interrupted
                            .capability
                        ),
                        taskId=(
                            interrupted
                            .task_id
                        ),
                        contextId=(
                            interrupted
                            .context_id
                        ),
                        state=(
                            interrupted
                            .state
                        ),
                    )
                )

                event(
                    "task",
                    "Task Suspended",
                    "completed",
                    json.dumps(
                        {
                            "status":
                                interrupted
                                .state,

                            "agent":
                                interrupted
                                .agent
                                .name,

                            "capability":
                                interrupted
                                .capability,

                            "taskId":
                                interrupted
                                .task_id,

                            "contextId":
                                interrupted
                                .context_id,
                        },
                        ensure_ascii=False,
                    ),
                )

                # =============================================
                # Suspended Task Memory
                #
                # 将：
                #
                # 用户原始问题
                # Agent 要求补充的信息
                #
                # 作为正常会话历史保存。
                # =============================================

                if (
                    req.conversation_id
                    is not None
                ):

                    try:

                        await self.memory.append(
                            user_id=(
                                req.user_id
                            ),
                            conversation_id=(
                                req
                                .conversation_id
                            ),
                            message=(
                                MemoryMessage(
                                    role="user",
                                    content=(
                                        req.task
                                    ),
                                )
                            ),
                        )

                        await self.memory.append(
                            user_id=(
                                req.user_id
                            ),
                            conversation_id=(
                                req
                                .conversation_id
                            ),
                            message=(
                                MemoryMessage(
                                    role="assistant",
                                    content=(
                                        interrupted
                                        .message
                                    ),
                                )
                            ),
                        )

                        event(
                            "memory",
                            (
                                "Memory Context "
                                "Saved"
                            ),
                            "completed",
                            json.dumps(
                                {
                                    "conversation_id":
                                        req
                                        .conversation_id,

                                    "messages_saved":
                                        2,

                                    "reason":
                                        "task_suspended",
                                },
                                ensure_ascii=False,
                            ),
                        )

                    except Exception as exc:

                        event(
                            "memory",
                            (
                                "Memory Context "
                                "Save Failed"
                            ),
                            "error",
                            str(exc),
                        )

                # =============================================
                # IMPORTANT
                #
                # feedback 此时没有 success=False。
                #
                # 所以：
                #
                # agentFailures 不应因为 INPUT_REQUIRED 增长。
                # =============================================

                observability = (
                    build_observability_summary(
                        trace=(
                            trace
                        ),
                        feedback=(
                            feedback
                        ),
                        dag=(
                            dag
                        ),
                    )
                )

                event(
                    "observability",
                    (
                        "Runtime Metrics "
                        "Aggregated"
                    ),
                    "completed",
                    json.dumps(
                        observability
                        .model_dump(
                            by_alias=True
                        ),
                        ensure_ascii=False,
                    ),
                )

                return RuntimeResponse(
                    request_id=(
                        req.request_id
                    ),
                    status=(
                        interrupted
                        .state
                    ),
                    answer=(
                        interrupted
                        .message
                    ),
                    continuation=(
                        continuation
                    ),
                    scheduler=(
                        req.scheduler
                    ),
                    task_profile=(
                        profile
                    ),
                    selected_agents=(
                        selected_names
                    ),
                    estimated_cost=round(
                        interrupted
                        .estimated_cost,
                        6,
                    ),
                    elapsed_ms=(
                        elapsed()
                    ),
                    trace=(
                        trace
                    ),
                    dag=(
                        dag
                    ),
                    agent_feedback=(
                        feedback
                    ),
                    observability=(
                        observability
                    ),
                )

            # =================================================
            # DAG completed normally
            # =================================================

            event(
                "runtime",
                "DAG Runtime",
                "completed",
                " → ".join(
                    dag_result
                    .completion_order
                ),
            )

            # =================================================
            # 7. Aggregate Results
            # =================================================

            parts: list[
                str
            ] = []

            estimated_cost = (
                0.0
            )

            # 保持 plan / DAG business order，
            # 不使用 async completion order。Semantic Plan 使用稳定的
            # step-* node id；legacy topology 继续使用 agent-*。

            execution_nodes = [
                node
                for node in dag.nodes
                if node.kind == "agent"
            ]

            for node in execution_nodes:
                node_result = dag_result.outputs.get(node.id)
                if node_result is None:
                    if node.status == "skipped" or node.optional:
                        continue
                    raise RuntimeError(
                        f"mandatory DAG node produced no output: {node.id}"
                    )

                (
                    _,
                    result,
                    local_feedback,
                    cost,
                ) = node_result

                parts.append(result)
                feedback.extend(local_feedback)
                estimated_cost += cost

            # =================================================
            # 8. Synthesis Policy
            # =================================================

            synthesis_node = next(
                node

                for node
                in dag.nodes

                if (
                    node.id
                    == "synthesize"
                )
            )

            if (
                req.synthesis_mode
                == "always"
            ):

                should_synthesize = (
                    True
                )

            elif (
                req.synthesis_mode
                == "never"
            ):

                should_synthesize = (
                    False
                )

            else:

                should_synthesize = (
                    collaboration_plan
                    .requires_synthesis
                )

            # =================================================
            # Synthesis
            # =================================================

            if blocked_step_reasons:
                should_synthesize = False

            if should_synthesize:

                synthesis_node.status = (
                    "running"
                )

                event(
                    "synthesis",
                    (
                        "Result "
                        "Synthesizer"
                    ),
                    "running",
                    json.dumps(
                        {
                            "mode":
                                req
                                .synthesis_mode,

                            "topology":
                                collaboration_plan
                                .topology,

                            "agent_results":
                                len(
                                    parts
                                ),

                            "decision":
                                "synthesize",
                        },
                        ensure_ascii=False,
                    ),
                )

                try:

                    synthesis_model = (
                        self.registry
                        .context
                        .get(
                            "model.default"
                        )
                    )

                    # Agent outputs are untrusted intermediate prose. The
                    # synthesis model must receive the SAME request-local,
                    # authorization-checked evidence and citation namespace
                    # as the earlier Agent calls; citing an earlier Agent
                    # answer is not equivalent to citing retrieved evidence.
                    synthesis_hits = select_synthesis_evidence(
                        rag_context_hits,
                        policy_mode=policy_mode,
                        explicit_rag_off=explicit_rag_off,
                        memory_overview_query=memory_overview_query,
                        has_blocked_steps=bool(blocked_step_reasons),
                        initial_retrieval_enabled=rag_decision.retrieve,
                        initial_injection_enabled=rag_decision.inject_context,
                        grounding_policy=rag_grounding_policy,
                    )
                    if rag_decision.retrieve or rag_context_hits or rag_grounding_policy:
                        synthesis_prompt = build_synthesis_context(
                            task=req.task,
                            agent_results=parts,
                            retrieval_hits=synthesis_hits,
                            grounding_sufficient=(
                                None
                                if (
                                    semantic_intent.knowledge_dependency
                                    == KnowledgeDependency.OPTIONAL
                                    and rag_grounding_sufficient is False
                                )
                                else rag_grounding_sufficient
                            ),
                            grounding_reason=rag_grounding_reason,
                            grounding_stopped_reason=rag_grounding_stopped_reason,
                        )
                    else:
                        synthesis_prompt = (
                            "请综合以下 Agent 结果，形成清晰、准确的最终答案：\n\n"
                            + "\n\n".join(parts)
                        )
                    event(
                        "synthesis", "Synthesis Evidence Context", "completed",
                        json.dumps({
                            "evidenceCount": len(synthesis_hits),
                            "hasCitationPolicy": bool(
                                build_evidence_provenance(synthesis_hits)
                            ),
                            "groundingPolicy": rag_grounding_policy,
                        }, ensure_ascii=False),
                    )
                    # Stream only where later private-memory / knowledge guards
                    # cannot invalidate or replace a potentially sensitive draft.
                    # Completion is still authoritative; a disconnect never
                    # changes the underlying execution or persisted final answer.
                    allow_delta = (
                        delta_sink is not None
                        and not rag_context_hits
                        and not rag_decision.retrieve
                        and not blocked_step_reasons
                        and not memory_overview_query
                        and not memory_forget_requested
                        and memory_write_outcome is None
                        and not long_term_memories
                        and not conversation_memories
                        and not memory_messages
                        and not required_knowledge
                        and "agentmesh" not in req.task.casefold()
                    )
                    if allow_delta and callable(getattr(synthesis_model, "generate_stream", None)):
                        answer = await synthesis_model.generate_stream(
                            synthesis_prompt, model_event, delta_sink,
                        )
                    else:
                        answer = await synthesis_model.generate(
                            synthesis_prompt, model_event,
                        )

                except Exception as exc:

                    synthesis_node.status = (
                        "error"
                    )

                    event(
                        "synthesis",
                        (
                            "Result "
                            "Synthesizer"
                        ),
                        "error",
                        str(exc),
                    )

                    raise

                synthesis_node.status = (
                    "completed"
                )

                event(
                    "synthesis",
                    (
                        "Result "
                        "Synthesizer"
                    ),
                    "completed",
                )

            # =================================================
            # Synthesis Bypass
            # =================================================

            else:

                if (
                    len(parts)
                    == 1
                ):

                    raw_result = (
                        parts[
                            0
                        ]
                    )

                    first_newline = (
                        raw_result.find(
                            "\n"
                        )
                    )

                    if (
                        first_newline
                        >= 0
                    ):

                        answer = (
                            raw_result[
                                first_newline
                                + 1:
                            ]
                        )

                    else:

                        answer = (
                            raw_result
                        )

                else:

                    answer = (
                        "\n\n".join(
                            parts
                        )
                    )

                synthesis_node.status = (
                    "skipped"
                )

                event(
                    "synthesis",
                    (
                        "Result Synthesizer "
                        "Bypassed"
                    ),
                    "completed",
                    json.dumps(
                        {
                            "mode":
                                req
                                .synthesis_mode,

                            "topology":
                                collaboration_plan
                                .topology,

                            "agent_results":
                                len(
                                    parts
                                ),

                            "decision":
                                "bypass",
                        },
                        ensure_ascii=False,
                    ),
                )
            if blocked_step_reasons:
                # Never claim the whole request completed. This output only
                # contains independently executed model-only steps; the
                # missing-policy steps and their dependants have no outputs.
                blocked_labels = [
                    f"- {step.id}: {step.objective}（{blocked_step_reasons[step.id]}）"
                    for step in semantic_plan.steps
                    if step.id in blocked_step_reasons
                ]
                answer = (
                    "仅完成了不依赖缺失知识的独立步骤；整项任务尚未完成。\n\n"
                    + answer + "\n\n以下步骤未执行（缺少已授权证据）：\n"
                    + "\n".join(blocked_labels)
                    + "\n请提供所需资料或调整知识范围后重新发起未完成的步骤。"
                )
                event("rag", "Partial Knowledge Result", "completed",
                      json.dumps({"status": "INSUFFICIENT_EVIDENCE",
                                  "completedSteps": [s.id for s in semantic_plan.steps
                                                     if self.plan_compiler.node_id(s.id)
                                                     in dag_result.outputs],
                                  "blockedSteps": sorted(blocked_step_reasons)}))

            # =================================================
            # 8.03 Conversational Forget Guard
            #
            # Forget is a control command, not a normal content question.
            # The user-visible answer is deterministic so the model cannot
            # claim a deletion happened when it did not.
            # =================================================

            if memory_forget_requested and memory_forget_outcome is not None:
                rag_grounding_policy = ""
                runtime_citations = []

                if memory_forget_outcome.status == "error":
                    answer = "我现在没能完成这次忘记操作，请稍后再试。"
                elif memory_forget_outcome.reason == "memory_forgotten":
                    answer = "好的，我已经忘记这项信息了。"
                elif memory_forget_outcome.reason in {
                    "need_more_specific_request",
                    "ambiguous_memory_match",
                }:
                    answer = "我不确定你想让我忘记哪一项。请再说得具体一点，我会避免误删。"
                else:
                    answer = "我没有找到与你这次请求相符的已保存信息。"

            # =================================================
            # 8.04 Sensitive Memory Request Guard
            #
            # A rejected secret/credential write must also be honest at the
            # user-visible answer layer.  Do not claim that OTP/password/token
            # material was "remembered", and do not echo the supplied value.
            # This guard is intentionally limited to explicit memory requests
            # so normal diagnostic/log questions containing credential-like
            # strings are not hijacked by memory semantics.
            # =================================================

            sensitive_memory_request = False
            if (
                memory_write_outcome is not None
                and memory_write_outcome.status == "skipped"
                and memory_write_outcome.reason == "sensitive_secret"
            ):
                detector = getattr(
                    self.long_term_memory_writer,
                    "detector",
                    None,
                )
                explicit_checker = getattr(
                    detector,
                    "is_explicit_memory_request",
                    None,
                )
                if callable(explicit_checker):
                    sensitive_memory_request = bool(
                        explicit_checker(req.task)
                    )

            if sensitive_memory_request:
                rag_grounding_policy = ""
                runtime_citations = []
                answer = (
                    "这类验证码、密码、Token、API Key 或凭据信息涉及安全，"
                    "我不会保存，也不会在回复中复述你提供的具体值。"
                )
                event(
                    "memory_guard",
                    "Sensitive Memory Request Guard",
                    "completed",
                    json.dumps(
                        {
                            "action": "sensitive_memory_rejected",
                            "reason": "sensitive_secret",
                        },
                        ensure_ascii=False,
                    ),
                )

            # =================================================
            # 8.05 Memory Epistemic Guard
            #
            # Memory-overview questions are grounded only in
            # User-global Long-term Memory (plus explicitly shown
            # Conversation Memory).  Project/RAG evidence and model
            # priors are not evidence that AgentMesh "remembers" a
            # user preference.  If retrieval returned no relevant
            # long-term memory, replace any model guess with a
            # deterministic, truthful answer.
            # =================================================

            if memory_overview_query:
                # Memory meta-questions must never inherit the RAG
                # citation contract or expose Project Knowledge as
                # remembered user context.
                rag_grounding_policy = ""
                runtime_citations = []

                if not long_term_memories:
                    if conversation_memories:
                        # Older same-conversation capsules are legitimate
                        # evidence for "之前说过什么" questions. They are not
                        # user-global memories, so keep the model answer grounded
                        # by those capsules instead of replacing it with a false
                        # "I forgot" response.
                        event(
                            "memory_guard",
                            "Memory Epistemic Guard",
                            "completed",
                            json.dumps(
                                {
                                    "action": "conversation_memory_grounded",
                                    "retrievalReason": memory_retrieval_reason,
                                    "selectedCount": 0,
                                    "conversationMessages": len(memory_messages),
                                    "conversationCapsules": len(conversation_memories),
                                },
                                ensure_ascii=False,
                            ),
                        )
                    else:
                        if memory_messages:
                            answer = (
                                "我目前没有保存你在这方面的偏好。"
                                "如果你刚在当前对话里提到过，我仍会参考这次对话的上下文。"
                            )
                            guard_action = "no_saved_memory_conversation_context_present"
                        else:
                            answer = (
                                "我目前没有记住你在这方面的偏好。"
                                "如果你希望以后都按某种方式处理，直接告诉我就可以。"
                            )
                            guard_action = "no_saved_memory"

                        event(
                            "memory_guard",
                            "Memory Epistemic Guard",
                            "completed",
                            json.dumps(
                                {
                                    "action": guard_action,
                                    "retrievalReason": memory_retrieval_reason,
                                    "selectedCount": 0,
                                    "conversationMessages": len(memory_messages),
                                    "conversationCapsules": 0,
                                },
                                ensure_ascii=False,
                            ),
                        )
                else:
                    remembered = [
                        item.memory.content
                        for item in long_term_memories[:5]
                        if item.memory.content.strip()
                    ]
                    if len(remembered) == 1:
                        answer = f"我记得你提过：{remembered[0]}"
                    else:
                        answer = "我记得你提过这些：\n" + "\n".join(
                            f"- {item}" for item in remembered
                        )

                    event(
                        "memory_guard",
                        "Memory Epistemic Guard",
                        "completed",
                        json.dumps(
                            {
                                "action": "memory_grounded",
                                "retrievalReason": memory_retrieval_reason,
                                "selectedCount": len(long_term_memories),
                            },
                            ensure_ascii=False,
                        ),
                    )

            # =================================================
            # 8.1 Deterministic Grounded Answer Guard
            #
            # v2.0.4C
            #
            # IMPORTANT:
            #
            # Prompt policy is a soft constraint.
            #
            # Therefore the final user-visible answer must
            # pass a deterministic runtime guard before:
            #
            # 1. Conversation Memory persistence
            # 2. RuntimeResponse
            #
            # This protects both output grounding and
            # future memory grounding.
            # =================================================

            if (
                rag_grounding_policy
                == "grounded_partial_only"
            ):

                answer_guard_result = (
                    guard_grounded_answer(
                        task=(
                            req.task
                        ),

                        answer=(
                            answer
                        ),

                        policy=(
                            rag_grounding_policy
                        ),

                        retrieval_hits=(
                            rag_context_hits
                        ),
                    )
                )

                answer = (
                    answer_guard_result
                    .answer
                )

                event(
                    "rag",
                    (
                        "Grounded Answer "
                        "Guard"
                    ),
                    "completed",
                    json.dumps(
                        {
                            "policy":
                                rag_grounding_policy,

                            "passed":
                                answer_guard_result
                                .passed,

                            "action":
                                answer_guard_result
                                .action,

                            "violations":
                                list(
                                    answer_guard_result
                                    .violations
                                ),

                            "contextHits":
                                len(
                                    rag_context_hits
                                ),
                        },
                        ensure_ascii=False,
                    ),
                )

            # =================================================
            # 8.15 AgentMesh Platform Capability Grounding Guard
            #
            # Product-self questions are high-risk for stale model priors:
            # a model can otherwise invent menus, YAML schemas, plugins,
            # hosted domains or a generic "I cannot operate your computer"
            # disclaimer even when request-scoped local.* tools exist.
            # The prompt receives an authoritative capability snapshot above,
            # and this deterministic final guard provides a fail-closed layer
            # before Conversation Memory / RuntimeResponse persistence.
            # =================================================

            platform_guard_result = guard_platform_capability_answer(
                task=req.task,
                answer=answer,
                history=req.history,
                tools=req.tools,
                mcp_servers=req.mcp_servers,
                agents=req.agents,
                selected_tool_names=(
                    capability_plan.selected_tool_names
                ),
                selected_mcp_tool_names=(
                    capability_plan.selected_mcp_tool_names
                ),
            )
            if platform_guard_result.action != "not_applicable":
                answer = platform_guard_result.answer
                event(
                    "capability_grounding",
                    "AgentMesh Platform Capability Grounding Guard",
                    "completed",
                    json.dumps(
                        {
                            "passed": platform_guard_result.passed,
                            "action": platform_guard_result.action,
                            "violations": list(
                                platform_guard_result.violations
                            ),
                        },
                        ensure_ascii=False,
                    ),
                )

            # A REQUIRED evidence obligation is a runtime output contract,
            # not merely a prompt. This guard also covers late knowledge
            # requirements added by the semantic planner. A missing source,
            # an OFF policy, or insufficient evidence cannot be replaced with
            # the model's knowledge of the user's private/project documents.
            required_knowledge = (
                semantic_intent.knowledge_dependency == KnowledgeDependency.REQUIRED
                or (
                    semantic_plan is not None
                    and any(step.knowledge_dependency == "REQUIRED" for step in semantic_plan.steps)
                )
            )
            if required_knowledge and not blocked_step_reasons and (
                not rag_context_hits or rag_grounding_sufficient is False
            ):
                answer = (
                    "本次任务要求依据指定的知识资料，但当前没有足够的已授权证据。"
                    "我无法据此确认相关规则、结论或执行条件；请提供资料，"
                    "或开启并授权对应知识库后重试。"
                )
                runtime_citations = []
                rag_grounding_policy = "insufficiency_only"
                event(
                    "rag", "Required Knowledge Evidence Gate", "completed",
                    json.dumps({
                        "status": "INSUFFICIENT_EVIDENCE",
                        "reason": "required_knowledge_unavailable",
                        "retrievalAttempted": rag_decision.retrieve,
                        "evidenceCount": len(rag_context_hits),
                    }, ensure_ascii=False),
                )

                        # =================================================
            # 8.2 Deterministic Citation Guard
            #
            # v2.0.5C
            #
            # IMPORTANT:
            #
            # Citation-aware prompting is only a soft
            # constraint.
            #
            # Therefore the final answer must pass a
            # deterministic citation validation step before:
            #
            # 1. Conversation Memory persistence
            # 2. RuntimeResponse
            #
            # Runtime policy:
            #
            # grounded_only
            #     Evidence is sufficient.
            #     At least one valid citation is required.
            #
            # grounded_partial_only
            #     Evidence is incomplete.
            #     Citations are optional because a pure
            #     insufficiency answer may legitimately contain
            #     no factual evidence claim.
            #
            #     However, any citation that DOES appear must
            #     resolve to real EvidenceProvenance.
            #
            # NO_RAG / FAST_RAG without Agentic grounding
            #     Do not apply the RAG citation contract.
            #
            # This avoids interpreting ordinary text such as
            # "[1]" as a RAG citation when no RAG citation
            # namespace exists for the request.
            # =================================================

            if (
                rag_grounding_policy
                in {
                    "grounded_only",
                    "grounded_partial_only",
                }
            ):
                citation_provenance = (
                    build_evidence_provenance(
                        rag_context_hits
                    )
                )

                require_citation = (
                    rag_grounding_policy
                    == "grounded_only"
                )

                citation_guard_result = (
                    guard_answer_citations(
                        task=(
                            req.task
                        ),
                        answer=(
                            answer
                        ),
                        provenance=(
                            citation_provenance
                        ),
                        require_citation=(
                            require_citation
                        ),
                    )
                )

                answer = (
                    citation_guard_result
                    .answer
                )

                event(
                    "rag",
                    "Citation Guard",
                    "completed",
                    json.dumps(
                        {
                            "policy":
                                rag_grounding_policy,

                            "requireCitation":
                                require_citation,

                            "passed":
                                citation_guard_result
                                .passed,

                            "action":
                                citation_guard_result
                                .action,

                            "availableCitations": [
                                item
                                .citation_label

                                for item
                                in citation_provenance
                            ],

                            "citations": [
                                (
                                    f"[{citation_id}]"
                                )

                                for citation_id
                                in (
                                    citation_guard_result
                                    .citations
                                )
                            ],

                            "invalidCitations": [
                                (
                                    f"[{citation_id}]"
                                )

                                for citation_id
                                in (
                                    citation_guard_result
                                    .invalid_citations
                                )
                            ],

                            "violations":
                                list(
                                    citation_guard_result
                                    .violations
                                ),

                            "contextHits":
                                len(
                                    rag_context_hits
                                ),
                        },
                        ensure_ascii=False,
                    ),
                )
                            # =============================================
                # v2.0.5D Structured Citation Projection
                #
                # IMPORTANT:
                #
                # Citation Guard answers:
                #
                #     "Are the answer citation references valid?"
                #
                # Citation Projection answers:
                #
                #     "Which validated evidence items were
                #      actually used by the final answer?"
                #
                # Only validated, actually-used citations are
                # exposed through RuntimeResponse.
                #
                # If Citation Guard replaced the original answer
                # with safe_rejection, the replacement answer
                # contains no evidence citations, therefore the
                # public citation list must be empty.
                # =============================================

                if (
                    citation_guard_result
                    .passed
                ):
                    runtime_citations = (
                        project_used_citations(
                            provenance=(
                                citation_provenance
                            ),
                            used_citation_ids=(
                                citation_guard_result
                                .citations
                            ),
                        )
                    )

                else:
                    runtime_citations = []

                event(
                    "rag",
                    (
                        "Citation Provenance "
                        "Projected"
                    ),
                    "completed",
                    json.dumps(
                        {
                            "availableCount":
                                len(
                                    citation_provenance
                                ),

                            "usedCount":
                                len(
                                    runtime_citations
                                ),

                            "citations": [
                                citation
                                .model_dump(
                                    by_alias=True
                                )

                                for citation
                                in runtime_citations
                            ],
                        },
                        ensure_ascii=False,
                    ),
                )
            # =================================================
            # 9. Conversation Memory Write-back
            #
            # 只保存：
            #
            # raw user task
            # final answer
            #
            # 不保存：
            #
            # RAG Context
            # execution context
            # upstream context
            # =================================================

            if (
                req.conversation_id
                is not None
            ):

                try:

                    await self.memory.append(
                        user_id=(
                            req.user_id
                        ),
                        conversation_id=(
                            req
                            .conversation_id
                        ),
                        message=(
                            MemoryMessage(
                                role="user",
                                content=(
                                    req.task
                                ),
                            )
                        ),
                    )

                    await self.memory.append(
                        user_id=(
                            req.user_id
                        ),
                        conversation_id=(
                            req
                            .conversation_id
                        ),
                        message=(
                            MemoryMessage(
                                role="assistant",
                                content=(
                                    answer
                                ),
                            )
                        ),
                    )

                    event(
                        "memory",
                        (
                            "Memory Context "
                            "Saved"
                        ),
                        "completed",
                        json.dumps(
                            {
                                "conversation_id":
                                    req
                                    .conversation_id,

                                "messages_saved":
                                    2,
                            },
                            ensure_ascii=False,
                        ),
                    )

                except Exception as exc:

                    event(
                        "memory",
                        (
                            "Memory Context "
                            "Save Failed"
                        ),
                        "error",
                        str(exc),
                    )

            # LLM compaction is asynchronous and threshold-triggered. It never
            # blocks the user response and is retried on a later turn if it fails.
            if req.conversation_id is not None:
                self.conversation_memory_compactor.schedule(
                    user_id=req.user_id,
                    conversation_id=req.conversation_id,
                    model_gateway=self.rag_intelligence_model,
                    model_name=(
                        settings.conversation_memory_compaction_model_name.strip()
                        or settings.model_name
                    ),
                )

            # =================================================
            # 10. Task Completed
            # =================================================

            event(
                "task",
                "Task Completed",
                "completed",
            )

            # =================================================
            # 11. Observability
            # =================================================

            observability = (
                build_observability_summary(
                    trace=(
                        trace
                    ),
                    feedback=(
                        feedback
                    ),
                    dag=(
                        dag
                    ),
                )
            )

            event(
                "observability",
                (
                    "Runtime Metrics "
                    "Aggregated"
                ),
                "completed",
                json.dumps(
                    observability
                    .model_dump(
                        by_alias=True
                    ),
                    ensure_ascii=False,
                ),
            )

            # =================================================
            # 12. P6 Run Scorecard
            #
            # Eval is isolated from the main task: a scorecard failure becomes
            # an observability event and never flips a successful user task.
            # =================================================

            scorecard = None

            if settings.eval_scorecard_enabled:
                try:
                    scorecard = build_run_scorecard(
                        ScorecardInputs(
                            answer=answer,
                            trace=trace,
                            feedback=feedback,
                            citations=runtime_citations,
                            constraints=req.constraints,
                            elapsed_ms=elapsed(),
                            estimated_cost=estimated_cost,
                            observability=observability,
                            rag_grounding_sufficient=rag_grounding_sufficient,
                        )
                    )

                    event(
                        "eval",
                        "Run Scorecard",
                        "completed",
                        json.dumps(
                            scorecard.model_dump(by_alias=True),
                            ensure_ascii=False,
                        ),
                    )
                except Exception as exc:
                    event(
                        "eval",
                        "Run Scorecard",
                        "error",
                        json.dumps(
                            {
                                "reason": "scorecard_unavailable",
                                "errorType": type(exc).__name__,
                            },
                            ensure_ascii=False,
                        ),
                    )

            # =================================================
            # 13. Runtime Response
            # =================================================

            return RuntimeResponse(
                request_id=(
                    req.request_id
                ),

                status=(
                    "COMPLETED"
                ),

                answer=(
                    answer
                ),

                citations=(
                    runtime_citations
                ),

                continuation=None,

                scheduler=(
                    req.scheduler
                ),

                task_profile=(
                    profile
                ),

                selected_agents=(
                    selected_names
                ),

                estimated_cost=round(
                    estimated_cost,
                    6,
                ),

                elapsed_ms=(
                    elapsed()
                ),

                trace=(
                    trace
                ),

                dag=(
                    dag
                ),

                agent_feedback=(
                    feedback
                ),

                observability=(
                    observability
                ),

                scorecard=scorecard,
            )
