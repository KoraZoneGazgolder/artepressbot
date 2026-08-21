from __future__ import annotations

import asyncio
from io import BytesIO

from aiogram import F, Router
from aiogram.filters import BaseFilter, Command, StateFilter
from aiogram.types import CallbackQuery, Message

from app.db import db, fmt_day, fmt_dt, fmt_time, parse_bp
from app.filters import ApprovedUser
from app.keyboards import ListCb, PhotoBpCb, list_keyboard, main_keyboard, photo_bp_keyboard
from app.ocr import extract_bp_from_image
from app import texts

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
        return "/" in text and any(ch.isdigit() for ch in text)


def _format_reading(row: dict) -> str:
    return (
        f"{fmt_dt(row['measured_at'])} — "
        f"{row['systolic']}/{row['diastolic']}, пульс {row['pulse']}"
    )


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
        text = "Пока нет измерений. Пришлите фото экрана или <code>120/80 72</code>"
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


@router.message(StateFilter(None), ApprovedUser(), IsBp())
async def save_pressure(
    message: Message, db_user: dict, systolic: int, diastolic: int, pulse: int
) -> None:
    row = await db.add_bp(db_user["id"], systolic, diastolic, pulse)
    await message.answer(
        f"Записал: {systolic}/{diastolic}, пульс {pulse}\n"
        f"{fmt_dt(row['measured_at'])}",
        reply_markup=main_keyboard(),
    )


@router.message(StateFilter(None), ApprovedUser(), LooksLikeBp())
async def almost_pressure(message: Message) -> None:
    await message.answer(texts.NOT_A_BP)


@router.message(StateFilter(None), ApprovedUser(), F.photo)
async def photo_pressure(message: Message) -> None:
    photo = message.photo[-1]
    await _ocr_and_ask(message, photo.file_id)


@router.message(
    StateFilter(None),
    ApprovedUser(),
    F.document.mime_type.startswith("image/"),
)
async def document_pressure(message: Message) -> None:
    document = message.document
    if document is None:
        return
    await _ocr_and_ask(message, document.file_id)


async def _ocr_and_ask(message: Message, file_id: str) -> None:
    await message.answer("Смотрю фото тонометра…")
    buffer = BytesIO()
    await message.bot.download(file_id, destination=buffer)
    data = buffer.getvalue()
    reading = await asyncio.to_thread(extract_bp_from_image, data)
    if reading is None:
        await message.answer(
            "Не разобрал цифры. Снимите экран ближе, без блика, "
            "или напишите <code>120/80 72</code>"
        )
        return
    systolic, diastolic, pulse = reading
    await message.answer(
        f"На фото: <b>{systolic}/{diastolic}</b>, пульс <b>{pulse}</b>\n"
        "Записать?",
        reply_markup=photo_bp_keyboard(systolic, diastolic, pulse),
    )


@router.callback_query(PhotoBpCb.filter(), ApprovedUser())
async def photo_bp_decision(
    query: CallbackQuery, callback_data: PhotoBpCb, db_user: dict
) -> None:
    if callback_data.action != "ok":
        await query.answer("Ок, не записываю")
        if query.message:
            await query.message.edit_text(
                "Не записал. Можно прислать другое фото или <code>120/80 72</code>"
            )
        return

    row = await db.add_bp(
        db_user["id"], callback_data.s, callback_data.d, callback_data.p
    )
    await query.answer("Записал")
    if query.message:
        await query.message.edit_text(
            f"Записал: {callback_data.s}/{callback_data.d}, "
            f"пульс {callback_data.p}\n{fmt_dt(row['measured_at'])}"
        )
