from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import requests

log = logging.getLogger("roostoo_bot")

_BINANCE_HOSTS = (
    "https://api.binance.com",
    "https://data-api.binance.vision",
)


@dataclass
class Candle:
    high: float
    low: float
    close: float


def loop_to_interval(loop_seconds: int) -> str:
    mapping = (
        (60, "1m"),
        (180, "3m"),
        (300, "5m"),
        (900, "15m"),
        (1800, "30m"),
        (3600, "1h"),
        (14400, "4h"),
        (86400, "1d"),
    )
    best = mapping[0][1]
    best_diff = abs(loop_seconds - mapping[0][0])
    for seconds, interval in mapping:
        diff = abs(loop_seconds - seconds)
        if diff < best_diff:
            best = interval
            best_diff = diff
    return best


def roostoo_pair_to_binance(pair: str) -> Optional[str]:
    pair = pair.upper().strip()
    if "/" not in pair:
        return None
    base, quote = pair.split("/", 1)
    if quote != "USD":
        return None
    if base.endswith("B") and base not in {"BNB"}:
        return None
    return f"{base}USDT"


def fetch_candles(
    pair: str,
    loop_seconds: int,
    limit: int,
    timeout: int = 15,
    drop_incomplete: bool = True,
) -> list[Candle]:
    """Fetch completed candles only (drops the last in-progress Binance bar)."""
    symbol = roostoo_pair_to_binance(pair)
    if not symbol:
        raise RuntimeError(f"no public kline source mapped for {pair}")
    interval = loop_to_interval(loop_seconds)
    # +1 so after dropping incomplete we still have enough
    req_limit = max(20, min(limit + (1 if drop_incomplete else 0), 500))
    last_err: Exception | None = None
    for host in _BINANCE_HOSTS:
        url = f"{host}/api/v3/klines"
        try:
            res = requests.get(
                url,
                params={"symbol": symbol, "interval": interval, "limit": req_limit},
                timeout=timeout,
            )
            res.raise_for_status()
            rows = res.json()
            candles = [
                Candle(high=float(r[2]), low=float(r[3]), close=float(r[4])) for r in rows
            ]
            if drop_incomplete and len(candles) > 1:
                candles = candles[:-1]
            if len(candles) < 5:
                raise RuntimeError(f"too few klines from {host}: {len(candles)}")
            log.info(
                "bootstrapped %d %s candles for %s via %s (%s)",
                len(candles),
                interval,
                pair,
                host,
                symbol,
            )
            return candles[-limit:]
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            log.warning("kline fetch failed host=%s err=%s", host, exc)
    raise RuntimeError(f"kline bootstrap failed for {pair}: {last_err}")


def fetch_close_prices(
    pair: str,
    loop_seconds: int,
    limit: int,
    timeout: int = 15,
) -> list[float]:
    return [c.close for c in fetch_candles(pair, loop_seconds, limit, timeout=timeout)]
