import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

DEFAULT_WATCH = "ETH/USD,SOL/USD,BNB/USD,XRP/USD,DOGE/USD,ADA/USD,AVAX/USD,LINK/USD"


def _clean(value: str) -> str:
    value = value.strip().strip("\ufeff")
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1].strip()
    return value


def _require(name: str) -> str:
    value = _clean(os.getenv(name, ""))
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return default if raw is None or raw.strip() == "" else float(raw)


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return default if raw is None or raw.strip() == "" else int(raw)


@dataclass(frozen=True)
class Settings:
    api_key: str
    api_secret: str
    base_url: str
    trade_pair: str
    watch_pairs: tuple[str, ...]
    loop_seconds: int
    sma_fast: int
    sma_slow: int
    http_timeout: int
    max_abs_position: float
    min_position_adjust: float
    min_breadth_assets: int
    atr_period: int


def load_settings() -> Settings:
    sma_fast = _int("SMA_FAST", 5)
    sma_slow = _int("SMA_SLOW", 15)
    if sma_fast < 2 or sma_slow <= sma_fast:
        raise RuntimeError("SMA_SLOW must be greater than SMA_FAST, and SMA_FAST >= 2")
    watch_raw = _clean(os.getenv("WATCH_PAIRS", DEFAULT_WATCH))
    watch = tuple(p.strip().upper() for p in watch_raw.split(",") if p.strip())
    max_abs = _float("MAX_ABS_POSITION", 0.65)
    if not 0 < max_abs <= 1:
        raise RuntimeError("MAX_ABS_POSITION must be in (0, 1]")
    return Settings(
        api_key=_require("ROOSTOO_API_KEY"),
        api_secret=_require("ROOSTOO_API_SECRET"),
        base_url=_clean(os.getenv("ROOSTOO_BASE_URL", "https://mock-api.roostoo.com")).rstrip("/"),
        trade_pair=_clean(os.getenv("TRADE_PAIR", "BTC/USD")).upper(),
        watch_pairs=watch,
        loop_seconds=max(300, _int("LOOP_SECONDS", 3600)),
        sma_fast=sma_fast,
        sma_slow=sma_slow,
        http_timeout=max(5, _int("HTTP_TIMEOUT", 15)),
        max_abs_position=max_abs,
        min_position_adjust=_float("MIN_POSITION_ADJUST", 0.05),
        min_breadth_assets=max(3, _int("MIN_BREADTH_ASSETS", 4)),
        atr_period=max(5, _int("ATR_PERIOD", 14)),
    )
