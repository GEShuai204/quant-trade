# Roostoo BTC Market-Confirm Bot (V1)

Trade **only BTC/USD** (spot long + 1x short). ETH/SOL/BNB/XRP/DOGE/ADA/AVAX/LINK are **market sensors** for breadth / confirmation — never ordered.

## Strategy (V1)

1. **Dual loop:** `STRATEGY_BAR_SECONDS=3600` — SMA / breadth / Signal Score only when a new **closed 1h** bar arrives (Binance seed). `LOOP_SECONDS=900` — every **15m** refresh equity, drawdown, ATR stop, and rebalance toward the cached signal target.
2. BTC SMA5 / SMA15 on **1h** bars + 2-bar confirmation.
3. Market breadth = share of watch assets with positive 1h return.
4. ETH 1h confirmation + BTC momentum → **Signal Score** (−100…+100).
5. Score → target position (−65%…+65%), then × volatility × drawdown multipliers.
6. ATR(14) hard stop (2×) and trailing (2.5×). Rebalance only if |Δposition| ≥ 5%.

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
