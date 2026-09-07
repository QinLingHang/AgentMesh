import asyncio
import json
import re
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any
from app.models.contracts import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCall,
)
from app.models.errors import ModelError, ModelErrorType
import httpx

class MockModelProvider:
    name = "mock"
    async def generate(self, request: ModelRequest) -> ModelResponse:
        started = time.perf_counter()
        await asyncio.sleep(0.02)
        prompt = " ".join(request.messages[-1].content.split())
        observation = next((m.content for m in reversed(request.messages) if m.role == "tool"), None)
        calls: list[ToolCall] = []
        if observation is None and request.tools:
            lower = " ".join(m.content.lower() for m in request.messages if m.role == "user")
            rules = (("logistics", "get_logistics"), ("物流", "get_logistics"), ("diagnose", "diagnose_service"), ("诊断", "diagnose_service"), ("order", "get_order"), ("订单", "get_order"))
            available = {t.name for t in request.tools}
            name = next((tool for keyword, tool in rules if keyword in lower and tool in available), None)
            arguments = {"query": prompt[:200]}

            if name is None and "calculator" in available and (
                "计算" in lower
                or "calculate" in lower
                or "calculator" in lower
                or re.search(r"\d\s*[+\-*/%]\s*\d", lower)
            ):
                expression_match = re.search(
                    r"(?<![\w.])[-+]?\d+(?:\.\d+)?(?:\s*(?:\*\*|//|[+\-*/%])\s*[-+]?\d+(?:\.\d+)?)+",
                    prompt,
                )
                name = "calculator"
                arguments = {
                    "expression": expression_match.group(0) if expression_match else "1+1"
                }

            if name is None and "current_time" in available and any(
                keyword in lower
                for keyword in ("current time", "what time", "date", "几点", "时间", "日期")
            ):
                name = "current_time"
                timezone = "Asia/Shanghai" if any(
                    keyword in lower for keyword in ("beijing", "shanghai", "北京", "上海", "中国")
                ) else "UTC"
                arguments = {"timezone": timezone}

            if name is None and "text_stats" in available and any(
                keyword in lower
                for keyword in ("word count", "character count", "text stats", "字数", "字符数", "统计文本")
            ):
                name = "text_stats"
                arguments = {"text": prompt[:10000]}

            if name is None and "weather" in lower:
                name=next((tool for tool in available if tool.endswith("_lookup_weather")),None);arguments={"city":"Shenyang"}
            if name is None and ("shipping" in lower or "eta" in lower):
                name=next((tool for tool in available if tool.endswith("_calculate_shipping_eta")),None);arguments={"order_id":"ORD-1001"}
            if name is None and ("order status" in lower or "订单状态" in lower):
                name=next((tool for tool in available if tool.endswith("_get_order_status")),None);arguments={"order_id":"ORD-1001"}
            if name: calls = [ToolCall(id=f"call_{uuid.uuid4().hex[:12]}", name=name, arguments=arguments)]
        content = f"[Mock Answer] Tool observation: {observation}" if observation is not None else ("" if calls else f"[Mock Answer] {prompt[:1000]}")
        input_tokens = max(1, sum(len(x.content) for x in request.messages) // 4)
        output_tokens = max(1, len(content) // 4)
        return ModelResponse(content=content, provider=self.name, model=request.model,
            input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=input_tokens + output_tokens,
            latency_ms=int((time.perf_counter() - started) * 1000), finish_reason="tool_calls" if calls else "stop", estimated_cost=0.0, tool_calls=calls)

    async def stream(self, request: ModelRequest) -> AsyncIterator[dict[str, Any]]:
        response = await self.generate(request)
        text = response.content
        if not text:
            yield {"type": "done", "content": "", "model": response.model, "provider": self.name,
                   "input_tokens": response.input_tokens, "output_tokens": response.output_tokens,
                   "total_tokens": response.total_tokens, "estimated_cost": response.estimated_cost}
            return
        step = 12
        for start in range(0, len(text), step):
            await asyncio.sleep(0.01)
            yield {"type": "delta", "delta": text[start:start + step]}
        yield {"type": "done", "content": text, "model": response.model, "provider": self.name,
               "input_tokens": response.input_tokens, "output_tokens": response.output_tokens,
               "total_tokens": response.total_tokens, "estimated_cost": response.estimated_cost}

def _serialize_openai_message(
    message: ModelMessage,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "role": message.role,
        "content": message.content,
    }

    if message.tool_call_id is not None:
        payload["tool_call_id"] = (
            message.tool_call_id
        )

    if message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(
                        call.arguments,
                        ensure_ascii=False,
                    ),
                },
            }
            for call in message.tool_calls
        ]

    return payload

def _serialize_openai_messages(request: ModelRequest) -> list[dict[str, Any]]:
    payload = [_serialize_openai_message(message) for message in request.messages]
    if not request.attachments:
        return payload

    # OpenAI-compatible multimodal chat accepts image_url parts on a user
    # message. Only request-local images are transported here; document
    # attachments are converted to bounded text context by RuntimeEngine.
    user_index = next(
        (index for index in range(len(request.messages) - 1, -1, -1)
         if request.messages[index].role == "user"),
        None,
    )
    if user_index is None:
        return payload

    text = str(payload[user_index].get("content") or "")
    parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for attachment in request.attachments:
        parts.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:{attachment.media_type};base64,{attachment.content_base64}"
            },
        })
    payload[user_index]["content"] = parts
    return payload


class OpenAICompatibleModelProvider:
    name = "openai_compatible"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        trust_env: bool = True,
        input_cost_per_million: float = 0.0,
        output_cost_per_million: float = 0.0,
    ) -> None:
        if not api_key:
            raise ModelError(
                ModelErrorType.AUTH,
                "MODEL_API_KEY is required",
                retryable=False,
            )

        from openai import AsyncOpenAI

        http_client = httpx.AsyncClient(
            trust_env=trust_env,
        )

        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=http_client,
        )
        self.input_cost_per_million = max(0.0, float(input_cost_per_million))
        self.output_cost_per_million = max(0.0, float(output_cost_per_million))

    async def generate(self, request: ModelRequest) -> ModelResponse:
        started = time.perf_counter()
        try:
            kwargs: dict[str, Any] = {
    "model": request.model,
    "messages": _serialize_openai_messages(request),
}
            if request.tools:
                kwargs["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.input_schema}} for t in request.tools]
            if request.temperature is not None: kwargs["temperature"] = request.temperature
            if request.max_tokens is not None: kwargs["max_tokens"] = request.max_tokens
            if request.timeout is not None: kwargs["timeout"] = request.timeout
            response = await self.client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise normalize_provider_error(exc) from exc
        usage = response.usage
        choice = response.choices[0]
        tool_calls = []
        for call in getattr(choice.message, "tool_calls", None) or []:
            try:
                arguments = json.loads(call.function.arguments or "{}")
                if not isinstance(arguments, dict): raise ValueError("arguments must be a JSON object")
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                raise ModelError(ModelErrorType.BAD_REQUEST, f"invalid tool arguments for {call.function.name}: {exc}", retryable=False) from exc
            tool_calls.append(ToolCall(id=call.id, name=call.function.name, arguments=arguments))
        input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
        output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
        total_tokens = getattr(usage, "total_tokens", 0) if usage else 0
        # Defensive defaults keep provider response parsing robust even when a
        # lightweight test/dynamic fixture bypasses __init__. Normal production
        # construction still sets these attributes explicitly.
        input_cost_per_million = max(
            0.0,
            float(getattr(self, "input_cost_per_million", 0.0) or 0.0),
        )
        output_cost_per_million = max(
            0.0,
            float(getattr(self, "output_cost_per_million", 0.0) or 0.0),
        )
        pricing_configured = (
            input_cost_per_million > 0
            or output_cost_per_million > 0
        )
        estimated_cost = (
            input_tokens / 1_000_000.0 * input_cost_per_million
            + output_tokens / 1_000_000.0 * output_cost_per_million
            if pricing_configured
            else None
        )
        return ModelResponse(content=choice.message.content or "", provider=self.name,
            model=response.model or request.model,
            input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=total_tokens,
            latency_ms=int((time.perf_counter() - started) * 1000), finish_reason=choice.finish_reason,
            estimated_cost=estimated_cost, tool_calls=tool_calls)


    async def stream(self, request: ModelRequest) -> AsyncIterator[dict[str, Any]]:
        """Yield true provider deltas from an OpenAI-compatible streaming API.

        This path intentionally has no retry after the first byte is emitted:
        replaying a partially streamed answer would duplicate user-visible text.
        """
        started = time.perf_counter()
        kwargs: dict[str, Any] = {
            "model": request.model,
            "messages": _serialize_openai_messages(request),
            "stream": True,
        }
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.max_tokens is not None:
            kwargs["max_tokens"] = request.max_tokens
        if request.timeout is not None:
            kwargs["timeout"] = request.timeout

        try:
            stream = await self.client.chat.completions.create(**kwargs)
            content_parts: list[str] = []
            finish_reason: str | None = None
            async for chunk in stream:
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                choice = choices[0]
                finish_reason = getattr(choice, "finish_reason", None) or finish_reason
                delta = getattr(getattr(choice, "delta", None), "content", None)
                if not delta:
                    continue
                if not isinstance(delta, str):
                    delta = str(delta)
                content_parts.append(delta)
                yield {"type": "delta", "delta": delta}
        except Exception as exc:
            raise normalize_provider_error(exc) from exc

        content = "".join(content_parts)
        input_chars = sum(len(message.content) for message in request.messages)
        input_tokens = max(1, input_chars // 4)
        output_tokens = max(1, len(content) // 4) if content else 0
        total_tokens = input_tokens + output_tokens
        input_cost_per_million = max(0.0, float(getattr(self, "input_cost_per_million", 0.0) or 0.0))
        output_cost_per_million = max(0.0, float(getattr(self, "output_cost_per_million", 0.0) or 0.0))
        pricing_configured = input_cost_per_million > 0 or output_cost_per_million > 0
        estimated_cost = (
            input_tokens / 1_000_000.0 * input_cost_per_million
            + output_tokens / 1_000_000.0 * output_cost_per_million
            if pricing_configured else None
        )
        yield {
            "type": "done",
            "content": content,
            "model": request.model,
            "provider": self.name,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "finish_reason": finish_reason,
            "estimated_cost": estimated_cost,
        }

def normalize_provider_error(exc: Exception) -> ModelError:
    name, status, message = type(exc).__name__.lower(), getattr(exc, "status_code", None), str(exc)
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)) or "timeout" in name:
        return ModelError(ModelErrorType.TIMEOUT, message, retryable=True)
    if status in (401, 403) or "authentication" in name or "permission" in name:
        return ModelError(ModelErrorType.AUTH, message, retryable=False)
    if status == 429 or "ratelimit" in name or "rate_limit" in name:
        return ModelError(ModelErrorType.RATE_LIMIT, message, retryable=True)
    if status is not None and 400 <= status < 500:
        return ModelError(ModelErrorType.BAD_REQUEST, message, retryable=False)
    if status is not None and status >= 500 or "connection" in name:
        return ModelError(ModelErrorType.UNAVAILABLE, message, retryable=True)
    return ModelError(ModelErrorType.UNKNOWN, message, retryable=False)
