from aiogram.filters.callback_data import CallbackData
from aiogram.types import KeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
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


class ListCb(CallbackData, prefix="list"):
    offset: int


class SettingsCb(CallbackData, prefix="bpset"):
    action: str


class OnboardCb(CallbackData, prefix="onb"):
    action: str


class FeedbackCb(CallbackData, prefix="fb"):
    action: str
    feedback_id: int


class BroadcastCb(CallbackData, prefix="bcast"):
    action: str


BTN_TODAY = "Сегодня"
BTN_LIST = "Список"
BTN_MEDS = "Таблетки"
BTN_EXPORT = "Таблица"
BTN_HELP = "Справка"
BTN_SETTINGS = "Настройки"
MENU_BUTTONS = {BTN_TODAY, BTN_LIST, BTN_MEDS, BTN_EXPORT, BTN_HELP, BTN_SETTINGS}


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_HELP)],
            [KeyboardButton(text=BTN_TODAY), KeyboardButton(text=BTN_LIST)],
            [KeyboardButton(text=BTN_MEDS), KeyboardButton(text=BTN_EXPORT)],
            [KeyboardButton(text=BTN_SETTINGS)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def keyboard_for(user: dict | None):
    if user and user.get("status") == "approved":
        return main_keyboard()
    return ReplyKeyboardRemove()


def settings_keyboard(reminders_on: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Выключить напоминания" if reminders_on else "Включить напоминания",
        callback_data=SettingsCb(action="toggle"),
    )
    builder.button(
        text="Время утром",
        callback_data=SettingsCb(action="morning"),
    )
    builder.button(
        text="Время вечером",
        callback_data=SettingsCb(action="evening"),
    )
    builder.adjust(1, 2)
    return builder.as_markup()


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


def _short_med_name(name: str, max_len: int = 16) -> str:
    name = name.strip()
    if len(name) <= max_len:
        return name
    return name[: max_len - 1] + "…"


def meds_manage_keyboard(meds: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for med in meds:
        short = _short_med_name(med["name"])
        builder.button(
            text=f"Выпил: {short}",
            callback_data=MedCb(action="take", med_id=med["id"]),
        )
        builder.button(
            text="Доза",
            callback_data=MedCb(action="dose", med_id=med["id"]),
        )
        builder.button(
            text="Удалить",
            callback_data=MedCb(action="delete", med_id=med["id"]),
        )
    builder.adjust(3)
    return builder.as_markup()


def skip_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Пропустить", callback_data=OnboardCb(action="skip"))
    return builder.as_markup()


def feedback_reply_keyboard(feedback_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Ответить",
        callback_data=FeedbackCb(action="reply", feedback_id=feedback_id),
    )
    return builder.as_markup()


def broadcast_confirm_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Отправить всем", callback_data=BroadcastCb(action="send"))
    builder.button(text="Отмена", callback_data=BroadcastCb(action="cancel"))
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
