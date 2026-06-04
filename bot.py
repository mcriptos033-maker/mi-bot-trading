import json
import logging
from datetime import datetime, date, timedelta, time as dt_time
from pathlib import Path

import pytz
from telegram import Update, Bot
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config import Config
from scraper import get_high_impact_events
from analyst import analyze_pre_event, analyze_post_event, answer_question

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
# Formatting
# ---------------------------------------------------------------------------

def _local_time(time_utc: datetime | None, tz: pytz.timezone) -> str:
    if time_utc is None:
        return "?:??"
    return time_utc.astimezone(tz).strftime("%H:%M")


def _fmt_event_row(event: dict, tz: pytz.timezone, released: bool = False) -> str:
    t = _local_time(event.get("time_utc"), tz)
    cur = event.get("currency", "")
    title = event.get("title", "")
    forecast = event.get("forecast")
    previous = event.get("previous")
    actual = event.get("actual")
    source = event.get("source", "")

    if released and actual:
        icon = "✅"
        line = f"{icon} *{t}* | {cur} | {title}"
        line += f"\n   🎯 Actual: `{actual}`"
        if forecast:
            line += f"  |  Est: `{forecast}`"
        if previous:
            line += f"  |  Ant: `{previous}`"
    else:
        icon = "🔴"
        line = f"{icon} *{t}* | {cur} | {title}"
        if forecast:
            line += f"\n   📊 Estimado: `{forecast}`"
        if previous:
            line += f"\n   ⬅️ Anterior: `{previous}`"

    line += f"\n   📌 _{source}_"
    return line


def _fmt_digest(events: list[dict], tz: pytz.timezone, target_date: date) -> str:
    date_str = target_date.strftime("%A %d de %B de %Y")
    tz_label = str(tz).split("/")[-1].replace("_", " ")
    now_utc = datetime.now(pytz.utc)

    past = [e for e in events if e.get("time_utc") and e["time_utc"] < now_utc]
    upcoming = [e for e in events if not e.get("time_utc") or e["time_utc"] >= now_utc]

    sections = [
        f"📅 *CALENDARIO ECONÓMICO — Alto Impacto*",
        f"_{date_str}_ · {tz_label}\n",
    ]

    if past:
        sections.append("━━━━━━━━━━━━━━━━━━━")
        sections.append("✅ *YA PUBLICADOS*")
        sections.append("━━━━━━━━━━━━━━━━━━━\n")
        sections.extend(_fmt_event_row(e, tz, released=True) for e in past)

    if upcoming:
        sections.append("\n━━━━━━━━━━━━━━━━━━━")
        sections.append("⏳ *PENDIENTES HOY*")
        sections.append("━━━━━━━━━━━━━━━━━━━\n")
        sections.extend(_fmt_event_row(e, tz, released=False) for e in upcoming)

    if not past and not upcoming:
        sections.append("Sin eventos de alto impacto programados para hoy ✅")

    return "\n".join(sections)


def _events_context_str(events: list[dict]) -> str:
    lines = []
    for e in events:
        actual = e.get("actual")
        forecast = e.get("forecast")
        previous = e.get("previous")
        status = f"actual={actual}" if actual else f"estimado={forecast}"
        lines.append(f"- {e.get('title')} ({e.get('currency')}): {status}, anterior={previous}")
    return "\n".join(lines)


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
        "✅ *Bot de Análisis Fundamental activado*\n\n"
        "Recibirás automáticamente:\n"
        f"• 🌅 *Calendario diario* a las {Config.MORNING_HOUR:02d}:{Config.MORNING_MINUTE:02d} ({tz_label})\n"
        f"• ⚡ *Alerta + pre-análisis IA* {Config.PRE_NEWS_MINUTES} min antes de cada evento\n"
        f"• 📊 *Resultado + análisis fundamental* ~{Config.POST_EVENT_DELAY_MIN} min después del dato\n\n"
        "También podés escribirme cualquier pregunta de fundamental y te respondo con IA 🤖\n\n"
        "Comandos:\n"
        "/hoy — Calendario de hoy\n"
        "/manana — Calendario de mañana\n"
        "/stop — Desactivar notificaciones",
        parse_mode="Markdown",
    )


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    subs = load_subscribers()
    subs.discard(chat_id)
    save_subscribers(subs)
    await update.message.reply_text(
        "🛑 Notificaciones desactivadas.\nUsá /start para reactivarlas."
    )


async def cmd_hoy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tz = pytz.timezone(Config.TIMEZONE)
    today = datetime.now(tz).date()
    await update.message.reply_text("⏳ Consultando calendarios económicos...")
    events = get_high_impact_events(today)
    await update.message.reply_text(
        _fmt_digest(events, tz, today), parse_mode="Markdown"
    )


async def cmd_manana(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tz = pytz.timezone(Config.TIMEZONE)
    tomorrow = datetime.now(tz).date() + timedelta(days=1)
    await update.message.reply_text("⏳ Consultando calendarios económicos...")
    events = get_high_impact_events(tomorrow)
    await update.message.reply_text(
        _fmt_digest(events, tz, tomorrow), parse_mode="Markdown"
    )


async def handle_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle any free-text message as a fundamental analysis question."""
    question = update.message.text
    await context.bot.send_chat_action(update.effective_chat.id, "typing")

    tz = pytz.timezone(Config.TIMEZONE)
    today = datetime.now(tz).date()
    events = get_high_impact_events(today)
    ctx_str = _events_context_str(events)

    answer = answer_question(question, ctx_str)
    await update.message.reply_text(answer)


# ---------------------------------------------------------------------------
# Scheduled jobs
# ---------------------------------------------------------------------------

async def job_morning_digest(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send daily calendar and queue per-event jobs."""
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

        # 7-minute pre-alert
        alert_at = time_utc - timedelta(minutes=Config.PRE_NEWS_MINUTES)
        if alert_at > now_utc:
            context.job_queue.run_once(
                job_pre_alert,
                when=alert_at,
                data={"event": event, "subscribers": list(subs)},
                name=f"pre_{event.get('title', '')[:20]}_{time_utc.isoformat()}",
            )

        # Post-event analysis
        post_at = time_utc + timedelta(minutes=Config.POST_EVENT_DELAY_MIN)
        if post_at > now_utc:
            context.job_queue.run_once(
                job_post_analysis,
                when=post_at,
                data={
                    "event": event,
                    "subscribers": list(subs),
                    "target_date": today,
                },
                name=f"post_{event.get('title', '')[:20]}_{time_utc.isoformat()}",
            )

    logger.info("Morning digest sent to %d subscribers, %d events scheduled.", len(subs), len(events))


async def job_pre_alert(context: ContextTypes.DEFAULT_TYPE) -> None:
    """7-minute pre-event alert with AI pre-analysis."""
    data = context.job.data
    event = data["event"]
    subs = data["subscribers"]

    tz = pytz.timezone(Config.TIMEZONE)
    t = _local_time(event.get("time_utc"), tz)
    cur = event.get("currency", "")
    title = event.get("title", "")
    forecast = event.get("forecast")
    previous = event.get("previous")

    header_lines = [
        f"⚡ *ALERTA — {Config.PRE_NEWS_MINUTES} MIN PARA EL DATO*\n",
        f"🔴 *{title}*",
        f"💱 {cur}  🕐 {t}",
    ]
    if forecast:
        header_lines.append(f"📊 Estimado: `{forecast}`")
    if previous:
        header_lines.append(f"⬅️ Anterior: `{previous}`")
    header_lines.append(f"\n⚠️ *Evitá operar hasta 15 min después del dato*\n")

    header = "\n".join(header_lines)

    # Get AI pre-analysis
    bot: Bot = context.bot
    for chat_id in subs:
        try:
            await bot.send_message(chat_id=chat_id, text=header, parse_mode="Markdown")
        except Exception as exc:
            logger.error("Pre-alert header failed for %s: %s", chat_id, exc)

    analysis_text = analyze_pre_event(event)
    analysis_msg = f"🤖 *PRE-ANÁLISIS FUNDAMENTAL*\n\n{analysis_text}"

    for chat_id in subs:
        try:
            await bot.send_message(chat_id=chat_id, text=analysis_msg, parse_mode="Markdown")
        except Exception as exc:
            logger.error("Pre-alert analysis failed for %s: %s", chat_id, exc)


async def job_post_analysis(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Post-event: fetch actual result and send full fundamental analysis."""
    data = context.job.data
    original_event = data["event"]
    target_date = data["target_date"]
    subs = data["subscribers"]

    # Re-fetch to get actual value
    fresh_events = get_high_impact_events(target_date)
    title_key = (original_event.get("title") or "").strip().lower()[:35]
    event = next(
        (e for e in fresh_events if (e.get("title") or "").strip().lower()[:35] == title_key),
        original_event,
    )

    actual = event.get("actual")
    forecast = event.get("forecast")
    previous = event.get("previous")
    cur = event.get("currency", "")
    title = event.get("title", "")
    tz = pytz.timezone(Config.TIMEZONE)
    t = _local_time(event.get("time_utc"), tz)

    if not actual:
        logger.info("No actual value yet for '%s', skipping post-analysis.", title)
        return

    result_lines = [
        f"📊 *RESULTADO — {title}*\n",
        f"💱 {cur}  🕐 {t}",
        f"🎯 *Actual: `{actual}`*",
    ]
    if forecast:
        result_lines.append(f"📈 Estimado: `{forecast}`")
    if previous:
        result_lines.append(f"⬅️ Anterior: `{previous}`")

    result_msg = "\n".join(result_lines)

    bot: Bot = context.bot
    for chat_id in subs:
        try:
            await bot.send_message(chat_id=chat_id, text=result_msg, parse_mode="Markdown")
        except Exception as exc:
            logger.error("Post result failed for %s: %s", chat_id, exc)

    analysis_text = analyze_post_event(event)
    analysis_msg = f"🤖 *ANÁLISIS FUNDAMENTAL*\n\n{analysis_text}"

    for chat_id in subs:
        try:
            await bot.send_message(chat_id=chat_id, text=analysis_msg, parse_mode="Markdown")
        except Exception as exc:
            logger.error("Post analysis failed for %s: %s", chat_id, exc)


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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_question))

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
        "Bot iniciado. Resumen diario %02d:%02d (%s).",
        Config.MORNING_HOUR,
        Config.MORNING_MINUTE,
        Config.TIMEZONE,
    )
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
