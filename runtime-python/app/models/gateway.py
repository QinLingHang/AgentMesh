import asyncio
from collections.abc import Callable
from typing import Any
from app.models.contracts import ModelProvider, ModelRequest, ModelResponse
from app.models.errors import ModelError, ModelErrorType
from app.models.providers import normalize_provider_error

ModelEventHandler = Callable[[dict[str, Any]], None]

class ModelGateway:
    def __init__(self, provider: ModelProvider, *, timeout: float, max_retries: int) -> None:
        self.provider, self.timeout, self.max_retries = provider, timeout, max(0, max_retries)

    async def generate(self, request: ModelRequest, on_event: ModelEventHandler | None = None) -> ModelResponse:
        timeout = request.timeout or self.timeout
        self._emit(on_event, "model_call_started", provider=self.provider.name, model=request.model)
        for attempt in range(self.max_retries + 1):
            try:
                response = await asyncio.wait_for(self.provider.generate(request), timeout=timeout)
                self._emit(on_event, "model_call_completed", provider=response.provider, model=response.model,
                    latency_ms=response.latency_ms, input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens, total_tokens=response.total_tokens,
                    estimated_cost=response.estimated_cost or 0.0,
                    cost_known=response.estimated_cost is not None, attempts=attempt + 1)
                return response
            except asyncio.TimeoutError:
                error = ModelError(ModelErrorType.TIMEOUT, f"model call timed out after {timeout}s", retryable=True)
            except ModelError as exc:
                error = exc
            except Exception as exc:
                error = normalize_provider_error(exc)
            will_retry = error.retryable and attempt < self.max_retries
            kind = "model_call_retry" if will_retry else "model_call_failed"
            self._emit(on_event, kind, provider=self.provider.name, model=request.model,
                error_type=error.error_type.value, attempt=attempt + 1,
                max_retries=self.max_retries, retrying=will_retry)
            if not will_retry: raise error
            await asyncio.sleep(min(0.25 * (2**attempt), 1.0))
        raise AssertionError("unreachable")

    async def generate_stream(
        self,
        request: ModelRequest,
        on_event: ModelEventHandler | None = None,
        on_delta: Callable[[str], None] | None = None,
    ) -> ModelResponse:
        """Stream provider deltas with a progress timeout, not a whole-response timeout.

        The configured timeout is an idle/progress deadline for each provider
        stream item. A healthy long generation may exceed that duration overall
        as long as the provider keeps producing progress. Retry is allowed only
        before the first real delta; replaying after emitted content could
        duplicate externally visible text.
        """
        stream_method = getattr(self.provider, "stream", None)
        if not callable(stream_method) or getattr(self.provider, "name", "") == "mock":
            return await self.generate(request, on_event)

        timeout = request.timeout or self.timeout
        self._emit(
            on_event,
            "model_call_started",
            provider=self.provider.name,
            model=request.model,
            streaming=True,
        )

        for attempt in range(self.max_retries + 1):
            parts: list[str] = []
            done: dict[str, Any] | None = None
            emitted_delta = False
            iterator = stream_method(request).__aiter__()
            try:
                while True:
                    try:
                        item = await asyncio.wait_for(
                            iterator.__anext__(),
                            timeout=timeout,
                        )
                    except StopAsyncIteration:
                        break

                    if item.get("type") == "delta":
                        chunk = item.get("delta", "")
                        if not isinstance(chunk, str):
                            raise ValueError("model stream delta must be text")
                        if chunk:
                            emitted_delta = True
                            parts.append(chunk)
                            if on_delta is not None:
                                try:
                                    on_delta(chunk)
                                except Exception:
                                    # A broken/disconnected UI is never a reason to
                                    # cancel the authoritative Agent execution.
                                    pass
                    elif item.get("type") == "done":
                        done = item

                if done is None:
                    raise RuntimeError(
                        "model stream ended without an authoritative done event"
                    )

                text = "".join(parts)
                if text != str(done.get("content", "")):
                    raise RuntimeError(
                        "model stream content did not match emitted deltas"
                    )

                result = ModelResponse(
                    content=text,
                    provider=str(done.get("provider") or self.provider.name),
                    model=str(done.get("model") or request.model),
                    input_tokens=int(done.get("input_tokens") or 0),
                    output_tokens=int(done.get("output_tokens") or 0),
                    total_tokens=int(done.get("total_tokens") or 0),
                    latency_ms=int(done.get("latency_ms") or 0),
                    finish_reason=done.get("finish_reason"),
                    estimated_cost=done.get("estimated_cost"),
                )
                self._emit(
                    on_event,
                    "model_call_completed",
                    provider=result.provider,
                    model=result.model,
                    latency_ms=result.latency_ms,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    total_tokens=result.total_tokens,
                    estimated_cost=result.estimated_cost or 0.0,
                    cost_known=result.estimated_cost is not None,
                    attempts=attempt + 1,
                    streaming=True,
                )
                return result

            except asyncio.TimeoutError:
                error: Exception = ModelError(
                    ModelErrorType.TIMEOUT,
                    f"model stream made no progress for {timeout}s",
                    retryable=True,
                )
            except ModelError as exc:
                error = exc
            except Exception as exc:
                error = exc
            finally:
                close = getattr(iterator, "aclose", None)
                if callable(close):
                    try:
                        await close()
                    except Exception:
                        pass

            retryable = (
                isinstance(error, ModelError)
                and error.retryable
                and not emitted_delta
                and attempt < self.max_retries
            )
            self._emit(
                on_event,
                "model_call_retry" if retryable else "model_call_failed",
                provider=self.provider.name,
                model=request.model,
                error_type=(
                    error.error_type.value
                    if isinstance(error, ModelError)
                    else type(error).__name__
                ),
                attempt=attempt + 1,
                max_retries=self.max_retries,
                retrying=retryable,
                streaming=True,
                emitted_delta=emitted_delta,
            )
            if not retryable:
                raise error
            await asyncio.sleep(min(0.25 * (2**attempt), 1.0))

        raise AssertionError("unreachable")

    @staticmethod
    def _emit(handler: ModelEventHandler | None, kind: str, **detail: Any) -> None:
        if handler is not None: handler({"kind": kind, **detail})
