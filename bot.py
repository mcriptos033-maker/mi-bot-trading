import json
import logging
from datetime import datetime, date, timedelta, time as dt_time
from pathlib import Path

import pytz
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes

from config import Config
from scraper import get_high_impact_events

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

SUBSCRIBERS_FILE = Path("subscribers.json")


# ---------------------------------------------------------------------------
# Subscriber persistence
# ---------------------------------------------------------------------------

def load_subscribers() -> set[int]:
    if SUBSCRIBERS_FILE.exists():
        with open(SUBSCRIBERS_FILE) as f:
            return set(json.load(f))
    return set()


def save_subscribers(subs: set[int]) -> None:
    with open(SUBSCRIBERS_FILE, "w") as f:
        json.dump(list(subs), f)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _local_time(time_utc: datetime | None, tz: pytz.timezone) -> str:
    if time_utc is None:
        return "?:??"
    return time_utc.astimezone(tz).strftime("%H:%M")


def _fmt_event(event: dict, tz: pytz.timezone) -> str:
    t = _local_time(event.get("time_utc"), tz)
    currency = event.get("currency", "")
    title = event.get("title", "")
    forecast = event.get("forecast")
    previous = event.get("previous")
    source = event.get("source", "")

    lines = [f"🔴 *{t}* | {currency} | {title}"]
    if forecast:
        lines.append(f"   📊 Estimado: `{forecast}`")
    if previous:
        lines.append(f"   ⬅️ Anterior: `{previous}`")
    lines.append(f"   📌 _{source}_")
    return "\n".join(lines)


def _fmt_digest(events: list[dict], tz: pytz.timezone, target_date: date) -> str:
    date_str = target_date.strftime("%A %d de %B de %Y")
    tz_label = str(tz).split("/")[-1].replace("_", " ")

    if not events:
        return (
            f"📅 *Noticias de alto impacto — {date_str}*\n\n"
            "Sin eventos de alto impacto programados para hoy ✅"
        )

    header = (
        f"📅 *Noticias de Alto Impacto*\n"
        f"_{date_str}_ · {tz_label}\n"
        f"Total: {len(events)} eventos\n"
    )
    body = "\n\n".join(_fmt_event(e, tz) for e in events)
    return header + "\n" + body


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    subs = load_subscribers()
    subs.add(chat_id)
    save_subscribers(subs)

    tz_label = Config.TIMEZONE.split("/")[-1].replace("_", " ")
    await update.message.reply_text(
        "✅ *Bot de Noticias Económicas activado*\n\n"
        "Recibirás automáticamente:\n"
        f"• 🌅 Resumen diario a las *{Config.MORNING_HOUR:02d}:{Config.MORNING_MINUTE:02d}* ({tz_label})\n"
        f"• ⚡ Alertas *{Config.PRE_NEWS_MINUTES} min* antes de cada noticia de alto impacto\n\n"
        "Comandos:\n"
        "/hoy — Noticias de hoy\n"
        "/manana — Noticias de mañana\n"
        "/stop — Desactivar notificaciones",
        parse_mode="Markdown",
    )


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    subs = load_subscribers()
    subs.discard(chat_id)
    save_subscribers(subs)
    await update.message.reply_text(
        "🛑 Notificaciones desactivadas.\nUsa /start para reactivarlas cuando quieras."
    )


async def cmd_hoy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tz = pytz.timezone(Config.TIMEZONE)
    today = datetime.now(tz).date()
    await update.message.reply_text("⏳ Consultando calendarios...")
    events = get_high_impact_events(today)
    await update.message.reply_text(
        _fmt_digest(events, tz, today), parse_mode="Markdown"
    )


async def cmd_manana(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tz = pytz.timezone(Config.TIMEZONE)
    tomorrow = datetime.now(tz).date() + timedelta(days=1)
    await update.message.reply_text("⏳ Consultando calendarios...")
    events = get_high_impact_events(tomorrow)
    await update.message.reply_text(
        _fmt_digest(events, tz, tomorrow), parse_mode="Markdown"
    )


# ---------------------------------------------------------------------------
# Scheduled jobs
# ---------------------------------------------------------------------------

async def job_morning_digest(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send daily digest and queue per-event alerts."""
    tz = pytz.timezone(Config.TIMEZONE)
    today = datetime.now(tz).date()
    events = get_high_impact_events(today)

    subs = load_subscribers()
    msg = _fmt_digest(events, tz, today)

    bot: Bot = context.bot
    for chat_id in subs:
        try:
            await bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
        except Exception as exc:
            logger.error("Morning digest failed for %s: %s", chat_id, exc)

    now_utc = datetime.now(pytz.utc)
    for event in events:
        time_utc = event.get("time_utc")
        if not time_utc:
            continue

        alert_at = time_utc - timedelta(minutes=Config.PRE_NEWS_MINUTES)
        if alert_at <= now_utc:
            continue  # already past

        job_name = f"alert_{event.get('title', '')[:25]}_{time_utc.isoformat()}"
        context.job_queue.run_once(
            job_pre_event_alert,
            when=alert_at,
            data={"event": event, "subscribers": list(subs)},
            name=job_name,
        )
        logger.info("Scheduled alert: %s at %s", event.get("title"), alert_at)


async def job_pre_event_alert(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fire an alert N minutes before a news event."""
    data = context.job.data
    event = data["event"]
    subs = data["subscribers"]

    tz = pytz.timezone(Config.TIMEZONE)
    t = _local_time(event.get("time_utc"), tz)
    currency = event.get("currency", "")
    title = event.get("title", "")
    forecast = event.get("forecast")
    previous = event.get("previous")

    lines = [
        f"⚡ *ALERTA — {Config.PRE_NEWS_MINUTES} min para la noticia*\n",
        f"🔴 *{title}*",
        f"💱 {currency}  🕐 {t}",
    ]
    if forecast:
        lines.append(f"📊 Estimado: `{forecast}`")
    if previous:
        lines.append(f"⬅️ Anterior: `{previous}`")

    msg = "\n".join(lines)
    bot: Bot = context.bot
    for chat_id in subs:
        try:
            await bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
        except Exception as exc:
            logger.error("Alert failed for %s: %s", chat_id, exc)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    app = Application.builder().token(Config.TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("hoy", cmd_hoy))
    app.add_handler(CommandHandler("manana", cmd_manana))

    tz = pytz.timezone(Config.TIMEZONE)
    app.job_queue.run_daily(
        job_morning_digest,
        time=dt_time(
            hour=Config.MORNING_HOUR,
            minute=Config.MORNING_MINUTE,
            tzinfo=tz,
        ),
        name="morning_digest",
    )

    logger.info(
        "Bot iniciado. Resumen diario a las %02d:%02d (%s). Ctrl+C para detener.",
        Config.MORNING_HOUR,
        Config.MORNING_MINUTE,
        Config.TIMEZONE,
    )
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
