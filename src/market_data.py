from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.kline_bootstrap import Candle, fetch_candles


class PriceHistory:
    def __init__(self, path: Path, maxlen: int = 200) -> None:
        self.path = path
        self.maxlen = maxlen
        self.closes: list[float] = []
        self.highs: list[float] = []
        self.lows: list[float] = []
        self.last_bar_open_ms: int = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    @property
    def prices(self) -> list[float]:
        return self.closes

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                self.closes = [float(x) for x in raw][-self.maxlen :]
                self.highs = list(self.closes)
                self.lows = list(self.closes)
                self.last_bar_open_ms = 0
            else:
                self.closes = [float(x) for x in raw.get("closes", [])][-self.maxlen :]
                self.highs = [float(x) for x in raw.get("highs", self.closes)][-self.maxlen :]
                self.lows = [float(x) for x in raw.get("lows", self.closes)][-self.maxlen :]
                n = len(self.closes)
                self.highs = (self.highs + self.closes)[:n][-self.maxlen :]
                self.lows = (self.lows + self.closes)[:n][-self.maxlen :]
                self.last_bar_open_ms = int(raw.get("last_bar_open_ms", 0))
        except (OSError, ValueError, TypeError):
            self.closes, self.highs, self.lows = [], [], []
            self.last_bar_open_ms = 0

    def _save(self) -> None:
        payload = {
            "closes": self.closes,
            "highs": self.highs,
            "lows": self.lows,
            "last_bar_open_ms": self.last_bar_open_ms,
        }
        self.path.write_text(json.dumps(payload), encoding="utf-8")

    def seed_candles(self, candles: list[Candle]) -> None:
        valid = [c for c in candles if c.close > 0]
        self.closes = [c.close for c in valid][-self.maxlen :]
        self.highs = [c.high for c in valid][-self.maxlen :]
        self.lows = [c.low for c in valid][-self.maxlen :]
        if valid:
            self.last_bar_open_ms = valid[-1].open_time_ms
        self._save()

    def append_candle(self, candle: Candle) -> bool:
        if candle.open_time_ms <= self.last_bar_open_ms:
            return False
        self.closes.append(candle.close)
        self.highs.append(candle.high)
        self.lows.append(candle.low)
        self.closes = self.closes[-self.maxlen :]
        self.highs = self.highs[-self.maxlen :]
        self.lows = self.lows[-self.maxlen :]
        self.last_bar_open_ms = candle.open_time_ms
        self._save()
        return True

    def seed(self, prices: list[float]) -> None:
        vals = [float(x) for x in prices if float(x) > 0][-self.maxlen :]
        self.closes = vals
        self.highs = list(vals)
        self.lows = list(vals)
        self._save()


def sync_closed_bar(
    history: PriceHistory,
    pair: str,
    bar_seconds: int,
    timeout: int,
) -> bool:
    """Append latest completed bar if Binance has a newer closed candle."""
    candles = fetch_candles(pair, bar_seconds, limit=2, timeout=timeout, quiet=True)
    if not candles:
        return False
    latest = candles[-1]
    return history.append_candle(latest)


def extract_ticker_row(ticker_response: dict[str, Any], pair: str) -> dict[str, Any]:
    data = ticker_response.get("Data") or {}
    row = data.get(pair)
    if not row:
        raise RuntimeError(f"Ticker missing pair {pair}")
    return row


def available_pairs(exchange_info: dict[str, Any]) -> set[str]:
    return set((exchange_info.get("TradePairs") or {}).keys())


def resolve_watch_pairs(
    exchange_info: dict[str, Any],
    trade_pair: str,
    candidates: tuple[str, ...],
) -> list[str]:
    listed = available_pairs(exchange_info)
    if trade_pair not in listed:
        raise RuntimeError(f"trade pair {trade_pair} missing from exchangeInfo — halt")
    valid = [p for p in candidates if p in listed and p != trade_pair]
    return valid
