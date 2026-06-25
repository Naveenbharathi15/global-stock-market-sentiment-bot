# CalmDownBot 🩸
> *"Be greedy when others are fearful."* — Warren Buffett

Watches Fear & Greed indices for **US, India, and Crypto** markets.
Pings you when blood is on the streets — your contrarian buy signal.

---

## Markets Watched

| Market | Source | Notes |
|--------|--------|-------|
| 🇺🇸 US Equities | CNN Fear & Greed Index | Via RapidAPI (free tier) or direct scrape |
| 🇮🇳 India (Nifty) | India VIX via Yahoo Finance | VIX converted to 0–100 fear/greed scale |
| ₿ Crypto (BTC) | Alternative.me F&G Index | Free, no API key needed |

---

## Setup

### 1. Create your bot
1. Open Telegram → search `@BotFather`
2. Send `/newbot` → follow prompts → copy your **bot token**
3. Get your **chat ID** via `@userinfobot`

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure environment
```bash
cp .env.example .env
# Edit .env and fill in TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
```

### 4. (Optional) Get RapidAPI key for US market
- Sign up free at https://rapidapi.com/rpi4gx/api/fear-and-greed-index
- Add `RAPIDAPI_KEY` to your `.env`
- Without it, the bot uses CNN's direct endpoint (works but less stable)

### 5. Run
```bash
# Load env vars and run
export $(cat .env | xargs) && python bot.py
```

Or with python-dotenv installed:
```bash
pip install python-dotenv
# Add this to top of bot.py: from dotenv import load_dotenv; load_dotenv()
python bot.py
```

---

## Bot Commands

| Command | Description |
|---------|-------------|
| `/sentiment` | Fetch current sentiment for all 3 markets right now |
| `/setalert` | Set your fear threshold (inline buttons) |
| `/threshold` | View your current alert threshold |
| `/help` | Show help |

---

## Alert Thresholds

| Threshold | Zone | What it means |
|-----------|------|---------------|
| ≤ 15 | 🩸 Maximum Blood | Rothschild territory |
| ≤ 20 | 😨 Extreme Fear | Buffett is smiling |
| ≤ 25 | 📉 Strong Buy Zone | Contrarian sweet spot |
| ≤ 30 | 👀 Fear (Default) | Worth watching |
| ≤ 40 | 🔍 Mild Fear | Stay alert |

---

## Schedule

- **8:00 AM IST** — Daily report sent automatically
- **Every 30 min** — Alert check runs silently; pings only when threshold crossed

---

## Running 24/7 (on a server)

```bash
# Using screen
screen -S calmdownbot
export $(cat .env | xargs) && python bot.py
# Ctrl+A, D to detach

# Or with systemd (recommended for VPS)
# Create /etc/systemd/system/calmdownbot.service
```

Cheapest options: **Oracle Cloud Free Tier** (always free VPS) or a ₹200/mo Hetzner VPS.
