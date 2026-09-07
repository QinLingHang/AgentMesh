from __future__ import annotations

import time

from dataclasses import (
    dataclass,
    field,
)

from typing import (
    Any,
    Literal,
    Protocol,
)


MemoryRole = Literal[
    "user",
    "assistant",
    "system",
    "tool",
]


# =========================================================
# Memory Domain Model
# =========================================================


@dataclass(
    frozen=True,
    slots=True,
)
class MemoryMessage:
    """
    Agent Runtime Memory 的统一消息结构。

    注意：

    这不是 OpenAI Message DTO。

    它属于 AgentMesh 自己的
    Memory Domain。

    后续 Redis / MySQL Adapter
    都使用这个领域结构。
    """

    role: MemoryRole

    content: str

    created_at: float = field(
        default_factory=time.time
    )

    metadata: dict[
        str,
        Any,
    ] = field(
        default_factory=dict
    )


# =========================================================
# Memory Contract
# =========================================================


class ConversationMemory(
    Protocol
):
    """
    对话短期记忆 Contract。

    user_id + conversation_id
    构成 Memory Scope。

    因此：

        User A / Conversation 1

    不可能读取：

        User B / Conversation 1

    这是后续多租户 Memory 隔离的基础。
    """

    async def append(
        self,
        *,
        user_id: int,
        conversation_id: int,
        message: MemoryMessage,
    ) -> None:
        ...

    async def recent(
        self,
        *,
        user_id: int,
        conversation_id: int,
        limit: int | None = None,
    ) -> list[
        MemoryMessage
    ]:
        ...

    async def clear(
        self,
        *,
        user_id: int,
        conversation_id: int,
    ) -> None:
        ...


# =========================================================
# In-Memory Baseline
# =========================================================


class InMemoryConversationMemory:
    """
    Conversation Memory Baseline。

    当前作用：

        建立 Memory Contract
        +
        验证 Agent Runtime 接入逻辑

    不是最终生产存储。

    后续替换：

        Redis
            → Short-term Memory

        MySQL
            → Long-term Memory
    """

    def __init__(
        self,
        *,
        max_messages: int = 20,
    ) -> None:

        if max_messages <= 0:
            raise ValueError(
                (
                    "max_messages "
                    "must be > 0"
                )
            )

        self.max_messages = (
            max_messages
        )

        self._messages: dict[
            tuple[
                int,
                int,
            ],
            list[
                MemoryMessage
            ],
        ] = {}

    # =====================================================
    # Append
    # =====================================================

    async def append(
        self,
        *,
        user_id: int,
        conversation_id: int,
        message: MemoryMessage,
    ) -> None:

        if not (
            message.content
            .strip()
        ):
            raise ValueError(
                (
                    "memory message "
                    "content cannot be empty"
                )
            )

        key = (
            user_id,
            conversation_id,
        )

        bucket = (
            self._messages
            .setdefault(
                key,
                [],
            )
        )

        bucket.append(
            message
        )

        # -------------------------------------------------
        # Short-term sliding window。
        #
        # 例如 max_messages=20：
        #
        # 只保留最近 20 条。
        # -------------------------------------------------

        if (
            len(bucket)
            > self.max_messages
        ):
            del bucket[
                :-self.max_messages
            ]

    # =====================================================
    # Recent
    # =====================================================

    async def recent(
        self,
        *,
        user_id: int,
        conversation_id: int,
        limit: int | None = None,
    ) -> list[
        MemoryMessage
    ]:

        key = (
            user_id,
            conversation_id,
        )

        bucket = (
            self._messages
            .get(
                key,
                [],
            )
        )

        if limit is None:
            limit = (
                self.max_messages
            )

        if limit <= 0:
            return []

        # 返回 copy，
        # 防止调用方直接修改内部 list。
        return list(
            bucket[
                -limit:
            ]
        )

    # =====================================================
    # Clear
    # =====================================================

    async def clear(
        self,
        *,
        user_id: int,
        conversation_id: int,
    ) -> None:

        self._messages.pop(
            (
                user_id,
                conversation_id,
            ),
            None,
        )