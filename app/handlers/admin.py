from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.db import db
from app.filters import AdminUser
from app.keyboards import AccessCb, access_keyboard

router = Router()


def _label(user: dict) -> str:
    name = user.get("full_name") or "без имени"
    username = f" @{user['username']}" if user.get("username") else ""
    return f"{name}{username} ({user['telegram_id']}) — {user['status']}"


@router.message(Command("users"), AdminUser())
async def cmd_users(message: Message) -> None:
    users = await db.list_users()
    if not users:
        await message.answer("Пользователей нет.")
        return
    lines = ["Семья:"] + [f"• {_label(user)}" for user in users]
    await message.answer("\n".join(lines))


@router.message(Command("pending"), AdminUser())
async def cmd_pending(message: Message) -> None:
    pending = await db.list_pending()
    if not pending:
        await message.answer("Заявок нет.")
        return
    for user in pending:
        await message.answer(
            f"Заявка: {_label(user)}",
            reply_markup=access_keyboard(user["telegram_id"]),
        )


@router.callback_query(AccessCb.filter(), AdminUser())
async def access_decision(query: CallbackQuery, callback_data: AccessCb) -> None:
    status = "approved" if callback_data.action == "approve" else "denied"
    user = await db.set_access(callback_data.telegram_id, status)
    if user is None:
        await query.answer("Пользователь не найден", show_alert=True)
        return

    if callback_data.action == "approve":
        note = f"Одобрил {user.get('full_name') or callback_data.telegram_id}"
        user_text = "Доступ открыт. Можно писать давление: 120/80 72\n/help — команды"
    else:
        note = f"Отклонил {user.get('full_name') or callback_data.telegram_id}"
        user_text = "Доступ отклонён."

    await query.answer(note)
    if query.message:
        await query.message.edit_text(note)
    try:
        await query.bot.send_message(callback_data.telegram_id, user_text)
    except Exception:
        pass
