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
python -m pip install -r requirements.txt -r requirements-openjiuwen-deps.txt
python -m pip install --no-deps -r requirements-openjiuwen-phase0.txt
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

## Production dependency gate (resolved in Phase 1)

The official `0.1.18` metadata requires:

- `openai>=1.108.0` (the pre-Phase-1 runtime pinned `openai==1.99.9`);
- `pymilvus>=2.6.2,<2.6.10` (the pre-Phase-1 runtime pinned
  `pymilvus==3.0.1`).

The Phase 1 dependency decision is to upgrade the shared OpenAI client range
to `openai>=1.108.0,<2` and pin Milvus to `pymilvus==2.6.9`, which is the
supported 2.6.x line. The exact SDK wheel is pinned in
`runtime-python/requirements-openjiuwen-sdk.txt`; its compatible direct
dependencies are in `requirements-openjiuwen-deps.txt`. The complete runtime
install must use both files alongside `requirements.txt` and still run the
normal regression suites before deployment; the probe remains the compatibility
gate for future OpenJiuwen upgrades.
