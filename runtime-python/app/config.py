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

    # Optional pricing metadata for P6 cost telemetry.  Keep zero when the
    # provider/account pricing is unknown; this never invents a monetary cost.
    model_input_cost_per_million: float = 0.0
    model_output_cost_per_million: float = 0.0

    # P7 adaptive Model Router. Extra runtimes are optional and configured as
    # a JSON array. Existing deployments with a single default runtime keep the
    # exact P1-P6 behaviour. Example entries are documented in docs/p7.
    model_router_enabled: bool = True
    model_runtime_pool_json: str = "[]"
    model_routing_default_quality: float = 0.82
    model_routing_default_latency_ms: int = 1200
    model_routing_default_avg_cost: float = 0.0
    model_routing_default_success_rate: float = 1.0

    # P6 deterministic evaluation is isolated from the main task: an evaluator
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
    # P8 Distributed Runtime Worker
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

    memory_max_messages: int = 20

    # 7 days
    memory_ttl_seconds: int = (
        7 * 24 * 60 * 60
    )

    # =====================================================
    # User-global Long-term Memory Auto Write (P3.2)
    # =====================================================

    memory_auto_write_enabled: bool = True

    memory_auto_inference_enabled: bool = True

    memory_auto_write_timeout_seconds: float = 5.0

    memory_auto_write_max_items: int = 3

    # =====================================================
    # User-global Long-term Memory Retrieval (P3.3)
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