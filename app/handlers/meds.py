from datetime import timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app import texts
from app.config import settings
from app.db import db, iso, now_msk, now_utc, parse_times_list
from app.filters import ApprovedUser
from app.keyboards import MedCb, PillCb, main_keyboard, meds_manage_keyboard

router = Router()


class AddMed(StatesGroup):
    name = State()
    dosage = State()
    times = State()


class EditDose(StatesGroup):
    value = State()


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
        await message.answer(
            "Препаратов нет. Добавьте через /addmed",
            reply_markup=main_keyboard(),
        )
        return
    lines = ["Ваши таблетки:"]
    for med in meds:
        lines.append(f"• {texts.med_title(med)} — {_times_label(med['times'])}")
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
    await state.set_state(AddMed.dosage)
    await message.answer("Дозировка, например: <code>10 мг</code> или <code>125 мкг</code>")


@router.message(AddMed.dosage, ApprovedUser(), F.text)
async def addmed_dosage(message: Message, state: FSMContext) -> None:
    dosage = (message.text or "").strip()
    if not dosage or dosage.startswith("/"):
        await message.answer("Пришлите дозировку текстом, или /cancel")
        return
    await state.update_data(dosage=dosage)
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
    await db.add_med(db_user["id"], data["name"], times, data.get("dosage", ""))
    await state.clear()
    title = texts.med_title({"name": data["name"], "dosage": data.get("dosage", "")})
    await message.answer(f"Добавил {title} — {_times_label(times)}")


@router.message(EditDose.value, ApprovedUser(), F.text)
async def edit_dose_value(message: Message, db_user: dict, state: FSMContext) -> None:
    dosage = (message.text or "").strip()
    if not dosage or dosage.startswith("/"):
        await message.answer("Пришлите новую дозировку текстом, или /cancel")
        return
    data = await state.get_data()
    med_id = data.get("med_id")
    if not med_id:
        await state.clear()
        await message.answer("Не нашёл препарат. Откройте /meds ещё раз.")
        return
    ok = await db.update_med_dosage(med_id, db_user["id"], dosage)
    await state.clear()
    if not ok:
        await message.answer("Не удалось обновить дозировку.")
        return
    med = await db.get_med(med_id)
    title = texts.med_title(med) if med else dosage
    await message.answer(f"Дозировка обновлена: {title}")


@router.callback_query(MedCb.filter(), ApprovedUser())
async def med_actions(
    query: CallbackQuery, callback_data: MedCb, db_user: dict, state: FSMContext
) -> None:
    med = await db.get_med(callback_data.med_id)
    if med is None or med["user_id"] != db_user["id"]:
        await query.answer("Не найдено", show_alert=True)
        return

    if callback_data.action == "delete":
        await db.deactivate_med(med["id"], db_user["id"])
        await query.answer("Удалил")
        if query.message:
            await query.message.edit_text(f"Удалил {texts.med_title(med)}")
        return

    if callback_data.action == "dose":
        from html import escape

        await state.set_state(EditDose.value)
        await state.update_data(med_id=med["id"])
        current = (med.get("dosage") or "").strip() or "не указана"
        await query.answer()
        if query.message:
            await query.message.answer(
                f"Новая дозировка для {escape(med['name'])} (сейчас: {escape(current)}):"
            )
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
            await query.message.answer(
                f"✓ {texts.med_title(med)} — выпили в {hhmm}"
            )
        return

    await query.answer()


@router.callback_query(PillCb.filter(), ApprovedUser())
async def pill_actions(query: CallbackQuery, callback_data: PillCb, db_user: dict) -> None:
    log = await db.get_pill_log(callback_data.log_id)
    if log is None or log["user_id"] != db_user["id"]:
        await query.answer("Запись не найдена", show_alert=True)
        return
    med = await db.get_med(log["medication_id"])
    title = texts.med_title(med) if med else "таблетка"
    taken_hhmm = now_msk().strftime("%H:%M")

    if callback_data.action == "taken":
        await db.update_pill_log(
            log["id"],
            status="taken",
            confirmed_at=iso(now_utc()),
            snooze_until=None,
        )
        await query.answer("Отлично")
        if query.message:
            await query.message.edit_text(f"✓ {title} — выпили в {taken_hhmm}")
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
            await query.message.edit_text(f"✗ {title} — пропуск {log['scheduled_time']}")
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
                f"⏳ {title} — напомню через {settings.snooze_minutes} мин"
            )
        return

    await query.answer()
