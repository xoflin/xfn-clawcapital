# 🦅 ClawCapital

> **Autonomous Quantitative Portfolio Manager** — Multi-agent AI that monitors global markets, synthesizes intelligence, and executes on Hyperliquid L1. Human approval required.

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue?style=flat-square&logo=python)](https://www.python.org/)
[![Status](https://img.shields.io/badge/status-alpha-orange?style=flat-square)](.)
[![License](https://img.shields.io/badge/license-proprietary-black?style=flat-square)](.)
[![Blockchain](https://img.shields.io/badge/blockchain-Hyperliquid%20L1-purple?style=flat-square)](https://hyperliquid.xyz/)

---

## 🎯 What is ClawCapital?

A **human-in-the-loop quantitative trading system** that:

- 📊 Collects macro data (FRED, CoinGecko, Alpha Vantage, CryptoPanic)
- 🧠 Synthesizes with **Gemini 2.5 Flash** (research) + **Gemini 2.5 Pro** (decisions)
- ⏸️ **Waits for your approval** via Telegram before executing
- 🚀 Executes on **Hyperliquid L1** — no public mempool, protection against frontrunning
- 📈 Preserves capital above all else

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                   MAIN LOOP (every 2–3 hours)                  │
└────────────┬────────────────────────────────────────────────────┘
             │
    ┌────────▼────────────────────────────┐
    │  1️⃣  HEARTBEAT                     │  Connectivity check
    │      (skip if any API down)        │  Before spending quota
    └────────┬─────────────────────────────┘
             │
    ┌────────▼────────────────────────────┐
    │  2️⃣  INVESTIGATOR                  │  Gemini 2.5 Flash
    │      ├─ FRED (rates, inflation)    │
    │      ├─ CoinGecko (prices, vol)    │  Synthesizes briefing
    │      ├─ Alpha Vantage (RSI, MACD)  │  per asset: thesis,
    │      ├─ CryptoPanic (sentiment)    │  risk factors, bias
    │      └─► JSON Briefing             │
    └────────┬─────────────────────────────┘
             │
    ┌────────▼────────────────────────────┐
    │  3️⃣  MANAGER                       │  Gemini 2.5 Pro
    │      (1 req/cycle, 100 req/day)    │
    │      ├─ Receives briefing          │  Final decision:
    │      ├─ Applies risk veto          │  BUY / SELL / HOLD
    │      └─► Decisions[]               │  with sizing
    └────────┬─────────────────────────────┘
             │
    ┌────────▼────────────────────────────┐
    │  4️⃣  TELEGRAM APPROVAL             │  Human-in-the-loop
    │      ├─ Send thesis summary        │
    │      ├─ Wait for /sim or /nao      │  5-min timeout →
    │      └─ Auto-reject if no response │  auto-reject
    └────────┬─────────────────────────────┘
             │
    ┌────────▼────────────────────────────┐
    │  5️⃣  HYPERLIQUID EXECUTION         │  Only if approved
    │      ├─ Entry order (IOC limit)    │
    │      ├─ Stop-loss (reduce-only)    │  No frontrunning
    │      ├─ Take-profit (reduce-only)  │  protection via L1
    │      └─► LIVE POSITIONS            │
    └────────────────────────────────────┘
```

---

## 📁 Project Structure

```
clawcapital/
│
├── 🚀 main.py                    entry point, CLI, loop manager
├── 🎭 orchestrator.py            cycle coordinator
│
├── 🧠 agents/
│   ├── investigator.py           data synthesis (Gemini Flash)
│   └── manager.py                final decisions (Gemini Pro)
│
├── 🔧 skills/                    stateless, reusable building blocks
│   ├── data_fetchers/
│   │   ├── coingecko.py          prices, OHLC, snapshots
│   │   ├── cryptopanic.py        news + sentiment votes
│   │   ├── fred.py               macro series (rates, CPI, yield curve)
│   │   └── alpha_vantage.py      RSI, MACD, daily OHLCV
│   ├── sentiment/
│   │   └── gemini_sentiment.py   Flash-based sentiment scoring
│   ├── technical/
│   │   ├── sma.py                simple moving averages
│   │   └── signal.py             price vs SMA directional signal
│   └── sizing/
│       ├── kelly.py              full Kelly + fractional
│       └── fixed_fractional.py   fixed-risk sizing
│
├── ⚙️ executor/
│   └── hyperliquid.py            PAPER / TEST / LIVE execution
│
├── 💬 notifications/
│   └── telegram.py               thesis delivery + approval polling
│
├── 🛡️ risk/
│   └── calculator.py             Kelly hybrid, position sizing
│
├── 📚 docs/                       design notes, principles
└── 💾 memory/                     cycle logs, trades (gitignored)
```

---

## 🤖 AI Models

| Agent | Model | Role | Quota |
|:---:|:---:|---|:---:|
| **Investigator** 🔍 | Gemini 2.5 Flash | Fast data synthesis, briefing | ✅ Generous |
| **Manager** 📊 | Gemini 2.5 Pro | Final investment decision | ⚠️ 100/day |

**One API key, two models.** Manager is called once per cycle. Investigator is called once per cycle.

---

## 🛡️ Risk Controls

Every order passes through **4 independent vetoes:**

```
📋 Manager Agent Decision
    ↓ (conviction + confidence scoring)

🚫 Safety Vetoes (code-level)
    ├─ Min confidence threshold
    ├─ Max open positions
    └─ Geometrically valid stop-loss
    ↓

👤 Human Approval (Telegram)
    ├─ /sim → execute
    ├─ /nao → reject
    └─ Timeout → auto-reject
    ↓

🔒 Hyperliquid (reduce_only SL/TP)
    └─ Prevents position growth on protection orders
```

**Capital preservation > returns.** Every decision prioritizes defense.

---

## ⚡ Quick Start

### Prerequisites
- **Python 3.12** (Google Cloud Ubuntu 24.04)
- **Hyperliquid** testnet or mainnet wallet
- **API Keys:** Gemini, CoinGecko, CryptoPanic (free tiers available)

### Installation

```bash
# Clone & setup
git clone https://github.com/seu_usuario/clawcapital.git
cd clawcapital
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# 👉 Edit .env with your tokens
```

### Required Variables

```env
# AI & Data APIs
GEMINI_API_KEY=your_key_here              # https://aistudio.google.com
CRYPTOPANIC_TOKEN=your_token_here         # https://cryptopanic.com

# Optional (higher limits)
COINGECKO_API_KEY=your_key_here           # free
ALPHA_VANTAGE_API_KEY=your_key_here       # 25 req/day free
FRED_API_KEY=your_key_here                # free

# Telegram (human approval)
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_CHAT_ID=your_chat_id

# Hyperliquid Live Trading
HL_MODE=paper|test|live                   # start with paper!
HL_WALLET_ADDRESS=0x...                   # your wallet
HL_PRIVATE_KEY=...                        # sub-account only, never main
```

---

## 🚀 Usage

```bash
# Test one cycle (no Telegram)
python main.py --skip-telegram --json

# Production: every 2 hours
python main.py --loop 7200

# Every 3 hours
python main.py --loop 10800

# Debug mode (skip approval)
python main.py --loop 7200 --skip-telegram
```

---

## 🎮 Execution Modes

| Mode | Behaviour | Use Case |
|:---:|---|---|
| **paper** 📄 | Simulates fills locally | Initial testing |
| **test** 🧪 | Real orders on testnet | Validate logic |
| **live** 🟢 | Real orders on mainnet | Production |

```
paper → test → live
(30 min)  (1-2 days)  (when confident)
```

---

## 📊 Alpha Vantage Quota Strategy

Free plan: **25 requests/day**

- Each ticker = 3 requests (snapshot + RSI + MACD)
- Default: `MAX_AV_TICKERS=2`
- Supports 4 cycles/day safely
- 🎯 Adjust based on your cycle frequency

---

## 💾 Memory & Logging

All runtime data is persisted in `memory/` (gitignored):

| File | Contents |
|---|---|
| `cycles-log.json` | Full cycle output (last 500) |
| `heartbeat-log.json` | Connectivity history |
| `trades-history.json` | All submitted orders + fills |
| `closed-trades.json` | Closed positions with PnL |

**Inspect anytime:**
```bash
tail -f memory/cycles-log.json | jq '.'
```

---

## 🔍 Debugging

**Order didn't execute?**
- Check Telegram approval history
- Verify `HYPERLIQUID_PRIVATE_KEY` permissions (sub-account only)
- Review `memory/trades-history.json`

**Low conviction scores?**
- Check macro data freshness (`memory/heartbeat-log.json`)
- Verify CryptoPanic is returning headlines
- Run with `--json` flag to see raw briefing

**API rate limits hit?**
- Increase cycle interval (e.g., `--loop 14400` = 4h)
- Upgrade free tiers to paid (CoinGecko, Alpha Vantage)
- Check `memory/heartbeat-log.json` for failed fetches

---

## 📈 Performance Metrics

ClawCapital targets:

- **Sharpe Ratio > 1.5**
- **Win Rate > 55%** with RRR > 2:1
- **Max Drawdown < 15%** annually
- **Benchmark:** S&P 500 returns with 50% lower volatility

Review weekly. Backtest monthly. Audit quarterly.

---

## 🤝 Contributing

This is a **proprietary system**. No external contributions.

For internal improvements:
1. Test on `paper` mode for 1 week
2. Test on testnet for 2–3 days
3. Code review with lead developer
4. Merge to `main` only

---

## 📜 License

**Proprietary.** All rights reserved. Not for redistribution.

---

## 🔗 Resources

- **Hyperliquid Docs:** https://hyperliquid.xyz/
- **Gemini API:** https://aistudio.google.com
- **CryptoPanic:** https://cryptopanic.com
- **FRED:** https://fred.stlouisfed.org

---

## 💡 Principles (SOUL.md)

1. **Capital preservation** is rule #1
2. **No revenge trading** — wait for the next signal
3. **Validate across 3 sources:** macro + sentiment + technicals
4. **Human always approves** — AI suggests, humans decide
5. **No leverage > 3x** — safety first

---

<div align="center">

**Built with ❤️ for disciplined, systematic trading.**

Questions? Open an issue. (Proprietary repo — internal only.)

</div>