from __future__ import annotations

import pytest
from mcp.server import MCPServer

from app.mcp import MCPServerDefinition
from app.rag.runtime import RetrievalDocument, RetrievalHit
from app.schemas import AgentProfile, InteractiveMessage, RuntimeRequest
from app.services import RuntimeEngine, create_registry
from app.tools import ToolDefinition


def _agent(
    agent_id: int,
    name: str,
    capabilities: list[str],
) -> AgentProfile:
    return AgentProfile(
        id=agent_id,
        name=name,
        endpoint=f"internal://{name.casefold().replace(' ', '-')}",
        protocol="internal",
        capabilities=capabilities,
        provider="mock",
        qualityScore=0.95,
        avgLatencyMs=100,
        avgCost=0.001,
        successRate=0.99,
    )


def _calculator_definition() -> ToolDefinition:
    return ToolDefinition(
        id=1,
        name="calculator",
        description="Safely evaluate a mathematical expression.",
        protocol="internal",
        inputSchema={
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
            "additionalProperties": False,
        },
        enabled=True,
    )


def _weather_mcp() -> MCPServer:
    server = MCPServer("v4-1-weather")

    @server.tool()
    def lookup_weather(city: str) -> dict:
        return {"city": city, "condition": "sunny", "temperatureC": 23}

    return server


@pytest.mark.asyncio
async def test_natural_calculation_discovers_and_executes_tool_without_tool_name():
    registry = await create_registry()
    try:
        result = await RuntimeEngine(registry).run(
            RuntimeRequest(
                user_id=1,
                request_id="v4-1-auto-tool",
                task="帮我算一下 382 * 927 是多少？",
                agents=[_agent(1, "General", ["general"])],
                tools=[_calculator_definition()],
            )
        )

        discovery = [event for event in result.trace if event.kind == "capability_discovery"]
        completed = [
            event
            for event in result.trace
            if event.kind == "tool" and event.title == "Tool Completed"
        ]

        assert discovery
        assert completed
        assert any('"tool":"calculator"' in event.detail.replace(" ", "") for event in completed)
        assert any("354114" in event.detail for event in completed)
    finally:
        await registry.stop_all()


@pytest.mark.asyncio
async def test_natural_weather_request_discovers_mcp_and_executes_remote_tool_without_mcp_words():
    registry = await create_registry()
    try:
        server = MCPServerDefinition(
            id=44,
            name="Weather Service",
            transport="streamable_http",
            endpoint="http://unused/weather",
            enabled=True,
        )
        result = await RuntimeEngine(
            registry,
            mcp_targets={44: _weather_mcp()},
        ).run(
            RuntimeRequest(
                user_id=1,
                request_id="v4-1-auto-mcp",
                task="Check the current weather in Shenyang.",
                agents=[_agent(1, "General", ["general"])],
                mcp_servers=[server],
            )
        )

        titles = [event.title for event in result.trace]
        assert "Autonomous Capability Discovery" in titles
        assert "MCP Discovery Completed" in titles
        assert "MCP Capability Discovery" in titles
        assert "MCP Call Completed" in titles
        assert "Tool Completed" in titles
    finally:
        await registry.stop_all()


@pytest.mark.asyncio
async def test_natural_code_review_discovers_agent_skill_and_scheduler_routes_to_matching_agent():
    registry = await create_registry()
    try:
        result = await RuntimeEngine(registry).run(
            RuntimeRequest(
                user_id=1,
                request_id="v4-1-auto-skill",
                task="帮我审查这段代码，找出明显缺陷和潜在 bug。",
                agents=[
                    _agent(1, "Code Reviewer", ["general", "code_review"]),
                    _agent(2, "Writer", ["general", "copywriting"]),
                ],
                scheduler="capability",
            )
        )

        skill_events = [
            event
            for event in result.trace
            if event.kind == "capability_discovery" and event.title == "Agent Skill Discovery"
        ]
        assert skill_events
        assert any("code_review" in event.detail for event in skill_events)
        assert "Code Reviewer" in result.selected_agents
    finally:
        await registry.stop_all()


class _ProjectRetriever:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def retrieve(self, query: str, *, top_k: int = 5, filters: dict | None = None):
        self.calls.append({"query": query, "top_k": top_k, "filters": filters})
        return [
            RetrievalHit(
                document=RetrievalDocument(
                    id="project-byok",
                    text="AgentMesh Project governance stores BYOK configuration under project governance scope.",
                    source="project-docs",
                    metadata={"knowledgeBaseId": 9},
                ),
                score=0.96,
            )
        ]


@pytest.mark.asyncio
async def test_project_specific_question_discovers_knowledge_without_saying_knowledge_base():
    registry = await create_registry()
    retriever = _ProjectRetriever()
    try:
        result = await RuntimeEngine(registry, retriever=retriever).run(
            RuntimeRequest(
                user_id=1,
                request_id="v4-1-auto-knowledge",
                ragPolicy={"mode": "ON", "scopes": ["PROJECT"]},
                effectiveRagPolicy={
                    "mode": "ON", "allowedScopes": ["PROJECT"],
                    "allowedKnowledgeBaseIds": [9],
                },
                knowledgeCatalog=[{
                    "knowledgeBaseId": 9, "name": "AgentMesh Project BYOK 设计实现",
                    "scope": "PROJECT", "accessible": True,
                }],
                task="AgentMesh Project BYOK 是怎么设计和实现的？",
                agents=[_agent(1, "General", ["general"])],
            )
        )

        assert retriever.calls
        discovery = [event for event in result.trace if event.kind == "capability_discovery"]
        assert discovery
        assert any('"projectKnowledge":true' in event.detail.replace(" ", "") for event in discovery)
        assert any(event.kind == "rag" and "Retrieval" in event.title for event in result.trace)
    finally:
        await registry.stop_all()

@pytest.mark.asyncio
async def test_knowledge_continuation_retrieves_previous_topic_instead_of_bare_followup():
    registry = await create_registry()
    retriever = _ProjectRetriever()
    try:
        await RuntimeEngine(registry, retriever=retriever).run(
            RuntimeRequest(
                user_id=1,
                request_id="v4-1-knowledge-continuation",
                ragPolicy={"mode": "ON", "scopes": ["PROJECT"]},
                effectiveRagPolicy={
                    "mode": "ON", "allowedScopes": ["PROJECT"],
                    "allowedKnowledgeBaseIds": [9],
                },
                knowledgeCatalog=[{
                    "knowledgeBaseId": 9, "name": "AgentMesh Project BYOK 设计实现",
                    "scope": "PROJECT", "accessible": True,
                }],
                conversationId=86,
                task="展开讲讲",
                history=[
                    InteractiveMessage(
                        role="user",
                        content="AgentMesh Project BYOK 是怎么设计和实现的？",
                    ),
                    InteractiveMessage(
                        role="assistant",
                        content="我可以继续从实现链路展开。",
                    ),
                ],
                agents=[_agent(1, "General", ["general"])],
            )
        )

        assert retriever.calls
        assert "AgentMesh Project BYOK" in retriever.calls[0]["query"]
        assert retriever.calls[0]["query"] != "展开讲讲"
    finally:
        await registry.stop_all()

