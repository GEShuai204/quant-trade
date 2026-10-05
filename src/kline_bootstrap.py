from __future__ import annotations

import logging
from typing import Optional

import requests

log = logging.getLogger("roostoo_bot")

# Roostoo has no OHLCV endpoint. Seed SMA from Binance public klines for crypto/*USD.
_BINANCE_HOSTS = (
    "https://api.binance.com",
    "https://data-api.binance.vision",
)


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
    # Stock mirrors on Roostoo end with B and are not on Binance spot.
    if base.endswith("B") and base not in {"BNB"}:
        return None
    return f"{base}USDT"


def fetch_close_prices(
    pair: str,
    loop_seconds: int,
    limit: int,
    timeout: int = 15,
) -> list[float]:
    symbol = roostoo_pair_to_binance(pair)
    if not symbol:
        raise RuntimeError(f"no public kline source mapped for {pair}")
    interval = loop_to_interval(loop_seconds)
    limit = max(20, min(limit, 500))
    last_err: Exception | None = None
    for host in _BINANCE_HOSTS:
        url = f"{host}/api/v3/klines"
        try:
            res = requests.get(
                url,
                params={"symbol": symbol, "interval": interval, "limit": limit},
                timeout=timeout,
            )
            res.raise_for_status()
            rows = res.json()
            closes = [float(row[4]) for row in rows]
            if len(closes) < 5:
                raise RuntimeError(f"too few klines from {host}: {len(closes)}")
            log.info(
                "bootstrapped %d %s closes for %s via %s (%s)",
                len(closes),
                interval,
                pair,
                host,
                symbol,
            )
            return closes
        except Exception as exc:  # noqa: BLE001 - try next host
            last_err = exc
            log.warning("kline fetch failed host=%s err=%s", host, exc)
    raise RuntimeError(f"kline bootstrap failed for {pair}: {last_err}")
