# Roostoo BTC Market-Confirm Bot (V1)

Trade **only BTC/USD** (spot long + 1x short). ETH/SOL/BNB/XRP/DOGE/ADA/AVAX/LINK are **market sensors** for breadth / confirmation — never ordered.

## Strategy (V1)

1. **Dual loop:** `STRATEGY_BAR_SECONDS=3600` — SMA / breadth / Signal Score only when a new **closed 1h** bar arrives (Binance seed). `LOOP_SECONDS=900` — every **15m** refresh equity, drawdown, ATR stop, and rebalance toward the cached signal target.
2. BTC SMA5 / SMA15 on **1h** bars + 2-bar confirmation.
3. Market breadth = share of watch assets with positive 1h return.
4. ETH 1h confirmation + BTC momentum → **Signal Score** (−100…+100).
5. Score → target position (max about ±50%), then × volatility × drawdown.
6. ATR stop/trailing. Rebalance only if |Δ| ≥ 8%.
7. Anti-whipsaw: large size only when BTC trend is **confirmed** (2 bars). If unconfirmed, still hold a light ±10% aligned with market breadth so the bot is not idle all day. After a flip, wait 2h before reverse entry; add risk in steps of ≤15%.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# put competition API key/secret in .env
python main.py --test
python main.py --live
```

EC2 systemd: see `deploy/roostoo-bot.service` (set paths to `/home/ssm-user/quant-trade`). After `git pull`:

```bash
# LOOP_SECONDS=900 and STRATEGY_BAR_SECONDS=3600 in .env, then:
sudo systemctl restart roostoo-bot
sudo journalctl -u roostoo-bot -n 80
```

Do not commit `.env`.
