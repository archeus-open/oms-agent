# Order Types and Time-in-Force — OMS Operations Manual

## Market orders
A market order executes immediately at the best available price. It guarantees
execution but not price. In this prototype, market orders fill against the
simulated quote (buy at the ask, sell at the bid), possibly in several partial
fills for realism.

## Limit orders
A limit order executes only at the specified limit price or better: a buy limit
fills when the ask is at or below the limit; a sell limit fills when the bid is
at or above the limit. If the market never touches the limit, the order keeps
working (status ACKNOWLEDGED) until cancelled, amended, or expired.

## Stop orders
A stop order rests until the stop price is touched (buy: ask >= stop;
sell: bid <= stop), then it behaves like a market order. Used for stop-loss
and breakout entries.

## Time-in-force
- DAY: expires at end of the trading day if not filled.
- GTC (good-till-cancelled): keeps working until filled or cancelled.
- IOC (immediate-or-cancel): fill whatever is available now, cancel the rest.
- FOK (fill-or-kill): fill the entire quantity at once or kill the order.

## Amending and cancelling
Only working orders (NEW, ACKNOWLEDGED, PARTIALLY_FILLED) can be amended or
cancelled. Amendments to quantity or limit price re-run pre-trade compliance.
Filled, cancelled, rejected or expired orders are terminal and immutable.
