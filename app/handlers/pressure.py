from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.filters import BaseFilter, Command, StateFilter
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from app.db import db, fmt_day, fmt_dt, fmt_time, now_msk, parse_bp
from app.export import pills_csv, pressure_csv
from app.filters import ApprovedUser
from app.keyboards import ListCb, list_keyboard, main_keyboard
from app import fun, texts

router = Router()

PAGE_SIZE = 20


class IsBp(BaseFilter):
    async def __call__(self, message: Message) -> bool | dict:
        parsed = parse_bp(message.text or "")
        if parsed is None:
            return False
        systolic, diastolic, pulse = parsed
        return {"systolic": systolic, "diastolic": diastolic, "pulse": pulse}


class LooksLikeBp(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        text = (message.text or "").strip()
        if not text or parse_bp(text) is not None:
            return False
        # два-три числа через любой из разделителей — похоже на давление, но не полный формат
        return bool(re.search(r"\d{2,3}\s*[/\\.,;\-:]\s*\d{2,3}", text))


def format_bp_page(rows: list[dict], total: int, offset: int) -> str:
    lines = [f"Список измерений ({offset + 1}–{offset + len(rows)} из {total})"]
    current_day = None
    for row in rows:
        day = fmt_day(row["measured_at"])
        if day != current_day:
            current_day = day
            lines.append(f"\n<b>{day}</b>")
        lines.append(
            f"• {fmt_time(row['measured_at'])} — "
            f"{row['systolic']}/{row['diastolic']}, пульс {row['pulse']}"
        )
    return "\n".join(lines)


@router.message(Command("history"), ApprovedUser())
@router.message(Command("list"), ApprovedUser())
async def cmd_list(message: Message, db_user: dict) -> None:
    await _send_list(message, db_user, offset=0, edit=False)


@router.callback_query(ListCb.filter(), ApprovedUser())
async def list_page(query: CallbackQuery, callback_data: ListCb, db_user: dict) -> None:
    await query.answer()
    if query.message:
        await _send_list(query.message, db_user, offset=callback_data.offset, edit=True)


async def _send_list(message: Message, db_user: dict, offset: int, edit: bool) -> None:
    total = await db.count_bp(db_user["id"])
    if total == 0:
        text = f"Пока нет измерений.\n{texts.BP_HOW}"
        if edit:
            await message.edit_text(text)
        else:
            await message.answer(text, reply_markup=main_keyboard())
        return
    offset = max(0, min(offset, max(0, total - 1)))
    rows = await db.list_bp(db_user["id"], limit=PAGE_SIZE, offset=offset)
    text = format_bp_page(rows, total, offset)
    markup = list_keyboard(offset, total, PAGE_SIZE)
    if edit:
        await message.edit_text(text, reply_markup=markup)
        return
    await message.answer(text, reply_markup=markup or main_keyboard())


@router.message(Command("export"), ApprovedUser())
@router.message(Command("table"), ApprovedUser())
async def cmd_export(message: Message, db_user: dict) -> None:
    readings = await db.list_bp(db_user["id"], limit=100000, offset=0)
    logs = await db.list_all_pill_logs(db_user["id"])
    if not readings and not logs:
        await message.answer(
            f"Пока нечего выгружать. Сначала запишите давление.\n{texts.BP_HOW}",
            reply_markup=main_keyboard(),
        )
        return

    stamp = now_msk().strftime("%Y-%m-%d")
    sent = 0
    if readings:
        await message.answer_document(
            BufferedInputFile(
                pressure_csv(readings),
                filename=f"davlenie_{stamp}.csv",
            ),
            caption=f"Давление: {len(readings)} записей. Откройте в Excel.",
        )
        sent += 1
    if logs:
        await message.answer_document(
            BufferedInputFile(
                pills_csv(logs),
                filename=f"tabletki_{stamp}.csv",
            ),
            caption=f"Таблетки: {len(logs)} отметок.",
        )
        sent += 1
    if sent:
        await message.answer("Готово.", reply_markup=main_keyboard())


@router.message(StateFilter(None), ApprovedUser(), IsBp())
async def save_pressure(
    message: Message, db_user: dict, systolic: int, diastolic: int, pulse: int
) -> None:
    row = await db.add_bp(db_user["id"], systolic, diastolic, pulse)
    count = await db.count_bp(db_user["id"])
    lines = [
        f"Записал: {systolic}/{diastolic}, пульс {pulse}",
        f"{fmt_dt(row['measured_at'])}",
    ]
    achievement = fun.achievement_message(count)
    note = fun.milestone_message(
        count,
        await db.bp_streak_days(db_user["id"]),
        systolic,
        diastolic,
    )
    if note:
        lines.append(f"\n{note}")
    await message.answer("\n".join(lines), reply_markup=main_keyboard())
    if achievement:
        try:
            await message.answer_animation(fun.cat_gif_url(), caption=achievement)
        except Exception:
            await message.answer(achievement)


@router.message(StateFilter(None), ApprovedUser(), LooksLikeBp())
async def almost_pressure(message: Message) -> None:
    await message.answer(texts.NOT_A_BP)


@router.message(StateFilter(None), ApprovedUser(), F.photo)
async def photo_hint(message: Message) -> None:
    await message.answer(f"Фото не разбираю.\n{texts.BP_HOW}")
