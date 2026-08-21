from aiogram import Router
from aiogram.filters import BaseFilter, Command, StateFilter
from aiogram.types import Message

from app.db import db, fmt_dt, parse_bp
from app.filters import ApprovedUser
from app import texts

router = Router()


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


@router.message(Command("history"), ApprovedUser())
async def cmd_history(message: Message, db_user: dict) -> None:
    rows = await db.list_bp(db_user["id"], limit=12)
    if not rows:
        await message.answer("Пока нет измерений. Пришлите <code>120/80 72</code>")
        return
    lines = ["Последние измерения:"] + [f"• {_format_reading(row)}" for row in rows]
    await message.answer("\n".join(lines))


@router.message(StateFilter(None), ApprovedUser(), IsBp())
async def save_pressure(
    message: Message, db_user: dict, systolic: int, diastolic: int, pulse: int
) -> None:
    row = await db.add_bp(db_user["id"], systolic, diastolic, pulse)
    await message.answer(
        f"Записал: {systolic}/{diastolic}, пульс {pulse}\n"
        f"{fmt_dt(row['measured_at'])}"
    )


@router.message(StateFilter(None), ApprovedUser(), LooksLikeBp())
async def almost_pressure(message: Message) -> None:
    await message.answer(texts.NOT_A_BP)
