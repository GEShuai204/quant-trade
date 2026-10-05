from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from config import load_settings
from roostoo_client import RoostooClient, RoostooError
from src.kline_bootstrap import fetch_candles
from src.logger import setup_logger
from src.market_data import (
    PriceHistory,
    extract_ticker_row,
    resolve_watch_pairs,
    sync_closed_bar,
)
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
from src.strategy_state import CachedStrategy, StrategyStateStore
from src.trade_guard import TradeGuard


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
    bar_seconds: int,
    need: int,
    timeout: int,
    log,
) -> None:
    if len(history.closes) >= need and history.last_bar_open_ms > 0:
        log.info("%s history ready bars=%d", pair, len(history.closes))
        return
    try:
        candles = fetch_candles(pair, bar_seconds, limit=max(need * 2, 40), timeout=timeout)
        history.seed_candles(candles)
        log.info("%s seeded bars=%d", pair, len(history.closes))
    except Exception as exc:
        log.warning("%s kline bootstrap skipped: %s", pair, exc)


def _sync_all_1h_bars(
    btc_hist: PriceHistory,
    watch_hist: dict[str, PriceHistory],
    trade_pair: str,
    bar_seconds: int,
    timeout: int,
    log,
) -> bool:
    """Return True if BTC got a new completed strategy bar."""
    btc_new = sync_closed_bar(btc_hist, trade_pair, bar_seconds, timeout)
    if btc_new:
        for pair, hist in watch_hist.items():
            try:
                sync_closed_bar(hist, pair, bar_seconds, timeout)
            except Exception as exc:
                log.warning("watch bar sync %s: %s", pair, exc)
    return btc_new


def _run_strategy_update(
    settings,
    strategy: MarketConfirmStrategy,
    btc_hist: PriceHistory,
    watch_hist: dict[str, PriceHistory],
    store: StrategyStateStore,
    log,
    force: bool = False,
) -> CachedStrategy:
    watch_closes = {p: h.closes for p, h in watch_hist.items()}
    snap = strategy.evaluate(
        btc_hist.closes,
        btc_hist.highs,
        btc_hist.lows,
        watch_closes,
        eth_pair="ETH/USD",
    )
    breadth_ok = (
        snap.breadth is not None and len(watch_closes) >= settings.min_breadth_assets
    )
    signal_pos = snap.signal_position if breadth_ok else snap.signal_position * 0.25
    cached = CachedStrategy(
        signal_position=signal_pos,
        signal_score=snap.signal_score,
        btc_confirmed_trend=snap.btc_confirmed_trend,
        breadth_ok=breadth_ok,
        atr_value=snap.atr_value,
        last_bar_open_ms=btc_hist.last_bar_open_ms,
        updated=True,
    )
    store.save(cached)
    log.info(
        "STRATEGY %s bar_ms=%s score=%.1f sig_pos=%.2f conf=%s breadth=%s regime=%s",
        "refresh" if force else "new_1h_bar",
        cached.last_bar_open_ms,
        snap.signal_score,
        signal_pos,
        snap.btc_confirmed_trend,
        f"{snap.breadth * 100:.1f}%" if snap.breadth is not None else "n/a",
        snap.market_regime,
    )
    return cached


def run_live() -> int:
    log = setup_logger()
    settings, client = build_client()

    log.info(
        "V1 dual-loop: strategy=%ss (~%.0fh) risk/exec=%ss (~%.0fm) trade=%s",
        settings.strategy_bar_seconds,
        settings.strategy_bar_seconds / 3600,
        settings.loop_seconds,
        settings.loop_seconds / 60,
        settings.trade_pair,
    )

    client.sync_time()
    exchange = client.get_exchange_info()
    watch = resolve_watch_pairs(exchange, settings.trade_pair, settings.watch_pairs)
    log.info("watch pairs valid=%s", watch)

    rules = pair_rules(exchange, settings.trade_pair)
    data_dir = Path("data")
    strat_tag = f"{settings.strategy_bar_seconds}s"
    btc_hist = PriceHistory(data_dir / f"btc_{strat_tag}.json", maxlen=300)
    watch_hist = {
        p: PriceHistory(data_dir / f"{p.replace('/', '_').lower()}_{strat_tag}.json", maxlen=300)
        for p in watch
    }

    need = max(settings.sma_slow + 2, settings.atr_period + 2)
    _bootstrap_history(
        btc_hist, settings.trade_pair, settings.strategy_bar_seconds, need, settings.http_timeout, log
    )
    for p, hist in watch_hist.items():
        _bootstrap_history(hist, p, settings.strategy_bar_seconds, need, settings.http_timeout, log)

    strategy = MarketConfirmStrategy(
        settings.sma_fast,
        settings.sma_slow,
        settings.atr_period,
        require_confirmed=settings.require_confirmed,
    )
    store = StrategyStateStore(data_dir / "strategy_cache.json")
    cached = store.load()
    if not cached.updated or cached.last_bar_open_ms != btc_hist.last_bar_open_ms:
        cached = _run_strategy_update(settings, strategy, btc_hist, watch_hist, store, log, force=True)

    dd_ctl = DrawdownController(data_dir / "equity_peak.json")
    stops = AtrStopManager(data_dir / "atr_stop.json")
    guard = TradeGuard(
        data_dir / "trade_guard.json",
        flip_cooldown_seconds=settings.flip_cooldown_seconds,
        max_step_fraction=settings.max_step_fraction,
    )
    orders = OrderManager(
        client,
        settings.trade_pair,
        rules,
        log,
        cooldown_seconds=max(300, settings.loop_seconds),
        rebalance_band=settings.min_position_adjust,
    )

    while True:
        try:
            client.sync_time()
            new_bar = _sync_all_1h_bars(
                btc_hist,
                watch_hist,
                settings.trade_pair,
                settings.strategy_bar_seconds,
                settings.http_timeout,
                log,
            )
            if new_bar:
                cached = _run_strategy_update(
                    settings, strategy, btc_hist, watch_hist, store, log
                )

            all_tickers = client.get_ticker()
            btc_row = extract_ticker_row(all_tickers, settings.trade_pair)
            btc_px = mark_price(btc_row)

            balance = client.get_balance()
            shorts = client.get_short_positions()
            eq = equity_usd(balance, shorts, btc_row, settings.trade_pair)
            current = current_net_fraction(balance, shorts, btc_row, settings.trade_pair, eq)
            dd, dd_mult = dd_ctl.update(eq)
            vol_mult, vol_state = volatility_multiplier(cached.atr_value, btc_px)

            target = clamp_target(
                cached.signal_position * vol_mult * dd_mult,
                settings.max_abs_position,
            )

            stops.sync_with_position(current, btc_px)
            if stops.check(btc_px, cached.atr_value):
                log.warning("RISK ATR stop/trailing hit → flatten")
                target = 0.0

            if (
                cached.btc_confirmed_trend == "NEUTRAL"
                and abs(target) > abs(current)
                and abs(current) >= settings.min_position_adjust
            ):
                target = current if (target * current) > 0 else 0.0

            target, guard_reason = guard.filter_target(current, target)
            if guard_reason != "ok":
                log.info("GUARD %s → target=%.3f (from signal)", guard_reason, target)

            log.info(
                "RISK/EXEC px=%.2f equity=%.2f dd=%.2f%%×%.2f vol=%s×%.2f | "
                "signal_pos=%.2f (score=%.1f conf=%s) | current=%.3f target=%.3f atr=%s",
                btc_px,
                eq,
                dd * 100,
                dd_mult,
                vol_state,
                vol_mult,
                cached.signal_position,
                cached.signal_score,
                cached.btc_confirmed_trend,
                current,
                target,
                f"{cached.atr_value:.2f}" if cached.atr_value is not None else "n/a",
            )

            action = orders.rebalance(
                target,
                balance,
                shorts,
                btc_row,
                int(all_tickers.get("ServerTime") or 0),
            )
            if action not in {"on_target", "cooldown", "stale", "no_equity", "no_price", "flat"}:
                # Refresh position after a fill for guard bookkeeping.
                try:
                    bal2 = client.get_balance()
                    sh2 = client.get_short_positions()
                    eq2 = equity_usd(bal2, sh2, btc_row, settings.trade_pair)
                    cur2 = current_net_fraction(bal2, sh2, btc_row, settings.trade_pair, eq2)
                    guard.note_fill(cur2)
                except Exception:
                    guard.note_fill(target)
            log.info(
                "decision=%s target=%.3f (score_map=%.2f)",
                action,
                target,
                score_to_position(cached.signal_score),
            )
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
