from types import (
    SimpleNamespace,
)

import pytest

import app.agents.a2a_executor as a2a_module

from a2a.helpers import (
    new_text_message,
)
from a2a.types import (
    Artifact,
    Part,
    Role,
    Task,
    TaskState,
    TaskStatus,
)
from a2a.utils import (
    to_stream_response,
)

from app.agents import (
    A2AAgentExecutionError,
    A2AAgentExecutor,
    A2AAgentInterruptedError,
    AgentExecutionRequest,
)
from app.schemas import (
    AgentProfile,
)


def make_agent() -> AgentProfile:
    return AgentProfile(
        id=501,
        name="RemoteA2AAgent",
        endpoint=(
            "http://a2a.test"
        ),
        protocol="a2a",
        capabilities=[
            "general"
        ],
    )


class FakeResolver:
    def __init__(
        self,
        httpx_client,
        base_url,
        agent_card_path=(
            "/.well-known/"
            "agent-card.json"
        ),
    ):
        self.httpx_client = (
            httpx_client
        )
        self.base_url = (
            base_url
        )
        self.agent_card_path = (
            agent_card_path
        )

    async def get_agent_card(
        self,
    ):
        return SimpleNamespace(
            name="Remote Demo Agent",
            version="1.0.0",
            skills=[
                SimpleNamespace(
                    id="general"
                )
            ],
        )


class FakeClient:
    def __init__(
        self,
        responses,
    ):
        self.responses = (
            responses
        )

        self.received_request = (
            None
        )

        self.closed = (
            False
        )

    async def send_message(
        self,
        request,
    ):
        self.received_request = (
            request
        )

        for response in (
            self.responses
        ):
            yield response

    async def close(
        self,
    ):
        self.closed = (
            True
        )


# =========================================================
# Direct Message Response
# =========================================================


@pytest.mark.asyncio
async def test_a2a_executor_maps_agentmesh_task_to_a2a_message(
    monkeypatch,
):
    response_message = (
        new_text_message(
            "remote answer",
            role=(
                Role.ROLE_AGENT
            ),
        )
    )

    fake_client = (
        FakeClient(
            [
                to_stream_response(
                    response_message
                )
            ]
        )
    )

    async def fake_create_client(
        *,
        agent,
        client_config,
        **kwargs,
    ):
        assert (
            agent.name
            == "Remote Demo Agent"
        )

        assert (
            client_config.streaming
            is False
        )

        return fake_client

    monkeypatch.setattr(
        a2a_module,
        "A2ACardResolver",
        FakeResolver,
    )

    monkeypatch.setattr(
        a2a_module,
        "create_client",
        fake_create_client,
    )

    runtime_events = []

    executor = (
        A2AAgentExecutor(
            timeout_seconds=5.0,
            trust_env=False,
            streaming=False,
        )
    )

    result = (
        await executor.execute(
            AgentExecutionRequest(
                agent=(
                    make_agent()
                ),

                capability=(
                    "general"
                ),

                task=(
                    "Explain AgentMesh"
                ),

                on_runtime_event=(
                    runtime_events
                    .append
                ),
            )
        )
    )

    assert (
        result.content
        == "remote answer"
    )

    assert (
        result.metadata[
            "protocol"
        ]
        == "a2a"
    )

    assert (
        result.metadata[
            "remote_agent"
        ]
        == "Remote Demo Agent"
    )

    assert (
        fake_client
        .received_request
        is not None
    )

    sent_message = (
        fake_client
        .received_request
        .message
    )

    assert (
        sent_message.role
        == Role.ROLE_USER
    )

    assert (
        sent_message
        .parts[0]
        .text
        == "Explain AgentMesh"
    )

    assert (
        fake_client.closed
        is True
    )

    titles = {
        item["title"]
        for item
        in runtime_events
    }

    assert (
        "A2A Agent Card Discovery"
        in titles
    )

    assert (
        "A2A Message Sent"
        in titles
    )

    assert (
        "A2A Message Received"
        in titles
    )

    assert (
        "A2A Response Completed"
        in titles
    )


# =========================================================
# Task + Artifact Response
# =========================================================


@pytest.mark.asyncio
async def test_a2a_executor_extracts_completed_task_artifact(
    monkeypatch,
):
    task = Task(
        id="task-001",

        context_id=(
            "context-001"
        ),

        status=TaskStatus(
            state=(
                TaskState
                .TASK_STATE_COMPLETED
            )
        ),

        artifacts=[
            Artifact(
                artifact_id=(
                    "artifact-001"
                ),

                name="answer",

                parts=[
                    Part(
                        text=(
                            "artifact answer"
                        )
                    )
                ],
            )
        ],
    )

    fake_client = (
        FakeClient(
            [
                to_stream_response(
                    task
                )
            ]
        )
    )

    async def fake_create_client(
        **kwargs,
    ):
        return fake_client

    monkeypatch.setattr(
        a2a_module,
        "A2ACardResolver",
        FakeResolver,
    )

    monkeypatch.setattr(
        a2a_module,
        "create_client",
        fake_create_client,
    )

    executor = (
        A2AAgentExecutor()
    )

    result = (
        await executor.execute(
            AgentExecutionRequest(
                agent=(
                    make_agent()
                ),

                capability=(
                    "general"
                ),

                task="hello",
            )
        )
    )

    assert (
        result.content
        == "artifact answer"
    )

    assert (
        result.metadata[
            "task_id"
        ]
        == "task-001"
    )

    assert (
        result.metadata[
            "context_id"
        ]
        == "context-001"
    )

    assert (
        result.metadata[
            "task_state"
        ]
        == (
            "TASK_STATE_"
            "COMPLETED"
        )
    )


# =========================================================
# Failed Task
# =========================================================


@pytest.mark.asyncio
async def test_a2a_executor_raises_when_remote_task_fails(
    monkeypatch,
):
    failure_message = (
        new_text_message(
            "remote execution failed",
            role=(
                Role.ROLE_AGENT
            ),
        )
    )

    task = Task(
        id="task-failed",

        status=TaskStatus(
            state=(
                TaskState
                .TASK_STATE_FAILED
            ),

            message=(
                failure_message
            ),
        ),
    )

    fake_client = (
        FakeClient(
            [
                to_stream_response(
                    task
                )
            ]
        )
    )

    async def fake_create_client(
        **kwargs,
    ):
        return fake_client

    monkeypatch.setattr(
        a2a_module,
        "A2ACardResolver",
        FakeResolver,
    )

    monkeypatch.setattr(
        a2a_module,
        "create_client",
        fake_create_client,
    )

    executor = (
        A2AAgentExecutor()
    )

    with pytest.raises(
        A2AAgentExecutionError,
        match=(
            "TASK_STATE_FAILED"
        ),
    ):
        await executor.execute(
            AgentExecutionRequest(
                agent=(
                    make_agent()
                ),

                capability=(
                    "general"
                ),

                task="hello",
            )
        )

    assert (
        fake_client.closed
        is True
    )


# =========================================================
# Interrupted Task
# =========================================================


@pytest.mark.asyncio
async def test_a2a_executor_distinguishes_input_required(
    monkeypatch,
):
    task = Task(
        id="task-input",

        status=TaskStatus(
            state=(
                TaskState
                .TASK_STATE_INPUT_REQUIRED
            ),

            message=(
                new_text_message(
                    (
                        "please provide "
                        "the order number"
                    ),

                    role=(
                        Role.ROLE_AGENT
                    ),
                )
            ),
        ),
    )

    fake_client = (
        FakeClient(
            [
                to_stream_response(
                    task
                )
            ]
        )
    )

    async def fake_create_client(
        **kwargs,
    ):
        return fake_client

    monkeypatch.setattr(
        a2a_module,
        "A2ACardResolver",
        FakeResolver,
    )

    monkeypatch.setattr(
        a2a_module,
        "create_client",
        fake_create_client,
    )

    executor = (
        A2AAgentExecutor()
    )

    with pytest.raises(
        A2AAgentInterruptedError,
        match=(
            "INPUT_REQUIRED"
        ),
    ):
        await executor.execute(
            AgentExecutionRequest(
                agent=(
                    make_agent()
                ),

                capability=(
                    "general"
                ),

                task="hello",
            )
        )