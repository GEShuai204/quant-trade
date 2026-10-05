from __future__ import annotations

from dataclasses import dataclass

from src.indicators import atr, pct_return, sma


@dataclass
class StrategySnapshot:
    btc_price: float
    sma5: float | None
    sma15: float | None
    spread: float | None
    btc_raw_trend: str
    btc_confirmed_trend: str
    eth_return: float | None
    eth_state: str
    breadth: float | None
    breadth_valid: bool
    market_regime: str
    btc_momentum: float | None
    btc_score: float
    breadth_score: float
    eth_score: float
    momentum_score: float
    signal_score: float
    signal_position: float
    atr_value: float | None


def _raw_trend(spread: float | None, dead: float = 0.002) -> str:
    if spread is None:
        return "NEUTRAL"
    if spread > dead:
        return "BULLISH"
    if spread < -dead:
        return "BEARISH"
    return "NEUTRAL"


def _confirm_trend(history_trends: list[str]) -> str:
    if len(history_trends) < 2:
        return "NEUTRAL"
    a, b = history_trends[-2], history_trends[-1]
    if a == b == "BULLISH":
        return "BULLISH"
    if a == b == "BEARISH":
        return "BEARISH"
    return "NEUTRAL"


def _breadth_score(breadth: float | None, valid: bool) -> float:
    if not valid or breadth is None:
        return 0.0
    if breadth >= 0.70:
        return 100.0
    if breadth >= 0.55:
        return 50.0
    if breadth >= 0.45:
        return 0.0
    if breadth >= 0.30:
        return -50.0
    return -100.0


def _regime(breadth: float | None, valid: bool) -> str:
    if not valid or breadth is None:
        return "INVALID"
    if breadth >= 0.70:
        return "STRONG_BULL"
    if breadth >= 0.55:
        return "BULL"
    if breadth >= 0.45:
        return "NEUTRAL"
    if breadth >= 0.30:
        return "BEAR"
    return "STRONG_BEAR"


def _eth_score(eth_ret: float | None) -> tuple[float, str]:
    if eth_ret is None:
        return 0.0, "NEUTRAL"
    if eth_ret > 0.003:
        return 100.0, "BULLISH"
    if eth_ret < -0.003:
        return -100.0, "BEARISH"
    return 0.0, "NEUTRAL"


def _mom_score(btc_ret: float | None) -> float:
    if btc_ret is None:
        return 0.0
    if btc_ret > 0.005:
        return 100.0
    if btc_ret < -0.005:
        return -100.0
    return 0.0


def _btc_score(confirmed: str, raw: str) -> float:
    if confirmed == "BULLISH":
        return 100.0
    if confirmed == "BEARISH":
        return -100.0
    if raw == "BULLISH":
        return 60.0
    if raw == "BEARISH":
        return -60.0
    return 0.0


def score_to_position(score: float) -> float:
    # Slightly less aggressive than first V1 to cut fee churn.
    if score >= 85:
        return 0.50
    if score >= 70:
        return 0.35
    if score >= 55:
        return 0.25
    if score >= 40:
        return 0.15
    if score >= 25:
        return 0.10
    if score > -25:
        return 0.0
    if score > -40:
        return -0.10
    if score > -55:
        return -0.15
    if score > -70:
        return -0.25
    if score > -85:
        return -0.35
    return -0.50


class MarketConfirmStrategy:
    """BTC-only trading with multi-asset market confirmation (V1)."""

    def __init__(
        self,
        sma_fast: int = 5,
        sma_slow: int = 15,
        atr_period: int = 14,
        require_confirmed: bool = True,
    ) -> None:
        self.sma_fast = sma_fast
        self.sma_slow = sma_slow
        self.atr_period = atr_period
        self.require_confirmed = require_confirmed
        self._raw_trend_hist: list[str] = []

    def evaluate(
        self,
        btc_closes: list[float],
        btc_highs: list[float],
        btc_lows: list[float],
        watch_closes: dict[str, list[float]],
        eth_pair: str = "ETH/USD",
    ) -> StrategySnapshot:
        s5 = sma(btc_closes, self.sma_fast)
        s15 = sma(btc_closes, self.sma_slow)
        spread = None if s5 is None or s15 is None or s15 == 0 else (s5 - s15) / s15
        raw = _raw_trend(spread)
        self._raw_trend_hist.append(raw)
        self._raw_trend_hist = self._raw_trend_hist[-48:]
        confirmed = _confirm_trend(self._raw_trend_hist)

        returns: list[float] = []
        for pair, closes in watch_closes.items():
            r = pct_return(closes, 1)
            if r is not None:
                returns.append(r)
        breadth_valid = len(returns) >= 1  # tightened below by caller min assets
        breadth = (sum(1 for r in returns if r > 0) / len(returns)) if returns else None

        eth_closes = watch_closes.get(eth_pair) or []
        eth_ret = pct_return(eth_closes, 1)
        eth_sc, eth_state = _eth_score(eth_ret)
        btc_ret = pct_return(btc_closes, 1)
        mom = _mom_score(btc_ret)
        btc_sc = _btc_score(confirmed, raw)
        br_sc = _breadth_score(breadth, breadth_valid and bool(returns))
        score = btc_sc * 0.40 + br_sc * 0.30 + eth_sc * 0.15 + mom * 0.15
        atr_v = atr(btc_highs, btc_lows, btc_closes, self.atr_period)
        price = btc_closes[-1] if btc_closes else 0.0
        pos = score_to_position(score)
        # Unconfirmed SMA noise must not open fresh directional risk.
        if self.require_confirmed and confirmed == "NEUTRAL":
            pos = 0.0
        elif self.require_confirmed and confirmed == "BULLISH" and pos < 0:
            pos = 0.0
        elif self.require_confirmed and confirmed == "BEARISH" and pos > 0:
            pos = 0.0

        return StrategySnapshot(
            btc_price=price,
            sma5=s5,
            sma15=s15,
            spread=spread,
            btc_raw_trend=raw,
            btc_confirmed_trend=confirmed,
            eth_return=eth_ret,
            eth_state=eth_state,
            breadth=breadth,
            breadth_valid=breadth_valid,
            market_regime=_regime(breadth, breadth_valid and bool(returns)),
            btc_momentum=btc_ret,
            btc_score=btc_sc,
            breadth_score=br_sc,
            eth_score=eth_sc,
            momentum_score=mom,
            signal_score=score,
            signal_position=pos,
            atr_value=atr_v,
        )
