from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


class AccessCb(CallbackData, prefix="access"):
    action: str
    telegram_id: int


class PillCb(CallbackData, prefix="pill"):
    action: str
    log_id: int


class MedCb(CallbackData, prefix="med"):
    action: str
    med_id: int


def access_keyboard(telegram_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Одобрить",
        callback_data=AccessCb(action="approve", telegram_id=telegram_id),
    )
    builder.button(
        text="Отклонить",
        callback_data=AccessCb(action="deny", telegram_id=telegram_id),
    )
    builder.adjust(2)
    return builder.as_markup()


def pill_keyboard(log_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Выпил", callback_data=PillCb(action="taken", log_id=log_id))
    builder.button(text="Пропустил", callback_data=PillCb(action="skip", log_id=log_id))
    builder.button(text="Позже", callback_data=PillCb(action="later", log_id=log_id))
    builder.adjust(3)
    return builder.as_markup()


def meds_manage_keyboard(meds: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for med in meds:
        builder.button(
            text=f"Выпил: {med['name']}",
            callback_data=MedCb(action="take", med_id=med["id"]),
        )
        builder.button(
            text="Удалить",
            callback_data=MedCb(action="delete", med_id=med["id"]),
        )
    builder.adjust(2)
    return builder.as_markup()
