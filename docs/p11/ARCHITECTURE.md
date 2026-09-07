# P11 Productization Architecture

```text
Browser
  |
  | production same-origin /api
  v
AgentMesh product shell
  |
  +-- Workspace (eager primary path)
  |     +-- Run Details (lazy)
  |
  +-- Agents (lazy)
  +-- Knowledge Center (lazy)
  +-- Extensions (lazy)
  +-- Tasks (lazy)
  +-- Governance (lazy)
  |
  +-- AppErrorBoundary
  +-- Suspense loading state
  +-- friendlyApiError
```

## Error boundary

API failures and React render failures are intentionally separate:

- API failures become safe/actionable product messages.
- Render failures are isolated to the active product panel.
- Switching tabs resets the render boundary.
- No raw secret/token material is introduced into error UI.

## Browser E2E boundary

The mandatory P11 deterministic browser E2E runs the real `dist/` assets in a
real Chrome/Chromium/Edge process. A local mock API provides stable data so the
browser test is not coupled to email verification, external model providers, or
Docker Hub availability.

Backend correctness remains covered by P1-P10 Go/Python/MySQL integration tests.
Final live Browser → Gateway → Go → Python → DB behavior is also part of the
project-wide final manual acceptance after P12.
