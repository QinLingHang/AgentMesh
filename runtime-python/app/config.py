from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)


class Settings(
    BaseSettings
):
    # =====================================================
    # Runtime
    # =====================================================

    runtime_port: int = 9572

    internal_token: str = (
        "change-me-runtime-internal-token"
    )

    # =====================================================
    # Model
    # =====================================================

    model_provider: str = "mock"

    model_api_key: str = ""

    model_base_url: str = (
        "https://dashscope.aliyuncs.com/"
        "compatible-mode/v1"
    )

    model_name: str = "qwen-plus"

    # Multimodal requests use a vision-capable model on the same provider.
    # DashScope-compatible deployments can keep qwen-plus for normal chat while
    # routing images to qwen-vl-plus.  Override in .env when another provider
    # uses a different model name.
    model_vision_name: str = "qwen-vl-plus"

    model_timeout_seconds: float = 30.0

    model_max_retries: int = 2

    model_http_trust_env: bool = True

    # Optional pricing metadata for Evaluation cost telemetry.  Keep zero when the
    # provider/account pricing is unknown; this never invents a monetary cost.
    model_input_cost_per_million: float = 0.0
    model_output_cost_per_million: float = 0.0

    # Adaptive Routing adaptive Model Router. Extra runtimes are optional and configured as
    # a JSON array. Existing deployments with a single default runtime keep the
    # exact Evaluation behaviour. Example entries are documented in docs/runtime.
    model_router_enabled: bool = True
    model_runtime_pool_json: str = "[]"
    model_routing_default_quality: float = 0.82
    model_routing_default_latency_ms: int = 1200
    model_routing_default_avg_cost: float = 0.0
    model_routing_default_success_rate: float = 1.0

    # Evaluation deterministic evaluation is isolated from the main task: an evaluator
    # failure must not turn a successful Agent task into a failed task.
    eval_scorecard_enabled: bool = True

    # =====================================================
    # Agent / Tool Runtime
    # =====================================================

    http_agent_timeout_seconds: float = 8.0

    tool_timeout_seconds: float = 8.0

    max_tool_iterations: int = 5

    tool_max_retries: int = 1

    tool_retry_backoff_seconds: float = 0.1

    max_reschedule_attempts: int = 2

    # =====================================================
    # Adaptive Workflow Orchestration
    # =====================================================

    # Medium/high-complexity requests can be decomposed into a bounded semantic
    # ExecutionPlan. Invalid/unavailable model output fails safely to the
    # existing deterministic profiler/scheduler path.
    execution_routing_semantic_model_enabled: bool = True
    execution_routing_semantic_model_timeout_seconds: float = 6.0

    semantic_planner_enabled: bool = True
    semantic_planner_timeout_seconds: float = 12.0
    semantic_planner_max_steps: int = 8
    max_replan_attempts: int = 1

    # Runtime quality gate. Heuristic evaluation is deliberately calibrated
    # independently from scheduler min_quality because the two scores have
    # different semantics. Repair/replan stays bounded and side-effect-safe.
    quality_gate_enabled: bool = True
    quality_gate_pass_threshold: float = 0.58
    quality_gate_hard_fail_threshold: float = 0.20
    max_quality_repair_attempts: int = 1

    # LangGraph workflow-local answer repair. Tool routes are evaluated but are
    # never replayed solely for quality because tool execution may have effects.
    langgraph_quality_threshold: float = 0.58
    langgraph_max_repairs: int = 1

    # =====================================================
    # Local Desktop Bridge
    # =====================================================

    # Local Windows Runtime embeds Desktop capability by default, so normal
    # local development does not require a second Desktop Bridge process.
    # Set DESKTOP_EMBEDDED_ENABLED=false to disable local embedded execution.
    desktop_embedded_enabled: bool = True

    # Optional remote/restricted Desktop Bridge transport. When enabled it
    # takes precedence over embedded execution. V4.1 acceptance deliberately
    # uses this path to preserve its explicit Restricted Root isolation proof.
    desktop_bridge_enabled: bool = False
    desktop_bridge_base_url: str = "http://127.0.0.1:9583"
    desktop_bridge_token: str = ""
    desktop_bridge_timeout_seconds: float = 8.0
    desktop_max_tool_iterations: int = 20

    # =====================================================
    # Durable Runtime Distributed Runtime Worker
    # =====================================================

    runtime_worker_enabled: bool = True
    runtime_worker_id: str = "runtime-local-1"
    runtime_worker_endpoint: str = "http://127.0.0.1:9572"
    control_plane_internal_base_url: str = "http://127.0.0.1:8086"
    runtime_worker_capacity: int = 4
    runtime_node_id: str = ""
    runtime_node_zone: str = "local"
    runtime_node_version: str = "3.0.0-dev"
    runtime_node_capacity: int = 0
    runtime_worker_heartbeat_seconds: float = 5.0
    runtime_worker_callback_timeout_seconds: float = 5.0
    runtime_worker_callback_max_retries: int = 5
    runtime_worker_shutdown_grace_seconds: float = 20.0
    runtime_worker_dedupe_retention_seconds: float = 3600.0

    # =====================================================
    # Event Delivery Event Plane / Runtime Result Transport
    # =====================================================

    # http preserves the Durable Runtime callback path. kafka persists results into a local
    # SQLite outbox first, then publishes runtime.execution.result events.
    runtime_result_transport: str = "http"
    kafka_brokers: str = "127.0.0.1:29092"
    kafka_runtime_result_topic: str = "agentmesh.runtime.events"
    kafka_client_id: str = "agentmesh-runtime-python"
    kafka_outbox_path: str = "./data/runtime_result_outbox.sqlite3"
    kafka_publish_timeout_seconds: float = 10.0

        # =====================================================
    # A2A Agent
    # =====================================================

    a2a_timeout_seconds: float = 15.0

    a2a_http_trust_env: bool = False

    # v1.9.1:
    # 先走 non-streaming message/send。
    #
    # v1.9.4 再开启完整 streaming task lifecycle。
    a2a_streaming: bool = False

    a2a_discovery_cache_ttl_seconds: float = 300.0

    # =====================================================
    # Memory
    # =====================================================

    memory_backend: str = "redis"

    redis_url: str = (
        "redis://127.0.0.1:6382/0"
    )

    memory_key_prefix: str = (
        "agentmesh:memory"
    )

    # Runtime-only short-term cache. This does NOT cap or delete durable
    # conversation history; MySQL messages remain the source of truth.
    memory_max_messages: int = 20

    # 7 days (cache TTL only; never a conversation-history retention policy)
    memory_ttl_seconds: int = (
        7 * 24 * 60 * 60
    )

    # =====================================================
    # User-global Long-term Memory Auto Write (memory write policy)
    # =====================================================

    memory_auto_write_enabled: bool = True

    memory_auto_inference_enabled: bool = True

    memory_auto_write_timeout_seconds: float = 5.0

    memory_auto_write_max_items: int = 3

    # =====================================================
    # User-global Long-term Memory Retrieval (memory retrieval)
    # =====================================================

    memory_retrieval_enabled: bool = True

    memory_retrieval_timeout_seconds: float = 5.0

    memory_retrieval_candidate_limit: int = 100

    memory_retrieval_top_k: int = 6

    memory_retrieval_min_score: float = 0.28

    # Independent from Project Knowledge RAG.  Hash is the deterministic
    # local default; openai_compatible can reuse the existing embedding
    # provider settings when semantic quality is desired.
    memory_retrieval_embedding_backend: str = "hash"

    memory_retrieval_semantic_weight: float = 0.40
    memory_retrieval_lexical_weight: float = 0.25
    memory_retrieval_confidence_weight: float = 0.10
    memory_retrieval_authority_weight: float = 0.10
    memory_retrieval_relevance_weight: float = 0.15

    # =====================================================
    # Conversation Memory Compression / Selective Recall
    # =====================================================

    # Raw Redis memory remains a small working-memory window. Older turns are
    # compressed into durable MySQL capsules only when enough completed history
    # exists, so ordinary requests do not pay an extra LLM call.
    conversation_memory_compaction_enabled: bool = True
    conversation_memory_compaction_min_messages: int = 12
    conversation_memory_compaction_max_messages: int = 18
    conversation_memory_compaction_reserve_recent: int = 16
    conversation_memory_compaction_min_input_chars: int = 1200
    conversation_memory_compaction_max_input_chars: int = 10000
    conversation_memory_compaction_max_output_tokens: int = 600
    conversation_memory_compaction_timeout_seconds: float = 12.0
    conversation_memory_compaction_failure_backoff_seconds: float = 60.0
    conversation_memory_compaction_lock_ttl_seconds: int = 45
    conversation_memory_compaction_lock_prefix: str = "agentmesh:conversation-memory:compact-lock"

    # Optional cheaper model for memory compression. Empty means reuse the
    # request/default model; operators can point this at a low-cost model.
    conversation_memory_compaction_model_name: str = ""

    # Retrieval is local/deterministic (hash semantic + lexical + importance +
    # recency), so selecting old memory adds no paid model call.
    conversation_memory_retrieval_enabled: bool = True
    conversation_memory_retrieval_candidate_limit: int = 80
    conversation_memory_retrieval_top_k: int = 3
    conversation_memory_retrieval_min_score: float = 0.12
    conversation_memory_retrieval_max_chars: int = 3200


        # =====================================================
    # RAG / Milvus
    # =====================================================

    rag_candidate_k: int = 8

    rag_rrf_k: int = 60

    milvus_hybrid_collection: str = (
        "agentmesh_knowledge_hybrid_v1"
    )

    rag_backend: str = "hybrid_milvus"

    rag_top_k: int = 3

    milvus_uri: str = (
        "http://127.0.0.1:19530"
    )

    milvus_collection: str = (
        "agentmesh_knowledge_256_v1"
    )



        # =====================================================
    # Reranker
    # =====================================================

    reranker_backend: str = "qwen"

    reranker_model: str = (
        "qwen3-rerank"
    )

    reranker_api_key: str = ""

    reranker_base_url: str = (
        "https://dashscope.aliyuncs.com/"
        "compatible-api/v1"
    )

    reranker_timeout_seconds: float = 20.0

    reranker_http_trust_env: bool = True

    reranker_instruct: str = (
        "Given a web search query, "
        "retrieve relevant passages "
        "that answer the query."
    )

    # =====================================================
    # Embedding
    # =====================================================

    embedding_backend: str = "hash"

    embedding_dimension: int = 256

    embedding_model: str = (
        "text-embedding-v4"
    )

    embedding_api_key: str = ""

    embedding_base_url: str = (
        "https://dashscope.aliyuncs.com/"
        "compatible-mode/v1"
    )

    embedding_http_trust_env: bool = True

    # =====================================================
    # Settings
    # =====================================================

    model_config = (
        SettingsConfigDict(
            env_file=".env",
            extra="ignore",
        )
    )


settings = Settings()
