import os
from html import escape
from pathlib import Path

from aiogram import F, Router
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app import fun, texts
from app.config import settings
from app.db import db, fmt_dt, fmt_day
from app.filters import AdminUser
from app.keyboards import (
    AccessCb,
    BroadcastCb,
    access_keyboard,
    broadcast_confirm_keyboard,
    keyboard_for,
    main_keyboard,
)

router = Router()


def _label(user: dict) -> str:
    name = escape(user.get("full_name") or "без имени")
    username = f" @{escape(user['username'])}" if user.get("username") else ""
    return f"{name}{username} ({user['telegram_id']}) — {user['status']}"


@router.message(Command("users"), AdminUser())
async def cmd_users(message: Message) -> None:
    users = await db.list_users()
    if not users:
        await message.answer("Пользователей нет.")
        return
    lines = ["Семья:"] + [f"• {_label(user)}" for user in users]
    await message.answer("\n".join(lines))


@router.message(Command("pending"), AdminUser())
async def cmd_pending(message: Message) -> None:
    pending = await db.list_pending()
    if not pending:
        await message.answer("Заявок нет.")
        return
    for user in pending:
        lines = [f"Заявка: {_label(user)}"]
        if user.get("intro"):
            lines.append(f"Кто: {escape(user['intro'])}")
        if user.get("referral_source"):
            lines.append(f"Откуда узнал(а): {escape(user['referral_source'])}")
        await message.answer(
            "\n".join(lines),
            reply_markup=access_keyboard(user["telegram_id"]),
        )


def _bar(value: float, total: int, width: int = 10) -> str:
    """Маленькая текстовая шкала вида ██████░░░░."""
    if total <= 0:
        return "░" * width
    filled = round(width * value / total)
    return "█" * filled + "░" * (width - filled)


@router.message(Command("stats"), AdminUser())
async def cmd_stats(message: Message) -> None:
    counts = await db.user_status_counts()
    lines = [
        "Статистика дневника\n",
        f"Семья: {counts['approved']} одобрено, "
        f"{counts['pending']} ждут, {counts['denied']} отклонено\n",
    ]

    approved = await db.list_approved()
    if not approved:
        lines.append("Одобренных пользователей пока нет.")
    for user in approved:
        name = escape(user.get("full_name") or "без имени")
        lines.append(f"—— {name} ——")

        stats30 = await db.bp_stats(user["id"], 30)
        stats7 = await db.bp_stats(user["id"], 7)
        if stats30["n"]:
            lines.append(
                f"Давление за 30 дней: {stats30['n']} замеров, "
                f"в {stats30['active_days']} дн. из 30 "
                f"{_bar(stats30['active_days'], 30)}"
            )
            lines.append(
                f"Среднее: {stats30['avg_sys']:.0f}/{stats30['avg_dia']:.0f}, "
                f"пульс {stats30['avg_pulse']:.0f}"
            )
        else:
            lines.append("Давление за 30 дней: замеров нет")

        if stats7["n"]:
            lines.append(
                f"За 7 дней: {stats7['n']} замеров, "
                f"среднее {stats7['avg_sys']:.0f}/{stats7['avg_dia']:.0f}, "
                f"пульс {stats7['avg_pulse']:.0f}"
            )

        last = await db.last_bp_at(user["id"])
        if last:
            lines.append(f"Последний замер: {fmt_dt(last)}")

        pills = await db.pill_stats(user["id"], 30)
        decided = pills["taken"] + pills["skipped"]
        if decided:
            pct = round(100 * pills["taken"] / decided)
            lines.append(
                f"Таблетки за 30 дней: выпил {pills['taken']}, "
                f"пропустил {pills['skipped']} ({pct}% дисциплина) "
                f"{_bar(pills['taken'], decided)}"
            )

        fb = await db.count_feedback(user["id"])
        if fb:
            lines.append(f"Сообщений в обратную связь: {fb}")
        lines.append("")

    await message.answer("\n".join(lines))


@router.message(Command("konami"), AdminUser())
async def cmd_konami(message: Message) -> None:
    total = await db.total_readings()
    users_count = len(await db.list_users())
    created = await db.bot_birthday()
    await message.answer(
        fun.konami_text(
            total,
            users_count,
            fmt_day(created) if created else None,
        )
    )


@router.callback_query(AccessCb.filter(), AdminUser())
async def access_decision(query: CallbackQuery, callback_data: AccessCb) -> None:
    current = await db.get_user_by_telegram(callback_data.telegram_id)
    if current is None:
        await query.answer("Пользователь не найден", show_alert=True)
        return
    if current["status"] != "pending":
        await query.answer("Заявка уже обработана", show_alert=True)
        return
    status = "approved" if callback_data.action == "approve" else "denied"
    user = await db.set_access(callback_data.telegram_id, status)
    if user is None:
        await query.answer("Пользователь не найден", show_alert=True)
        return

    if callback_data.action == "approve":
        note = f"Одобрил {escape(user.get('full_name') or str(callback_data.telegram_id))}"
        user_text = texts.ACCESS_OPENED
        user_kb = main_keyboard()
    else:
        note = f"Отклонил {escape(user.get('full_name') or str(callback_data.telegram_id))}"
        user_text = "Доступ отклонён."
        user_kb = keyboard_for(user)

    await query.answer(note)
    if query.message:
        await query.message.edit_text(note)
    try:
        await query.bot.send_message(
            callback_data.telegram_id, user_text, reply_markup=user_kb
        )
    except Exception:
        pass


@router.message(Command("dbstats"), AdminUser())
async def cmd_dbstats(message: Message) -> None:
    counts = await db.table_counts()
    size_kb = os.path.getsize(settings.db_path) / 1024
    backups = sorted(Path(settings.backup_dir).glob("diary-*.db"))

    lines = [
        "База дневника",
        f"Файл: {size_kb:.0f} КБ; бэкапов: {len(backups)}"
        + (f", последний {backups[-1].name}" if backups else ""),
        "",
        "Таблицы:",
        *[f"• {table}: {n}" for table, n in counts.items()],
    ]

    for user in await db.list_approved():
        name = escape(user.get("full_name") or "без имени")
        last = await db.last_bp_at(user["id"])
        total = await db.count_bp(user["id"])
        meds = await db.list_meds(user["id"])
        pills = await db.pill_stats(user["id"], 7)
        lines.append("")
        lines.append(f"—— {name} ——")
        lines.append(
            f"Замеров всего: {total}; последний: {fmt_dt(last) if last else 'нет'}"
        )
        lines.append(
            f"Препаратов: {len(meds)}; за 7 дней: выпил {pills['taken']}, "
            f"пропуск {pills['skipped']}"
        )
        if user.get("bot_blocked"):
            lines.append("⚠️ заблокировал бота")

    await message.answer("\n".join(lines))


class BroadcastForm(StatesGroup):
    text = State()
    confirm = State()


@router.message(Command("broadcast"), AdminUser())
async def cmd_broadcast(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(BroadcastForm.text)
    await message.answer(
        "Текст новости для семьи одним сообщением (можно с HTML-разметкой). "
        "Отмена — /cancel."
    )


@router.message(BroadcastForm.text, AdminUser())
async def broadcast_text(message: Message, state: FSMContext) -> None:
    if not message.text or not message.text.strip():
        await message.answer("Нужен текст. Отмена — /cancel.")
        return
    news = message.text.strip()
    try:
        await message.answer(news)
    except Exception:
        await message.answer(
            "Разметка сломалась (проверьте HTML-теги). Пришлите текст ещё раз. "
            "Отмена — /cancel."
        )
        return
    await state.update_data(text=news)
    await state.set_state(BroadcastForm.confirm)
    await message.answer(
        "Так новость будет выглядеть. Отправляем всей семье?",
        reply_markup=broadcast_confirm_keyboard(),
    )


@router.callback_query(BroadcastCb.filter(F.action == "cancel"), BroadcastForm.confirm, AdminUser())
async def broadcast_cancel(query: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await query.answer("Отменил")
    if query.message:
        await query.message.edit_text("Рассылка отменена.")


@router.callback_query(BroadcastCb.filter(F.action == "send"), BroadcastForm.confirm, AdminUser())
async def broadcast_send(query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    news = (data.get("text") or "").strip()
    if not news:
        await query.answer("Текст потерялся. Начните /broadcast заново.", show_alert=True)
        return
    sent = blocked = failed = 0
    for user in await db.list_approved():
        try:
            await query.bot.send_message(user["telegram_id"], news)
            sent += 1
        except TelegramForbiddenError:
            await db.set_bot_blocked(user["id"], True)
            blocked += 1
        except Exception:
            failed += 1
    await query.answer()
    report = f"Новость отправлена: {sent}."
    missed = blocked + failed
    if missed:
        report += f" Не дошло: {missed} (из них заблокировали бота: {blocked})."
    if query.message:
        await query.message.edit_text(report)
