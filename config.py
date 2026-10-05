import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
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
    loop_seconds: int
    target_fraction: float
    sma_fast: int
    sma_slow: int
    http_timeout: int


def load_settings() -> Settings:
    sma_fast = _int("SMA_FAST", 5)
    sma_slow = _int("SMA_SLOW", 15)
    if sma_fast < 2 or sma_slow <= sma_fast:
        raise RuntimeError("SMA_SLOW must be greater than SMA_FAST, and SMA_FAST >= 2")
    target = _float("TARGET_FRACTION", 0.20)
    if not 0 < target <= 1:
        raise RuntimeError("TARGET_FRACTION must be in (0, 1]")
    return Settings(
        api_key=_require("ROOSTOO_API_KEY"),
        api_secret=_require("ROOSTOO_API_SECRET"),
        base_url=os.getenv("ROOSTOO_BASE_URL", "https://mock-api.roostoo.com").rstrip("/"),
        trade_pair=os.getenv("TRADE_PAIR", "BTC/USD").strip().upper(),
        loop_seconds=max(60, _int("LOOP_SECONDS", 300)),
        target_fraction=target,
        sma_fast=sma_fast,
        sma_slow=sma_slow,
        http_timeout=max(5, _int("HTTP_TIMEOUT", 15)),
    )
