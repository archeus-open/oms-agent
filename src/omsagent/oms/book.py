"""Order book: the OMS's central store of orders, positions and cash."""

from __future__ import annotations

import time

from .compliance import ComplianceEngine, ComplianceConfig
from .market import SimulatedMarket
from .models import (
    OPEN_STATUSES, Fill, Order, OrderStatus, OrderType, Position, Side,
    TimeInForce, new_fill_id, new_order_id,
)


class OrderBook:
    """In-memory order book with compliance gating and fill processing."""

    def __init__(self, compliance: ComplianceEngine | None = None,
                 market: SimulatedMarket | None = None,
                 starting_cash: float = 100_000_000.0) -> None:
        self.market = market or SimulatedMarket()
        self.compliance = compliance or ComplianceEngine(market=self.market)
        self.orders: dict[str, Order] = {}
        self.positions: dict[str, Position] = {}
        self.cash = starting_cash
        self.realized_pnl = 0.0

    # ------------------------------------------------------------------ orders
    def create_order(self, symbol: str, side: Side | str, quantity: int,
                     order_type: OrderType | str = OrderType.MARKET,
                     limit_price: float | None = None,
                     stop_price: float | None = None,
                     time_in_force: TimeInForce | str = TimeInForce.DAY) -> Order:
        side = Side(side.upper()) if isinstance(side, str) else side
        order_type = OrderType(order_type.upper()) if isinstance(order_type, str) else order_type
        tif = TimeInForce(time_in_force.upper()) if isinstance(time_in_force, str) else time_in_force

        order = Order(order_id=new_order_id(), symbol=symbol.upper(), side=side,
                      quantity=int(quantity), order_type=order_type,
                      limit_price=limit_price, stop_price=stop_price,
                      time_in_force=tif)
        if order.order_type == OrderType.LIMIT and order.limit_price is None:
            order.status = OrderStatus.REJECTED
            order.reject_reason = "LIMIT orders require a limit price."
        elif order.order_type == OrderType.STOP and order.stop_price is None:
            order.status = OrderStatus.REJECTED
            order.reject_reason = "STOP orders require a stop price."
        else:
            pos_qty = self.positions.get(order.symbol, Position(order.symbol)).quantity
            violations = self.compliance.check(order, current_position_qty=pos_qty)
            if violations:
                order.status = OrderStatus.REJECTED
                order.reject_reason = "; ".join(f"[{x.rule}] {x.message}" for x in violations)
            else:
                order.status = OrderStatus.NEW
                order.updated_at = time.time()
        self.orders[order.order_id] = order
        return order

    def acknowledge(self, order: Order) -> Order:
        """Simulate venue acknowledgement of a NEW order."""
        if order.status == OrderStatus.NEW:
            order.status = OrderStatus.ACKNOWLEDGED
            order.updated_at = time.time()
        return order

    def amend_order(self, order_id: str, quantity: int | None = None,
                    limit_price: float | None = None) -> Order:
        order = self.get_order(order_id)
        if not order.is_open:
            raise ValueError(f"Cannot amend {order_id}: status is {order.status.value}.")
        if quantity is not None:
            if quantity < order.filled_quantity:
                raise ValueError("New quantity cannot be below filled quantity.")
            order.quantity = int(quantity)
        if limit_price is not None:
            if order.order_type != OrderType.LIMIT:
                raise ValueError("limit_price only applies to LIMIT orders.")
            order.limit_price = float(limit_price)
        # re-run compliance on the amended order
        pos_qty = self.positions.get(order.symbol, Position(order.symbol)).quantity
        # exclude the order's own not-yet-filled size from the position projection
        violations = self.compliance.check(order, current_position_qty=pos_qty)
        if violations:
            raise ValueError("Amendment failed compliance: " +
                             "; ".join(f"[{x.rule}] {x.message}" for x in violations))
        order.updated_at = time.time()
        return order

    def cancel_order(self, order_id: str) -> Order:
        order = self.get_order(order_id)
        if not order.is_open:
            raise ValueError(f"Cannot cancel {order_id}: status is {order.status.value}.")
        if order.filled_quantity > 0:
            # partial cancel: keep filled portion, cancel the rest
            pass
        order.status = OrderStatus.CANCELLED
        order.updated_at = time.time()
        return order

    def get_order(self, order_id: str) -> Order:
        try:
            return self.orders[order_id]
        except KeyError:
            raise KeyError(f"Unknown order id: {order_id}") from None

    def list_orders(self, status: OrderStatus | str | None = None,
                    symbol: str | None = None) -> list[Order]:
        orders = list(self.orders.values())
        if status is not None:
            status = OrderStatus(status.upper()) if isinstance(status, str) else status
            orders = [o for o in orders if o.status == status]
        if symbol is not None:
            orders = [o for o in orders if o.symbol == symbol.upper()]
        return sorted(orders, key=lambda o: o.created_at)

    @property
    def open_orders(self) -> list[Order]:
        return [o for o in self.orders.values() if o.is_open]

    # ------------------------------------------------------------------- fills
    def process_fills(self) -> list[Fill]:
        """Run one matching cycle over all open orders. Returns new fills."""
        new_fills: list[Fill] = []
        for order in self.open_orders:
            if order.status == OrderStatus.NEW:
                self.acknowledge(order)
            fills = FillSimulator.fill_order(order, self.market)
            for f in fills:
                order.apply_fill(f)
                self._apply_fill_to_portfolio(f)
                self.compliance.record_fill_notional(f.quantity * f.price)
                new_fills.append(f)
            if order.status == OrderStatus.ACKNOWLEDGED:
                # IOC/FOK semantics for unfilled remainder
                if order.order_type == OrderType.MARKET or order.time_in_force in (
                        TimeInForce.IOC, TimeInForce.FOK):
                    order.status = (OrderStatus.CANCELLED
                                    if order.filled_quantity else OrderStatus.EXPIRED)
                    order.updated_at = time.time()
        return new_fills

    def _apply_fill_to_portfolio(self, fill: Fill) -> None:
        pos = self.positions.setdefault(fill.symbol, Position(fill.symbol))
        notional = fill.quantity * fill.price
        if fill.side == Side.BUY:
            new_qty = pos.quantity + fill.quantity
            pos.avg_price = ((pos.avg_price * pos.quantity + notional) / new_qty
                             if new_qty else 0.0)
            pos.quantity = new_qty
            self.cash -= notional
        else:
            # selling: realize P&L against average cost
            self.realized_pnl += fill.quantity * (fill.price - pos.avg_price)
            pos.quantity -= fill.quantity
            self.cash += notional
            if pos.quantity == 0:
                pos.avg_price = 0.0

    # --------------------------------------------------------------- portfolio
    def get_positions(self) -> list[dict]:
        out = []
        for symbol, pos in sorted(self.positions.items()):
            if pos.quantity != 0:
                out.append(pos.to_dict(ref_price=self.market.reference_price(symbol)))
        return out

    def portfolio_summary(self) -> dict:
        positions = self.get_positions()
        mv = sum(p.get("market_value", 0.0) for p in positions)
        upnl = sum(p.get("unrealized_pnl", 0.0) for p in positions)
        return {
            "cash": round(self.cash, 2),
            "positions_market_value": round(mv, 2),
            "unrealized_pnl": round(upnl, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "total_equity": round(self.cash + mv, 2),
            "open_orders": len(self.open_orders),
            "positions": positions,
        }

    def blotter(self, limit: int = 50) -> list[dict]:
        orders = sorted(self.orders.values(), key=lambda o: o.created_at, reverse=True)
        return [o.to_dict() for o in orders[:limit]]


class FillSimulator:
    """Prototype matching logic against the simulated market."""

    @staticmethod
    def fill_order(order: Order, market: SimulatedMarket) -> list[Fill]:
        if not order.is_open or order.remaining <= 0:
            return []
        q = market.quote(order.symbol)
        fills: list[Fill] = []

        def _fill(qty: int, price: float) -> None:
            fills.append(Fill(fill_id=new_fill_id(), order_id=order.order_id,
                              symbol=order.symbol, side=order.side,
                              quantity=qty, price=price))

        if order.order_type == OrderType.MARKET:
            px = q["ask"] if order.side == Side.BUY else q["bid"]
            if order.time_in_force == TimeInForce.FOK:
                _fill(order.remaining, px)  # all-or-nothing in one print
            else:
                # up to 3 partial fills for realism
                total = order.remaining
                third = total // 3
                for qty in (third, third, total - 2 * third):
                    if qty > 0:
                        _fill(qty, px)
        elif order.order_type == OrderType.LIMIT:
            assert order.limit_price is not None
            if order.side == Side.BUY and order.limit_price >= q["ask"]:
                _fill(order.remaining, min(order.limit_price, q["ask"]))
            elif order.side == Side.SELL and order.limit_price <= q["bid"]:
                _fill(order.remaining, max(order.limit_price, q["bid"]))
            # else: no touch, order keeps working
        elif order.order_type == OrderType.STOP:
            assert order.stop_price is not None
            triggered = (order.side == Side.BUY and q["ask"] >= order.stop_price) or \
                        (order.side == Side.SELL and q["bid"] <= order.stop_price)
            if triggered:
                px = q["ask"] if order.side == Side.BUY else q["bid"]
                _fill(order.remaining, px)
        return fills
