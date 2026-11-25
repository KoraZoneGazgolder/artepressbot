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
    if count % 10 == 0 and count <= 100:
        return None  # круглые десятки отмечаем ачивкой с котиком
    if count % 100 == 0:
        return None  # сотни — тоже ачивка
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


ACHIEVEMENTS: dict[int, str] = {
    10: "10 замеров! Дневник наполняется — вы молодец!",
    20: "20 замеров! Два десятка заботы о себе. Так держать!",
    30: "30 замеров! Уже целая история наблюдений. Отличная работа!",
    40: "40 замеров! Сороковая отметка — приятно смотреть на ваши успехи!",
    50: "50 замеров! Полсотни! Вы следите за собой очень старательно.",
    60: "60 замеров! Шесть десятков записей — пример для всей семьи!",
    70: "70 замеров! Семьдесят — красивое число и красивая привычка!",
    80: "80 замеров! Восемьдесят раз вы не забыли о себе. Браво!",
    90: "90 замеров! До сотни рукой подать — так держать!",
    100: "100 замеров! Сотня! Вы это сделали — настоящий рекорд дневника!",
}

ACHIEVEMENT_BIG = (
    "{count} замеров! Ещё одна сотня позади — ваша регулярность восхищает!"
)

# Гифки с котиками-грамотниками (проверенные ссылки GIPHY)
CAT_GIFS = [
    "https://media.giphy.com/media/JIX9t2j0ZTN9S/giphy.gif",      # кот за ноутбуком
    "https://media.giphy.com/media/MDJ9IbxxvDUQM/giphy.gif",      # котёнок тянется лапками
    "https://media.giphy.com/media/3oriO0OEd9QIDdllqo/giphy.gif", # пушистый котёнок
    "https://media.giphy.com/media/12HZukMBlutpoQ/giphy.gif",     # кот-селфи с лапой
    "https://media.giphy.com/media/mlvseq9yvZhba/giphy.gif",      # кот с пилочкой
]


def cat_gif_url() -> str:
    return random.choice(CAT_GIFS)


def achievement_message(count: int) -> str | None:
    """Ачивка за круглые десятки (10…100) и за каждую следующую сотню."""
    if count in ACHIEVEMENTS:
        return ACHIEVEMENTS[count]
    if count > 100 and count % 100 == 0:
        return ACHIEVEMENT_BIG.format(count=count)
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
