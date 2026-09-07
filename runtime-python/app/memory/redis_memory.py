from __future__ import annotations

import json

from typing import (
    Any,
)

from redis.asyncio import (
    Redis,
)

from app.memory.runtime import (
    MemoryMessage,
)


class RedisConversationMemory:
    """
    Redis Short-term Conversation Memory.

    Storage:

        Redis List

    Key:

        agentmesh:memory:{user_id}:{conversation_id}

    Example:

        agentmesh:memory:7:123

    Value:

        [
            user message,
            assistant message,
            user message,
            assistant message,
            ...
        ]

    Features:

        - user isolation
        - conversation isolation
        - sliding window
        - TTL
        - persistent across Runtime restart
        - Redis AOF / volume persistence
    """

    def __init__(
        self,
        *,
        redis_url: str,
        max_messages: int = 20,
        ttl_seconds: int = (
            7
            * 24
            * 60
            * 60
        ),
        key_prefix: str = (
            "agentmesh:memory"
        ),
        client: Redis | None = None,
    ) -> None:

        if max_messages <= 0:
            raise ValueError(
                (
                    "max_messages "
                    "must be > 0"
                )
            )

        if ttl_seconds <= 0:
            raise ValueError(
                (
                    "ttl_seconds "
                    "must be > 0"
                )
            )

        if not key_prefix.strip():
            raise ValueError(
                (
                    "key_prefix "
                    "cannot be empty"
                )
            )

        self.max_messages = (
            max_messages
        )

        self.ttl_seconds = (
            ttl_seconds
        )

        self.key_prefix = (
            key_prefix.rstrip(":")
        )

        self._owns_client = (
            client is None
        )

        self._redis = (
            client
            if client is not None
            else Redis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        )

    # =====================================================
    # Key
    # =====================================================

    def _key(
        self,
        *,
        user_id: int,
        conversation_id: int,
    ) -> str:

        return (
            f"{self.key_prefix}:"
            f"{user_id}:"
            f"{conversation_id}"
        )

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

        key = self._key(
            user_id=user_id,
            conversation_id=(
                conversation_id
            ),
        )

        payload = json.dumps(
            {
                "role":
                    message.role,

                "content":
                    message.content,

                "created_at":
                    message.created_at,

                "metadata":
                    message.metadata,
            },
            ensure_ascii=False,
            separators=(
                ",",
                ":",
            ),
        )

        # -------------------------------------------------
        # Pipeline:
        #
        # RPUSH
        #   → 追加消息
        #
        # LTRIM
        #   → 只保留最近 N 条
        #
        # EXPIRE
        #   → 刷新 TTL
        #
        # transaction=True:
        #   Redis MULTI / EXEC
        # -------------------------------------------------

        pipeline = (
            self._redis.pipeline(
                transaction=True
            )
        )

        pipeline.rpush(
            key,
            payload,
        )

        pipeline.ltrim(
            key,
            -self.max_messages,
            -1,
        )

        pipeline.expire(
            key,
            self.ttl_seconds,
        )

        await pipeline.execute()

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

        if limit is None:
            limit = (
                self.max_messages
            )

        if limit <= 0:
            return []

        limit = min(
            limit,
            self.max_messages,
        )

        key = self._key(
            user_id=user_id,
            conversation_id=(
                conversation_id
            ),
        )

        # Redis:
        #
        # LRANGE key -8 -1
        #
        # = 最近 8 条
        raw_messages = (
            await self._redis
            .lrange(
                key,
                -limit,
                -1,
            )
        )

        if not raw_messages:
            return []

        messages: list[
            MemoryMessage
        ] = []

        for raw in raw_messages:
            try:
                payload = (
                    json.loads(
                        raw
                    )
                )

                metadata = (
                    payload.get(
                        "metadata"
                    )
                    or {}
                )

                if not isinstance(
                    metadata,
                    dict,
                ):
                    metadata = {}

                messages.append(
                    MemoryMessage(
                        role=(
                            payload[
                                "role"
                            ]
                        ),

                        content=str(
                            payload[
                                "content"
                            ]
                        ),

                        created_at=float(
                            payload.get(
                                "created_at",
                                0.0,
                            )
                            or 0.0
                        ),

                        metadata=(
                            metadata
                        ),
                    )
                )

            except (
                json.JSONDecodeError,
                KeyError,
                TypeError,
                ValueError,
            ):
                # -----------------------------------------
                # 某一条 Memory 数据损坏，
                # 不应该导致整个会话不可用。
                #
                # 当前 V1：
                # 跳过损坏消息。
                #
                # 后续可以增加：
                # corruption metric / audit。
                # -----------------------------------------

                continue

        # -------------------------------------------------
        # Sliding TTL
        #
        # 读取说明会话仍然活跃，
        # 因此刷新过期时间。
        # -------------------------------------------------

        if messages:
            await self._redis.expire(
                key,
                self.ttl_seconds,
            )

        return messages

    # =====================================================
    # Clear
    # =====================================================

    async def clear(
        self,
        *,
        user_id: int,
        conversation_id: int,
    ) -> None:

        key = self._key(
            user_id=user_id,
            conversation_id=(
                conversation_id
            ),
        )

        await self._redis.delete(
            key
        )

    # =====================================================
    # Health
    # =====================================================

    async def ping(
        self,
    ) -> bool:

        result = (
            await self._redis.ping()
        )

        return bool(
            result
        )

    # =====================================================
    # Lifecycle
    # =====================================================

    async def aclose(
        self,
    ) -> None:

        if not self._owns_client:
            return

        await self._redis.aclose()