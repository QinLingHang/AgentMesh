import pytest
from app.schemas import AgentProfile, RuntimeRequest, TaskConstraints
from app.services import RuntimeEngine, create_registry, profile_task

def agent(id: int, name: str, endpoint: str, caps: list[str], quality=.9, latency=1000, cost=.01, success=.95):
    return AgentProfile(
        id=id,
        name=name,
        endpoint=endpoint,
        protocol="internal",
        capabilities=caps,
        provider="mock",
        qualityScore=quality,
        avgLatencyMs=latency,
        avgCost=cost,
        successRate=success,
    )

def test_profiler_multiple_capabilities():
    p = profile_task("请根据PDF和CSV数据分析异常")
    assert "document" in p.required_capabilities
    assert "data" in p.required_capabilities
    assert "diagnostic" in p.required_capabilities

@pytest.mark.asyncio
async def test_runtime_parallel_and_fallback():
    registry = await create_registry()
    try:
        engine = RuntimeEngine(registry)
        req = RuntimeRequest(
            user_id=1,
            request_id="req-test",
            task="请根据PDF和CSV数据分析",
            scheduler="greedy",
            constraints=TaskConstraints(maxLatencyMs=8000, maxCost=.15, minQuality=.8),
            agents=[
                agent(1, "DocumentAgent", "internal://document", ["document"], .93, 1500, .02, .96),
                agent(2, "DataPrimary", "internal://fail/data", ["data"], .97, 800, .01, .98),
                agent(3, "DataBackup", "internal://data", ["data"], .90, 1200, .015, .95),
                agent(4, "General", "internal://general", ["general"], .80, 600, .005, .99),
            ],
        )
        result = await engine.run(req)
        assert result.answer
        assert "DataPrimary" in result.selected_agents
        assert "DataBackup" in result.selected_agents
        assert any(x.kind == "reschedule" and x.status == "completed" for x in result.trace)
        assert any(not f.success for f in result.agent_feedback)
        assert any(f.success and f.agent_id == 3 for f in result.agent_feedback)
        assert any(x.kind == "model" and x.title == "Model Call Started" for x in result.trace)
        assert any(x.kind == "model" and x.title == "Model Call Completed" for x in result.trace)
    finally:
        await registry.stop_all()

@pytest.mark.asyncio
async def test_plugins_ready():
    registry = await create_registry()
    try:
        info = registry.info()
        assert any(x["id"] == "scheduler.greedy" and x["status"] == "ready" for x in info)
        assert any(x["id"].startswith("model.") for x in info)
    finally:
        await registry.stop_all()
