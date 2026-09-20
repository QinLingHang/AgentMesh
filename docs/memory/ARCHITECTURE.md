# Memory Architecture

## Scope rule

AgentMesh now treats long-term Memory and Knowledge as two different domains:

- **Memory is User-global.** Its owner is `user_id` and it may later be used across normal conversations and all Projects owned by that same user.
- **Project Knowledge is strictly Project-scoped.** Its retrieval scope continues to depend on the current Project and must not become global just because Memory is global.

The Memory schema intentionally has no `project_id` column in `user_memories`.

## Memory foundation responsibility

The durable Memory foundation provides:

`JWT -> Memory Handler -> Memory Service -> Memory Repository -> MySQL user_memories`

The durable storage layer is separated from runtime write and prompt-assembly behaviour.

An internal-token-protected read contract is prepared at:

`GET /internal/v1/users/:userId/memories`

This returns active memories for a user, but no runtime code consumes it yet.

## Ownership

Every row is owned by a user. CRUD reads and writes are always constrained by both resource ID and `user_id`.

Examples:

- `WHERE id = ? AND user_id = ?`
- `WHERE user_id = ? AND memory_key = ?`

Knowing another user's memory ID does not grant access.

## Stable key

`memory_key` is normalized to lowercase and limited to `[a-z0-9._-]` with a maximum length of 128 characters.

`UNIQUE(user_id, memory_key)` means one user has one authoritative row for one logical memory key. This provides deterministic merge/update behaviour for later memory writes.

Examples:

- `coding.explanation_style`
- `ui.language`
- `career.target_role`

## Current categories

- `preference`
- `profile`
- `goal`
- `workflow`
- `fact`
- `other`

## Current sources

- `explicit_user`
- `manual`

The base API intentionally restricts memory sources; inferred writes are handled by the automatic-memory layer.

## Current status

Active memories use the project's existing deletion semantics.
