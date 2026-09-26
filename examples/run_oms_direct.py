"""Pure-Python OMS demo (no inference server needed): direct OrderBook usage."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from omsagent.oms import OrderBook


def main() -> None:
    book = OrderBook()

    # 1. a plain market order -> fills
    o1 = book.create_order("AAPL", "BUY", 500)
    print("created:", o1.order_id, o1.status.value, "| reject:", o1.reject_reason)
    fills = book.process_fills()
    print("fills:", [(f.quantity, f.price) for f in fills])
    print("order now:", book.get_order(o1.order_id).status.value,
          "avg px:", round(book.get_order(o1.order_id).avg_fill_price, 2))

    # 2. a fat-finger limit order -> compliance reject
    o2 = book.create_order("AAPL", "BUY", 500, order_type="LIMIT", limit_price=50.0)
    print("\ncreated:", o2.order_id, o2.status.value)
    print("reject reason:", o2.reject_reason)

    # 3. a working limit order -> amend -> cancel
    q = book.market.quote("MSFT")
    o3 = book.create_order("MSFT", "SELL", 100, order_type="LIMIT",
                           limit_price=round(q["bid"] * 1.05, 2))
    book.process_fills()
    print("\ncreated:", o3.order_id, book.get_order(o3.order_id).status.value, "(working)")
    book.amend_order(o3.order_id, quantity=80)
    print("amended qty ->", book.get_order(o3.order_id).quantity)
    book.cancel_order(o3.order_id)
    print("cancelled ->", book.get_order(o3.order_id).status.value)

    # 4. blotter + portfolio
    print("\nblotter:")
    for row in book.blotter():
        print(f"  {row['order_id']} {row['side']:4} {row['quantity']:5} "
              f"{row['symbol']:5} {row['status']:16} filled={row['filled_quantity']}")
    print("\nportfolio:", book.portfolio_summary())


if __name__ == "__main__":
    main()
