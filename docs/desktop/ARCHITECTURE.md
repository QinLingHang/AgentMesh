# AgentMesh Local Desktop Integration

## Scope

Phase 1 intentionally implements **safe local filesystem access**, not arbitrary shell/GUI control.

```text
Browser / Workspace
        |
Go Control Plane
  Tool ownership / project scope / human approval
        |
Python Runtime
  ToolLoop + final governance boundary
        |
Desktop Bridge client
  token kept server-side only
        |
127.0.0.1:9583
AgentMesh Desktop Bridge
        |
Authorized local roots only
```

The Desktop Bridge is a separate process so the Runtime does not receive unrestricted filesystem authority simply because it runs on the same machine.

## Official tools

- `local.fs.list`
- `local.fs.stat`
- `local.fs.read`
- `local.fs.search`
- `local.fs.write`
- `local.fs.mkdir`
- `local.fs.copy`
- `local.fs.move`
- `local.fs.delete`

Read-only operations are low risk. All writes require human confirmation. Move/delete are high risk and always require confirmation.

## Project scope

The official tools are normal AgentMesh Tool resources. Personal workspaces can use the user's enabled tools. Shared projects still use the existing project Tool binding/governance path; local desktop access is never implicitly granted to a project.
