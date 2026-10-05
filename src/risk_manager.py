from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class PairRules:
    price_precision: int
    amount_precision: int
    mini_order: float


def pair_rules(exchange_info: dict[str, Any], pair: str) -> PairRules:
    info = (exchange_info.get("TradePairs") or {}).get(pair)
    if not info:
        raise RuntimeError(f"exchangeInfo missing pair {pair}")
    return PairRules(
        price_precision=int(info["PricePrecision"]),
        amount_precision=int(info["AmountPrecision"]),
        mini_order=float(info["MiniOrder"]),
    )


def floor_to(value: float, decimals: int) -> float:
    factor = 10 ** decimals
    return math.floor(value * factor + 1e-12) / factor


def clamp_target(target: float, max_abs: float) -> float:
    return max(-max_abs, min(max_abs, target))


def notional_ok(price: float, qty: float, mini_order: float) -> bool:
    return price * qty >= mini_order


def volatility_multiplier(atr_value: float | None, price: float) -> tuple[float, str]:
    if atr_value is None or price <= 0:
        return 1.0, "UNKNOWN"
    atr_pct = atr_value / price
    if atr_pct < 0.015:
        return 1.0, "NORMAL"
    if atr_pct < 0.030:
        return 0.6, "HIGH"
    return 0.0, "EXTREME"


class DrawdownController:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.peak = 0.0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            self.peak = float(json.loads(self.path.read_text(encoding="utf-8")).get("peak", 0))
        except (OSError, ValueError, TypeError):
            self.peak = 0.0

    def _save(self) -> None:
        self.path.write_text(json.dumps({"peak": self.peak}), encoding="utf-8")

    def update(self, equity: float) -> tuple[float, float]:
        """Return (drawdown, multiplier)."""
        if equity > self.peak:
            self.peak = equity
            self._save()
        if self.peak <= 0:
            return 0.0, 1.0
        dd = (self.peak - equity) / self.peak
        if dd < 0.03:
            mult = 1.0
        elif dd < 0.05:
            mult = 0.75
        elif dd < 0.08:
            mult = 0.50
        elif dd < 0.10:
            mult = 0.25
        else:
            mult = 0.0
        return dd, mult


@dataclass
class StopState:
    side: str  # LONG / SHORT / FLAT
    entry_price: float
    extreme_price: float  # highest for long, lowest for short


class AtrStopManager:
    def __init__(self, path: Path, stop_atr: float = 2.0, trail_atr: float = 2.5) -> None:
        self.path = path
        self.stop_atr = stop_atr
        self.trail_atr = trail_atr
        self.state: StopState | None = None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if raw.get("side") in {"LONG", "SHORT"}:
                self.state = StopState(
                    side=raw["side"],
                    entry_price=float(raw["entry_price"]),
                    extreme_price=float(raw["extreme_price"]),
                )
        except (OSError, ValueError, TypeError, KeyError):
            self.state = None

    def _save(self) -> None:
        if self.state is None:
            if self.path.exists():
                self.path.unlink(missing_ok=True)
            return
        self.path.write_text(
            json.dumps(
                {
                    "side": self.state.side,
                    "entry_price": self.state.entry_price,
                    "extreme_price": self.state.extreme_price,
                }
            ),
            encoding="utf-8",
        )

    def sync_with_position(self, current_frac: float, price: float) -> None:
        if abs(current_frac) < 0.02:
            self.state = None
            self._save()
            return
        side = "LONG" if current_frac > 0 else "SHORT"
        if self.state is None or self.state.side != side:
            self.state = StopState(side=side, entry_price=price, extreme_price=price)
            self._save()
            return
        if side == "LONG":
            self.state.extreme_price = max(self.state.extreme_price, price)
        else:
            self.state.extreme_price = min(self.state.extreme_price, price)
        self._save()

    def check(self, price: float, atr_value: float | None) -> bool:
        """True if stop/trailing hit → force flat."""
        if self.state is None or atr_value is None or atr_value <= 0:
            return False
        if self.state.side == "LONG":
            hard = self.state.entry_price - self.stop_atr * atr_value
            trail = self.state.extreme_price - self.trail_atr * atr_value
            return price <= hard or price <= trail
        hard = self.state.entry_price + self.stop_atr * atr_value
        trail = self.state.extreme_price + self.trail_atr * atr_value
        return price >= hard or price >= trail
