# Secure Action + Human-in-the-loop
The secure-action layer turns Tool/MCP execution into a controlled action system rather than an unconstrained model side effect.

## Execution rule

- low risk + no explicit confirmation requirement: may execute automatically.
- medium risk: may execute automatically unless the Tool contract requests confirmation.
- high risk: always requires explicit user confirmation.
- disabled/unbound resources: never executable, even after an earlier approval request.
- MCP tools receive a conservative risk classification when the remote protocol does not publish one.

## Approval lifecycle

1. Model selects a Tool and exact arguments.
2. Runtime validates Tool governance before any side effect.
3. If confirmation is required, Runtime creates an immutable action fingerprint and returns `AUTH_REQUIRED`.
4. Go persists the authoritative continuation; raw arguments are never accepted back from the browser.
5. UI shows a browser-safe approval card with redacted argument preview.
6. User chooses `approve` or `reject`.
7. Go reloads current Agent/Tool/MCP + Project Runtime bindings and uses DB CAS to acquire resume execution.
8. Python reconstructs the Tool registry, recomputes the fingerprint, and rejects execution if Tool configuration or arguments no longer match.
9. An approved side-effect is executed once without automatic retry. Ambiguous execution failures fail closed rather than restoring the approval and risking a duplicate side effect.
10. `approval`, `tool`, and `mcp` Trace events provide an audit trail.

## Security invariants

- Approval is not permission: disabled or Project-unbound resources remain blocked.
- Browser approval never carries authoritative Tool arguments, endpoint, continuation state, or a replacement fingerprint.
- Approval is bound to exact Tool identity/configuration + canonical arguments through SHA-256.
- Duplicate/concurrent approval clicks are rejected by the existing Task state CAS.
- High-impact approved calls do not use transient automatic retry.
- Approval previews redact password/token/secret/credential/OTP/API-key style fields and obvious inline secret values.
- Rejecting an action completes the task without calling the Tool.

## Project Runtime interaction

Project Runtime continues to define the effective Agent / Tool / MCP pool. A pending approval does not freeze old permissions; resources are reloaded and re-filtered at resume time.

## User experience

The user sees a natural “需要你的确认” card with:

- action/tool name
- risk level
- safe argument preview
- `取消操作`
- `确认执行`

Technical continuation/fingerprint details remain server-side and in developer observability only.
