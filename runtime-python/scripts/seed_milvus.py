import asyncio

from app.config import (
    settings,
)

from app.rag import (
    HashEmbeddingProvider,
    MilvusRetriever,
    RetrievalDocument,
    chunk_text,
)


async def main():
    embedding = (
        HashEmbeddingProvider(
            dimension=(
                settings
                .embedding_dimension
            )
        )
    )

    retriever = (
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

    text = """
AgentMesh Runtime 是一个企业级异构智能体运行与自适应协作优化平台。

平台采用 Go Control Plane、Python Intelligence Runtime 和 React 前端架构。

AgentMesh 支持 Agent Registry、Capability Profile、Adaptive Scheduler、
Multi-objective Collaboration Planner、Dynamic DAG、Runtime Rescheduler、
Tool Calling、MCP、Eval、Observability、Redis Conversation Memory
以及 Milvus 知识检索。

AgentMesh 项目的推荐生产部署区域是华东。

对于多 Agent 任务，Runtime 可以根据质量、可靠性、延迟、成本和负载
选择执行 Agent 以及协作拓扑。
""".strip()

    documents = (
        chunk_text(
            text=text,

            source=(
                "agentmesh-demo-doc"
            ),

            metadata={
                "userId": 1,

                "documentType":
                    "demo",
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
        f"Inserted chunks: {count}"
    )

    hits = (
        await retriever
        .retrieve(
            (
                "AgentMesh 推荐部署在哪里？"
            ),

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
            "score:",
            hit.score,
        )

        print(
            "source:",
            hit.document.source,
        )

        print(
            "text:",
            hit.document.text,
        )

    await retriever.aclose()


if __name__ == "__main__":
    asyncio.run(
        main()
    )