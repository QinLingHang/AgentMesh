#!/usr/bin/env python3
"""Run the Phase 0 OpenJiuwen compatibility probe.

The probe deliberately avoids a real model endpoint.  It verifies the SDK
extension points that the production adapter needs:

* the official Runner lifecycle and batch/streaming APIs;
* an AgentMesh-shaped custom ``BaseModelClient`` registered with the SDK;
* an official ``Tool`` registered in the SDK resource manager;
* the built-in ``ReActAgent`` receiving the custom model and tool descriptor;
* a custom ``BaseAgent`` executed through ``Runner.run_agent``.

Run from ``runtime-python`` after installing the pinned phase-0 dependency:

    python scripts/phase0_openjiuwen_probe.py

The script exits non-zero for an unavailable, incompatible, or failing SDK.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, AsyncIterator


RUNTIME_ROOT = Path(__file__).resolve().parents[1]
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))


def _session_id(session: Any) -> str:
    getter = getattr(session, "get_session_id", None)
    if callable(getter):
        return str(getter())
    return str(getattr(session, "session_id", ""))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate the official OpenJiuwen SDK integration points used by AgentMesh."
    )
    parser.add_argument(
        "--expected-version",
        default=os.getenv("OPENJIUWEN_PHASE0_VERSION", "0.1.18"),
        help="exact SDK version to require (default: 0.1.18 or OPENJIUWEN_PHASE0_VERSION)",
    )
    return parser.parse_args()


async def _run_probe(expected_version: str) -> dict[str, Any]:
    if sys.version_info < (3, 11) or sys.version_info >= (3, 14):
        raise RuntimeError(
            "OpenJiuwen requires Python >=3.11,<3.14; "
            f"found {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        )

    try:
        import openjiuwen
        from openjiuwen.core.foundation.llm import (
            AssistantMessage,
            AssistantMessageChunk,
            Model,
            ModelClientConfig,
            ModelRequestConfig,
            UserMessage,
        )
        from openjiuwen.core.foundation.llm.model_clients.base_model_client import (
            BaseModelClient,
        )
        from openjiuwen.core.foundation.llm.schema.generation_response import (
            AudioGenerationResponse,
            ImageGenerationResponse,
            VideoGenerationResponse,
        )
        from openjiuwen.core.foundation.tool import Tool, ToolCard, ToolInfo
        from openjiuwen.core.runner.runner import Runner
        from openjiuwen.core.single_agent import (
            AgentCard,
            BaseAgent,
            ReActAgent,
            ReActAgentConfig,
        )
    except ImportError as exc:
        raise RuntimeError(
            "OpenJiuwen SDK or one of its runtime dependencies is unavailable: "
            f"{exc}"
        ) from exc

    actual_version = str(getattr(openjiuwen, "__version__", ""))
    if expected_version and actual_version != expected_version:
        raise RuntimeError(
            f"OpenJiuwen version mismatch: expected {expected_version}, found {actual_version}"
        )

    required_runner_methods = (
        "start",
        "stop",
        "run_agent",
        "run_agent_streaming",
    )
    missing_runner_methods = [
        name for name in required_runner_methods if not callable(getattr(Runner, name, None))
    ]
    if missing_runner_methods:
        raise RuntimeError(
            "OpenJiuwen Runner is missing required methods: "
            + ", ".join(missing_runner_methods)
        )
    if not inspect.iscoroutinefunction(Runner.start) or not inspect.iscoroutinefunction(Runner.stop):
        raise RuntimeError("OpenJiuwen Runner.start/stop must be asynchronous")

    class ProbeModelClient(BaseModelClient):
        """A deterministic stand-in for the AgentMesh model gateway."""

        __client_name__ = "agentmesh_phase0_probe"
        __client_type__ = "llm"

        def __init__(self, model_config, model_client_config):
            super().__init__(
                model_config=model_config,
                model_client_config=model_client_config,
            )
            self.invocations: list[dict[str, Any]] = []
            self.stream_invocations: list[dict[str, Any]] = []

        async def invoke(
            self,
            messages,
            *,
            tools=None,
            temperature=None,
            top_p=None,
            model=None,
            max_tokens=None,
            stop=None,
            output_parser=None,
            timeout=None,
            **kwargs,
        ) -> AssistantMessage:
            self.invocations.append(
                {
                    "messageCount": len(messages) if isinstance(messages, list) else 1,
                    "toolCount": len(tools or []),
                    "model": model,
                }
            )
            return AssistantMessage(content="agentmesh-model-probe-ok")

        async def stream(
            self,
            messages,
            *,
            tools=None,
            temperature=None,
            top_p=None,
            model=None,
            max_tokens=None,
            stop=None,
            output_parser=None,
            timeout=None,
            **kwargs,
        ) -> AsyncIterator[AssistantMessageChunk]:
            self.stream_invocations.append(
                {
                    "messageCount": len(messages) if isinstance(messages, list) else 1,
                    "toolCount": len(tools or []),
                    "model": model,
                }
            )
            yield AssistantMessageChunk(content="agentmesh-")
            yield AssistantMessageChunk(content="model-stream-probe-ok")

        async def generate_image(self, messages, **kwargs) -> ImageGenerationResponse:
            raise NotImplementedError("phase-0 probe only covers text generation")

        async def generate_speech(self, messages, **kwargs) -> AudioGenerationResponse:
            raise NotImplementedError("phase-0 probe only covers text generation")

        async def generate_video(self, messages, **kwargs) -> VideoGenerationResponse:
            raise NotImplementedError("phase-0 probe only covers text generation")

    class ProbeTool(Tool):
        def __init__(self):
            super().__init__(
                ToolCard(
                    id="agentmesh_phase0_probe_tool",
                    name="agentmesh_phase0_probe_tool",
                    description="Deterministic Phase 0 tool",
                    input_params={
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                        "required": ["value"],
                    },
                    stateless=True,
                )
            )
            self.calls: list[dict[str, Any]] = []

        async def invoke(self, inputs: dict[str, Any], **kwargs) -> dict[str, Any]:
            self.calls.append(dict(inputs))
            return {"echo": inputs.get("value", "")}

        async def stream(self, inputs: dict[str, Any], **kwargs) -> AsyncIterator[dict[str, Any]]:
            yield await self.invoke(inputs, **kwargs)

    class ProbeAgent(BaseAgent):
        def __init__(self, card: AgentCard, tool_id: str):
            super().__init__(card)
            self.tool_id = tool_id

        def configure(self, config) -> "ProbeAgent":
            return self

        async def invoke(self, inputs: dict[str, Any], session=None) -> dict[str, Any]:
            tool = Runner.resource_mgr.get_tool(self.tool_id, session=session)
            if tool is None:
                raise RuntimeError(f"registered probe tool not found: {self.tool_id}")
            result = await tool.invoke(inputs)
            return {
                "mode": "batch",
                "tool": result,
                "sessionId": _session_id(session),
            }

        async def stream(self, inputs: dict[str, Any], session=None, stream_modes=None):
            tool = Runner.resource_mgr.get_tool(self.tool_id, session=session)
            if tool is None:
                raise RuntimeError(f"registered probe tool not found: {self.tool_id}")
            async for result in tool.stream(inputs):
                yield {
                    "mode": "stream",
                    "tool": result,
                    "sessionId": _session_id(session),
                }

    started = False
    tool = None
    try:
        await Runner.start()
        started = True

        model_config = ModelRequestConfig(model="phase0-probe-model")
        client_config = ModelClientConfig(
            client_provider="agentmesh_phase0_probe",
            api_key="phase0-no-network-key",
            api_base="http://agentmesh-gateway.invalid",
            verify_ssl=False,
        )
        model = Model(
            model_client_config=client_config,
            model_config=model_config,
        )
        model_tools = [
            ToolInfo(
                name="agentmesh_phase0_probe_tool",
                description="Deterministic Phase 0 tool",
                parameters={"type": "object", "properties": {}},
            )
        ]
        model_response = await model.invoke(
            [UserMessage(content="phase0")],
            tools=model_tools,
        )
        stream_chunks = [
            chunk.content
            async for chunk in model.stream(
                [UserMessage(content="phase0 stream")],
                tools=model_tools,
            )
        ]
        model_client = model._client

        tool = ProbeTool()
        Runner.resource_mgr.add_tool(tool)

        # Exercise the SDK's built-in ReAct agent as well as the small custom
        # BaseAgent below.  The pre-built agent accepts the same Model instance,
        # so this verifies that a registered AgentMesh model client reaches the
        # framework's actual reasoning path without a provider network call.
        react_agent = ReActAgent(
            AgentCard(
                id="agentmesh_phase0_react_agent",
                name="agentmesh_phase0_react_agent",
                description="Deterministic Phase 0 ReAct Agent",
            )
        )
        react_agent.configure(
            ReActAgentConfig(
                model_name="phase0-probe-model",
                model_provider="agentmesh_phase0_probe",
                model_client_config=client_config,
                model_config_obj=model_config,
                max_iterations=1,
            )
        )
        react_agent.set_llm(model)
        react_agent.ability_manager.add(tool.card)

        agent = ProbeAgent(
            AgentCard(
                id="agentmesh_phase0_probe_agent",
                name="agentmesh_phase0_probe_agent",
                description="Deterministic Phase 0 Agent",
            ),
            tool.card.id,
        )

        react_result = await Runner.run_agent(
            react_agent,
            {"query": "react", "conversation_id": "phase0-react"},
        )
        batch_result = await Runner.run_agent(
            agent,
            {"value": "batch", "conversation_id": "phase0-batch"},
        )
        streaming_result = [
            item
            async for item in Runner.run_agent_streaming(
                agent,
                {"value": "stream", "conversation_id": "phase0-stream"},
            )
        ]
    finally:
        if tool is not None:
            Runner.resource_mgr.remove_tool(tool.card.id)
        if started:
            await Runner.stop()

    if model_response.content != "agentmesh-model-probe-ok":
        raise RuntimeError(f"unexpected model response: {model_response.content!r}")
    if "".join(stream_chunks) != "agentmesh-model-stream-probe-ok":
        raise RuntimeError(f"unexpected model stream: {stream_chunks!r}")
    if react_result.get("output") != "agentmesh-model-probe-ok":
        raise RuntimeError(f"unexpected ReAct result: {react_result!r}")
    if batch_result["tool"] != {"echo": "batch"}:
        raise RuntimeError(f"unexpected Runner batch result: {batch_result!r}")
    if not streaming_result or streaming_result[-1]["tool"] != {"echo": "stream"}:
        raise RuntimeError(f"unexpected Runner streaming result: {streaming_result!r}")
    session_ids = {batch_result["sessionId"], streaming_result[-1]["sessionId"]}
    if len(session_ids) != 2:
        raise RuntimeError(f"Runner did not isolate sessions: {session_ids!r}")
    if len(tool.calls) != 2:
        raise RuntimeError(f"probe tool call count mismatch: {tool.calls!r}")
    react_tool_descriptor_count = next(
        (
            call["toolCount"]
            for call in model_client.invocations
            if call["toolCount"] >= 1
        ),
        0,
    )
    if react_tool_descriptor_count < 1:
        raise RuntimeError(
            "ReActAgent did not forward the registered tool descriptor to the model client"
        )

    return {
        "status": "pass",
        "python": ".".join(map(str, sys.version_info[:3])),
        "sdkVersion": actual_version,
        "runner": {
            "started": started,
            "batch": callable(Runner.run_agent),
            "streaming": callable(Runner.run_agent_streaming),
        },
        "modelClient": {
            "registeredProvider": client_config.client_provider,
            "invokeCalls": len(model_client.invocations),
            "streamCalls": len(model_client.stream_invocations),
            "toolDescriptorsSeen": model_client.invocations[0]["toolCount"],
        },
        "tool": {
            "registeredId": tool.card.id,
            "calls": len(tool.calls),
        },
        "agent": {
            "reactBatch": True,
            "reactToolDescriptorsSeen": react_tool_descriptor_count,
            "batchSession": batch_result["sessionId"],
            "streamSession": streaming_result[-1]["sessionId"],
        },
    }


def main() -> int:
    args = _parse_args()
    try:
        report = asyncio.run(_run_probe(args.expected_version))
    except Exception as exc:
        report = {
            "status": "fail",
            "errorType": type(exc).__name__,
            "error": str(exc),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2), file=sys.stderr)
        traceback.print_exc()
        return 1

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
