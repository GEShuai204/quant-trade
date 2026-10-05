# APAC Quant Hackathon × Roostoo — Cursor 初步开发说明

## 1. 项目目标

开发一个部署在 AWS EC2 上、通过 Roostoo API 自动交易的量化交易 Bot。

比赛目标：
- 最大化组合收益
- 同时控制风险
- 重点关注 Sortino、Sharpe、Calmar 等风险调整指标

比赛规则重点：
- 初始模拟资金：$100,000
- 支持 Spot，以及 1x Long / Short
- 禁止 HFT、Market Making、Arbitrage
- 不要高频请求 API
- Maker fee：0.05%
- Taker fee：0.1%
- 代码需要开源并可持续运行
- 策略可以使用传统量化、ML、RL、LLM 等，但第一版先做简单、可解释的 baseline

官方资料：
- Roostoo API: https://github.com/roostoo/Roostoo-API-Documents
- Hackathon: https://luma.com/coghwiyt

> 注意：不要把 API Key / Secret 提交到 GitHub，也不要写进代码。

---

## 2. 第一阶段：只做 API Connectivity

现在**不要开发自动交易策略，也不要下单**。

第一阶段目标：

```text
Python
  ↓
Roostoo API
  ↓
确认可以获取：
- Server Time
- Exchange Info
- Ticker
- Balance
- Short Positions
```

成功后再进入策略开发。

---

## 3. 推荐项目结构

```text
roostoo-quant-bot/
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── config.py
├── roostoo_client.py
├── main.py
├── src/
│   ├── market_data.py
│   ├── portfolio.py
│   ├── indicators.py
│   ├── strategy.py
│   ├── risk_manager.py
│   ├── order_manager.py
│   ├── backtester.py
│   ├── metrics.py
│   └── logger.py
├── tests/
├── data/
└── logs/
```

第一阶段可以只创建：

```text
README.md
requirements.txt
.env.example
.gitignore
config.py
roostoo_client.py
main.py
```

---

## 4. Roostoo API

Base URL：

```text
https://mock-api.roostoo.com
```

需要先实现：

```text
GET  /v3/serverTime
GET  /v3/exchangeInfo
GET  /v3/ticker
GET  /v3/balance
GET  /v3/short_positions
```

暂时不要调用：

```text
POST /v3/place_order
POST /v3/cancel_order
POST /v3/open_short
POST /v3/close_short
```

---

## 5. API Authentication

Signed API 使用：

```text
RST-API-KEY
MSG-SIGNATURE
```

Signature：

```text
HMAC-SHA256
```

Secret Key 作为 HMAC key。

签名内容必须严格按照 Roostoo 官方 API 文档要求生成。

Signed request 需要：

```text
timestamp
```

使用 13 位毫秒时间戳。

如果本机时间和服务器时间存在偏差，应使用：

```text
/v3/serverTime
```

进行校准。

POST 请求使用：

```text
Content-Type: application/x-www-form-urlencoded
```

---

## 6. 环境变量

`.env.example`：

```env
ROOSTOO_API_KEY=your_api_key
ROOSTOO_API_SECRET=your_api_secret
ROOSTOO_BASE_URL=https://mock-api.roostoo.com
```

真实 `.env`：

```text
不要提交到 Git
```

`.gitignore` 至少包含：

```gitignore
.env
__pycache__/
*.pyc
logs/
data/
.venv/
```

---

## 7. roostoo_client.py

建议封装：

```python
class RoostooClient:
    def get_server_time()
    def get_exchange_info()
    def get_ticker()
    def get_balance()
    def get_short_positions()
```

要求：

- 使用 `requests`
- 所有 HTTP request 设置 timeout
- 统一处理 HTTP error
- 统一处理 Roostoo API error
- 不在日志中输出 API Secret
- 支持 GET / POST
- 正确生成 HMAC SHA256 signature
- timestamp 使用毫秒
- 代码尽量简单、可读、可测试

---

## 8. main.py

提供：

```bash
python main.py --test
```

运行后依次测试：

```text
1. Server Time
2. Exchange Info
3. Ticker
4. Balance
5. Short Positions
```

输出类似：

```text
=== Roostoo API Test ===

[1] Server Time
OK

[2] Exchange Info
OK

[3] Ticker
OK

[4] Balance
OK

[5] Short Positions
OK

API connectivity test completed.
```

**绝对不能在 `--test` 模式下发送任何交易订单。**

---

## 9. 第一阶段完成标准

只有下面全部通过，才进入下一阶段：

- [ ] API Key 能正常认证
- [ ] Server Time 成功
- [ ] Exchange Info 成功
- [ ] Ticker 成功
- [ ] Balance 成功
- [ ] Short Positions 成功
- [ ] API error 能正确处理
- [ ] timeout 已配置
- [ ] `.env` 没有提交 Git
- [ ] test 模式不会下单

---

## 10. 第二阶段计划

第一阶段完成后，再开发：

### Market Data

```text
Ticker
↓
OHLCV / price history
↓
local data
```

### Indicators

第一版先做：

```text
SMA
EMA
RSI
ATR
Volatility
```

### Strategy

先做简单 baseline，例如：

```text
Fast MA > Slow MA
    → bullish
    → target long

Fast MA < Slow MA
    → bearish
    → target short
```

例如：

```text
target_position = +0.30
```

代表：

```text
30% long
```

```text
target_position = 0
```

代表：

```text
flat
```

```text
target_position = -0.30
```

代表：

```text
30% short
```

不要直接让 strategy 决定下单。

架构应该是：

```text
Market Data
     ↓
Indicators
     ↓
Strategy
     ↓
Target Position
     ↓
Risk Manager
     ↓
Order Manager
     ↓
Roostoo API
```

---

## 11. Risk Management

必须独立于 Strategy。

第一版至少包含：

```text
Max Position
Max Gross Exposure
Max Net Exposure
Max Order Size
Minimum Order Size
Price / Amount Precision
Drawdown Protection
Cooldown
Stale Data Protection
API Error Protection
```

注意：

```text
不能产生 >1x leverage
```

---

## 12. Backtest

正式 live trading 前必须有 backtester。

至少计算：

```text
Total Return
Volatility
Sharpe Ratio
Sortino Ratio
Maximum Drawdown
Calmar Ratio
Number of Trades
Win Rate
Total Fees
```

必须避免：

```text
Look-ahead bias
```

并考虑：

```text
Trading Fee
Slippage
Execution Delay
Position Size
```

---

## 13. Bot 运行模式

最终建议：

```bash
python main.py --test
```

只测试 API。

```bash
python main.py --dry-run
```

产生 signal，但不下单。

```bash
python main.py --live
```

真正交易。

**live 不应该是默认模式。**

---

## 14. AWS 部署

最终：

```text
AWS EC2
  ↓
Python Bot
  ↓
Roostoo API
```

建议使用：

```text
systemd
```

实现：

- 自动启动
- 自动重启
- 日志保存
- Bot 崩溃自动恢复

Bot 重启后应该：

```text
重新读取 Roostoo balance
重新读取 positions
重新读取 open orders
```

不能只依赖本地内存状态。

---

# 给 Cursor 的直接指令

你现在是这个项目的 coding agent。

请严格按照以下要求执行：

1. 先只完成 **Phase 1：Roostoo API Connectivity**。
2. 不要实现 live trading。
3. 不要调用 `place_order`、`open_short`、`close_short`、`cancel_order`。
4. 创建：
   - `roostoo_client.py`
   - `config.py`
   - `.env.example`
   - `.gitignore`
   - `main.py`
   - `requirements.txt`
   - `README.md`
5. 使用 Roostoo 官方 API 文档确认 endpoint、authentication、signature、timestamp 和 request format。
6. 实现：
   - `get_server_time()`
   - `get_exchange_info()`
   - `get_ticker()`
   - `get_balance()`
   - `get_short_positions()`
7. 使用 `.env` 保存 API credentials。
8. 不允许 credentials 出现在代码、日志或 Git。
9. 所有 HTTP request 设置 timeout。
10. 实现清晰的 error handling。
11. 实现：
   ```bash
   python main.py --test
   ```
12. `--test` 必须保证不会产生任何订单。
13. 完成后告诉我：
   - 创建了哪些文件
   - 每个文件的作用
   - authentication 如何实现
   - 如何配置 `.env`
   - 如何运行测试
   - 测试成功/失败原因
   - 任何不确定的 API 假设

**不要继续实现 Phase 2，除非我明确要求。**
