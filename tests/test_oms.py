"""Tests for the OMS core: lifecycle, compliance, fills, portfolio."""

import pytest

from omsagent.oms import (
    ComplianceConfig, ComplianceEngine, OrderBook, OrderStatus, SimulatedMarket,
)


def make_book(**kw) -> OrderBook:
    return OrderBook(market=SimulatedMarket(seed=7), **kw)


def test_market_order_fills_and_updates_position():
    book = make_book()
    order = book.create_order("AAPL", "BUY", 500)
    assert order.status == OrderStatus.NEW
    fills = book.process_fills()
    assert fills, "market order should fill"
    order = book.get_order(order.order_id)
    assert order.status == OrderStatus.FILLED
    assert order.filled_quantity == 500
    assert order.avg_fill_price and order.avg_fill_price > 0
    positions = book.get_positions()
    assert len(positions) == 1 and positions[0]["quantity"] == 500


def test_buy_then_sell_realizes_pnl():
    book = make_book()
    book.create_order("AAPL", "BUY", 100)
    book.process_fills()
    book.create_order("AAPL", "SELL", 100)
    book.process_fills()
    assert book.get_positions() == []
    assert book.realized_pnl != 0.0


def test_compliance_rejects_restricted_symbol():
    book = make_book()
    order = book.create_order("GME", "BUY", 100)
    assert order.status == OrderStatus.REJECTED
    assert "RESTRICTED_SYMBOL" in (order.reject_reason or "")


def test_compliance_rejects_oversize_notional():
    cfg = ComplianceConfig(max_order_notional=1_000.0)
    book = OrderBook(market=SimulatedMarket(seed=7),
                     compliance=ComplianceEngine(config=cfg))
    order = book.create_order("AAPL", "BUY", 500)  # ~$116k notional
    assert order.status == OrderStatus.REJECTED
    assert "MAX_ORDER_NOTIONAL" in (order.reject_reason or "")


def test_compliance_rejects_price_collar():
    book = make_book()
    order = book.create_order("AAPL", "BUY", 100, order_type="LIMIT", limit_price=50.0)
    assert order.status == OrderStatus.REJECTED
    assert "PRICE_COLLAR" in (order.reject_reason or "")


def test_limit_order_away_from_market_keeps_working():
    book = make_book()
    q = book.market.quote("MSFT")
    # sell limit well above the market: should not fill
    order = book.create_order("MSFT", "SELL", 100, order_type="LIMIT",
                              limit_price=round(q["bid"] * 1.08, 2))
    assert order.status == OrderStatus.NEW
    book.process_fills()
    assert book.get_order(order.order_id).status == OrderStatus.ACKNOWLEDGED
    assert book.get_order(order.order_id).filled_quantity == 0


def test_limit_order_touching_market_fills():
    book = make_book()
    q = book.market.quote("AAPL")
    order = book.create_order("AAPL", "BUY", 100, order_type="LIMIT",
                              limit_price=round(q["ask"] * 1.01, 2))
    book.process_fills()
    assert book.get_order(order.order_id).status == OrderStatus.FILLED


def test_amend_and_cancel():
    book = make_book()
    q = book.market.quote("MSFT")
    order = book.create_order("MSFT", "SELL", 100, order_type="LIMIT",
                              limit_price=round(q["bid"] * 1.08, 2))
    book.process_fills()
    amended = book.amend_order(order.order_id, quantity=80)
    assert amended.quantity == 80
    cancelled = book.cancel_order(order.order_id)
    assert cancelled.status == OrderStatus.CANCELLED


def test_amend_terminal_order_fails():
    book = make_book()
    order = book.create_order("AAPL", "BUY", 10)
    book.process_fills()
    with pytest.raises(ValueError):
        book.amend_order(order.order_id, quantity=5)


def test_stop_order_triggers():
    book = make_book()
    # buy stop far below market should not trigger
    q = book.market.quote("TSLA")
    order = book.create_order("TSLA", "BUY", 50, order_type="STOP",
                              stop_price=round(q["ask"] * 1.5, 2))
    book.process_fills()
    assert book.get_order(order.order_id).filled_quantity == 0
    # sell stop far above market triggers immediately on the sell side? No:
    # sell stop triggers when bid <= stop; set stop above bid -> triggers.
    order2 = book.create_order("TSLA", "SELL", 50, order_type="STOP",
                               stop_price=round(q["bid"] * 1.5, 2))
    book.process_fills()
    assert book.get_order(order2.order_id).status == OrderStatus.FILLED


def test_portfolio_summary_shape():
    book = make_book()
    book.create_order("AAPL", "BUY", 100)
    book.process_fills()
    summary = book.portfolio_summary()
    assert summary["total_equity"] > 0
    assert summary["open_orders"] == 0
    assert len(summary["positions"]) == 1
