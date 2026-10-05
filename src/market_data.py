from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class PriceHistory:
    def __init__(self, path: Path, maxlen: int = 200) -> None:
        self.path = path
        self.maxlen = maxlen
        self.prices: list[float] = []
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.prices = [float(x) for x in raw][-self.maxlen :]
        except (OSError, ValueError, TypeError):
            self.prices = []

    def _save(self) -> None:
        self.path.write_text(json.dumps(self.prices), encoding="utf-8")

    def append(self, price: float) -> None:
        self.prices.append(float(price))
        self.prices = self.prices[-self.maxlen :]
        self._save()


def extract_ticker_row(ticker_response: dict[str, Any], pair: str) -> dict[str, Any]:
    data = ticker_response.get("Data") or {}
    row = data.get(pair)
    if not row:
        raise RuntimeError(f"Ticker missing pair {pair}")
    return row
