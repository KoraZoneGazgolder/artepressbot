import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.db import db, due_within, iso, now_msk, now_utc, parse_iso
from app.keyboards import pill_keyboard

log = logging.getLogger(__name__)
scheduler = AsyncIOScheduler(timezone=settings.tz)


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler.add_job(tick, "interval", seconds=30, args=[bot], max_instances=1)
    return scheduler


async def tick(bot: Bot) -> None:
    now = now_msk()
    day = now.strftime("%Y-%m-%d")
    users = await db.list_approved()
    for user in users:
        await _maybe_bp_reminder(bot, user, now, day, "morning", settings.bp_morning)
        await _maybe_bp_reminder(bot, user, now, day, "evening", settings.bp_evening)
        await _maybe_pill_reminders(bot, user, now, day)


async def _maybe_bp_reminder(
    bot: Bot, user: dict, now, day: str, slot: str, hhmm: str
) -> None:
    if not due_within(hhmm, now, window_hours=2):
        return
    kind = f"bp_{slot}"
    if await db.was_reminder_sent(user["id"], kind, hhmm, day):
        return
    when = "утреннее" if slot == "morning" else "вечернее"
    text = (
        f"Пора записать {when} давление.\n"
        f"Пришлите одним сообщением: <code>120/80 72</code>"
    )
    try:
        await bot.send_message(user["telegram_id"], text)
    except Exception:
        log.exception("BP reminder failed for %s", user["telegram_id"])
        return
    await db.mark_reminder_sent(user["id"], kind, hhmm, day)


async def _maybe_pill_reminders(bot: Bot, user: dict, now, day: str) -> None:
    meds = await db.list_meds(user["id"])
    for med in meds:
        for hhmm in med["times"]:
            log_row = await db.get_or_create_pill_log(user["id"], med["id"], day, hhmm)
            if log_row["status"] in {"taken", "skipped"}:
                continue

            should_send = False
            if log_row["status"] == "snoozed" and log_row.get("snooze_until"):
                if now_utc() >= parse_iso(log_row["snooze_until"]):
                    should_send = True
            elif log_row["status"] == "pending" and not log_row.get("reminded_at"):
                if due_within(hhmm, now, window_hours=14):
                    should_send = True

            if not should_send:
                continue

            text = f"Пора выпить: <b>{med['name']}</b>\nВремя по расписанию: {hhmm}"
            try:
                await bot.send_message(
                    user["telegram_id"],
                    text,
                    reply_markup=pill_keyboard(log_row["id"]),
                )
            except Exception:
                log.exception("Pill reminder failed for %s", user["telegram_id"])
                continue
            await db.update_pill_log(
                log_row["id"],
                status="pending",
                reminded_at=iso(now_utc()),
                snooze_until=None,
            )
