from __future__ import annotations

from dataclasses import dataclass

from app.tools.contracts import (
    ToolDefinition,
    ToolErrorType,
)


@dataclass(
    frozen=True,
    slots=True,
)
class ToolGovernanceDecision:
    """
    Tool Governance 的纯策略结果。

    Policy 只负责回答：

        这个 Tool 当前能不能执行？

    它不负责真正执行 Tool。
    """

    allowed: bool

    requires_approval: bool = False

    error_type: (
        ToolErrorType
        | None
    ) = None

    reason: str = ""


class ToolGovernancePolicy:
    """
    AgentMesh Tool Governance V1.

    当前规则：

    disabled
        永远拒绝。

    high risk
        默认必须人工批准。

    requiresConfirmation=true
        必须人工批准。

    medium / low
        在没有额外确认要求时自动执行。

    approved=True
        可以绕过“人工批准”限制，
        但不能绕过 disabled。

    也就是说：

        Approval
        ≠
        Permission

    即使用户批准了，
    一个 disabled Tool
    依然不能执行。
    """

    def evaluate(
        self,
        tool: ToolDefinition,
        *,
        approved: bool = False,
    ) -> ToolGovernanceDecision:

        # =================================================
        # 1. Disabled
        # =================================================

        if not tool.enabled:
            return ToolGovernanceDecision(
                allowed=False,

                requires_approval=False,

                error_type=(
                    ToolErrorType
                    .PERMISSION_DENIED
                ),

                reason=(
                    f"tool disabled: "
                    f"{tool.name}"
                ),
            )

        # =================================================
        # 2. Explicit Approval
        #
        # Approval 只允许绕过：
        #
        # high risk
        # requires_confirmation
        #
        # 不允许绕过 disabled。
        # =================================================

        if approved:
            return ToolGovernanceDecision(
                allowed=True,
                reason=(
                    "human approval granted"
                ),
            )

        # =================================================
        # 3. High Risk
        # =================================================

        if (
            tool.risk_level
            == "high"
        ):
            return ToolGovernanceDecision(
                allowed=False,

                requires_approval=True,

                error_type=(
                    ToolErrorType
                    .REQUIRES_APPROVAL
                ),

                reason=(
                    "high-risk tool "
                    "requires human approval"
                ),
            )

        # =================================================
        # 4. Explicit Confirmation Requirement
        # =================================================

        if (
            tool
            .requires_confirmation
        ):
            return ToolGovernanceDecision(
                allowed=False,

                requires_approval=True,

                error_type=(
                    ToolErrorType
                    .REQUIRES_APPROVAL
                ),

                reason=(
                    "tool requires "
                    "human confirmation"
                ),
            )

        # =================================================
        # 5. Auto Execute
        # =================================================

        return ToolGovernanceDecision(
            allowed=True,
            reason=(
                "tool execution allowed"
            ),
        )