from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from config import load_settings
from roostoo_client import RoostooClient, RoostooError
from src.kline_bootstrap import fetch_candles
from src.logger import setup_logger
from src.market_data import PriceHistory, extract_ticker_row, resolve_watch_pairs
from src.order_manager import OrderManager
from src.portfolio import current_net_fraction, equity_usd, mark_price
from src.risk_manager import (
    AtrStopManager,
    DrawdownController,
    clamp_target,
    pair_rules,
    volatility_multiplier,
)
from src.strategy import MarketConfirmStrategy, score_to_position


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

    try:
        client.sync_time()
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
            if name in {"Balance", "Short Positions", "Exchange Info"}:
                if name == "Exchange Info":
                    watch = resolve_watch_pairs(data, settings.trade_pair, settings.watch_pairs)
                    print(f"trade={settings.trade_pair} watch={watch}")
                else:
                    print(data)
            print()
        except Exception as exc:
            failed = True
            print(f"FAIL: {exc}\n")

    if failed:
        print("API connectivity test failed.")
        return 1
    print("API connectivity test completed.")
    return 0


def _bootstrap_history(
    history: PriceHistory,
    pair: str,
    loop_seconds: int,
    need: int,
    timeout: int,
    log,
) -> None:
    if len(history.closes) >= need:
        log.info("%s history ready bars=%d", pair, len(history.closes))
        return
    try:
        candles = fetch_candles(pair, loop_seconds, limit=max(need * 2, 40), timeout=timeout)
        history.seed_candles(candles)
        log.info("%s seeded bars=%d", pair, len(history.closes))
    except Exception as exc:
        log.warning("%s kline bootstrap skipped: %s", pair, exc)


def run_live() -> int:
    log = setup_logger()
    settings, client = build_client()
    if settings.trade_pair != "BTC/USD":
        log.warning("V1 strategy is designed for BTC/USD; current=%s", settings.trade_pair)

    log.info(
        "V1 market-confirm bot starting trade=%s loop=%ss (~%.0f min)",
        settings.trade_pair,
        settings.loop_seconds,
        settings.loop_seconds / 60,
    )

    client.sync_time()
    exchange = client.get_exchange_info()
    watch = resolve_watch_pairs(exchange, settings.trade_pair, settings.watch_pairs)
    log.info("watch pairs valid=%s", watch)
    if len(watch) < settings.min_breadth_assets:
        log.warning(
            "few watch pairs (%d < %d); breadth may often be invalid",
            len(watch),
            settings.min_breadth_assets,
        )

    rules = pair_rules(exchange, settings.trade_pair)
    data_dir = Path("data")
    bar_tag = f"{settings.loop_seconds}s"
    btc_hist = PriceHistory(data_dir / f"btc_{bar_tag}.json", maxlen=300)
    watch_hist = {
        p: PriceHistory(data_dir / f"{p.replace('/', '_').lower()}_{bar_tag}.json", maxlen=300)
        for p in watch
    }

    need = max(settings.sma_slow + 2, settings.atr_period + 2)
    _bootstrap_history(
        btc_hist, settings.trade_pair, settings.loop_seconds, need, settings.http_timeout, log
    )
    for p, hist in watch_hist.items():
        _bootstrap_history(hist, p, settings.loop_seconds, need, settings.http_timeout, log)

    strategy = MarketConfirmStrategy(settings.sma_fast, settings.sma_slow, settings.atr_period)
    dd_ctl = DrawdownController(data_dir / "equity_peak.json")
    stops = AtrStopManager(data_dir / "atr_stop.json")
    orders = OrderManager(
        client,
        settings.trade_pair,
        rules,
        log,
        cooldown_seconds=max(300, settings.loop_seconds // 6),
        rebalance_band=settings.min_position_adjust,
    )

    while True:
        try:
            client.sync_time()
            # One ticker call for all pairs (same timestamp window).
            all_tickers = client.get_ticker()
            btc_row = extract_ticker_row(all_tickers, settings.trade_pair)
            btc_px = mark_price(btc_row)
            btc_hist.append(btc_px)

            watch_closes: dict[str, list[float]] = {}
            for p, hist in watch_hist.items():
                try:
                    row = extract_ticker_row(all_tickers, p)
                    hist.append(mark_price(row))
                    watch_closes[p] = hist.closes
                except Exception as exc:
                    log.warning("skip watch %s: %s", p, exc)

            snap = strategy.evaluate(
                btc_hist.closes,
                btc_hist.highs,
                btc_hist.lows,
                watch_closes,
                eth_pair="ETH/USD",
            )

            balance = client.get_balance()
            shorts = client.get_short_positions()
            eq = equity_usd(balance, shorts, btc_row, settings.trade_pair)
            current = current_net_fraction(balance, shorts, btc_row, settings.trade_pair, eq)
            dd, dd_mult = dd_ctl.update(eq)
            vol_mult, vol_state = volatility_multiplier(snap.atr_value, snap.btc_price)

            breadth_ok = (
                snap.breadth is not None and len(watch_closes) >= settings.min_breadth_assets
            )
            signal_pos = snap.signal_position if breadth_ok else snap.signal_position * 0.25
            if not breadth_ok:
                log.warning("breadth invalid (assets=%d); reducing new risk", len(watch_closes))

            target = clamp_target(
                signal_pos * vol_mult * dd_mult,
                settings.max_abs_position,
            )

            stops.sync_with_position(current, btc_px)
            if stops.check(btc_px, snap.atr_value):
                log.warning("ATR stop/trailing hit → flatten")
                target = 0.0

            # Neutral confirmed: keep current unless risk forces down.
            if (
                snap.btc_confirmed_trend == "NEUTRAL"
                and abs(target) > abs(current)
                and abs(current) >= settings.min_position_adjust
            ):
                target = current if (target * current) > 0 else 0.0

            log.info(
                "BTC=%.2f SMA5=%s SMA15=%s spread=%s raw=%s conf=%s | "
                "breadth=%s regime=%s eth_ret=%s eth=%s mom=%s | "
                "score=%.1f (btc=%.0f br=%.0f eth=%.0f mom=%.0f) sig_pos=%.2f | "
                "vol=%s×%.2f dd=%.2f%%×%.2f peak=%.2f equity=%.2f | "
                "current=%.3f target=%.3f atr=%s",
                snap.btc_price,
                f"{snap.sma5:.2f}" if snap.sma5 is not None else "n/a",
                f"{snap.sma15:.2f}" if snap.sma15 is not None else "n/a",
                f"{snap.spread * 100:.3f}%" if snap.spread is not None else "n/a",
                snap.btc_raw_trend,
                snap.btc_confirmed_trend,
                f"{snap.breadth * 100:.1f}%" if snap.breadth is not None else "n/a",
                snap.market_regime,
                f"{snap.eth_return * 100:.2f}%" if snap.eth_return is not None else "n/a",
                snap.eth_state,
                f"{snap.btc_momentum * 100:.2f}%" if snap.btc_momentum is not None else "n/a",
                snap.signal_score,
                snap.btc_score,
                snap.breadth_score,
                snap.eth_score,
                snap.momentum_score,
                signal_pos,
                vol_state,
                vol_mult,
                dd * 100,
                dd_mult,
                dd_ctl.peak,
                eq,
                current,
                target,
                f"{snap.atr_value:.2f}" if snap.atr_value is not None else "n/a",
            )

            action = orders.rebalance(
                target,
                balance,
                shorts,
                btc_row,
                int(all_tickers.get("ServerTime") or 0),
            )
            log.info("decision=%s target=%.3f (score_map=%.2f)", action, target, score_to_position(snap.signal_score))
        except RoostooError as exc:
            log.error("api error this round: %s", exc)
        except Exception as exc:
            log.exception("unexpected error: %s", exc)
        time.sleep(settings.loop_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="Roostoo BTC market-confirm bot V1")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--test", action="store_true", help="API connectivity only, no orders")
    group.add_argument("--live", action="store_true", help="run the live trading loop")
    args = parser.parse_args()
    if args.test:
        return run_test()
    return run_live()


if __name__ == "__main__":
    sys.exit(main())
