from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from config import load_settings
from roostoo_client import RoostooClient, RoostooError
from src.logger import setup_logger
from src.kline_bootstrap import fetch_close_prices
from src.market_data import PriceHistory, extract_ticker_row
from src.order_manager import OrderManager
from src.portfolio import equity_usd
from src.risk_manager import clamp_target, pair_rules
from src.strategy import target_position


def build_client():
    settings = load_settings()
    client = RoostooClient(
        api_key=settings.api_key,
        api_secret=settings.api_secret,
        base_url=settings.base_url,
        timeout=settings.http_timeout,
    )
    return settings, client


def run_test() -> int:
    print("=== Roostoo API Test ===\n")
    try:
        settings, client = build_client()
    except Exception as exc:
        print(f"FAIL config: {exc}")
        return 1

    key = settings.api_key
    secret = settings.api_secret
    print(f"base_url={settings.base_url}")
    print(f"api_key_len={len(key)} api_key_head={key[:4]}...{key[-4:] if len(key) >= 8 else ''}")
    print(f"api_secret_len={len(secret)}")
    print("If Balance/Short fail with auth errors: Key/Secret wrong, swapped, or quoted in .env\n")

    try:
        offset = client.sync_time()
        print(f"clock_offset_ms={offset}\n")
    except RoostooError as exc:
        print(f"WARN clock sync: {exc}\n")

    steps = [
        ("Server Time", lambda: client.get_server_time()),
        ("Exchange Info", lambda: client.get_exchange_info()),
        ("Ticker", lambda: client.get_ticker(settings.trade_pair)),
        ("Balance", lambda: client.get_balance()),
        ("Short Positions", lambda: client.get_short_positions()),
    ]
    failed = False
    for i, (name, fn) in enumerate(steps, start=1):
        print(f"[{i}] {name}")
        try:
            data = fn()
            print("OK")
            if name in {"Balance", "Short Positions"}:
                print(data)
            print()
        except RoostooError as exc:
            failed = True
            print(f"FAIL: {exc}\n")
        except Exception as exc:
            failed = True
            print(f"FAIL: {exc}\n")

    if failed:
        print("API connectivity test failed.")
        return 1
    print("API connectivity test completed.")
    return 0


def run_live() -> int:
    log = setup_logger()
    settings, client = build_client()
    log.info("live bot starting pair=%s loop=%ss", settings.trade_pair, settings.loop_seconds)

    client.sync_time()
    exchange = client.get_exchange_info()
    rules = pair_rules(exchange, settings.trade_pair)
    history = PriceHistory(Path("data") / "prices.json", maxlen=max(200, settings.sma_slow * 4))
    # Roostoo has no candles. Seed SMA from public klines so we need not wait for sma_slow loops.
    if len(history.prices) < settings.sma_slow:
        try:
            closes = fetch_close_prices(
                settings.trade_pair,
                settings.loop_seconds,
                limit=max(settings.sma_slow * 3, 45),
                timeout=settings.http_timeout,
            )
            history.seed(closes)
            log.info("price history seeded bars=%d (SMA ready)", len(history.prices))
        except Exception as exc:
            log.warning("kline bootstrap skipped: %s (will accumulate live ticks)", exc)
    else:
        log.info("reusing saved price history bars=%d", len(history.prices))

    orders = OrderManager(
        client,
        settings.trade_pair,
        rules,
        log,
        cooldown_seconds=max(60, settings.loop_seconds // 2),
    )

    while True:
        try:
            client.sync_time()
            ticker = client.get_ticker(settings.trade_pair)
            row = extract_ticker_row(ticker, settings.trade_pair)
            last = float(row["LastPrice"])
            history.append(last)

            balance = client.get_balance()
            shorts = client.get_short_positions()
            eq = equity_usd(balance, shorts, row, settings.trade_pair)

            raw_target = target_position(
                history.prices,
                settings.sma_fast,
                settings.sma_slow,
                settings.target_fraction,
            )
            target = clamp_target(raw_target, settings.target_fraction)
            log.info(
                "mark=%.4f equity=%.2f target=%.3f bars=%d",
                last,
                eq,
                target,
                len(history.prices),
            )
            action = orders.rebalance(
                target,
                balance,
                shorts,
                row,
                int(ticker.get("ServerTime") or 0),
            )
            log.info("action=%s", action)
        except RoostooError as exc:
            log.error("api error this round: %s", exc)
        except Exception as exc:
            log.exception("unexpected error: %s", exc)
        time.sleep(settings.loop_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="Roostoo directional trading bot")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--test", action="store_true", help="API connectivity only, no orders")
    group.add_argument("--live", action="store_true", help="run the live trading loop")
    args = parser.parse_args()
    if args.test:
        return run_test()
    return run_live()


if __name__ == "__main__":
    sys.exit(main())
