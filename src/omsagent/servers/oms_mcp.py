"""OMS MCP server: exposes order management operations as MCP tools.

State is kept in a process-global OrderBook so the agent (or any MCP client)
sees a consistent blotter across tool calls within one server process.

Tools:
  create_order   - stage a new order (runs pre-trade compliance)
  amend_order    - change qty / limit price of a working order
  cancel_order   - cancel a working order
  get_order      - fetch one order with fills
  list_orders    - blotter, filterable by status / symbol
  run_matching   - run one fill cycle over open orders
  get_positions  - current positions with market values
  portfolio_summary - cash, P&L, equity
  get_quote      - simulated market quote for a symbol
"""

from __future__ import annotations

import json
import sys

from mcp.server.fastmcp import FastMCP

from omsagent.oms import OrderBook

mcp = FastMCP("oms")
_book = OrderBook()


def _ok(data: dict) -> str:
    return json.dumps({"ok": True, **data})


def _err(message: str) -> str:
    return json.dumps({"ok": False, "error": message})


@mcp.tool()
def create_order(symbol: str, side: str, quantity: int,
                 order_type: str = "MARKET", limit_price: float | None = None,
                 stop_price: float | None = None,
                 time_in_force: str = "DAY") -> str:
    """Stage a new order. Runs pre-trade compliance; rejected orders come back
    with status REJECTED and a reject_reason."""
    try:
        order = _book.create_order(symbol=symbol, side=side, quantity=quantity,
                                   order_type=order_type, limit_price=limit_price,
                                   stop_price=stop_price, time_in_force=time_in_force)
        return _ok({"order": order.to_dict()})
    except Exception as e:  # invalid enums etc.
        return _err(str(e))


@mcp.tool()
def amend_order(order_id: str, quantity: int | None = None,
                limit_price: float | None = None) -> str:
    """Amend quantity and/or limit price of a working order."""
    try:
        order = _book.amend_order(order_id, quantity=quantity, limit_price=limit_price)
        return _ok({"order": order.to_dict()})
    except Exception as e:
        return _err(str(e))


@mcp.tool()
def cancel_order(order_id: str) -> str:
    """Cancel a working order."""
    try:
        order = _book.cancel_order(order_id)
        return _ok({"order": order.to_dict()})
    except Exception as e:
        return _err(str(e))


@mcp.tool()
def get_order(order_id: str) -> str:
    """Fetch a single order including its fills."""
    try:
        return _ok({"order": _book.get_order(order_id).to_dict()})
    except Exception as e:
        return _err(str(e))


@mcp.tool()
def list_orders(status: str | None = None, symbol: str | None = None) -> str:
    """Blotter of orders, optionally filtered by status and/or symbol."""
    try:
        orders = _book.list_orders(status=status, symbol=symbol)
        return _ok({"count": len(orders), "orders": [o.to_dict() for o in orders]})
    except Exception as e:
        return _err(str(e))


@mcp.tool()
def run_matching() -> str:
    """Run one matching cycle: acknowledge NEW orders and simulate fills."""
    fills = _book.process_fills()
    return _ok({"fills": [f.to_dict() for f in fills], "count": len(fills)})


@mcp.tool()
def get_positions() -> str:
    """Current positions with market values and unrealized P&L."""
    return _ok({"positions": _book.get_positions()})


@mcp.tool()
def portfolio_summary() -> str:
    """Cash, positions market value, realized/unrealized P&L, total equity."""
    return _ok({"portfolio": _book.portfolio_summary()})


@mcp.tool()
def get_quote(symbol: str) -> str:
    """Simulated market quote (bid/ask/last) for a symbol."""
    return _ok({"quote": _book.market.quote(symbol)})


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    sys.exit(main())
