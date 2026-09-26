"""Simulated market-data feed (deterministic).

Prototype stand-in for a real market-data venue. Each symbol follows a seeded
random walk so demos and tests are reproducible. NOT real prices.
"""

from __future__ import annotations

import hashlib
import random


class SimulatedMarket:
    def __init__(self, seed: int = 42, base_prices: dict[str, float] | None = None) -> None:
        self.seed = seed
        self.base_prices = dict(base_prices or {
            "AAPL": 232.50, "MSFT": 428.10, "NVDA": 131.20, "TSLA": 248.70,
            "AMZN": 197.30, "META": 563.40, "JPM": 224.90, "XOM": 118.60,
        })
        self._ticks: dict[str, int] = {}
        self._price: dict[str, float] = {}

    def _rng(self, symbol: str, tick: int) -> random.Random:
        key = f"{self.seed}:{symbol}:{tick}".encode()
        return random.Random(int(hashlib.md5(key).hexdigest(), 16) % (2**31))

    def _ensure(self, symbol: str) -> None:
        symbol = symbol.upper()
        if symbol not in self.base_prices:
            # deterministic pseudo price for unknown symbols
            h = int(hashlib.md5(symbol.encode()).hexdigest(), 16)
            self.base_prices[symbol] = 20.0 + (h % 480) + (h % 100) / 100.0
        if symbol not in self._ticks:
            self._ticks[symbol] = 0
            self._price[symbol] = self.base_prices[symbol]

    def quote(self, symbol: str) -> dict:
        """Advance one tick and return {bid, ask, last}."""
        symbol = symbol.upper()
        self._ensure(symbol)
        tick = self._ticks[symbol]
        rng = self._rng(symbol, tick)
        drift = rng.uniform(-0.0015, 0.0015)
        self._price[symbol] *= (1 + drift)
        self._ticks[symbol] = tick + 1
        last = round(self._price[symbol], 2)
        spread = max(0.01, round(last * 0.0004, 2))
        return {
            "symbol": symbol, "bid": round(last - spread / 2, 2),
            "ask": round(last + spread / 2, 2), "last": last,
            "tick": self._ticks[symbol],
        }

    def reference_price(self, symbol: str) -> float:
        return self.quote(symbol)["last"]
