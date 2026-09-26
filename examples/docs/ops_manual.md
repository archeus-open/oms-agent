# OMS Operations Manual — Order Lifecycle

## Lifecycle states
NEW -> ACKNOWLEDGED -> PARTIALLY_FILLED -> FILLED
NEW -> REJECTED (pre-trade compliance failure)
Any working state -> CANCELLED (trader cancel)
ACKNOWLEDGED -> EXPIRED (unfilled DAY order at close, or IOC/FOK remainder)

## Blotter
The blotter is the authoritative record of every order: id, symbol, side,
quantity, type, time-in-force, status, filled quantity, average fill price,
fills, and reject reasons. Query it with list_orders, filtered by status
and/or symbol.

## Positions and P&L
Fills update positions immediately. Buys add to quantity and re-average the
cost basis; sells reduce quantity and realize P&L against average cost.
portfolio_summary reports cash, positions market value, unrealized and
realized P&L, and total equity.

## Matching
run_matching advances one simulated matching cycle: NEW orders are
acknowledged, then each working order is evaluated against the current
simulated quote. Market orders fill; limit orders fill only on a price touch;
stop orders trigger then fill as market orders.

## Simulated market data
All quotes come from a deterministic simulated feed (seeded random walk).
They are NOT real market prices. This prototype must never be connected to a
real venue or used for real trading.
