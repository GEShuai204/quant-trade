# Roostoo BTC Market-Confirm Bot (V1)

Trade **only BTC/USD** (spot long + 1x short). ETH/SOL/BNB/XRP/DOGE/ADA/AVAX/LINK are **market sensors** for breadth / confirmation — never ordered.

## Strategy (V1)

1. Bootstrap completed **1h** candles from Binance (Roostoo has no OHLCV), then append Roostoo last prices each hour.
2. BTC SMA5 / SMA15 spread + 2-bar confirmation.
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
# update LOOP to 3600 in .env if still 300
sudo systemctl restart roostoo-bot
sudo journalctl -u roostoo-bot -n 80
```

Do not commit `.env`.
