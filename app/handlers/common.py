from aiogram import Router
from aiogram.types import CallbackQuery, Message

from app.db import db
from app import fun, texts

router = Router()


@router.message()
async def fallback(message: Message) -> None:
    if not message.from_user:
        return
    user = await db.get_user_by_telegram(message.from_user.id)
    if user is None:
        await message.answer("Напишите /start")
        return
    if user["status"] == "pending":
        await message.answer(texts.PENDING)
        return
    if user["status"] == "denied":
        await message.answer(texts.DENIED)
        return
    if message.text and fun.is_thanks(message.text):
        await message.answer(fun.thanks_reply())
        return
    await message.answer(f"Не понял.\n{texts.BP_HOW}\nИли нажмите Список / Справка.")


@router.callback_query()
async def callback_fallback(query: CallbackQuery) -> None:
    await query.answer()
