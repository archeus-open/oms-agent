"""Pre-trade compliance engine.

Runs a configurable set of checks on every new (and amended) order.
Returns a list of violations; an empty list means the order passes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .market import SimulatedMarket
from .models import Order, Side


@dataclass
class ComplianceConfig:
    max_order_notional: float = 5_000_000.0      # per-order notional cap
    max_position_notional: float = 25_000_000.0  # per-symbol gross position cap
    max_daily_notional: float = 100_000_000.0    # gross traded notional per day
    price_collar_pct: float = 0.10               # limit price must be within +/-10% of ref
    restricted_symbols: set[str] = field(default_factory=lambda: {"GME", "AMC"})
    allowed_tifs: set[str] = field(default_factory=lambda: {"DAY", "GTC", "IOC", "FOK"})


@dataclass
class Violation:
    rule: str
    message: str


class ComplianceEngine:
    def __init__(self, config: ComplianceConfig | None = None,
                 market: SimulatedMarket | None = None) -> None:
        self.config = config or ComplianceConfig()
        self.market = market or SimulatedMarket()
        self._daily_notional: float = 0.0

    @property
    def daily_notional(self) -> float:
        return self._daily_notional

    def record_fill_notional(self, notional: float) -> None:
        self._daily_notional += abs(notional)

    def reset_day(self) -> None:
        self._daily_notional = 0.0

    def check(self, order: Order, current_position_qty: int = 0) -> list[Violation]:
        """Validate `order` against all configured rules."""
        cfg = self.config
        v: list[Violation] = []
        symbol = order.symbol.upper()

        if order.quantity <= 0:
            v.append(Violation("POSITIVE_QTY", "Order quantity must be positive."))
            return v  # nothing else is meaningful

        if symbol in cfg.restricted_symbols:
            v.append(Violation("RESTRICTED_SYMBOL",
                               f"{symbol} is on the restricted list."))

        if order.time_in_force.value not in cfg.allowed_tifs:
            v.append(Violation("INVALID_TIF",
                               f"TIF {order.time_in_force.value} is not permitted."))

        ref = self.market.reference_price(symbol)

        # Estimate notional with limit price when available, else reference.
        px = order.limit_price if order.limit_price else ref
        notional = abs(order.quantity * px)
        if notional > cfg.max_order_notional:
            v.append(Violation("MAX_ORDER_NOTIONAL",
                               f"Order notional ${notional:,.0f} exceeds "
                               f"limit ${cfg.max_order_notional:,.0f}."))

        # Position limit: would the new position breach the per-symbol cap?
        new_qty = current_position_qty + (order.quantity if order.side == Side.BUY else -order.quantity)
        pos_notional = abs(new_qty * ref)
        if pos_notional > cfg.max_position_notional:
            v.append(Violation("MAX_POSITION_NOTIONAL",
                               f"Resulting {symbol} position notional ${pos_notional:,.0f} "
                               f"exceeds limit ${cfg.max_position_notional:,.0f}."))

        # Daily gross traded notional.
        if self._daily_notional + notional > cfg.max_daily_notional:
            v.append(Violation("MAX_DAILY_NOTIONAL",
                               f"Daily gross notional would exceed "
                               f"${cfg.max_daily_notional:,.0f}."))

        # Price collar on limit orders.
        if order.limit_price:
            dev = abs(order.limit_price - ref) / ref
            if dev > cfg.price_collar_pct:
                v.append(Violation("PRICE_COLLAR",
                                   f"Limit price {order.limit_price} deviates "
                                   f"{dev:.1%} from reference {ref:.2f} "
                                   f"(collar {cfg.price_collar_pct:.0%})."))

        return v
