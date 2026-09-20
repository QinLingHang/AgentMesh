# P37 OpenJiuwen Phase 0 Compatibility Result

## Scope

Phase 0 validates the official OpenJiuwen extension points without calling a
real model endpoint. The probe covers:

- the asynchronous `Runner.start()` / `Runner.stop()` lifecycle;
- `Runner.run_agent()` and `Runner.run_agent_streaming()`;
- registration of an AgentMesh-shaped `BaseModelClient`;
- forwarding model tool descriptors to that custom client;
- registration and invocation of an official `Tool`;
- execution of the built-in `ReActAgent` with the custom model client;
- execution of a custom `BaseAgent` with two isolated sessions.

The probe is intentionally separate from the production runtime dependency
set. It must not make the normal offline test suite depend on OpenJiuwen.

## Candidate and command

The candidate is pinned to `openjiuwen==0.1.18` in
`runtime-python/requirements-openjiuwen-phase0.txt`.

From `runtime-python`:

```text
python -m pip install -r requirements-openjiuwen-phase0.txt
python scripts/phase0_openjiuwen_probe.py
```

The script exits non-zero when the SDK is missing, the version is different,
the required Runner APIs are absent, or any contract check fails. A different
candidate can be checked with `--expected-version`.

## Result on 2026-09-20

The isolated probe passed with Python `3.12.14` and OpenJiuwen `0.1.18`:

```text
Runner lifecycle: PASS
Batch execution: PASS
Streaming execution: PASS
Custom AgentMesh model client: PASS (2 batch calls, 1 stream call)
Built-in ReActAgent through Runner: PASS (1 tool descriptor observed)
Tool registration and callback: PASS (2 calls)
Session isolation: PASS (phase0-batch != phase0-stream)
```

The model client was deterministic and did not make a network request. This
proves that the production adapter can keep model calls inside the AgentMesh
Gateway; it does not yet prove a real provider response.

The `0.1.18` source contains a note saying that `ReActAgent` should be invoked
directly instead of through `Runner.run_agent()`, while the executable probe
successfully ran it through `Runner`. Treat the pinned probe as the compatibility
contract and rerun it on every SDK upgrade; do not infer support from comments
alone.

## Production dependency gate

Do not add OpenJiuwen to `runtime-python/requirements.txt` yet. The official
`0.1.18` metadata requires:

- `openai>=1.108.0`, while the runtime currently pins `openai==1.99.9`;
- `pymilvus>=2.6.2,<2.6.10`, while the runtime currently pins
  `pymilvus==3.0.1`.

These are incompatible constraints. Phase 1 must choose one of the following
before enabling the SDK in production:

1. upgrade and regression-test the shared runtime dependency set;
2. split the OpenJiuwen executor into a separately packaged runtime process;
3. obtain an upstream SDK build compatible with the existing dependency set.

Until that decision is made, `OPENJIUWEN_EXECUTION_MODE=builtin` remains the
only production-safe mode and the official SDK probe remains an explicit
compatibility gate.
