# P3 Memory Architecture

## Scope rule

AgentMesh now treats long-term Memory and Knowledge as two different domains:

- **Memory is User-global.** Its owner is `user_id` and it may later be used across normal conversations and all Projects owned by that same user.
- **Project Knowledge is strictly Project-scoped.** Its retrieval scope continues to depend on the current Project and must not become global just because Memory is global.

The P3.1 schema intentionally has no `project_id` column in `user_memories`.

## P3.1 responsibility

P3.1 only builds the durable Memory foundation:

`JWT -> Memory Handler -> Memory Service -> Memory Repository -> MySQL user_memories`

The Python Runtime does not write memories in P3.1. It also does not receive memories in task prompts yet.

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

`UNIQUE(user_id, memory_key)` means one user has one authoritative row for one logical memory key. This is deliberate groundwork for later merge/update behavior in P3.2.

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

P3.1 intentionally does **not** allow an `inferred_user` source because automatic model extraction is not implemented yet.

## Current status

P3.1 supports `active` only. Deletion follows the project's existing hard-delete CRUD style.
