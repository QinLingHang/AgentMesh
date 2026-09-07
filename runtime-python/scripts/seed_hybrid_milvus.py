import asyncio

from app.config import (
    settings,
)

from app.rag import (
    HashEmbeddingProvider,
    HybridMilvusRetriever,
    OpenAICompatibleEmbeddingProvider,
    chunk_text,
)


def create_embedding():
    backend = (
        settings
        .embedding_backend
        .strip()
        .lower()
    )

    if (
        backend
        == "openai_compatible"
    ):
        return (
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

    return (
        HashEmbeddingProvider(
            dimension=(
                settings
                .embedding_dimension
            )
        )
    )


async def main():
    embedding = (
        create_embedding()
    )

    retriever = (
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
        )
    )

    documents = []

    knowledge = [
        (
            "agentmesh-architecture",
            """
AgentMesh Runtime 是企业级异构智能体运行与自适应协作优化平台。
平台采用 Go Control Plane、Python Intelligence Runtime
以及 React 前端架构。
系统支持 Agent Registry、Capability Profile、
Adaptive Scheduler、Multi-objective Collaboration Planner、
Dynamic DAG 和 Runtime Rescheduler。
""",
        ),

        (
            "agentmesh-deployment",
            """
AgentMesh 项目正式生产部署时推荐使用华东区域。
生产环境应将 Go Control Plane、Python Runtime、
MySQL、Redis、Milvus 进行容器化部署，并通过 Nginx
和 HTTPS 对外提供服务。
""",
        ),

        (
            "agentmesh-rag",
            """
AgentMesh 的知识检索模块使用 Milvus。
系统支持 Dense Vector Search、BM25 Full-text Search、
RRF Fusion 以及后置 Reranker。
混合检索用于同时解决语义匹配与关键词精确匹配问题。
""",
        ),

        (
            "agentmesh-mcp",
            """
AgentMesh 使用 MCP 对外部工具能力进行统一接入。
Runtime 包含 MCP Discovery Failure Backoff、
Tool Governance、Risk Level 和 Human-in-the-loop
审批基础能力。
""",
        ),
    ]

    for (
        source,
        text,
    ) in knowledge:

        documents.extend(
            chunk_text(
                text=(
                    text.strip()
                ),

                source=(
                    source
                ),

                metadata={
                    "userId": 1,
                    "documentType":
                        "agentmesh-demo",
                },

                chunk_size=500,

                overlap=100,
            )
        )

    count = (
        await retriever
        .upsert_documents(
            documents
        )
    )

    print(
        "Inserted chunks:",
        count,
    )

    queries = [
        (
            "AgentMesh 推荐部署在哪个区域？"
        ),

        (
            "这个平台上线时"
            "地理位置应该怎么选？"
        ),

        (
            "AgentMesh 的 RAG "
            "使用什么检索方式？"
        ),

        (
            "MCP 出现连续发现失败"
            "之后怎么处理？"
        ),
    ]

    for query in queries:
        print(
            "\n================================"
        )

        print(
            "Query:",
            query,
        )

        hits = (
            await retriever.retrieve(
                query,

                top_k=3,

                filters={
                    "userId": 1
                },
            )
        )

        for (
            index,
            hit,
        ) in enumerate(
            hits,
            start=1,
        ):

            print(
                f"\nHit #{index}"
            )

            print(
                "final score:",
                round(
                    hit.score,
                    6,
                ),
            )

            print(
                "source:",
                hit.document.source,
            )

            print(
                "metadata:",
                hit.document.metadata,
            )

            print(
                "text:",
                hit.document.text,
            )

    await (
        retriever
        .aclose()
    )


if __name__ == "__main__":
    asyncio.run(
        main()
    )