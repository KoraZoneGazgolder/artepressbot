import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeDefault

from app.backup import backup_db
from app.config import settings
from app.db import db
from app.handlers import admin, common, feedback, meds, pressure, settings as settings_handlers, start
from app.scheduler import scheduler, setup_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)


async def main() -> None:
    if not settings.bot_token or settings.bot_token.startswith("000000"):
        raise SystemExit("Укажите BOT_TOKEN в файле .env")
    await db.connect()
    try:
        await backup_db()
    except Exception:
        log.exception("Startup DB backup failed")
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(start.router)
    dp.include_router(admin.router)
    dp.include_router(settings_handlers.router)
    dp.include_router(meds.router)
    dp.include_router(feedback.router)
    dp.include_router(pressure.router)
    dp.include_router(common.router)

    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Старт / заявка"),
            BotCommand(command="today", description="Сегодня"),
            BotCommand(command="list", description="Список измерений давления"),
            BotCommand(command="meds", description="Таблетки"),
            BotCommand(command="export", description="Таблица CSV"),
            BotCommand(command="addmed", description="Добавить препарат"),
            BotCommand(command="settings", description="Напоминания о давлении"),
            BotCommand(command="feedback", description="Написать админу"),
            BotCommand(command="help", description="Справка"),
        ],
        scope=BotCommandScopeDefault(),
    )

    setup_scheduler(bot)
    scheduler.start()
    log.info("Bot started, polling")
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
