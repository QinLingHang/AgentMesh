from __future__ import annotations

import uuid
from typing import Any

import httpx

from a2a.client import (
    A2ACardResolver,
    ClientConfig,
    create_client,
)
from a2a.helpers import (
    get_artifact_text,
    get_message_text,
)
from a2a.types import (
    Message,
    Part,
    Role,
    SendMessageRequest,
    TaskState,
)

from app.agents.contracts import (
    AgentExecutionRequest,
    AgentExecutionResult,
)


class A2AAgentExecutionError(
    RuntimeError
):
    """Remote A2A Agent execution failed."""


class A2AAgentInterruptedError(
    A2AAgentExecutionError
):
    """
    A2A Task did not fail.

    It yielded control because caller action is required.

    Typical states:

        TASK_STATE_INPUT_REQUIRED
        TASK_STATE_AUTH_REQUIRED

    task_id + context_id form the continuation context
    needed for a later resume request.
    """

    def __init__(
        self,
        message: str,
        *,
        task_id: str,
        context_id: str,
        task_state: str,
        status_message: str = "",
    ) -> None:

        super().__init__(
            message
        )

        self.task_id = (
            task_id
        )

        self.context_id = (
            context_id
        )

        self.task_state = (
            task_state
        )

        self.status_message = (
            status_message
        )

    def metadata(
        self,
    ) -> dict[str, Any]:

        return {
            "protocol":
                "a2a",

            "interrupted":
                True,

            "task_id":
                self.task_id,

            "context_id":
                self.context_id,

            "task_state":
                self.task_state,

            "status_message":
                self.status_message,
        }


class A2AAgentExecutor:
    """
    AgentMesh A2A Client Adapter.

    Initial call:

        execute()
            ↓
        new Message
            ↓
        A2A Task

    Continuation:

        resume()
            ↓
        Message(
            task_id=old task,
            context_id=old context
        )
            ↓
        same remote workflow
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = 15.0,
        trust_env: bool = False,
        streaming: bool = False,
    ) -> None:

        if timeout_seconds <= 0:
            raise ValueError(
                (
                    "A2A timeout_seconds "
                    "must be > 0"
                )
            )

        self.timeout_seconds = (
            timeout_seconds
        )

        self.trust_env = (
            trust_env
        )

        self.streaming = (
            streaming
        )

    # =====================================================
    # Initial Execution
    # =====================================================

    async def execute(
        self,
        request: AgentExecutionRequest,
    ) -> AgentExecutionResult:

        return await self._execute_message(
            request=request,
            task_id="",
            context_id="",
        )

    # =====================================================
    # Resume Existing A2A Task
    # =====================================================

    async def resume(
        self,
        request: AgentExecutionRequest,
        *,
        task_id: str,
        context_id: str,
    ) -> AgentExecutionResult:
        """
        Continue an interrupted remote A2A task.

        Important:
            task_id identifies the task
            context_id identifies the conversation/workflow context
        """

        task_id = (
            task_id.strip()
        )

        context_id = (
            context_id.strip()
        )

        if not task_id:
            raise ValueError(
                (
                    "A2A resume task_id "
                    "must not be empty"
                )
            )

        if not context_id:
            raise ValueError(
                (
                    "A2A resume context_id "
                    "must not be empty"
                )
            )

        self._emit(
            request,
            "A2A Task Resume",
            "running",
            task_id=task_id,
            context_id=context_id,
        )

        result = await self._execute_message(
            request=request,
            task_id=task_id,
            context_id=context_id,
        )

        self._emit(
            request,
            "A2A Task Resume",
            "completed",
            task_id=task_id,
            context_id=context_id,
            task_state=(
                result
                .metadata
                .get(
                    "task_state",
                    "",
                )
            ),
        )

        return result

    # =====================================================
    # Common Execution
    # =====================================================

    async def _execute_message(
        self,
        *,
        request: AgentExecutionRequest,
        task_id: str,
        context_id: str,
    ) -> AgentExecutionResult:

        endpoint = (
            request
            .agent
            .endpoint
            .strip()
            .rstrip("/")
        )

        if not endpoint:
            raise A2AAgentExecutionError(
                (
                    "A2A agent endpoint "
                    "must not be empty"
                )
            )

        async with httpx.AsyncClient(
            timeout=(
                self.timeout_seconds
            ),
            trust_env=(
                self.trust_env
            ),
        ) as http_client:

            # =================================================
            # Agent Card
            # =================================================

            self._emit(
                request,
                (
                    "A2A Agent Card "
                    "Discovery"
                ),
                "running",
                endpoint=endpoint,
            )

            try:

                resolver = (
                    A2ACardResolver(
                        httpx_client=(
                            http_client
                        ),
                        base_url=(
                            endpoint
                        ),
                    )
                )

                agent_card = (
                    await resolver
                    .get_agent_card()
                )

            except Exception as exc:

                self._emit(
                    request,
                    (
                        "A2A Agent Card "
                        "Discovery"
                    ),
                    "error",
                    endpoint=endpoint,
                    error_type=(
                        type(exc)
                        .__name__
                    ),
                    error=str(exc),
                )

                raise A2AAgentExecutionError(
                    (
                        "failed to resolve "
                        "A2A Agent Card: "
                        f"{exc}"
                    )
                ) from exc

            remote_name = str(
                getattr(
                    agent_card,
                    "name",
                    "",
                )
            )

            remote_version = str(
                getattr(
                    agent_card,
                    "version",
                    "",
                )
            )

            skills = list(
                getattr(
                    agent_card,
                    "skills",
                    [],
                )
                or []
            )

            self._emit(
                request,
                (
                    "A2A Agent Card "
                    "Discovery"
                ),
                "completed",
                endpoint=endpoint,
                remote_agent=(
                    remote_name
                ),
                remote_version=(
                    remote_version
                ),
                skills=(
                    len(skills)
                ),
            )

            # =================================================
            # Client
            # =================================================

            config = (
                ClientConfig(
                    streaming=(
                        self.streaming
                    ),

                    polling=False,

                    httpx_client=(
                        http_client
                    ),

                    supported_protocol_bindings=[
                        "JSONRPC",
                        "HTTP+JSON",
                    ],
                )
            )

            try:

                client = (
                    await create_client(
                        agent=(
                            agent_card
                        ),
                        client_config=(
                            config
                        ),
                    )
                )

            except Exception as exc:

                raise A2AAgentExecutionError(
                    (
                        "failed to create "
                        f"A2A client: {exc}"
                    )
                ) from exc

            try:

                # =============================================
                # Explicit Message construction
                #
                # Initial:
                #     no task_id/context_id
                #
                # Resume:
                #     same task_id/context_id
                # =============================================

                message = (
                    Message(
                        role=(
                            Role.ROLE_USER
                        ),

                        message_id=(
                            str(
                                uuid.uuid4()
                            )
                        ),

                        parts=[
                            Part(
                                text=(
                                    request.task
                                )
                            )
                        ],

                        task_id=(
                            task_id
                        ),

                        context_id=(
                            context_id
                        ),
                    )
                )

                send_request = (
                    SendMessageRequest(
                        message=(
                            message
                        )
                    )
                )

                self._emit(
                    request,
                    "A2A Message Sent",
                    "running",
                    remote_agent=(
                        remote_name
                    ),
                    capability=(
                        request
                        .capability
                    ),
                    message_id=(
                        message.message_id
                    ),
                    task_id=(
                        task_id
                    ),
                    context_id=(
                        context_id
                    ),
                    streaming=(
                        self.streaming
                    ),
                )

                result = (
                    await self
                    ._consume_response(
                        request=request,

                        stream=(
                            client
                            .send_message(
                                send_request
                            )
                        ),

                        remote_name=(
                            remote_name
                        ),

                        remote_version=(
                            remote_version
                        ),
                    )
                )

                self._emit(
                    request,
                    (
                        "A2A Response "
                        "Completed"
                    ),
                    "completed",

                    remote_agent=(
                        remote_name
                    ),

                    task_id=(
                        result
                        .metadata
                        .get(
                            "task_id",
                            "",
                        )
                    ),

                    context_id=(
                        result
                        .metadata
                        .get(
                            "context_id",
                            "",
                        )
                    ),

                    task_state=(
                        result
                        .metadata
                        .get(
                            "task_state",
                            "",
                        )
                    ),
                )

                return result

            except (
                A2AAgentInterruptedError
            ) as exc:

                self._emit(
                    request,
                    "A2A Task Interrupted",
                    "completed",
                    task_id=(
                        exc.task_id
                    ),
                    context_id=(
                        exc.context_id
                    ),
                    task_state=(
                        exc.task_state
                    ),
                    status_message=(
                        exc.status_message
                    ),
                )

                raise

            except (
                A2AAgentExecutionError
            ):
                raise

            except Exception as exc:

                self._emit(
                    request,
                    (
                        "A2A Execution "
                        "Failed"
                    ),
                    "error",
                    remote_agent=(
                        remote_name
                    ),
                    error_type=(
                        type(exc)
                        .__name__
                    ),
                    error=str(exc),
                )

                raise A2AAgentExecutionError(
                    (
                        "A2A remote "
                        "execution failed: "
                        f"{exc}"
                    )
                ) from exc

            finally:

                await client.close()

    # =====================================================
    # Stream / Non-stream Response Consumer
    # =====================================================

    async def _consume_response(
        self,
        *,
        request: AgentExecutionRequest,
        stream,
        remote_name: str,
        remote_version: str,
    ) -> AgentExecutionResult:

        direct_messages: list[
            str
        ] = []

        artifact_texts: list[
            str
        ] = []

        status_messages: list[
            str
        ] = []

        history_messages: list[
            str
        ] = []

        task_id = ""
        context_id = ""
        task_state = ""

        event_count = 0

        async for response in stream:

            event_count += 1

            payload_type = (
                response
                .WhichOneof(
                    "payload"
                )
            )

            # =================================================
            # Direct Message
            # =================================================

            if (
                payload_type
                == "message"
            ):

                text = (
                    get_message_text(
                        response.message
                    )
                    .strip()
                )

                task_id = (
                    response
                    .message
                    .task_id
                    or task_id
                )

                context_id = (
                    response
                    .message
                    .context_id
                    or context_id
                )

                if text:
                    direct_messages.append(
                        text
                    )

                self._emit(
                    request,
                    (
                        "A2A Message "
                        "Received"
                    ),
                    "completed",
                    remote_agent=(
                        remote_name
                    ),
                    chars=(
                        len(text)
                    ),
                )

                continue

            # =================================================
            # Task Snapshot
            # =================================================

            if (
                payload_type
                == "task"
            ):

                task = (
                    response.task
                )

                task_id = (
                    task.id
                )

                context_id = (
                    task.context_id
                )

                task_state = (
                    TaskState.Name(
                        task
                        .status
                        .state
                    )
                )

                for artifact in (
                    task.artifacts
                ):

                    text = (
                        get_artifact_text(
                            artifact
                        )
                        .strip()
                    )

                    if text:
                        artifact_texts.append(
                            text
                        )

                if (
                    task.status
                    .HasField(
                        "message"
                    )
                ):

                    text = (
                        get_message_text(
                            task
                            .status
                            .message
                        )
                        .strip()
                    )

                    if text:
                        status_messages.append(
                            text
                        )

                for history_item in (
                    task.history
                ):

                    if (
                        history_item.role
                        != Role.ROLE_AGENT
                    ):
                        continue

                    text = (
                        get_message_text(
                            history_item
                        )
                        .strip()
                    )

                    if text:
                        history_messages.append(
                            text
                        )

                self._emit(
                    request,
                    "A2A Task Received",
                    "completed",
                    remote_agent=(
                        remote_name
                    ),
                    task_id=(
                        task_id
                    ),
                    context_id=(
                        context_id
                    ),
                    state=(
                        task_state
                    ),
                    artifacts=(
                        len(
                            task.artifacts
                        )
                    ),
                )

                self._validate_task_state(
                    task_state=(
                        task_state
                    ),
                    task_id=(
                        task_id
                    ),
                    context_id=(
                        context_id
                    ),
                    status_messages=(
                        status_messages
                    ),
                )

                continue

            # =================================================
            # Streaming Status
            # =================================================

            if (
                payload_type
                == "status_update"
            ):

                update = (
                    response
                    .status_update
                )

                task_id = (
                    update.task_id
                    or task_id
                )

                context_id = (
                    update.context_id
                    or context_id
                )

                task_state = (
                    TaskState.Name(
                        update
                        .status
                        .state
                    )
                )

                if (
                    update
                    .status
                    .HasField(
                        "message"
                    )
                ):

                    text = (
                        get_message_text(
                            update
                            .status
                            .message
                        )
                        .strip()
                    )

                    if text:
                        status_messages.append(
                            text
                        )

                self._emit(
                    request,
                    "A2A Task Update",
                    "completed",
                    task_id=(
                        task_id
                    ),
                    context_id=(
                        context_id
                    ),
                    state=(
                        task_state
                    ),
                )

                self._validate_task_state(
                    task_state=(
                        task_state
                    ),
                    task_id=(
                        task_id
                    ),
                    context_id=(
                        context_id
                    ),
                    status_messages=(
                        status_messages
                    ),
                )

                continue

            # =================================================
            # Streaming Artifact
            # =================================================

            if (
                payload_type
                == "artifact_update"
            ):

                update = (
                    response
                    .artifact_update
                )

                task_id = (
                    update.task_id
                    or task_id
                )

                context_id = (
                    update.context_id
                    or context_id
                )

                text = (
                    get_artifact_text(
                        update.artifact
                    )
                    .strip()
                )

                if text:
                    artifact_texts.append(
                        text
                    )

                self._emit(
                    request,
                    (
                        "A2A Artifact "
                        "Received"
                    ),
                    "completed",
                    task_id=(
                        task_id
                    ),
                    context_id=(
                        context_id
                    ),
                    chars=(
                        len(text)
                    ),
                    append=(
                        update.append
                    ),
                    last_chunk=(
                        update
                        .last_chunk
                    ),
                )

        # =================================================
        # Final Content
        # =================================================

        content = ""

        if direct_messages:

            content = (
                direct_messages[-1]
            )

        elif artifact_texts:

            content = (
                "\n\n".join(
                    artifact_texts
                )
            )

        elif status_messages:

            content = (
                status_messages[-1]
            )

        elif history_messages:

            content = (
                history_messages[-1]
            )

        if not content:

            raise A2AAgentExecutionError(
                (
                    "A2A agent returned "
                    "no textual result"
                )
            )

        return AgentExecutionResult(
            content=(
                content
            ),

            metadata={
                "protocol":
                    "a2a",

                "remote_agent":
                    remote_name,

                "remote_version":
                    remote_version,

                "task_id":
                    task_id,

                "context_id":
                    context_id,

                "task_state":
                    task_state,

                "event_count":
                    event_count,

                "streaming":
                    self.streaming,
            },
        )

    # =====================================================
    # State Semantics
    # =====================================================

    @staticmethod
    def _validate_task_state(
        *,
        task_state: str,
        task_id: str,
        context_id: str,
        status_messages: list[str],
    ) -> None:

        status_message = (
            status_messages[-1]
            if status_messages
            else ""
        )

        # =================================================
        # Actual failure
        # =================================================

        if task_state in {
            "TASK_STATE_FAILED",
            "TASK_STATE_CANCELED",
            "TASK_STATE_REJECTED",
        }:

            message = (
                status_message
                or task_state
            )

            raise (
                A2AAgentExecutionError(
                    (
                        "A2A task "
                        f"{task_id or '<unknown>'} "
                        f"ended in "
                        f"{task_state}: "
                        f"{message}"
                    )
                )
            )

        # =================================================
        # NOT failure.
        #
        # Yield control to caller.
        # =================================================

        if task_state in {
            "TASK_STATE_INPUT_REQUIRED",
            "TASK_STATE_AUTH_REQUIRED",
        }:

            message = (
                status_message
                or task_state
            )

            raise (
                A2AAgentInterruptedError(
                    (
                        "A2A task "
                        f"{task_id or '<unknown>'} "
                        "requires caller action: "
                        f"{task_state}; "
                        f"{message}"
                    ),

                    task_id=(
                        task_id
                    ),

                    context_id=(
                        context_id
                    ),

                    task_state=(
                        task_state
                    ),

                    status_message=(
                        status_message
                    ),
                )
            )

    # =====================================================
    # Runtime Trace
    # =====================================================

    @staticmethod
    def _emit(
        request: AgentExecutionRequest,
        title: str,
        status: str,
        **detail: Any,
    ) -> None:

        if (
            request
            .on_runtime_event
            is None
        ):
            return

        request.on_runtime_event(
            {
                "kind":
                    "a2a",

                "title":
                    title,

                "status":
                    status,

                **detail,
            }
        )