from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.db import db, fmt_dt, now_msk
from app.filters import ApprovedUser
from app.keyboards import (
    BTN_HELP,
    BTN_LIST,
    BTN_MEDS,
    BTN_TODAY,
    access_keyboard,
    keyboard_for,
    main_keyboard,
)
from app import texts

router = Router()


def _who(message: Message) -> tuple[int, str | None, str]:
    user = message.from_user
    assert user is not None
    full_name = user.full_name
    return user.id, user.username, full_name


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    telegram_id, username, full_name = _who(message)
    user = await db.upsert_on_start(telegram_id, username, full_name)

    if user["became_admin"]:
        await message.answer(
            f"{texts.FIRST_ADMIN}\n\n{texts.HELP}{texts.ADMIN_HELP}",
            reply_markup=main_keyboard(),
        )
        return

    if user["status"] == "approved":
        extra = texts.ADMIN_HELP if user["role"] == "admin" else ""
        await message.answer(
            f"Снова здравствуйте.\n\n{texts.HELP}{extra}",
            reply_markup=main_keyboard(),
        )
        return

    if user["status"] == "denied":
        await message.answer(texts.DENIED, reply_markup=keyboard_for(user))
        return

    if user.get("just_created") or user.get("reopened_request"):
        mention = f"@{username}" if username else full_name
        text = (
            f"Новая заявка в дневник.\n"
            f"{mention}\n"
            f"id: <code>{telegram_id}</code>"
        )
        for admin in await db.list_admins():
            try:
                await message.bot.send_message(
                    admin["telegram_id"],
                    text,
                    reply_markup=access_keyboard(telegram_id),
                )
            except Exception:
                continue
    await message.answer(texts.PENDING, reply_markup=keyboard_for(user))


@router.message(Command("help"))
@router.message(F.text == BTN_HELP)
async def cmd_help(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = await db.get_user_by_telegram(message.from_user.id) if message.from_user else None
    extra = texts.ADMIN_HELP if user and user["role"] == "admin" and user["status"] == "approved" else ""
    await message.answer(texts.HELP + extra, reply_markup=keyboard_for(user))


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = await db.get_user_by_telegram(message.from_user.id) if message.from_user else None
    await message.answer("Отменил.", reply_markup=keyboard_for(user))


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    if message.from_user:
        await message.answer(f"Ваш Telegram ID: <code>{message.from_user.id}</code>")


@router.message(Command("today"), ApprovedUser())
@router.message(F.text == BTN_TODAY, ApprovedUser())
async def cmd_today(message: Message, db_user: dict, state: FSMContext) -> None:
    await state.clear()
    day = now_msk().strftime("%Y-%m-%d")
    readings = await db.bp_for_date(db_user["id"], day)
    logs = await db.pill_logs_for_date(db_user["id"], day)
    meds = await db.list_meds(db_user["id"])

    lines = ["Сегодня"]
    if readings:
        lines.append("Давление:")
        for row in readings:
            lines.append(
                f"• {fmt_dt(row['measured_at'])} — "
                f"{row['systolic']}/{row['diastolic']}, пульс {row['pulse']}"
            )
    else:
        lines.append("Давление: ещё не записывали")

    if meds:
        lines.append("Таблетки:")
        log_map = {(log["medication_id"], log["scheduled_time"]): log for log in logs}
        for med in meds:
            for time_hhmm in med["times"]:
                log = log_map.get((med["id"], time_hhmm))
                mark = "•"
                extra = ""
                if log:
                    status = log["status"]
                    if status == "taken":
                        mark = "✓"
                    elif status == "skipped":
                        mark = "✗"
                    elif status == "snoozed":
                        mark = "⏳"
                    else:
                        mark = "○"
                extra = f" {time_hhmm}"
                lines.append(f"{mark} {med['name']}{extra}")
    else:
        lines.append("Таблетки: список пуст. Добавьте через /addmed")

    await message.answer("\n".join(lines), reply_markup=main_keyboard())


@router.message(F.text == BTN_LIST, ApprovedUser())
async def btn_list(message: Message, db_user: dict, state: FSMContext) -> None:
    await state.clear()
    from app.handlers.pressure import cmd_list

    await cmd_list(message, db_user)


@router.message(F.text == BTN_MEDS, ApprovedUser())
async def btn_meds(message: Message, db_user: dict, state: FSMContext) -> None:
    from app.handlers.meds import cmd_meds

    await cmd_meds(message, db_user, state)
