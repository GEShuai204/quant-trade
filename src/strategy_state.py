from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class CachedStrategy:
    signal_position: float
    signal_score: float
    btc_confirmed_trend: str
    breadth_ok: bool
    atr_value: float | None
    last_bar_open_ms: int
    updated: bool = True

    @classmethod
    def empty(cls) -> CachedStrategy:
        return cls(
            signal_position=0.0,
            signal_score=0.0,
            btc_confirmed_trend="NEUTRAL",
            breadth_ok=False,
            atr_value=None,
            last_bar_open_ms=0,
            updated=False,
        )


class StrategyStateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> CachedStrategy:
        if not self.path.exists():
            return CachedStrategy.empty()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return CachedStrategy(
                signal_position=float(raw.get("signal_position", 0)),
                signal_score=float(raw.get("signal_score", 0)),
                btc_confirmed_trend=str(raw.get("btc_confirmed_trend", "NEUTRAL")),
                breadth_ok=bool(raw.get("breadth_ok", False)),
                atr_value=raw.get("atr_value"),
                last_bar_open_ms=int(raw.get("last_bar_open_ms", 0)),
                updated=True,
            )
        except (OSError, ValueError, TypeError):
            return CachedStrategy.empty()

    def save(self, state: CachedStrategy) -> None:
        payload = asdict(state)
        self.path.write_text(json.dumps(payload), encoding="utf-8")
