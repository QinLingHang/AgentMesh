import asyncio
import json

import httpx
import pytest

from app.memory.long_term import (
    AutomaticLongTermMemoryWriter,
    ControlPlaneLongTermMemorySink,
    LongTermMemoryCandidate,
    MemoryCandidateDetector,
    MemoryWriteRecord,
    ModelBackedMemoryExtractor,
)
from app.models.contracts import ModelResponse
from app.schemas import AgentProfile, RuntimeContinuation, RuntimeRequest
from app.services import RuntimeEngine, create_registry


class RecordingSink:
    def __init__(self):
        self.calls = []

    async def upsert(self, *, user_id, candidate):
        self.calls.append((user_id, candidate))
        return MemoryWriteRecord("created", len(self.calls), candidate.memory_key, candidate.category)


class Gateway:
    def __init__(self, content=None, error=None, delay=0):
        self.content, self.error, self.delay, self.requests = content, error, delay, []

    async def generate(self, request):
        self.requests.append(request)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return ModelResponse(content=self.content, provider="fixture", model=request.model,
                             input_tokens=1, output_tokens=1, total_tokens=2,
                             latency_ms=1, finish_reason="stop", estimated_cost=0)


@pytest.mark.parametrize("text,source", [
    ("以后写 Go 代码时尽量和 Java 对比讲解", "explicit_user"),
    ("请记住：界面优先使用中文", "explicit_user"),
    ("我更倾向 Agent 开发岗位", "inferred_user"),
])
def test_p32_candidate_detection(text, source):
    detected = MemoryCandidateDetector().detect(text)
    assert detected.should_extract and detected.source_type == source


@pytest.mark.parametrize("text", [
    "解释一下 Go interface",
    "以后会怎样？",
    "以后我应该学习 Go 吗？",
    "今天先用这种格式。",
    "本项目数据库使用 PostgreSQL",
    "请记住这个项目的内部代号 Apollo",
])
def test_p32_non_durable_and_project_local_statements_are_skipped(text):
    detected = MemoryCandidateDetector().detect(text)
    assert not detected.should_extract


@pytest.mark.parametrize("text", [
    "记住我的 password: abc123", "记住 api_key=sk-abcdefghijklm",
    "记住 access token: token-value", "记住 secret: hidden-value",
    "记住验证码：123456", "记住 OTP: 654321",
    "记住 credential: admin:abc123", "记住 -----BEGIN PRIVATE KEY----- abc",
    "记住凭证：admin:abc123", "记住认证信息：bearer-secret",
])
@pytest.mark.asyncio
async def test_p32_sensitive_values_never_reach_sink_or_trace(text):
    sink = RecordingSink()
    outcome = await AutomaticLongTermMemoryWriter(sink=sink).process(user_id=7, text=text)
    assert outcome.status == "skipped"
    assert not sink.calls
    detail = json.dumps(outcome.trace_detail(), ensure_ascii=False)
    assert "abc123" not in detail and "123456" not in detail and "654321" not in detail
    assert "token-value" not in detail and "hidden-value" not in detail


@pytest.mark.asyncio
async def test_p32_global_project_wording_is_allowed_but_only_direct_text_is_sent():
    sink = RecordingSink()
    text = "以后所有项目的代码讲解都和 Java 对比"
    outcome = await AutomaticLongTermMemoryWriter(sink=sink).process(user_id=17, text=text)
    assert outcome.status == "completed" and outcome.extractor == "rule"
    assert sink.calls[0][0] == 17
    assert sink.calls[0][1].content == "所有项目的代码讲解都和 Java 对比"


@pytest.mark.asyncio
async def test_p32_model_backed_inference_and_candidate_safety_filter():
    gateway = Gateway(json.dumps({"items": [
        {"category": "goal", "memory_key": "goal.career.target_role",
         "content": "用户倾向 Agent 开发岗位", "confidence": .87},
        {"category": "fact", "memory_key": "project.database",
         "content": "PostgreSQL", "confidence": .9},
        {"category": "fact", "memory_key": "bad key",
         "content": "invalid", "confidence": .9},
        {"category": "fact", "memory_key": "secret.password",
         "content": "abc123", "confidence": .9},
    ]}, ensure_ascii=False))
    sink = RecordingSink()
    writer = AutomaticLongTermMemoryWriter(
        sink=sink, model_extractor=ModelBackedMemoryExtractor(gateway, model_name="fixture")
    )
    outcome = await writer.process(user_id=7, text="我更倾向 Agent 开发岗位")
    assert outcome.status == "completed" and outcome.extractor == "model"
    assert outcome.candidate_count == 1
    assert len(sink.calls) == 1
    candidate = sink.calls[0][1]
    assert candidate.source_type == "inferred_user"
    assert candidate.memory_key == "goal.career.target_role"
    # The model sees only the direct user string, never RAG/tool/MCP/assistant data.
    assert gateway.requests[0].messages[-1].content == "我更倾向 Agent 开发岗位"


@pytest.mark.parametrize("content", ["not-json", "null", "[]", '{"items": null}'])
@pytest.mark.asyncio
async def test_p32_invalid_or_none_model_output_falls_back(content):
    sink = RecordingSink()
    writer = AutomaticLongTermMemoryWriter(
        sink=sink, model_extractor=ModelBackedMemoryExtractor(Gateway(content), model_name="fixture")
    )
    outcome = await writer.process(user_id=7, text="我更倾向 Agent 开发岗位")
    assert outcome.status == "completed"
    assert outcome.extractor == "rule_fallback"
    assert sink.calls and sink.calls[0][1].source_type == "inferred_user"


@pytest.mark.asyncio
async def test_p32_model_exception_and_timeout_fall_back():
    for gateway in (Gateway(error=RuntimeError("model failed")), Gateway(delay=.05)):
        extractor = ModelBackedMemoryExtractor(gateway, model_name="fixture")
        if gateway.delay:
            class TimedExtractor:
                async def extract(self, *, text):
                    return await asyncio.wait_for(extractor.extract(text=text), timeout=.001)
            model_extractor = TimedExtractor()
        else:
            model_extractor = extractor
        sink = RecordingSink()
        outcome = await AutomaticLongTermMemoryWriter(
            sink=sink, model_extractor=model_extractor
        ).process(user_id=7, text="我更倾向 Agent 开发岗位")
        assert outcome.status == "completed" and outcome.extractor == "rule_fallback"
        assert len(sink.calls) == 1


@pytest.mark.asyncio
async def test_p32_control_plane_500_and_connection_failure_are_error_outcomes():
    async def fail(request):
        return httpx.Response(500, request=request)

    class TransportSink(ControlPlaneLongTermMemorySink):
        async def upsert(self, *, user_id, candidate):
            async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
                response = await client.post("http://control/internal", json={})
                response.raise_for_status()

    candidate_text = "请记住：界面优先使用中文"
    for sink in (TransportSink(internal_token="fixture"),
                 ControlPlaneLongTermMemorySink(internal_token="fixture", base_url="http://127.0.0.1:1", timeout_seconds=.05)):
        outcome = await AutomaticLongTermMemoryWriter(sink=sink).process(user_id=7, text=candidate_text)
        assert outcome.status == "error"
        assert outcome.candidate_count == 1 and not outcome.records


def internal_agent():
    return AgentProfile(id=1, name="General", endpoint="internal://general",
                        protocol="internal", capabilities=["general"], provider="mock")


@pytest.mark.asyncio
async def test_p32_runtime_failure_isolation_trace_order_and_input_boundary():
    class ErrorSink:
        async def upsert(self, **kwargs):
            raise httpx.HTTPStatusError("fixture 500", request=httpx.Request("POST", "http://control"),
                                        response=httpx.Response(500))

    registry = await create_registry()
    try:
        engine = RuntimeEngine(registry)
        engine.long_term_memory_writer = AutomaticLongTermMemoryWriter(sink=ErrorSink())
        result = await engine.run(RuntimeRequest(user_id=8, request_id="p32-failure",
                                  task="请记住：界面优先使用中文", agents=[internal_agent()]))
        assert result.status == "COMPLETED" and result.answer
        assert result.trace[0].kind == "task"
        event = next(item for item in result.trace if item.kind == "memory_write")
        assert event.status == "error"
        assert "请记住" not in event.detail and "界面优先" not in event.detail
    finally:
        await registry.stop_all()


@pytest.mark.asyncio
async def test_p32_runtime_only_passes_raw_user_input_to_writer():
    class WriterSpy:
        def __init__(self): self.calls = []
        async def process(self, **kwargs):
            self.calls.append(kwargs)
            from app.memory.long_term import AutomaticMemoryWriteOutcome
            return AutomaticMemoryWriteOutcome("skipped", "fixture")

    registry = await create_registry()
    try:
        engine = RuntimeEngine(registry)
        spy = WriterSpy()
        engine.long_term_memory_writer = spy
        direct = "普通用户输入；不得附加 RAG Evidence Citation Tool Result MCP Result Assistant Answer"
        result = await engine.run(RuntimeRequest(user_id=9, request_id="p32-source",
                                  task=direct, agents=[internal_agent()]))
        assert result.status == "COMPLETED"
        assert spy.calls == [{"user_id": 9, "text": direct}]
        assert result.trace[0].kind == "task"
    finally:
        await registry.stop_all()


@pytest.mark.asyncio
async def test_p32_resume_never_invokes_writer_for_otp_or_auth_input():
    class WriterSpy:
        def __init__(self): self.calls = []
        async def process(self, **kwargs): self.calls.append(kwargs); raise AssertionError("writer invoked")

    registry = await create_registry()
    try:
        engine = RuntimeEngine(registry)
        spy = WriterSpy()
        engine.long_term_memory_writer = spy
        request = RuntimeRequest(
            user_id=9, request_id="p32-resume", task="验证码 123456，token=secret-token",
            continuation=RuntimeContinuation(protocol="invalid", agentId=1, capability="general",
                                             taskId="fixture", contextId="fixture", state="AUTH_REQUIRED"),
            agents=[internal_agent()],
        )
        with pytest.raises(RuntimeError, match="unsupported runtime continuation protocol"):
            await engine.run(request)
        assert spy.calls == []
    finally:
        await registry.stop_all()


@pytest.mark.parametrize("text", [
    "记住 OTP: 654321",
    "记住 credential: admin:abc123",
])
@pytest.mark.asyncio
async def test_p32_sensitive_memory_request_answer_is_truthful_and_redacted(text):
    registry = await create_registry()
    try:
        engine = RuntimeEngine(registry)
        engine.long_term_memory_writer = AutomaticLongTermMemoryWriter(
            sink=RecordingSink()
        )
        result = await engine.run(
            RuntimeRequest(
                user_id=12,
                request_id="p32-sensitive-answer",
                task=text,
                agents=[internal_agent()],
            )
        )
        assert result.status == "COMPLETED"
        assert "我不会保存" in result.answer
        assert "长期记忆" not in result.answer
        assert "654321" not in result.answer
        assert "admin:abc123" not in result.answer
        guard = next(
            item for item in result.trace
            if item.kind == "memory_guard"
            and "sensitive_memory_rejected" in item.detail
        )
        assert "654321" not in guard.detail
        assert "admin:abc123" not in guard.detail
    finally:
        await registry.stop_all()


@pytest.mark.asyncio
async def test_p32_non_memory_secret_like_diagnostic_question_is_not_hijacked():
    registry = await create_registry()
    try:
        engine = RuntimeEngine(registry)
        engine.long_term_memory_writer = AutomaticLongTermMemoryWriter(
            sink=RecordingSink()
        )
        result = await engine.run(
            RuntimeRequest(
                user_id=12,
                request_id="p32-sensitive-diagnostic",
                task="分析这段日志为什么失败：credential: admin:abc123",
                agents=[internal_agent()],
            )
        )
        assert result.status == "COMPLETED"
        assert not any(
            item.kind == "memory_guard"
            and "sensitive_memory_rejected" in item.detail
            for item in result.trace
        )
    finally:
        await registry.stop_all()
