from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app import texts
from app.db import db, fmt_dt
from app.filters import AdminUser, ApprovedUser
from app.keyboards import FeedbackCb, feedback_reply_keyboard, keyboard_for, main_keyboard

router = Router()


class FeedbackForm(StatesGroup):
    writing = State()


class FeedbackReplyForm(StatesGroup):
    replying = State()


@router.message(Command("feedback"), ApprovedUser())
async def cmd_feedback(message: Message, db_user: dict, state: FSMContext) -> None:
    await state.set_state(FeedbackForm.writing)
    await message.answer(texts.FEEDBACK_PROMPT)


@router.message(FeedbackForm.writing, ApprovedUser())
async def feedback_written(message: Message, db_user: dict, state: FSMContext) -> None:
    if not message.text or not message.text.strip():
        await message.answer("Напишите текстом, пожалуйста. Если передумали — /cancel.")
        return
    await state.clear()
    feedback_id = await db.add_feedback(db_user["id"], message.text)

    name = escape(db_user.get("full_name") or "без имени")
    username = f" @{escape(db_user['username'])}" if db_user.get("username") else ""
    text = (
        f"Обратная связь от {name}{username}:\n\n"
        f"{escape(message.text.strip())}"
    )
    for admin in await db.list_admins():
        try:
            await message.bot.send_message(
                admin["telegram_id"],
                text,
                reply_markup=feedback_reply_keyboard(feedback_id),
            )
        except Exception:
            continue
    await message.answer(texts.FEEDBACK_SENT, reply_markup=main_keyboard())


@router.callback_query(FeedbackCb.filter(F.action == "reply"), AdminUser())
async def feedback_reply_start(
    query: CallbackQuery, callback_data: FeedbackCb, state: FSMContext
) -> None:
    entry = await db.get_feedback(callback_data.feedback_id)
    if entry is None:
        await query.answer("Сообщение не найдено", show_alert=True)
        return
    await state.set_state(FeedbackReplyForm.replying)
    await state.update_data(feedback_id=callback_data.feedback_id)
    await query.answer()
    if query.message:
        name = escape(entry.get("full_name") or "без имени")
        await query.message.answer(
            f"Отвечаем {name} на сообщение от {fmt_dt(entry['created_at'])}:\n"
            f"«{escape(entry['message'])}»\n\n"
            f"Напишите ответ одним сообщением. Отмена — /cancel."
        )


@router.message(FeedbackReplyForm.replying, AdminUser())
async def feedback_reply_written(message: Message, db_user: dict, state: FSMContext) -> None:
    if not message.text or not message.text.strip():
        await message.answer("Напишите текстом, пожалуйста. Отмена — /cancel.")
        return
    data = await state.get_data()
    await state.clear()
    entry = await db.get_feedback(int(data["feedback_id"]))
    if entry is None:
        await message.answer("Сообщение не найдено.")
        return
    await db.set_feedback_reply(entry["id"], message.text)
    try:
        await message.bot.send_message(
            entry["telegram_id"],
            f"{texts.FEEDBACK_REPLY_PREFIX}{escape(message.text.strip())}",
        )
    except Exception:
        await message.answer("Не удалось доставить ответ — пользователь недоступен.")
        return
    await message.answer(f"Ответ отправлен ({escape(entry.get('full_name') or 'без имени')}).")
