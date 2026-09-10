# AgentMesh V4 Public API

Public API base path：`/openapi/v1`。机器调用使用项目级 Service Account。

规范文件：`docs/v4/openapi.yaml`。

## Authentication

推荐：

```http
Authorization: Bearer am_sk_...
```

兼容：

```http
X-AgentMesh-Key: am_sk_...
```

Key 只在 Service Account 创建时返回一次。撤销或过期后立即失效。

## Scopes

| Scope | 能力 |
| --- | --- |
| `tasks:read` | 读取所属项目 Public API 创建的任务 |
| `tasks:write` | 提交任务 |
| `marketplace:read` | 浏览公开 Marketplace |
| `ecosystem:read` | 预留生态读取能力 |

## Idempotency

任务提交建议总是携带：

```http
Idempotency-Key: order-sync-20260907-001
```

服务端以 `ServiceAccountID + Idempotency-Key` 隔离，不同 Service Account 的相同 Key 不冲突。

行为：

1. 首次请求执行并持久化结果。
2. 相同 Key + 相同 payload 返回首次结果，并返回 `X-Idempotent-Replay: true`。
3. 相同 Key + 不同 payload 返回 `409`。
4. 未完成 reservation 不被当作成功结果。

## API Envelope

成功：

```json
{"code":0,"message":"ok","data":{}}
```

失败：

```json
{"code":40340,"message":"当前服务账号缺少所需 API Scope","data":null}
```

## Project Boundary

Service Account 不能在请求里切换 Project。Task / Conversation / Marketplace 权限由服务端 Principal 决定，客户端不能通过传参跨 Project。
