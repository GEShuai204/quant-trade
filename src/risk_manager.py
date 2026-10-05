from __future__ import annotations

import math
from dataclasses import dataclass
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
