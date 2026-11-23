from html import escape

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app import fun, texts
from app.db import db, fmt_dt, fmt_day
from app.filters import AdminUser
from app.keyboards import AccessCb, access_keyboard, keyboard_for, main_keyboard

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
