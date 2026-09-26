"""OMS domain models: orders, fills, positions, enums."""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field
from enum import Enum


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class TimeInForce(str, Enum):
    DAY = "DAY"
    GTC = "GTC"
    IOC = "IOC"  # immediate-or-cancel: fill what you can, cancel the rest
    FOK = "FOK"  # fill-or-kill: fill everything or nothing


class OrderStatus(str, Enum):
    NEW = "NEW"                      # accepted by OMS, not yet sent
    ACKNOWLEDGED = "ACKNOWLEDGED"    # venue accepted, working
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"            # failed pre-trade compliance
    EXPIRED = "EXPIRED"


OPEN_STATUSES = {OrderStatus.NEW, OrderStatus.ACKNOWLEDGED, OrderStatus.PARTIALLY_FILLED}
TERMINAL_STATUSES = {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED}

_order_ids = itertools.count(1)
_fill_ids = itertools.count(1)


def new_order_id() -> str:
    return f"ORD-{next(_order_ids):06d}"


def new_fill_id() -> str:
    return f"FILL-{next(_fill_ids):06d}"


@dataclass
class Fill:
    fill_id: str
    order_id: str
    symbol: str
    side: Side
    quantity: int
    price: float
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "fill_id": self.fill_id, "order_id": self.order_id, "symbol": self.symbol,
            "side": self.side.value, "quantity": self.quantity, "price": round(self.price, 2),
            "timestamp": self.timestamp,
        }


@dataclass
class Order:
    order_id: str
    symbol: str
    side: Side
    quantity: int
    order_type: OrderType
    time_in_force: TimeInForce = TimeInForce.DAY
    limit_price: float | None = None
    stop_price: float | None = None
    status: OrderStatus = OrderStatus.NEW
    filled_quantity: int = 0
    avg_fill_price: float | None = None
    reject_reason: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    fills: list[Fill] = field(default_factory=list)

    @property
    def remaining(self) -> int:
        return self.quantity - self.filled_quantity

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES

    def apply_fill(self, fill: Fill) -> None:
        prev_notional = (self.avg_fill_price or 0.0) * self.filled_quantity
        self.filled_quantity += fill.quantity
        self.avg_fill_price = (prev_notional + fill.price * fill.quantity) / self.filled_quantity
        self.fills.append(fill)
        self.updated_at = time.time()
        self.status = (
            OrderStatus.FILLED if self.remaining == 0 else OrderStatus.PARTIALLY_FILLED
        )

    def to_dict(self) -> dict:
        return {
            "order_id": self.order_id, "symbol": self.symbol, "side": self.side.value,
            "quantity": self.quantity, "order_type": self.order_type.value,
            "time_in_force": self.time_in_force.value, "limit_price": self.limit_price,
            "stop_price": self.stop_price, "status": self.status.value,
            "filled_quantity": self.filled_quantity,
            "avg_fill_price": round(self.avg_fill_price, 2) if self.avg_fill_price else None,
            "remaining": self.remaining, "reject_reason": self.reject_reason,
            "created_at": self.created_at, "updated_at": self.updated_at,
            "fills": [f.to_dict() for f in self.fills],
        }


@dataclass
class Position:
    symbol: str
    quantity: int = 0
    avg_price: float = 0.0

    def to_dict(self, ref_price: float | None = None) -> dict:
        d = {"symbol": self.symbol, "quantity": self.quantity, "avg_price": round(self.avg_price, 2)}
        if ref_price is not None:
            d["market_value"] = round(self.quantity * ref_price, 2)
            d["unrealized_pnl"] = round(self.quantity * (ref_price - self.avg_price), 2)
        return d
