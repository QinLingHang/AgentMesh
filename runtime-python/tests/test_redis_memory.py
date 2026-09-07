import fnmatch

import pytest

from app.memory import (
    MemoryMessage,
    RedisConversationMemory,
)


class FakePipeline:
    def __init__(
        self,
        redis,
    ):
        self.redis = redis

        self.commands = []

    def rpush(
        self,
        key,
        value,
    ):
        self.commands.append(
            (
                "rpush",
                key,
                value,
            )
        )

        return self

    def ltrim(
        self,
        key,
        start,
        end,
    ):
        self.commands.append(
            (
                "ltrim",
                key,
                start,
                end,
            )
        )

        return self

    def expire(
        self,
        key,
        seconds,
    ):
        self.commands.append(
            (
                "expire",
                key,
                seconds,
            )
        )

        return self

    async def execute(
        self,
    ):
        results = []

        for command in (
            self.commands
        ):
            name = (
                command[0]
            )

            if name == "rpush":
                _, key, value = (
                    command
                )

                bucket = (
                    self.redis
                    .data
                    .setdefault(
                        key,
                        [],
                    )
                )

                bucket.append(
                    value
                )

                results.append(
                    len(bucket)
                )

            elif name == "ltrim":
                (
                    _,
                    key,
                    start,
                    end,
                ) = command

                bucket = (
                    self.redis
                    .data
                    .get(
                        key,
                        [],
                    )
                )

                self.redis.data[
                    key
                ] = (
                    self.redis
                    .slice_range(
                        bucket,
                        start,
                        end,
                    )
                )

                results.append(
                    True
                )

            elif name == "expire":
                (
                    _,
                    key,
                    seconds,
                ) = command

                self.redis.ttls[
                    key
                ] = seconds

                results.append(
                    True
                )

        return results


class FakeRedis:
    def __init__(
        self,
    ):
        self.data = {}

        self.ttls = {}

        self.closed = False

    def pipeline(
        self,
        transaction=True,
    ):
        return FakePipeline(
            self
        )

    @staticmethod
    def slice_range(
        values,
        start,
        end,
    ):
        length = len(
            values
        )

        if start < 0:
            start = max(
                0,
                length + start,
            )

        if end < 0:
            end = (
                length + end
            )

        end = min(
            end,
            length - 1,
        )

        if (
            start >= length
            or end < start
        ):
            return []

        return values[
            start:
            end + 1
        ]

    async def lrange(
        self,
        key,
        start,
        end,
    ):
        return self.slice_range(
            self.data.get(
                key,
                [],
            ),
            start,
            end,
        )

    async def expire(
        self,
        key,
        seconds,
    ):
        if key in self.data:
            self.ttls[
                key
            ] = seconds

            return True

        return False

    async def delete(
        self,
        key,
    ):
        existed = (
            key in self.data
        )

        self.data.pop(
            key,
            None,
        )

        self.ttls.pop(
            key,
            None,
        )

        return (
            1
            if existed
            else 0
        )

    async def ping(
        self,
    ):
        return True

    async def aclose(
        self,
    ):
        self.closed = True


def create_memory(
    *,
    max_messages=20,
    ttl_seconds=3600,
):
    redis = (
        FakeRedis()
    )

    memory = (
        RedisConversationMemory(
            redis_url=(
                "redis://unused"
            ),

            max_messages=(
                max_messages
            ),

            ttl_seconds=(
                ttl_seconds
            ),

            key_prefix=(
                "agentmesh:test"
            ),

            client=redis,
        )
    )

    return (
        memory,
        redis,
    )


@pytest.mark.asyncio
async def test_redis_memory_round_trip():
    memory, redis = (
        create_memory()
    )

    await memory.append(
        user_id=1,
        conversation_id=10,

        message=(
            MemoryMessage(
                role="user",
                content="hello",
            )
        ),
    )

    await memory.append(
        user_id=1,
        conversation_id=10,

        message=(
            MemoryMessage(
                role="assistant",
                content="hi",
            )
        ),
    )

    messages = (
        await memory.recent(
            user_id=1,
            conversation_id=10,
        )
    )

    assert [
        item.content
        for item
        in messages
    ] == [
        "hello",
        "hi",
    ]

    assert (
        redis.ttls[
            "agentmesh:test:1:10"
        ]
        == 3600
    )


@pytest.mark.asyncio
async def test_redis_memory_isolates_users_and_conversations():
    memory, _ = (
        create_memory()
    )

    await memory.append(
        user_id=1,
        conversation_id=10,

        message=MemoryMessage(
            role="user",
            content="user-1",
        ),
    )

    await memory.append(
        user_id=2,
        conversation_id=10,

        message=MemoryMessage(
            role="user",
            content="user-2",
        ),
    )

    await memory.append(
        user_id=1,
        conversation_id=11,

        message=MemoryMessage(
            role="user",
            content="conversation-11",
        ),
    )

    first = (
        await memory.recent(
            user_id=1,
            conversation_id=10,
        )
    )

    second = (
        await memory.recent(
            user_id=2,
            conversation_id=10,
        )
    )

    third = (
        await memory.recent(
            user_id=1,
            conversation_id=11,
        )
    )

    assert (
        first[0].content
        == "user-1"
    )

    assert (
        second[0].content
        == "user-2"
    )

    assert (
        third[0].content
        == "conversation-11"
    )


@pytest.mark.asyncio
async def test_redis_memory_sliding_window():
    memory, redis = (
        create_memory(
            max_messages=3
        )
    )

    for index in range(
        5
    ):
        await memory.append(
            user_id=1,
            conversation_id=1,

            message=MemoryMessage(
                role="user",

                content=(
                    f"message-{index}"
                ),
            ),
        )

    messages = (
        await memory.recent(
            user_id=1,
            conversation_id=1,
        )
    )

    assert [
        item.content
        for item
        in messages
    ] == [
        "message-2",
        "message-3",
        "message-4",
    ]

    assert (
        len(
            redis.data[
                "agentmesh:test:1:1"
            ]
        )
        == 3
    )


@pytest.mark.asyncio
async def test_redis_memory_clear():
    memory, _ = (
        create_memory()
    )

    await memory.append(
        user_id=1,
        conversation_id=1,

        message=MemoryMessage(
            role="user",
            content="hello",
        ),
    )

    await memory.clear(
        user_id=1,
        conversation_id=1,
    )

    assert (
        await memory.recent(
            user_id=1,
            conversation_id=1,
        )
    ) == []


@pytest.mark.asyncio
async def test_redis_memory_ping():
    memory, _ = (
        create_memory()
    )

    assert (
        await memory.ping()
        is True
    )