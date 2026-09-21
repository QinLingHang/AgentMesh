# P37 OpenJiuwen Phase 1: Dependency and Lifecycle

## Implemented scope

- `runtime-python/requirements-openjiuwen-sdk.txt` pins the Phase 0
  candidate, `openjiuwen==0.1.18`, including the verified wheel hash. The SDK
  artifact is installed separately with `--no-deps` because its `fastmcp`
  metadata conflicts with the runtime's required MCP 2.x line.
- `runtime-python/requirements-openjiuwen-deps.txt` contains the compatible
  non-conflicting direct dependencies declared by the SDK. The shared
  `requirements.txt` remains the owner of the platform's overlapping pins.
- The shared dependency constraints are compatible with that SDK:
  `openai>=1.108.0,<2` and `pymilvus==2.6.9`.
- `OPENJIUWEN_EXECUTION_MODE` defaults to `sdk`.
- `builtin` is development/test-only and requires the explicit
  `OPENJIUWEN_ALLOW_BUILTIN=true` opt-in.
- SDK import, exact-version, Python-version, and official `Runner` API checks
  are centralized in `app/agents/openjiuwen_runtime.py`.
- FastAPI lifespan starts one process-wide OpenJiuwen `Runner` before the
  registry is exposed and stops it after the worker and plugin registry shut
  down. Requests only read the active validated SDK handle; they do not
  import, initialize, or tear down the Runner.
- Startup logs the mode, expected/actual SDK version, and Runner state. The
  same state is available under `/health` and gates `/readyz` in SDK mode.

## Failure contract

Missing SDKs, version mismatches, unsupported Python versions, missing Runner
methods, invalid modes, and failed `Runner.start()` calls fail startup with an
explicit `OpenJiuwenRuntimeError`. No builtin fallback is attempted. A
configured builtin mode without the explicit allow flag fails the same way.

## Verification

The Phase 0 isolated probe remains the SDK compatibility check:

```text
cd runtime-python
python scripts/phase0_openjiuwen_probe.py
```

The offline unit suite sets both builtin mode and its explicit allow flag in
`tests/conftest.py`; it therefore does not require the SDK to be installed.
The production image installs the dependency layers in this order:

```text
python -m pip install -r requirements.txt -r requirements-openjiuwen-deps.txt
python -m pip install --no-deps -r requirements-openjiuwen-sdk.txt
```

The full suite must be rerun in an environment installed with both layers
before deploying the new dependency set.

The SDK-backed AgentMesh adapter is implemented in the Phase 2 narrow adapter
layer (`app/agents/openjiuwen_sdk.py`); the lifecycle contract above remains
the prerequisite for that request-scoped execution path.
