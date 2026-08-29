from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.db import (
    db,
    parse_hhmm,
    user_bp_evening,
    user_bp_morning,
    user_bp_reminders_on,
)
from app.filters import ApprovedUser
from app.keyboards import BTN_SETTINGS, SettingsCb, settings_keyboard

router = Router()


class EditBpTime(StatesGroup):
    value = State()


def _settings_text(user: dict) -> str:
    enabled = "включены" if user_bp_reminders_on(user) else "выключены"
    return (
        "Напоминания о давлении\n\n"
        f"Сейчас: {enabled}\n"
        f"Утро: {user_bp_morning(user)}\n"
        f"Вечер: {user_bp_evening(user)}\n\n"
        "Здесь только замер давления. Напоминания про таблетки не меняются."
    )


async def _show_settings(message: Message, user: dict, edit: bool = False) -> None:
    text = _settings_text(user)
    markup = settings_keyboard(user_bp_reminders_on(user))
    if edit:
        await message.edit_text(text, reply_markup=markup)
        return
    await message.answer(text, reply_markup=markup)


@router.message(Command("settings"), ApprovedUser())
@router.message(F.text == BTN_SETTINGS, ApprovedUser())
async def cmd_settings(message: Message, db_user: dict, state: FSMContext) -> None:
    await state.clear()
    await _show_settings(message, db_user)


@router.callback_query(SettingsCb.filter(), ApprovedUser())
async def settings_actions(
    query: CallbackQuery, callback_data: SettingsCb, db_user: dict, state: FSMContext
) -> None:
    if callback_data.action == "toggle":
        user = await db.set_bp_reminders(db_user["id"], not user_bp_reminders_on(db_user))
        await query.answer("Сохранил")
        if query.message and user:
            await _show_settings(query.message, user, edit=True)
        return

    if callback_data.action in {"morning", "evening"}:
        label = "утром" if callback_data.action == "morning" else "вечером"
        current = (
            user_bp_morning(db_user)
            if callback_data.action == "morning"
            else user_bp_evening(db_user)
        )
        await state.set_state(EditBpTime.value)
        await state.update_data(slot=callback_data.action)
        await query.answer()
        if query.message:
            await query.message.answer(
                f"Новое время {label} (сейчас {current}), например <code>08:30</code>:"
            )
        return

    await query.answer()


@router.message(EditBpTime.value, ApprovedUser(), F.text)
async def edit_bp_time(message: Message, db_user: dict, state: FSMContext) -> None:
    hhmm = parse_hhmm(message.text or "")
    if not hhmm:
        await message.answer("Не разобрал время. Пример: <code>08:30</code> или /cancel")
        return
    data = await state.get_data()
    slot = data.get("slot")
    if slot not in {"morning", "evening"}:
        await state.clear()
        await message.answer("Не нашёл слот. Откройте Настройки ещё раз.")
        return
    user = await db.set_bp_time(db_user["id"], slot, hhmm)
    await state.clear()
    if user is None:
        await message.answer("Не удалось сохранить время.")
        return
    await _show_settings(message, user)
