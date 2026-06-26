"""
CalmDownBot — Contrarian Investor Sentiment Tracker
"Be greedy when others are fearful." — Warren Buffett

Watches Fear & Greed indices for US, India, and Crypto markets.
Alerts you when blood is on the streets.
"""
from dotenv import load_dotenv; load_dotenv()
import os
import sys
import json
import asyncio
import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ─── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ─── Config ─────────────────────────────────────────────────────────────────
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]          # your personal/group chat ID

# Alert thresholds — tweak these to your risk appetite
DEFAULT_ALERT_THRESHOLD = 30   # alert when index <= this value
EXTREME_FEAR_THRESHOLD  = 20   # "blood on the streets" level
BUY_SIGNAL_THRESHOLD    = 25   # strong contrarian buy zone

IST = ZoneInfo("Asia/Kolkata")
SCHEDULED_REPORT_TIMES = [
    (8, 0),   # 08:00 IST — morning snapshot before India market opens
    (15, 0),  # 15:00 IST — afternoon update for India and crypto markets
]

# ─── Sentiment Labels ────────────────────────────────────────────────────────
def sentiment_label(value: int) -> str:
    if value <= 20:  return "🩸 Extreme Fear"
    if value <= 40:  return "😨 Fear"
    if value <= 60:  return "😐 Neutral"
    if value <= 80:  return "😏 Greed"
    return               "🤑 Extreme Greed"

def sentiment_emoji_bar(value: int) -> str:
    """Visual progress bar for the index value."""
    filled = round(value / 10)
    empty  = 10 - filled
    return "█" * filled + "░" * empty

def buy_signal_comment(value: int) -> str:
    """Contrarian commentary based on the index value."""
    if value <= 10: return "🚨 MAXIMUM BLOOD. Rothschild would be foaming at the mouth."
    if value <= 20: return "🩸 Streets are bleeding. Buffett is smiling."
    if value <= 25: return "📉 Strong contrarian buy zone. Time to load up?"
    if value <= 30: return "👀 Fear is elevated. Worth watching closely."
    if value <= 40: return "🔍 Mild fear. Stay alert, not urgent."
    if value <= 60: return "😴 Neutral. Nothing to do here."
    if value <= 80: return "⚠️ Greed is building. Tread carefully."
    return                  "🔥 Extreme greed. Everyone's in. Be careful."

# ─── Data Fetchers ───────────────────────────────────────────────────────────

async def fetch_crypto_fear_greed() -> dict:
    """Alternative.me Crypto Fear & Greed Index — free, no key needed."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get("https://api.alternative.me/fng/?limit=2")
        r.raise_for_status()
        data = r.json()["data"]
        current  = data[0]
        previous = data[1]
        val      = int(current["value"])
        prev_val = int(previous["value"])
        return {
            "market":    "Crypto (BTC)",
            "value":     val,
            "prev":      prev_val,
            "trend":     "↑" if val > prev_val else ("↓" if val < prev_val else "→"),
            "label":     current["value_classification"],
            "sentiment": sentiment_label(val),
            "updated":   datetime.fromtimestamp(int(current["timestamp"]), tz=IST).strftime("%d %b %Y"),
        }


async def fetch_us_fear_greed() -> dict:
    """
    CNN Fear & Greed Index via RapidAPI (or scrape fallback).
    Free tier: https://rapidapi.com/rpi4gx/api/fear-and-greed-index
    Set RAPIDAPI_KEY env var, or we fall back to a scrape.
    """
    rapidapi_key = os.environ.get("RAPIDAPI_KEY")
    if rapidapi_key:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://fear-and-greed-index.p.rapidapi.com/v1/fgi",
                headers={
                    "X-RapidAPI-Key":  rapidapi_key,
                    "X-RapidAPI-Host": "fear-and-greed-index.p.rapidapi.com",
                },
            )
            r.raise_for_status()
            d   = r.json()["fgi"]
            val = round(d["now"]["value"])
            prev = round(d["previousClose"]["value"])
            return {
                "market":    "US Equities (S&P 500)",
                "value":     val,
                "prev":      prev,
                "trend":     "↑" if val > prev else ("↓" if val < prev else "→"),
                "label":     d["now"]["valueText"],
                "sentiment": sentiment_label(val),
                "updated":   datetime.now(IST).strftime("%d %b %Y"),
            }
    else:
        # Fallback: scrape CNN markets API (no key needed, may break)
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            r = await client.get(
                "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            r.raise_for_status()
            d   = r.json()
            val = round(d["fear_and_greed"]["score"])
            prev = round(d["fear_and_greed_historical"]["data"][-2]["y"]) if len(d.get("fear_and_greed_historical", {}).get("data", [])) > 1 else val
            return {
                "market":    "US Equities (S&P 500)",
                "value":     val,
                "prev":      prev,
                "trend":     "↑" if val > prev else ("↓" if val < prev else "→"),
                "label":     d["fear_and_greed"]["rating"],
                "sentiment": sentiment_label(val),
                "updated":   datetime.now(IST).strftime("%d %b %Y"),
            }


async def fetch_india_sentiment() -> dict:
    """
    India VIX as a proxy for fear (NSE).
    VIX > 20 = fear, > 30 = extreme fear (inverted scale mapped to 0-100).
    """
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        r = await client.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/%5EINDIAVIX?interval=1d&range=2d",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        r.raise_for_status()
        result  = r.json()["chart"]["result"][0]
        closes  = result["indicators"]["quote"][0]["close"]
        
        # Filter out None values and get valid data points
        valid_closes = [c for c in closes if c is not None]
        if not valid_closes:
            raise ValueError("No valid India VIX data available")
        
        vix_now  = valid_closes[-1]
        vix_prev = valid_closes[-2] if len(valid_closes) > 1 else vix_now

        # Convert VIX to a fear/greed score (0-100, inverted)
        # VIX 10 = 90 (greed), VIX 40 = 0 (extreme fear), linear clamp
        def vix_to_score(v): return max(0, min(100, round(100 - ((v - 10) / 30) * 100)))
        val  = vix_to_score(vix_now)
        prev = vix_to_score(vix_prev)

        return {
            "market":    "India (Nifty/VIX)",
            "value":     val,
            "prev":      prev,
            "trend":     "↑" if val > prev else ("↓" if val < prev else "→"),
            "label":     f"VIX {vix_now:.1f}",
            "sentiment": sentiment_label(val),
            "updated":   datetime.now(IST).strftime("%d %b %Y"),
        }


async def fetch_all() -> list[dict]:
    results = await asyncio.gather(
        fetch_crypto_fear_greed(),
        fetch_us_fear_greed(),
        fetch_india_sentiment(),
        return_exceptions=True,
    )
    out = []
    for r in results:
        if isinstance(r, Exception):
            log.error("Fetch error: %s", r)
        else:
            out.append(r)
    return out

# ─── Message Formatters ──────────────────────────────────────────────────────

def format_market_card(m: dict) -> str:
    bar   = sentiment_emoji_bar(m["value"])
    delta = m["value"] - m["prev"]
    delta_str = f"+{delta}" if delta > 0 else str(delta)
    comment = buy_signal_comment(m["value"])
    return (
        f"*{m['market']}*\n"
        f"`{bar}` {m['value']}/100 ({delta_str})\n"
        f"{m['sentiment']}  {m['trend']}  _{m['label']}_\n"
        f"{comment}\n"
    )


def format_full_report(markets: list[dict]) -> str:
    now  = datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST")
    body = "\n\n".join(format_market_card(m) for m in markets)
    lowest = min(markets, key=lambda x: x["value"])
    overall = buy_signal_comment(lowest["value"])
    return (
        f"📊 *Market Sentiment Report*\n"
        f"_{now}_\n\n"
        f"{body}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"*Contrarian Take:* {overall}"
    )


def format_alert(m: dict, threshold: int) -> str:
    now = datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST")
    return (
        f"🚨 *FEAR ALERT — {m['market']}*\n"
        f"_{now}_\n\n"
        f"Index dropped to *{m['value']}/100* (threshold: {threshold})\n"
        f"{m['sentiment']}\n\n"
        f"{buy_signal_comment(m['value'])}\n\n"
        f"_\"The time to buy is when there's blood in the streets.\" — Baron Rothschild_"
    )

# ─── Alert State ─────────────────────────────────────────────────────────────
# Tracks last alerted value per market to avoid repeat pings
alert_state: dict[str, int] = {}

# User-configurable threshold (persisted in memory; use a DB for production)
user_threshold: dict[str, int] = {}  # chat_id -> threshold

def get_threshold(chat_id: str) -> int:
    return user_threshold.get(str(chat_id), DEFAULT_ALERT_THRESHOLD)

# ─── Scheduled Jobs ──────────────────────────────────────────────────────────

async def send_scheduled_sentiment_report(app: Application | None = None):
    """Send the /sentiment-style report to the configured chat."""
    try:
        markets = await fetch_all()
        if not markets:
            log.warning("Scheduled sentiment report skipped: no market data")
            return
        msg = format_full_report(markets)
        if app is not None:
            await app.bot.send_message(
                chat_id=CHAT_ID,
                text=msg,
                parse_mode="Markdown",
            )
        else:
            bot = Bot(token=BOT_TOKEN)
            await bot.send_message(
                chat_id=CHAT_ID,
                text=msg,
                parse_mode="Markdown",
            )
        log.info("Scheduled sentiment report sent.")
    except Exception as e:
        log.error("Scheduled sentiment report failed: %s", e)


async def check_alerts(app: Application):
    """Check all markets and fire alerts if any cross the fear threshold."""
    try:
        markets  = await fetch_all()
        threshold = get_threshold(CHAT_ID)
        for m in markets:
            key       = m["market"]
            val       = m["value"]
            last_alerted = alert_state.get(key, 999)

            # Fire alert if:
            # 1. Value is below threshold AND
            # 2. We haven't already alerted at this level (avoid spam)
            if val <= threshold and val < last_alerted:
                alert_state[key] = val
                await app.bot.send_message(
                    chat_id=CHAT_ID,
                    text=format_alert(m, threshold),
                    parse_mode="Markdown",
                )
                log.info("Alert fired for %s at %d", key, val)
            elif val > threshold and key in alert_state:
                # Reset alert state once market recovers above threshold
                del alert_state[key]
                log.info("Alert reset for %s (recovered to %d)", key, val)
    except Exception as e:
        log.error("Alert check failed: %s", e)

# ─── Bot Commands ─────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *CalmDownBot* is watching the markets for you.\n\n"
        "I'll alert you when fear spikes — your contrarian buy signal.\n\n"
        "*Commands:*\n"
        "/sentiment — Current market sentiment\n"
        "/setalert — Configure your fear alert threshold\n"
        "/threshold — View current alert threshold\n"
        "/help — Show this message",
        parse_mode="Markdown",
    )


async def cmd_sentiment(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Fetching live sentiment data...")
    try:
        markets = await fetch_all()
        if not markets:
            await msg.edit_text("❌ Could not fetch data. Try again later.")
            return
        await msg.edit_text(
            format_full_report(markets),
            parse_mode="Markdown",
        )
    except Exception as e:
        log.error("cmd_sentiment error: %s", e)
        await msg.edit_text("❌ Error fetching data. Check logs.")


async def cmd_setalert(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("🩸 ≤ 15  (Extreme Blood)", callback_data="alert_15"),
            InlineKeyboardButton("😨 ≤ 20  (Extreme Fear)", callback_data="alert_20"),
        ],
        [
            InlineKeyboardButton("📉 ≤ 25  (Buy Zone)",     callback_data="alert_25"),
            InlineKeyboardButton("👀 ≤ 30  (Fear — Default)", callback_data="alert_30"),
        ],
        [
            InlineKeyboardButton("🔍 ≤ 40  (Mild Fear)",    callback_data="alert_40"),
        ],
    ]
    await update.message.reply_text(
        "⚙️ *Set your Fear Alert Threshold*\n\n"
        "I'll ping you when any market index drops *at or below* this value.\n"
        "_Lower = only alert when it's really bad (contrarian sweet spot)._",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def callback_setalert(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    threshold = int(query.data.split("_")[1])
    chat_id   = str(query.message.chat_id)
    user_threshold[chat_id] = threshold
    await query.edit_message_text(
        f"✅ Alert threshold set to *{threshold}/100*.\n\n"
        f"You'll be pinged when any market drops to *{sentiment_label(threshold)}* territory.\n"
        f"{buy_signal_comment(threshold)}",
        parse_mode="Markdown",
    )


async def cmd_threshold(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id   = str(update.message.chat_id)
    threshold = get_threshold(chat_id)
    await update.message.reply_text(
        f"📐 Current alert threshold: *{threshold}/100*\n"
        f"Zone: {sentiment_label(threshold)}\n\n"
        f"Use /setalert to change it.",
        parse_mode="Markdown",
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, ctx)

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Register commands
    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("sentiment", cmd_sentiment))
    app.add_handler(CommandHandler("setalert",  cmd_setalert))
    app.add_handler(CommandHandler("threshold", cmd_threshold))
    app.add_handler(CommandHandler("help",      cmd_help))
    app.add_handler(CallbackQueryHandler(callback_setalert, pattern=r"^alert_\d+$"))

    # Scheduler
    scheduler = AsyncIOScheduler(timezone=IST)

    # Scheduled sentiment reports at morning and afternoon IST times.
    for hour, minute in SCHEDULED_REPORT_TIMES:
        scheduler.add_job(
            send_scheduled_sentiment_report, "cron",
            hour=hour,
            minute=minute,
            args=[app],
            id=f"sentiment_report_{hour:02d}{minute:02d}",
        )

    # Alert checks every 30 minutes during market hours (8 AM – 11:30 PM IST covers all 3 markets)
    scheduler.add_job(
        check_alerts, "interval",
        minutes=30,
        args=[app],
        id="alert_check",
    )

    scheduler.start()
    log.info("CalmDownBot started. Scheduler running.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


async def run_one_off_report():
    await send_scheduled_sentiment_report()


if __name__ == "__main__":
    if "--send-report" in sys.argv:
        asyncio.run(run_one_off_report())
    else:
        main()
