# AgentMesh V4 Platform Ecosystem Architecture

V4 将 AgentMesh 从“可运行、可治理的 Agent 平台”扩展为“可被外部开发者调用、发布和扩展的平台生态”。V4 不绕过既有项目边界：Public API、SDK、Marketplace 安装和 Package 发布都继续受 Project / RBAC / BYOK / Audit / Runtime 安全边界约束。

## 1. 总体结构

```text
External App / CI / Backend
        │
        │ Service Account API Key
        ▼
/openapi/v1
        │
        ├── tasks/run
        ├── tasks/:id
        └── marketplace
        │
        ▼
Go Control Plane
        │
        ├── Scope / Project Boundary
        ├── Idempotency
        ├── API Usage
        ├── Marketplace / Version Registry
        └── Project Installation
        │
        ├───────────────┐
        ▼               ▼
Python Runtime       Agent / MCP Registry
```

React 的“生态中心”是内部治理界面；Public API 是外部集成界面。两者共享同一组服务层和数据库边界。


## 2. Personal Model Pool 与任务级模型路由

个人 BYOK 从单配置扩展为 `user_model_services` 模型服务池。每个服务独立保存 Provider、Base URL、文本模型、可选视觉模型、启用状态、自动路由状态和默认标记；API Key 仍只以 AES-GCM 密文保存。旧 `user_model_providers` 数据在首次读取时一次性迁移到新服务池，兼容 HTTP API 随后也从服务池投影返回。

工作台默认提交：

```text
modelSelection = { mode: "auto" }
```

也允许用户为当前任务显式选择一个自己的服务：

```text
modelSelection = { mode: "manual", serviceId: 123 }
```

路由优先级为：

1. 用户当前任务显式指定的个人模型服务；
2. 个人模型池中 `enabled + auto_route` 的候选集合；
3. 当用户没有可用个人模型服务时，才允许按既有 Project Governance 回退到项目管理员显式配置的项目模型。

`manual` 模式必须命中当前用户拥有且已启用的服务，不允许静默换模型。用户存在个人模型、但主动把所有服务移出自动路由时，`auto` 模式也 fail-closed，不会偷偷消费共享项目凭据。图片任务会先过滤没有显式视觉模型的服务。

P7 `AdaptiveModelRouter` 继续负责自动模式下的质量、可靠性、延迟、成本和冷启动探索评分。个人服务以 request-local candidate 进入 Router，不注册到全局 `RuntimeContext`，避免跨用户污染。默认服务只在冷启动同分时作为稳定偏好。

对于 durable task，MySQL / Queue 只持久化 `model_selection_json`，不持久化 API Key 或整个 Model Pool。Worker 真正 dispatch 时由 Go Control Plane 根据当前用户、项目边界与服务状态重新解析密钥，再通过可信内部 Go → Python 通道短暂发送本次请求候选。

## 3. Service Account

Service Account 是项目级机器身份。创建时返回一次性 API Key：

```text
am_sk_<prefix>_<high-entropy-secret>
```

数据库仅保存：

- `key_prefix`
- SHA-256 `secret_hash`
- Project ID
- Scope
- Status / Expiration
- Usage metadata

Raw Key 不持久化，也不会出现在列表 API、Audit 或浏览器持久状态中。

当前 Scope：

- `tasks:read`
- `tasks:write`
- `marketplace:read`
- `ecosystem:read`

## 4. Public API

V4 Public API 位于：

```text
/openapi/v1
```

支持：

- `POST /tasks/run`
- `GET /tasks/{id}`
- `GET /marketplace`
- `GET /marketplace/{slug}`

Public API Principal 始终绑定到创建 Service Account 的 Project。Public Task 创建的 Conversation 也必须绑定同一 Project。

`POST /tasks/run` 支持 `Idempotency-Key`。同一 Service Account + 同一 Key + 同一请求返回首次结果；相同 Key 对不同 payload 返回冲突，不允许重复执行。

## 5. Marketplace Registry

统一 Package Kind：

- `AGENT`
- `MCP`
- `PLUGIN`

Package 与 Version 分离：Package 保存 ownership / visibility / latest version；Version 保存 Manifest / checksum / validation state。

Manifest 使用闭合 typed schema，不提供任意 secret extension map。

## 6. Project Installation

安装行为受 Project RBAC 约束：

- 普通安全 Package：`DEVELOPER` 可安装。
- 包含 `network:outbound` 或 `mcp:connect`：要求 `ADMIN`。

Agent / MCP Package 安装后会实体化为现有 Agent/MCP 资源，继续复用已有 Runtime 和治理路径。Plugin V4 采用 Registry 安装语义，不执行任意第三方本地代码。

## 7. Publisher / Versioning

Publisher 可：

- 创建 Package
- 添加 Version
- 校验 Manifest
- Publish
- Export Bundle
- Import Bundle

Slug 全局唯一；Version 使用语义版本格式。未发布私有 Package 仅 Owner 可见；Public Marketplace 只暴露 `PUBLIC + PUBLISHED` Package。

## 8. Observability

V4 记录：

- Service Account last-used
- request / error count
- latency aggregate
- package install count
- Audit events

敏感值不进入普通观测数据。

## 9. 非目标

V4 不实现：

- 任意第三方 Plugin 二进制在服务器直接执行
- 自动信任未知 MCP endpoint
- Public API 绕过 Project Governance
- 全局共享 API Key
- Marketplace 作为远程代码执行通道

这些边界是平台安全设计的一部分。
