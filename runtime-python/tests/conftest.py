"""Shared pytest defaults and lightweight async fallback for AgentMesh runtime tests.

The test suite should run directly with ``python -m pytest -q`` and must not
require a wrapper script to force mock providers.  Environment variables that
are already supplied by the caller still win because these are defaults only.
"""
import asyncio
import inspect
import os

# Deterministic, offline-safe environment for the full runtime test suite.
#
# IMPORTANT:
# Do not use setdefault() here.
#
# The developer machine may already define production/local runtime values
# such as MODEL_PROVIDER=openai_compatible.  Allowing those values to leak
# into pytest makes deterministic tests unexpectedly call a real model,
# which can change tool-routing behaviour and make the suite environment
# dependent.
os.environ["MODEL_PROVIDER"] = "mock"
os.environ["RAG_BACKEND"] = "inmemory"
os.environ["EMBEDDING_BACKEND"] = "hash"
os.environ["RERANKER_BACKEND"] = "heuristic"

# Dedicated P3 retrieval tests inject their own deterministic sources.
# The ordinary full suite must never depend on a live Go/MySQL memory service.
os.environ["MEMORY_RETRIEVAL_ENABLED"] = "false"


def pytest_configure(config):
    config.addinivalue_line("markers", "asyncio: run an async test")


def pytest_pyfunc_call(pyfuncitem):
    if inspect.iscoroutinefunction(pyfuncitem.obj):
        kwargs = {
            name: pyfuncitem.funcargs[name]
            for name in inspect.signature(pyfuncitem.obj).parameters
        }
        asyncio.run(pyfuncitem.obj(**kwargs))
        return True
    return None
