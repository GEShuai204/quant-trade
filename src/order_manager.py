from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from roostoo_client import RoostooClient, RoostooError
from src.portfolio import current_net_fraction, equity_usd, mark_price, pair_short, wallet_qty
from src.risk_manager import PairRules, floor_to, notional_ok


def _fmt(value: float, decimals: int) -> str:
    return f"{floor_to(value, decimals):.{decimals}f}"


class OrderManager:
    def __init__(
        self,
        client: RoostooClient,
        pair: str,
        rules: PairRules,
        logger,
        cooldown_seconds: int = 60,
        rebalance_band: float = 0.03,
    ) -> None:
        self.client = client
        self.pair = pair
        self.coin = pair.split("/")[0]
        self.rules = rules
        self.log = logger
        self.cooldown_seconds = cooldown_seconds
        self.rebalance_band = rebalance_band
        self.last_order_ts = 0.0
        self.last_order_day = ""

    def _note_trade(self) -> None:
        self.last_order_ts = time.time()
        self.last_order_day = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _cooling(self) -> bool:
        return (time.time() - self.last_order_ts) < self.cooldown_seconds

    def _needs_daily_trade(self) -> bool:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.last_order_day != today

    def rebalance(
        self,
        target: float,
        balance: dict[str, Any],
        shorts: dict[str, Any],
        ticker_row: dict[str, Any],
        ticker_server_time: int,
    ) -> str:
        now_ms = int(time.time() * 1000) + self.client.offset_ms
        if abs(now_ms - int(ticker_server_time)) > 60_000:
            self.log.warning("stale ticker, skip orders")
            return "stale"

        if self._cooling():
            return "cooldown"

        equity = equity_usd(balance, shorts, ticker_row, self.pair)
        if equity <= 0:
            self.log.warning("equity is 0, skip")
            return "no_equity"

        current = current_net_fraction(balance, shorts, ticker_row, self.pair, equity)
        force_daily = target != 0 and self._needs_daily_trade()
        if abs(target - current) < self.rebalance_band and not force_daily:
            return "on_target"

        price = mark_price(ticker_row)
        if price <= 0:
            return "no_price"

        usd_free, _ = wallet_qty(balance, "USD")
        coin_free, _ = wallet_qty(balance, self.coin)
        short_pos = pair_short(shorts, self.pair)

        try:
            if target >= 0 and short_pos:
                self.log.info("closing short on %s", self.pair)
                result = self.client.short_close(self.pair)
                self.log.info("short_close ok: %s", result)
                self._note_trade()
                return "closed_short"

            if target <= 0 and coin_free > 0:
                qty = floor_to(coin_free, self.rules.amount_precision)
                if qty > 0 and notional_ok(price, qty, self.rules.mini_order):
                    self.log.info("selling spot %s qty=%s", self.pair, qty)
                    result = self.client.place_order(
                        self.pair, "SELL", _fmt(qty, self.rules.amount_precision)
                    )
                    self.log.info("place_order SELL ok: %s", result)
                    self._note_trade()
                    return "sold_spot"

            if target > 0:
                desired = target * equity
                current_long = coin_free * price
                delta = desired - current_long
                if force_daily and delta < self.rules.mini_order:
                    delta = max(self.rules.mini_order * 1.05, desired * 0.05)
                spend = min(delta, usd_free * 0.95)
                qty = floor_to(spend / price, self.rules.amount_precision)
                if qty > 0 and notional_ok(price, qty, self.rules.mini_order):
                    self.log.info("buying spot %s qty=%s", self.pair, qty)
                    result = self.client.place_order(
                        self.pair, "BUY", _fmt(qty, self.rules.amount_precision)
                    )
                    self.log.info("place_order BUY ok: %s", result)
                    self._note_trade()
                    return "bought_spot"
                return "buy_too_small"

            if target < 0:
                desired = abs(target) * equity
                current_collat = float((short_pos or {}).get("Collateral") or 0)
                delta = desired - current_collat
                if force_daily and delta < 1:
                    delta = max(1.0, desired * 0.05)
                collat = floor_to(min(delta, usd_free * 0.95), 2)
                if collat >= 1:
                    self.log.info("opening short %s collateral=%s", self.pair, collat)
                    result = self.client.short_open(self.pair, f"{collat:.2f}")
                    self.log.info("short_open ok: %s", result)
                    self._note_trade()
                    return "opened_short"
                return "short_too_small"

            return "flat"
        except RoostooError as exc:
            self.log.error("order failed: %s", exc)
            return "error"
