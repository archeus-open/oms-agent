# Pre-Trade Compliance Rules — Prototype Policy

Every new order — and every amendment — must pass these pre-trade checks
before it can reach the venue. A violation rejects the order with status
REJECTED and a machine-readable rule code.

## Rules
1. POSITIVE_QTY — quantity must be positive.
2. RESTRICTED_SYMBOL — symbols on the restricted list cannot be traded.
   Current list: GME, AMC.
3. INVALID_TIF — only DAY, GTC, IOC, FOK are permitted.
4. MAX_ORDER_NOTIONAL — single-order notional cap: $5,000,000.
   Notional is estimated from the limit price when present, else the
   reference price.
5. MAX_POSITION_NOTIONAL — the resulting per-symbol position may not exceed
   $25,000,000 gross notional at the reference price.
6. MAX_DAILY_NOTIONAL — gross traded notional per day may not exceed
   $100,000,000.
7. PRICE_COLLAR — a limit price must be within +/-10% of the reference price,
   to catch fat-finger errors.

## Procedure
- Checks run in the ComplianceEngine at order creation and on every amend.
- Fills accumulate into the daily gross notional counter.
- The trading desk can request a limit override only via the risk committee;
  the prototype has no override path (fail-closed by design).
