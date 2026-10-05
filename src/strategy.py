from __future__ import annotations

from src.indicators import sma


def target_position(prices: list[float], fast: int, slow: int, size: float) -> float:
    """+size long, -size short, 0 flat. Strategy never places orders."""
    fast_sma = sma(prices, fast)
    slow_sma = sma(prices, slow)
    if fast_sma is None or slow_sma is None:
        return 0.0
    if abs(fast_sma - slow_sma) / slow_sma < 0.0005:
        return 0.0
    if fast_sma > slow_sma:
        return size
    return -size
