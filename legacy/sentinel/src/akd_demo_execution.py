"""Truthful demo-order execution boundary.

This module deliberately separates a strategy decision from broker execution.
A successful result requires both an order identifier and an independent
verification result. Network responses, HTTP 200, or an internal paper-book
write are never sufficient evidence of execution.

Only the AKD virtual-trading account is allowed by the repository governance.
The live broker is never a valid endpoint for this client.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import os


class ExecutionStatus(str, Enum):
    VERIFIED = "VERIFIED"
    SUBMITTED = "SUBMITTED_NOT_VERIFIED"
    REJECTED = "REJECTED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class ExecutionResult:
    status: ExecutionStatus
    symbol: str
    side: str
    quantity: int
    requested_price: float
    order_id: str | None = None
    broker_status: str | None = None
    verification: str | None = None
    message: str = ""

    @property
    def verified(self) -> bool:
        return self.status is ExecutionStatus.VERIFIED and bool(
            self.order_id and self.verification
        )


class DemoExecutor:
    """Abstract demo executor.

    The concrete AKD transport is intentionally not guessed. The old bot had
    no order transport at all, so inventing an endpoint here would create
    exactly the false-success failure this boundary is meant to prevent.
    """

    def submit_and_verify(
        self,
        *,
        symbol: str,
        quantity: int,
        price: float,
        side: str = "BUY",
    ) -> ExecutionResult:
        raise NotImplementedError


class UnconfiguredAKDDemoExecutor(DemoExecutor):
    """Fail-closed executor used until the verified AKD demo transport exists."""

    def submit_and_verify(
        self,
        *,
        symbol: str,
        quantity: int,
        price: float,
        side: str = "BUY",
    ) -> ExecutionResult:
        return ExecutionResult(
            status=ExecutionStatus.UNAVAILABLE,
            symbol=symbol,
            side=side,
            quantity=quantity,
            requested_price=price,
            message=(
                "AKD demo execution is not configured with a verified "
                "virtual-trading transport. No broker order was sent."
            ),
        )


def load_demo_executor() -> DemoExecutor:
    """Return only a demo executor.

    There is deliberately no fallback to a live broker and no pretend-success
    path. A real AKD transport must be implemented and verified before it is
    returned here.
    """
    mode = os.environ.get("TRADING_MODE", "").strip().upper()
    if mode not in {"AKD_DEMO", "AKD_VIRTUAL"}:
        return UnconfiguredAKDDemoExecutor()
    return UnconfiguredAKDDemoExecutor()


def verified_entry(
    executor: DemoExecutor,
    *,
    symbol: str,
    quantity: int,
    price: float,
) -> ExecutionResult:
    """Submit and verify one demo BUY.

    A caller must not update its portfolio or daily-entry gate unless the
    returned result is VERIFIED.
    """
    if not symbol or quantity <= 0 or price <= 0:
        raise ValueError("symbol, quantity and price must be positive")
    result = executor.submit_and_verify(
        symbol=symbol,
        quantity=quantity,
        price=price,
        side="BUY",
    )
    if result.status is ExecutionStatus.SUBMITTED:
        return ExecutionResult(
            status=ExecutionStatus.REJECTED,
            symbol=result.symbol,
            side=result.side,
            quantity=result.quantity,
            requested_price=result.requested_price,
            order_id=result.order_id,
            broker_status=result.broker_status,
            verification=None,
            message=(
                "Broker accepted a submission but independent execution "
                "verification is missing. Treat as NOT EXECUTED."
            ),
        )
    return result
