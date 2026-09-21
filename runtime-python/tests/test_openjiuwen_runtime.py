"""Phase 1 OpenJiuwen dependency and lifecycle contracts."""

from __future__ import annotations

from types import ModuleType, SimpleNamespace

import pytest

from app.agents.openjiuwen_runtime import (
    OpenJiuwenRuntime,
    OpenJiuwenRuntimeError,
    OpenJiuwenSdk,
    get_active_openjiuwen_sdk,
    load_openjiuwen_sdk,
    validate_execution_mode,
)


def _settings(
    *,
    mode: str = "builtin",
    allow_builtin: bool = True,
    version: str = "0.1.18",
) -> SimpleNamespace:
    return SimpleNamespace(
        openjiuwen_execution_mode=mode,
        openjiuwen_allow_builtin=allow_builtin,
        openjiuwen_sdk_version=version,
    )


def test_builtin_requires_explicit_opt_in():
    with pytest.raises(OpenJiuwenRuntimeError, match="builtin mode is disabled"):
        validate_execution_mode("builtin", allow_builtin=False)


@pytest.mark.asyncio
async def test_builtin_lifecycle_does_not_import_or_start_sdk():
    runtime = OpenJiuwenRuntime(settings_obj=_settings())

    info = await runtime.start()

    assert info.mode == "builtin"
    assert info.sdk_version is None
    assert info.runner_started is False
    assert runtime.sdk is None


@pytest.mark.asyncio
async def test_builtin_does_not_require_sdk_version_setting():
    runtime = OpenJiuwenRuntime(
        settings_obj=_settings(version=""),
    )

    info = await runtime.start()

    assert info.expected_version == "not-used"


@pytest.mark.asyncio
async def test_sdk_lifecycle_starts_and_stops_runner_once():
    class FakeRunner:
        starts = 0
        stops = 0

        @classmethod
        async def start(cls):
            cls.starts += 1

        @classmethod
        async def stop(cls):
            cls.stops += 1

    sdk = OpenJiuwenSdk(
        module=ModuleType("openjiuwen"),
        runner=FakeRunner,
        version="0.1.18",
    )
    runtime = OpenJiuwenRuntime(
        settings_obj=_settings(mode="sdk", allow_builtin=False),
        sdk_loader=lambda expected: sdk,
    )

    first = await runtime.start()
    second = await runtime.start()
    assert get_active_openjiuwen_sdk() is sdk
    await runtime.stop()
    await runtime.stop()

    assert first is second
    assert first.runner_started is True
    assert runtime.info is not None
    assert runtime.info.runner_started is False
    assert FakeRunner.starts == 1
    assert FakeRunner.stops == 1
    assert get_active_openjiuwen_sdk() is None

    restarted = await runtime.start()
    await runtime.stop()
    assert restarted.runner_started is True
    assert FakeRunner.starts == 2
    assert FakeRunner.stops == 2


@pytest.mark.asyncio
async def test_sdk_loader_failure_is_not_converted_to_builtin():
    def fail(expected: str):
        raise OpenJiuwenRuntimeError(
            f"missing openjiuwen=={expected}"
        )

    runtime = OpenJiuwenRuntime(
        settings_obj=_settings(mode="sdk", allow_builtin=False),
        sdk_loader=fail,
    )

    with pytest.raises(OpenJiuwenRuntimeError, match="missing openjiuwen"):
        await runtime.start()


def test_sdk_loader_rejects_version_mismatch(monkeypatch):
    module = ModuleType("openjiuwen")
    module.__version__ = "0.1.17"

    class FakeRunner:
        async def start(self):
            pass

        async def stop(self):
            pass

        async def run_agent(self):
            pass

        async def run_agent_streaming(self):
            pass

    runner_module = SimpleNamespace(Runner=FakeRunner)

    def fake_import(name: str):
        if name == "openjiuwen":
            return module
        if name == "openjiuwen.core.runner.runner":
            return runner_module
        raise ImportError(name)

    import app.agents.openjiuwen_runtime as runtime_module

    monkeypatch.setattr(runtime_module.importlib, "import_module", fake_import)

    with pytest.raises(OpenJiuwenRuntimeError, match="version mismatch"):
        load_openjiuwen_sdk("0.1.18")


def test_sdk_loader_reports_missing_package(monkeypatch):
    import app.agents.openjiuwen_runtime as runtime_module

    def missing(name: str):
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(runtime_module.importlib, "import_module", missing)

    with pytest.raises(OpenJiuwenRuntimeError, match="unavailable"):
        load_openjiuwen_sdk("0.1.18")
