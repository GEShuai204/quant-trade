# Roostoo APAC Quant Bot

Directional 1x long/short bot for the Roostoo mock exchange. Simple SMA crossover, live orders, no dry-run.

## What it does

1. Polls ticker / balance / short positions about every 5 minutes.
2. Builds a local last-price series (Roostoo has no OHLCV endpoint).
3. If fast SMA > slow SMA, targets about +20% long via `POST /v3/place_order` MARKET BUY.
4. If fast SMA < slow SMA, targets about -20% short via `POST /v6/short_open` (USD collateral).
5. Flattens by selling spot and `POST /v6/short_close`.
6. Logs every request to `logs/bot.log`. Secrets are never logged.

`--test` never places orders.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with the **competition** API key pair (not the pre-competition test keys).

```bash
python main.py --test
python main.py --live
```

## EC2

Follow the official AWS guide, then:

```bash
git clone <your-repo> /home/ubuntu/hackathon
cd /home/ubuntu/hackathon
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env
```

Adjust paths in `deploy/roostoo-bot.service`, then:

```bash
sudo cp deploy/roostoo-bot.service /etc/systemd/system/roostoo-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now roostoo-bot
sudo journalctl -u roostoo-bot -f
```

Do not commit `.env`.

## Auth

Signed routes send `RST-API-KEY` and `MSG-SIGNATURE`. Signature is HMAC-SHA256 of alphabetically sorted `key=value` params (the exact query string or POST body). Timestamps are 13-digit milliseconds, offset-corrected with `/v3/serverTime`.
