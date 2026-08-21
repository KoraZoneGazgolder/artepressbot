from aiogram import Router
from aiogram.types import CallbackQuery, Message

from app.db import db
from app import texts

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
    await message.answer("Не понял. Давление: фото экрана, <code>120/80 72</code> или /list")


@router.callback_query()
async def callback_fallback(query: CallbackQuery) -> None:
    await query.answer()
