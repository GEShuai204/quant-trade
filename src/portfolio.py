from __future__ import annotations

from typing import Any


def wallet_qty(wallet: dict[str, Any], coin: str) -> tuple[float, float]:
    row = (wallet.get("Wallet") or {}).get(coin) or {}
    return float(row.get("Free") or 0), float(row.get("Lock") or 0)


def pair_short(positions_response: dict[str, Any], pair: str) -> dict[str, Any] | None:
    for pos in positions_response.get("Positions") or []:
        if pos.get("Pair") == pair:
            return pos
    return None


def mark_price(ticker_row: dict[str, Any]) -> float:
    last = float(ticker_row.get("LastPrice") or 0)
    ask = float(ticker_row.get("MinAsk") or last)
    bid = float(ticker_row.get("MaxBid") or last)
    if last > 0:
        return last
    if ask > 0:
        return ask
    return bid


def equity_usd(
    balance: dict[str, Any],
    shorts: dict[str, Any],
    ticker_row: dict[str, Any],
    pair: str,
) -> float:
    coin = pair.split("/")[0]
    price = mark_price(ticker_row)
    usd_free, usd_lock = wallet_qty(balance, "USD")
    coin_free, coin_lock = wallet_qty(balance, coin)
    equity = usd_free + usd_lock + (coin_free + coin_lock) * price
    pos = pair_short(shorts, pair)
    if pos:
        equity += float(pos.get("UnrealizedPNL") or 0)
    return equity


def current_net_fraction(
    balance: dict[str, Any],
    shorts: dict[str, Any],
    ticker_row: dict[str, Any],
    pair: str,
    equity: float,
) -> float:
    if equity <= 0:
        return 0.0
    coin = pair.split("/")[0]
    price = mark_price(ticker_row)
    coin_free, coin_lock = wallet_qty(balance, coin)
    long_notional = (coin_free + coin_lock) * price
    pos = pair_short(shorts, pair)
    short_notional = float(pos.get("PositionValue") or 0) if pos else 0.0
    if pos and short_notional <= 0:
        short_notional = float(pos.get("Collateral") or 0) + float(pos.get("UnrealizedPNL") or 0)
    return (long_notional - short_notional) / equity
