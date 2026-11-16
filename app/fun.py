"""Добрые пасхалки: сезонные приветствия и тёплые заметки за регулярность."""
from __future__ import annotations

import random
from datetime import datetime

from app import texts

# (месяц, день) -> приветствие в напоминании
SEASONAL: dict[tuple[int, int], str] = {
    (1, 1): "С Новым годом! Пусть в нём давление будет ровным, а поводов для радости — много.",
    (12, 31): "Последний день года. Спасибо, что весь год следили за здоровьем вместе с нами!",
    (3, 8): "С 8 Марта! Здоровья, тепла и весеннего настроения.",
    (5, 17): "Сегодня Всемирный день борьбы с гипертонией — хороший повод измерить давление.",
    (9, 29): "Сегодня Всемирный день сердца. Побеспокойтесь о своём — измерьте давление.",
    (10, 1): "Сегодня Международный день пожилых людей. Берегите себя!",
}


def seasonal_greeting(now: datetime) -> str | None:
    """Особое приветствие к напоминанию, если сегодня особенный день."""
    return SEASONAL.get((now.month, now.day))


def birthday_greeting(is_bot_birthday: bool) -> str | None:
    if is_bot_birthday:
        return "Сегодня день рождения этого бота. Спасибо, что вы с нами!"
    return None


def milestone_message(count: int, streak: int, systolic: int, diastolic: int) -> str | None:
    """Тёплая заметка к сохранённому замеру. Показываем не чаще одной за раз."""
    if count == 1:
        return "Первая запись в дневнике — с чистого листа. Так держать!"
    if count == 10:
        return "Десятая запись! Дневник потихоньку наполняется."
    if count == 50:
        return "Пятьдесят замеров! Вы следите за собой очень старательно."
    if count % 100 == 0:
        return f"Уже {count} замеров! Вашему тонометру есть что вспомнить."
    if streak == 7:
        return "Семь дней подряд с замерами — отличная привычка!"
    if streak == 14:
        return "Две недели подряд! Регулярность — залог хорошего дневника."
    if streak == 30:
        return "Месяц ежедневных замеров. Это настоящая забота о себе."
    if streak > 0 and streak % 100 == 0:
        return f"{streak} дней подряд с замерами — просто образцово!"
    if systolic == 120 and diastolic == 80:
        return "Ровно 120/80 — давление как в учебнике. Так держать!"
    return None


def thanks_reply() -> str:
    return random.choice(texts.THANKS_REPLIES)


THANKS_WORDS = {"спасибо", "спасибо!", "спасибо.", "благодарю", "благодарю!", "спс"}


def is_thanks(text: str) -> bool:
    return text.strip().lower() in THANKS_WORDS


def konami_text(total_readings: int, users_count: int, bot_created: str | None) -> str:
    return (
        "🥚 Вы нашли пасхалку!\n\n"
        "За кулисами этого бота:\n"
        f"• записано замеров давления: {total_readings}\n"
        f"• человек в семье бота: {users_count}\n"
        "• состояние: бодр, чемодан собран, готов ехать на VPS\n\n"
        "Хорошего дня, босс."
    )
