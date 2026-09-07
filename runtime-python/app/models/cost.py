from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CostStatus = Literal["actual", "estimated", "unavailable"]


@dataclass(frozen=True, slots=True)
class ModelPricing:
    input_cost_per_million: float = 0.0
    output_cost_per_million: float = 0.0
    currency: str = "USD"

    @property
    def configured(self) -> bool:
        return self.input_cost_per_million > 0 or self.output_cost_per_million > 0


@dataclass(frozen=True, slots=True)
class UsageCost:
    amount: float | None
    status: CostStatus
    currency: str = "USD"


class UsageCostCalculator:
    @staticmethod
    def calculate(
        *,
        input_tokens: int,
        output_tokens: int,
        pricing: ModelPricing,
    ) -> UsageCost:
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("token usage cannot be negative")
        if not pricing.configured:
            return UsageCost(amount=None, status="unavailable", currency=pricing.currency)
        amount = (
            input_tokens / 1_000_000.0 * max(0.0, pricing.input_cost_per_million)
            + output_tokens / 1_000_000.0 * max(0.0, pricing.output_cost_per_million)
        )
        return UsageCost(amount=round(amount, 12), status="estimated", currency=pricing.currency)
