from __future__ import annotations


def sma(values: list[float], period: int) -> float | None:
    if period <= 0 or len(values) < period:
        return None
    window = values[-period:]
    return sum(window) / period


def pct_return(prices: list[float], bars: int = 1) -> float | None:
    if len(prices) < bars + 1:
        return None
    prev = prices[-(bars + 1)]
    now = prices[-1]
    if prev <= 0:
        return None
    return now / prev - 1.0


def true_ranges(highs: list[float], lows: list[float], closes: list[float]) -> list[float]:
    out: list[float] = []
    for i in range(len(closes)):
        if i == 0:
            out.append(max(highs[i] - lows[i], 0.0))
            continue
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        out.append(tr)
    return out


def atr(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int,
) -> float | None:
    if len(closes) < period + 1:
        return None
    trs = true_ranges(highs, lows, closes)
    window = trs[-period:]
    return sum(window) / period
