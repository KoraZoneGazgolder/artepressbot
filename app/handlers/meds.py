from datetime import timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.config import settings
from app.db import db, iso, now_msk, now_utc, parse_times_list
from app.filters import ApprovedUser
from app.keyboards import MedCb, PillCb, meds_manage_keyboard

router = Router()


class AddMed(StatesGroup):
    name = State()
    times = State()


def _times_label(times: list[str]) -> str:
    return ", ".join(times)


def _minutes(hhmm: str) -> int:
    hour, minute = map(int, hhmm.split(":"))
    return hour * 60 + minute


@router.message(Command("meds"), ApprovedUser())
async def cmd_meds(message: Message, db_user: dict, state: FSMContext) -> None:
    await state.clear()
    meds = await db.list_meds(db_user["id"])
    if not meds:
        await message.answer("Препаратов нет. Добавьте через /addmed")
        return
    lines = ["Ваши таблетки:"]
    for med in meds:
        lines.append(f"• {med['name']} — {_times_label(med['times'])}")
    await message.answer("\n".join(lines), reply_markup=meds_manage_keyboard(meds))


@router.message(Command("addmed"), ApprovedUser())
async def cmd_addmed(message: Message, state: FSMContext) -> None:
    await state.set_state(AddMed.name)
    await message.answer("Название препарата, как на упаковке:")


@router.message(AddMed.name, ApprovedUser(), F.text)
async def addmed_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name or name.startswith("/"):
        await message.answer("Пришлите название текстом, или /cancel")
        return
    await state.update_data(name=name)
    await state.set_state(AddMed.times)
    await message.answer(
        "Время приёма через запятую, например:\n"
        "<code>08:00, 20:00</code>"
    )


@router.message(AddMed.times, ApprovedUser(), F.text)
async def addmed_times(message: Message, db_user: dict, state: FSMContext) -> None:
    times = parse_times_list(message.text or "")
    if not times:
        await message.answer("Не разобрал время. Пример: <code>08:00, 20:00</code>")
        return
    data = await state.get_data()
    await db.add_med(db_user["id"], data["name"], times)
    await state.clear()
    await message.answer(f"Добавил {data['name']} — {_times_label(times)}")


@router.callback_query(MedCb.filter(), ApprovedUser())
async def med_actions(query: CallbackQuery, callback_data: MedCb, db_user: dict) -> None:
    med = await db.get_med(callback_data.med_id)
    if med is None or med["user_id"] != db_user["id"]:
        await query.answer("Не найдено", show_alert=True)
        return

    if callback_data.action == "delete":
        await db.deactivate_med(med["id"], db_user["id"])
        await query.answer("Удалил")
        if query.message:
            await query.message.edit_text(f"Удалил {med['name']}")
        return

    if callback_data.action == "take":
        day = now_msk().strftime("%Y-%m-%d")
        hhmm = now_msk().strftime("%H:%M")
        closest = min(med["times"], key=lambda t: abs(_minutes(t) - _minutes(hhmm)))
        log = await db.get_or_create_pill_log(db_user["id"], med["id"], day, closest)
        await db.update_pill_log(
            log["id"],
            status="taken",
            confirmed_at=iso(now_utc()),
            snooze_until=None,
        )
        await query.answer("Отметил")
        if query.message:
            await query.message.answer(f"✓ {med['name']} в {closest}")
        return

    await query.answer()


@router.callback_query(PillCb.filter(), ApprovedUser())
async def pill_actions(query: CallbackQuery, callback_data: PillCb, db_user: dict) -> None:
    log = await db.get_pill_log(callback_data.log_id)
    if log is None or log["user_id"] != db_user["id"]:
        await query.answer("Запись не найдена", show_alert=True)
        return
    med = await db.get_med(log["medication_id"])
    name = med["name"] if med else "таблетка"

    if callback_data.action == "taken":
        await db.update_pill_log(
            log["id"],
            status="taken",
            confirmed_at=iso(now_utc()),
            snooze_until=None,
        )
        await query.answer("Отлично")
        if query.message:
            await query.message.edit_text(f"✓ {name} — выпили в {log['scheduled_time']}")
        return

    if callback_data.action == "skip":
        await db.update_pill_log(
            log["id"],
            status="skipped",
            confirmed_at=iso(now_utc()),
            snooze_until=None,
        )
        await query.answer("Записал пропуск")
        if query.message:
            await query.message.edit_text(f"✗ {name} — пропуск {log['scheduled_time']}")
        return

    if callback_data.action == "later":
        until = now_utc() + timedelta(minutes=settings.snooze_minutes)
        await db.update_pill_log(
            log["id"],
            status="snoozed",
            snooze_until=iso(until),
        )
        await query.answer(f"Напомню через {settings.snooze_minutes} мин")
        if query.message:
            await query.message.edit_text(
                f"⏳ {name} — напомню через {settings.snooze_minutes} мин"
            )
        return

    await query.answer()
