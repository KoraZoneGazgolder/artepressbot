from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject

from app.db import db


class ApprovedUser(BaseFilter):
    async def __call__(self, event: TelegramObject) -> bool | dict:
        user = getattr(event, "from_user", None)
        if user is None:
            return False
        record = await db.get_user_by_telegram(user.id)
        if record is None or record["status"] != "approved":
            return False
        return {"db_user": record}


class AdminUser(BaseFilter):
    async def __call__(self, event: TelegramObject) -> bool | dict:
        user = getattr(event, "from_user", None)
        if user is None:
            return False
        record = await db.get_user_by_telegram(user.id)
        if record is None or record["status"] != "approved" or record["role"] != "admin":
            return False
        return {"db_user": record}
