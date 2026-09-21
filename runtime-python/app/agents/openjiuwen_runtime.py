"""OpenJiuwen SDK compatibility checks and process lifecycle.

The official SDK owns a process-wide ``Runner``.  This module keeps its
import/version/API validation in one place so startup and request execution
cannot disagree about which SDK is available.  It deliberately does not
provide a fallback path: ``builtin`` is an explicit development/test mode.
"""

from __future__ import annotations

import importlib
import inspect
import sys
from dataclasses import dataclass, replace
from types import ModuleType
from typing import Any, Callable

from app.config import settings


class OpenJiuwenRuntimeError(RuntimeError):
    """The configured OpenJiuwen runtime is unavailable or incompatible."""


@dataclass(frozen=True)
class OpenJiuwenSdk:
    """Validated SDK handles used by startup and the executor adapter."""

    module: ModuleType
    runner: Any
    version: str


@dataclass(frozen=True)
class OpenJiuwenRuntimeInfo:
    """Observable state for health checks and startup diagnostics."""

    mode: str
    expected_version: str
    sdk_version: str | None
    runner_started: bool


_SUPPORTED_MODES = frozenset({"builtin", "sdk"})
_REQUIRED_RUNNER_METHODS = (
    "start",
    "stop",
    "run_agent",
    "run_agent_streaming",
    "release",
)
_REQUIRED_SDK_IMPORTS = (
    (
        "openjiuwen.core.foundation.llm",
        ("Model", "ModelClientConfig", "ModelRequestConfig"),
    ),
    (
        "openjiuwen.core.foundation.llm.model_clients.base_model_client",
        ("BaseModelClient",),
    ),
    (
        "openjiuwen.core.foundation.tool",
        ("Tool", "ToolCard", "ToolInfo"),
    ),
    (
        "openjiuwen.core.single_agent",
        ("AgentCard", "ReActAgent", "ReActAgentConfig", "create_agent_session"),
    ),
    (
        "openjiuwen.core.foundation.llm.schema.message",
        ("AssistantMessage",),
    ),
    (
        "openjiuwen.core.foundation.llm.schema.message_chunk",
        ("AssistantMessageChunk",),
    ),
    (
        "openjiuwen.core.foundation.llm.schema.tool_call",
        ("ToolCall",),
    ),
    (
        "openjiuwen.core.foundation.llm.schema.config",
        ("ModelClientConfig", "ModelRequestConfig"),
    ),
    (
        "openjiuwen.core.foundation.llm.schema.generation_response",
        (),
    ),
)
_active_sdk: OpenJiuwenSdk | None = None


def get_active_openjiuwen_sdk() -> OpenJiuwenSdk | None:
    """Return the SDK handle started by the current application lifespan."""

    return _active_sdk


def normalize_execution_mode(mode: str | None) -> str:
    """Normalize and validate the configured execution mode.

    Empty values are rejected instead of silently selecting a fallback mode.
    """

    normalized = str(mode or "").strip().lower()
    if normalized not in _SUPPORTED_MODES:
        expected = ", ".join(sorted(_SUPPORTED_MODES))
        raise OpenJiuwenRuntimeError(
            "invalid OPENJIUWEN_EXECUTION_MODE: "
            f"{mode!r}; expected one of {expected}"
        )
    return normalized


def validate_execution_mode(
    mode: str | None,
    *,
    allow_builtin: bool,
) -> str:
    """Validate mode policy, including the explicit builtin opt-in."""

    normalized = normalize_execution_mode(mode)
    if normalized == "builtin" and not allow_builtin:
        raise OpenJiuwenRuntimeError(
            "OpenJiuwen builtin mode is disabled; set "
            "OPENJIUWEN_ALLOW_BUILTIN=true only for development/test "
            "and keep OPENJIUWEN_EXECUTION_MODE=builtin explicit"
        )
    return normalized


def _expected_version(expected_version: str | None) -> str:
    value = str(
        expected_version
        if expected_version is not None
        else settings.openjiuwen_sdk_version
    ).strip()
    if not value:
        raise OpenJiuwenRuntimeError(
            "OPENJIUWEN_SDK_VERSION must be a non-empty exact version"
        )
    return value


def load_openjiuwen_sdk(
    expected_version: str | None = None,
) -> OpenJiuwenSdk:
    """Import and validate the pinned OpenJiuwen package and Runner API."""

    expected = _expected_version(expected_version)

    if sys.version_info < (3, 11) or sys.version_info >= (3, 14):
        found = ".".join(str(item) for item in sys.version_info[:3])
        raise OpenJiuwenRuntimeError(
            "OpenJiuwen SDK requires Python >=3.11,<3.14; "
            f"found {found} (expected openjiuwen=={expected})"
        )

    try:
        module = importlib.import_module("openjiuwen")
    except Exception as exc:
        raise OpenJiuwenRuntimeError(
            "OpenJiuwen SDK is unavailable or failed to import; "
            f"expected openjiuwen=={expected}: {exc}"
        ) from exc

    actual = str(getattr(module, "__version__", "")).strip()
    if actual != expected:
        raise OpenJiuwenRuntimeError(
            "OpenJiuwen SDK version mismatch: "
            f"expected {expected}, found {actual or '<unknown>'}"
        )

    try:
        runner_module = importlib.import_module(
            "openjiuwen.core.runner.runner"
        )
        runner = getattr(runner_module, "Runner", None)
    except Exception as exc:
        raise OpenJiuwenRuntimeError(
            "OpenJiuwen SDK is missing the official Runner module; "
            f"expected openjiuwen=={expected}: {exc}"
        ) from exc

    if runner is None:
        raise OpenJiuwenRuntimeError(
            "OpenJiuwen SDK is missing openjiuwen.core.runner.runner.Runner; "
            f"expected openjiuwen=={expected}"
        )

    missing = [
        name
        for name in _REQUIRED_RUNNER_METHODS
        if not callable(getattr(runner, name, None))
    ]
    if missing:
        raise OpenJiuwenRuntimeError(
            "OpenJiuwen Runner API is incompatible; missing methods: "
            + ", ".join(missing)
            + f" (expected openjiuwen=={expected})"
        )

    missing_sdk_api: list[str] = []
    for module_name, names in _REQUIRED_SDK_IMPORTS:
        try:
            api_module = importlib.import_module(module_name)
        except Exception as exc:
            raise OpenJiuwenRuntimeError(
                "OpenJiuwen SDK foundation API is unavailable; "
                f"failed to import {module_name}: {exc} "
                f"(expected openjiuwen=={expected})"
            ) from exc
        missing_sdk_api.extend(
            f"{module_name}.{name}"
            for name in names
            if not hasattr(api_module, name)
        )
    if missing_sdk_api:
        raise OpenJiuwenRuntimeError(
            "OpenJiuwen SDK API is incompatible; missing: "
            + ", ".join(missing_sdk_api)
            + f" (expected openjiuwen=={expected})"
        )

    for lifecycle_method in ("start", "stop"):
        if not inspect.iscoroutinefunction(
            getattr(runner, lifecycle_method)
        ):
            raise OpenJiuwenRuntimeError(
                "OpenJiuwen Runner API is incompatible; "
                f"Runner.{lifecycle_method} must be async "
                f"(expected openjiuwen=={expected})"
            )

    return OpenJiuwenSdk(
        module=module,
        runner=runner,
        version=actual,
    )


class OpenJiuwenRuntime:
    """Own the process-wide OpenJiuwen Runner for one FastAPI lifespan."""

    def __init__(
        self,
        *,
        settings_obj: Any = settings,
        sdk_loader: Callable[[str], OpenJiuwenSdk] | None = None,
    ) -> None:
        self._settings = settings_obj
        self._sdk_loader = sdk_loader or load_openjiuwen_sdk
        self._sdk: OpenJiuwenSdk | None = None
        self._info: OpenJiuwenRuntimeInfo | None = None

    @property
    def info(self) -> OpenJiuwenRuntimeInfo | None:
        return self._info

    @property
    def sdk(self) -> OpenJiuwenSdk | None:
        """Return the validated SDK handle after startup, if in sdk mode."""

        return self._sdk

    async def start(self) -> OpenJiuwenRuntimeInfo:
        """Validate configuration and start Runner exactly once."""

        global _active_sdk

        if self._info is not None and (
            self._info.mode == "builtin"
            or self._info.runner_started
        ):
            return self._info

        # A stopped SDK lifecycle object can be reused by a controlled
        # application restart; rebuild its validated handle instead of
        # returning the stale stopped status.
        self._info = None

        mode = validate_execution_mode(
            getattr(self._settings, "openjiuwen_execution_mode", None),
            allow_builtin=bool(
                getattr(self._settings, "openjiuwen_allow_builtin", False)
            ),
        )
        if mode == "builtin":
            configured_version = str(
                getattr(
                    self._settings,
                    "openjiuwen_sdk_version",
                    settings.openjiuwen_sdk_version,
                )
                or ""
            ).strip()
            self._info = OpenJiuwenRuntimeInfo(
                mode=mode,
                expected_version=configured_version or "not-used",
                sdk_version=None,
                runner_started=False,
            )
            return self._info

        expected = _expected_version(
            getattr(self._settings, "openjiuwen_sdk_version", None)
        )
        sdk = self._sdk_loader(expected)
        if _active_sdk is not None:
            # A second application lifespan in the same process must not take
            # ownership of the singleton Runner behind the first one.
            raise OpenJiuwenRuntimeError(
                "another OpenJiuwen Runner is already active in this process"
            )

        try:
            await sdk.runner.start()
        except Exception as exc:
            raise OpenJiuwenRuntimeError(
                "OpenJiuwen Runner.start() failed for "
                f"openjiuwen=={expected}: {exc}"
            ) from exc

        _active_sdk = sdk
        self._sdk = sdk
        self._info = OpenJiuwenRuntimeInfo(
            mode=mode,
            expected_version=expected,
            sdk_version=sdk.version,
            runner_started=True,
        )
        return self._info

    async def stop(self) -> None:
        """Stop Runner once; leave a truthful stopped status for diagnostics."""

        global _active_sdk

        sdk = self._sdk
        info = self._info
        if sdk is None:
            return

        try:
            await sdk.runner.stop()
        except Exception as exc:
            raise OpenJiuwenRuntimeError(
                "OpenJiuwen Runner.stop() failed: "
                f"{exc}"
            ) from exc
        finally:
            self._sdk = None
            if _active_sdk is sdk:
                _active_sdk = None
            if info is not None:
                self._info = replace(info, runner_started=False)


__all__ = [
    "OpenJiuwenRuntime",
    "OpenJiuwenRuntimeError",
    "OpenJiuwenRuntimeInfo",
    "OpenJiuwenSdk",
    "get_active_openjiuwen_sdk",
    "load_openjiuwen_sdk",
    "normalize_execution_mode",
    "validate_execution_mode",
]
