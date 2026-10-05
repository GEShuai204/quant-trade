from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.kline_bootstrap import Candle


class PriceHistory:
    def __init__(self, path: Path, maxlen: int = 200) -> None:
        self.path = path
        self.maxlen = maxlen
        self.closes: list[float] = []
        self.highs: list[float] = []
        self.lows: list[float] = []
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
                # backward compat: plain close list
                self.closes = [float(x) for x in raw][-self.maxlen :]
                self.highs = list(self.closes)
                self.lows = list(self.closes)
            else:
                self.closes = [float(x) for x in raw.get("closes", [])][-self.maxlen :]
                self.highs = [float(x) for x in raw.get("highs", self.closes)][-self.maxlen :]
                self.lows = [float(x) for x in raw.get("lows", self.closes)][-self.maxlen :]
                n = len(self.closes)
                self.highs = (self.highs + self.closes)[:n][-self.maxlen :]
                self.lows = (self.lows + self.closes)[:n][-self.maxlen :]
        except (OSError, ValueError, TypeError):
            self.closes, self.highs, self.lows = [], [], []

    def _save(self) -> None:
        payload = {"closes": self.closes, "highs": self.highs, "lows": self.lows}
        self.path.write_text(json.dumps(payload), encoding="utf-8")

    def seed_candles(self, candles: list[Candle]) -> None:
        self.closes = [c.close for c in candles if c.close > 0][-self.maxlen :]
        self.highs = [c.high for c in candles if c.close > 0][-self.maxlen :]
        self.lows = [c.low for c in candles if c.close > 0][-self.maxlen :]
        self._save()

    def seed(self, prices: list[float]) -> None:
        vals = [float(x) for x in prices if float(x) > 0][-self.maxlen :]
        self.closes = vals
        self.highs = list(vals)
        self.lows = list(vals)
        self._save()

    def append(self, price: float, high: float | None = None, low: float | None = None) -> None:
        p = float(price)
        self.closes.append(p)
        self.highs.append(float(high) if high is not None else p)
        self.lows.append(float(low) if low is not None else p)
        self.closes = self.closes[-self.maxlen :]
        self.highs = self.highs[-self.maxlen :]
        self.lows = self.lows[-self.maxlen :]
        self._save()


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
