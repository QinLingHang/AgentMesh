# P37 OpenJiuwen Phase 2: Official SDK Execution Chain

## Implemented scope

- `runtime-python/app/agents/openjiuwen_sdk.py` is the only module that imports
  OpenJiuwen classes. It adapts the pinned `0.1.18` APIs (`Runner`,
  `ReActAgent`, `BaseModelClient`, `Tool`, `ToolCard`, and `Session`) to the
  AgentMesh contracts.
- `OpenJiuwenModelAdapter` registers an SDK `BaseModelClient` whose `invoke`
  and `stream` methods construct AgentMesh `ModelRequest` objects and call the
  existing `ModelGateway`. OpenJiuwen never receives provider credentials and
  cannot make a provider call outside the gateway.
- Request-scoped `ToolDefinition` objects are projected to SDK `Tool` objects.
  Every callback enters `OpenJiuwenToolBridge.call()`, which performs the
  existing authorization, approval, schema, timeout, adapter, and audit path in
  `ToolRegistry`. MCP, HTTP, and internal tools therefore share one boundary.
- The SDK request carries the prepared AgentMesh task context. Attachments are
  retained on every gateway request, while the context section names for
  Conversation Memory, User Long-term Memory, RAG, and platform capability
  context are exposed as request metadata. SDK-side retrieval and memory
  access are not enabled.
- Batch and streaming execution honor the monotonic request deadline and an
  optional cancellation event. Streaming SDK frames are bridged to runtime
  events; approval frames are converted back to the platform's
  `ToolApprovalRequired` control-flow signal.
- Each execution creates a new tenant-hashed SDK Session ID, registers
  temporary stateful tools, reports executor/SDK/agent/session metadata, then
  calls `Runner.release(..., force=True)` and tears down temporary tools in a
  `finally` block.

## Observable result metadata

SDK executions include:

```text
executorType=openjiuwen
sdk=true
sdkVersion=<validated version>
agentType=ReActAgent
sessionId=<tenant-qualified one-shot session>
modelCalls=<gateway call count>
streamCalls=<gateway stream count>
registeredTools=<request-scoped tool names>
attachmentCount=<request attachment count>
contextSections=<prepared context headings>
```

## Dependency installation

The project currently uses `mcp>=2.1,<3`. OpenJiuwen `0.1.18` declares
`fastmcp>=2.14.2,<3`, whose 2.x line requires MCP 1.x, so installing the SDK
with normal dependency resolution would make the runtime image unsatisfiable.
The validated Runner/ReActAgent core path does not import `fastmcp`; production
therefore installs the compatible direct dependencies first and then installs
the exact SDK wheel without re-resolving its incompatible integration metadata:

```text
python -m pip install -r requirements.txt -r requirements-openjiuwen-deps.txt
python -m pip install --no-deps -r requirements-openjiuwen-sdk.txt
```

`load_openjiuwen_sdk()` still checks the exact SDK version and required official
foundation APIs at startup. A future SDK upgrade that makes `fastmcp` mandatory
must be handled as a compatibility change, not by silently changing the MCP
major version.

## Verification

Static verification performed for this change:

```text
python -m compileall -q runtime-python/app/agents runtime-python/app/models runtime-python/app/services/engine.py
git diff --check
```

The full pytest suite and the real SDK smoke run must be executed in an
environment installed with the two production dependency layers above; the
current desktop interpreter is the LibreOffice Python distribution and does not
have the runtime dependencies installed. The Phase 0 official SDK probe remains
a required compatibility gate when changing the pinned SDK.

Validation completed on 2026-09-20:

- runtime-python: `453 passed`;
- phase 2, gateway, lifecycle, and RAG targeted tests: passed;
- Phase 0 official SDK probe with OpenJiuwen `0.1.18`: passed for Runner
  lifecycle, batch/streaming execution, model-client registration, Tool
  callbacks, and Session isolation;
- dependency resolver dry-run for the two production layers: exit `0`.
