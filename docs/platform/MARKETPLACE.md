# AgentMesh Marketplace / Registry

## Package kinds

### AGENT

Manifest 包含：

- name
- endpoint
- protocol (`http` / `a2a` / `internal`)
- capabilities
- provider / modelName（可选）

### MCP

Manifest 包含：

- name
- transport（为 `streamable_http`）
- endpoint
- connectTimeoutMs
- callTimeoutMs

### PLUGIN

Plugin 采用 Registry 语义，支持 metadata、capabilities、config schema 和 permission 声明，不直接执行任意上传代码。

## Endpoint validation

远程 endpoint 必须：

- HTTPS
- 无 URL userinfo
- 非 localhost
- 非 `.local` / `.internal`
- 非 loopback / private / link-local IP

Agent `internal` protocol 只允许显式 `internal://` 路径。

## Permissions

当前允许声明：

- `knowledge:read`
- `memory:read`
- `tools:invoke`
- `tasks:submit`
- `network:outbound`
- `mcp:connect`

高风险权限 `network:outbound` / `mcp:connect` 在 Project 安装时要求 ADMIN。

## Versioning

Package 和 Version 分离：

```text
Package
 ├── 1.0.0
 ├── 1.1.0
 └── 2.0.0-beta.1
```

Version Manifest 会生成 SHA-256 checksum。Publish 只允许已通过 typed validation 的 Version。

## Import / Export

Export Bundle 包含 Package metadata + 单个 Version Manifest。Import 仍重新经过当前服务端 validation，不信任 Bundle 中原始状态。
