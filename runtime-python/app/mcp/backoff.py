from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from app.mcp.contracts import (
    MCPServerDefinition,
)


@dataclass(slots=True)
class MCPBackoffEntry:
    """
    保存一个 MCP Server 的连续失败状态。

    consecutive_failures:
        连续失败次数。

    retry_at:
        基于 monotonic clock 的下次允许尝试时间。

    error_type / message:
        最近一次失败原因，用于 Trace / Debug。
    """

    consecutive_failures: int

    retry_at: float

    error_type: str = ""

    message: str = ""


@dataclass(slots=True)
class MCPBackoffDecision:
    """
    Runtime 在一次 Task 开始前，
    查询某个 MCP Server 是否应该被暂时跳过。
    """

    blocked: bool

    remaining_ms: int = 0

    consecutive_failures: int = 0

    error_type: str = ""

    message: str = ""


class MCPFailureBackoff:
    """
    MCP Server 失败抑制器。

    当前设计：
        第一次失败 -> 30s
        第二次失败 -> 60s
        第三次失败 -> 120s
        ...
        最大不超过 max_seconds。

    成功后：
        清空失败状态。

    为什么使用 time.monotonic()：
        Backoff 关心的是“过去多少秒”，
        而不是系统当前日期时间。

        monotonic clock 不会因为用户修改系统时间、
        NTP 校时而向后跳。
    """

    def __init__(
        self,
        base_seconds: float = 30.0,
        max_seconds: float = 300.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if base_seconds <= 0:
            raise ValueError(
                "base_seconds must be > 0"
            )

        if max_seconds < base_seconds:
            raise ValueError(
                (
                    "max_seconds must be "
                    ">= base_seconds"
                )
            )

        self.base_seconds = (
            float(
                base_seconds
            )
        )

        self.max_seconds = (
            float(
                max_seconds
            )
        )

        self._clock = (
            clock
            or time.monotonic
        )

        self._entries: dict[
            tuple[int, str],
            MCPBackoffEntry,
        ] = {}

    @staticmethod
    def _key(
        server: MCPServerDefinition,
    ) -> tuple[int, str]:
        """
        ID + Endpoint 一起组成身份。

        这样用户修改同一个 Server 的 Endpoint 后，
        不会继续被旧 Endpoint 的失败状态误伤。
        """

        return (
            server.id,
            server.endpoint,
        )

    def decision(
        self,
        server: MCPServerDefinition,
    ) -> MCPBackoffDecision:
        key = self._key(
            server
        )

        entry = (
            self._entries.get(
                key
            )
        )

        if entry is None:
            return MCPBackoffDecision(
                blocked=False
            )

        now = self._clock()

        remaining = (
            entry.retry_at
            - now
        )

        if remaining <= 0:
            # Backoff 到期。
            #
            # 这里不删除 entry，
            # 因为如果下一次 Probe 再失败，
            # 我们希望继续增加连续失败次数。
            return MCPBackoffDecision(
                blocked=False,
                consecutive_failures=(
                    entry
                    .consecutive_failures
                ),
                error_type=(
                    entry.error_type
                ),
                message=(
                    entry.message
                ),
            )

        return MCPBackoffDecision(
            blocked=True,

            remaining_ms=max(
                1,
                int(
                    remaining
                    * 1000
                ),
            ),

            consecutive_failures=(
                entry
                .consecutive_failures
            ),

            error_type=(
                entry.error_type
            ),

            message=(
                entry.message
            ),
        )

    def record_failure(
        self,
        server: MCPServerDefinition,
        *,
        error_type: str = "",
        message: str = "",
    ) -> MCPBackoffEntry:
        key = self._key(
            server
        )

        previous = (
            self._entries.get(
                key
            )
        )

        if previous is None:
            failures = 1

        else:
            failures = (
                previous
                .consecutive_failures
                + 1
            )

        delay_seconds = min(
            self.max_seconds,

            self.base_seconds
            * (
                2
                ** (
                    failures
                    - 1
                )
            ),
        )

        entry = (
            MCPBackoffEntry(
                consecutive_failures=(
                    failures
                ),

                retry_at=(
                    self._clock()
                    + delay_seconds
                ),

                error_type=(
                    error_type
                ),

                message=(
                    message
                ),
            )
        )

        self._entries[
            key
        ] = entry

        return entry

    def record_success(
        self,
        server: MCPServerDefinition,
    ) -> None:
        """
        一次成功 Discovery
        即认为 Server 已恢复，
        清空连续失败状态。
        """

        self._entries.pop(
            self._key(
                server
            ),
            None,
        )

    def clear(
        self,
    ) -> None:
        """
        测试 / Runtime 重置时使用。
        """

        self._entries.clear()