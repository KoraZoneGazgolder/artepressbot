from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder


class AccessCb(CallbackData, prefix="access"):
    action: str
    telegram_id: int


class PillCb(CallbackData, prefix="pill"):
    action: str
    log_id: int


class MedCb(CallbackData, prefix="med"):
    action: str
    med_id: int


class PhotoBpCb(CallbackData, prefix="pbp"):
    action: str
    s: int
    d: int
    p: int


class ListCb(CallbackData, prefix="list"):
    offset: int


BTN_TODAY = "Сегодня"
BTN_LIST = "Список"
BTN_MEDS = "Таблетки"
BTN_HELP = "Справка"
MENU_BUTTONS = {BTN_TODAY, BTN_LIST, BTN_MEDS, BTN_HELP}


def main_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text=BTN_TODAY)
    builder.button(text=BTN_LIST)
    builder.button(text=BTN_MEDS)
    builder.button(text=BTN_HELP)
    builder.adjust(2, 2)
    return builder.as_markup(resize_keyboard=True, is_persistent=True)


def keyboard_for(user: dict | None):
    if user and user.get("status") == "approved":
        return main_keyboard()
    return ReplyKeyboardRemove()


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


def photo_bp_keyboard(systolic: int, diastolic: int, pulse: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Записать",
        callback_data=PhotoBpCb(action="ok", s=systolic, d=diastolic, p=pulse),
    )
    builder.button(
        text="Не то",
        callback_data=PhotoBpCb(action="no", s=systolic, d=diastolic, p=pulse),
    )
    builder.adjust(2)
    return builder.as_markup()


def list_keyboard(offset: int, total: int, page_size: int) -> InlineKeyboardMarkup | None:
    builder = InlineKeyboardBuilder()
    if offset > 0:
        builder.button(
            text="Новее",
            callback_data=ListCb(offset=max(0, offset - page_size)),
        )
    if offset + page_size < total:
        builder.button(
            text="Раньше",
            callback_data=ListCb(offset=offset + page_size),
        )
    markup = builder.as_markup()
    if not markup.inline_keyboard:
        return None
    return markup
