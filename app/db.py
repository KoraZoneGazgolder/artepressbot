from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import aiosqlite

from app.config import settings

MSK = ZoneInfo(settings.tz)

BP_RE = re.compile(
    r"^\s*(\d{2,3})\s*[/\\\s]\s*(\d{2,3})(?:\s*[,/]?\s*|\s+)(\d{2,3})\s*$"
)
TIME_RE = re.compile(r"^(\d{1,2})[:.](\d{2})$")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_msk() -> datetime:
    return datetime.now(MSK)


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MSK)
    return dt.astimezone(timezone.utc).isoformat()


def parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def fmt_dt(value: str) -> str:
    return parse_iso(value).astimezone(MSK).strftime("%d.%m %H:%M")


def fmt_day(value: str) -> str:
    return parse_iso(value).astimezone(MSK).strftime("%d.%m.%Y")


def fmt_time(value: str) -> str:
    return parse_iso(value).astimezone(MSK).strftime("%H:%M")


def parse_hhmm(value: str) -> str | None:
    match = TIME_RE.match(value.strip())
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def user_bp_reminders_on(user: dict) -> bool:
    value = user.get("bp_reminders")
    if value is None:
        return True
    return bool(int(value))


def user_bp_morning(user: dict) -> str:
    return user.get("bp_morning") or settings.bp_morning


def user_bp_evening(user: dict) -> str:
    return user.get("bp_evening") or settings.bp_evening


def parse_times_list(raw: str) -> list[str] | None:
    parts = [p.strip() for p in re.split(r"[,;]\s*|\s+", raw.strip()) if p.strip()]
    times: list[str] = []
    for part in parts:
        parsed = parse_hhmm(part)
        if not parsed:
            return None
        if parsed not in times:
            times.append(parsed)
    return sorted(times) if times else None


def parse_bp(text: str) -> tuple[int, int, int] | None:
    match = BP_RE.match(text.strip())
    if not match:
        return None
    systolic, diastolic, pulse = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    if not (70 <= systolic <= 250 and 40 <= diastolic <= 150 and 30 <= pulse <= 220):
        return None
    if systolic <= diastolic:
        return None
    return systolic, diastolic, pulse


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA foreign_keys = ON")
        await self._db.execute("PRAGMA journal_mode = WAL")
        await self._init_schema()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        assert self._db is not None
        return self._db

    async def _init_schema(self) -> None:
        await self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                full_name TEXT,
                role TEXT NOT NULL DEFAULT 'user',
                status TEXT NOT NULL DEFAULT 'pending',
                bp_reminders INTEGER NOT NULL DEFAULT 1,
                bp_morning TEXT NOT NULL DEFAULT '09:00',
                bp_evening TEXT NOT NULL DEFAULT '20:00',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS bp_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                systolic INTEGER NOT NULL,
                diastolic INTEGER NOT NULL,
                pulse INTEGER NOT NULL,
                measured_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS medications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                dosage TEXT NOT NULL DEFAULT '',
                times TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pill_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                medication_id INTEGER NOT NULL REFERENCES medications(id) ON DELETE CASCADE,
                scheduled_date TEXT NOT NULL,
                scheduled_time TEXT NOT NULL,
                status TEXT NOT NULL,
                snooze_until TEXT,
                reminded_at TEXT,
                confirmed_at TEXT,
                UNIQUE(user_id, medication_id, scheduled_date, scheduled_time)
            );

            CREATE TABLE IF NOT EXISTS reminder_sends (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                kind TEXT NOT NULL,
                slot TEXT NOT NULL,
                sent_date TEXT NOT NULL,
                UNIQUE(user_id, kind, slot, sent_date)
            );

            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                message TEXT NOT NULL,
                reply TEXT,
                created_at TEXT NOT NULL,
                replied_at TEXT
            );
            """
        )
        await self.db.commit()
        await self._ensure_columns()

    async def _ensure_columns(self) -> None:
        await self._add_column_if_missing(
            "medications", "dosage", "TEXT NOT NULL DEFAULT ''"
        )
        await self._add_column_if_missing(
            "users", "bp_reminders", "INTEGER NOT NULL DEFAULT 1"
        )
        await self._add_column_if_missing(
            "users", "bp_morning", "TEXT NOT NULL DEFAULT '09:00'"
        )
        await self._add_column_if_missing(
            "users", "bp_evening", "TEXT NOT NULL DEFAULT '20:00'"
        )
        await self._add_column_if_missing("users", "intro", "TEXT")
        await self._add_column_if_missing("users", "referral_source", "TEXT")
        await self._add_column_if_missing(
            "users", "bot_blocked", "INTEGER NOT NULL DEFAULT 0"
        )

    async def _add_column_if_missing(self, table: str, name: str, decl: str) -> None:
        cursor = await self.db.execute(f"PRAGMA table_info({table})")
        columns = {row[1] for row in await cursor.fetchall()}
        if name not in columns:
            await self.db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
            await self.db.commit()

    async def upsert_on_start(
        self,
        telegram_id: int,
        username: str | None,
        full_name: str,
    ) -> dict:
        now = iso(now_utc())
        existing = await self.get_user_by_telegram(telegram_id)
        admin_count = await self.count_admins()
        bootstrap_admin = (
            settings.admin_telegram_id is not None
            and telegram_id == settings.admin_telegram_id
        )

        if existing is None:
            if bootstrap_admin or admin_count == 0:
                role, status = "admin", "approved"
            else:
                role, status = "user", "pending"
            await self.db.execute(
                """
                INSERT INTO users (telegram_id, username, full_name, role, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (telegram_id, username, full_name, role, status, now, now),
            )
            await self.db.commit()
            user = await self.get_user_by_telegram(telegram_id)
            assert user is not None
            user["just_created"] = True
            user["became_admin"] = role == "admin"
            return user

        await self.db.execute(
            """
            UPDATE users
            SET username = ?, full_name = ?, updated_at = ?, bot_blocked = 0,
                status = CASE
                    WHEN ? = 1 THEN 'approved'
                    WHEN status = 'denied' THEN 'pending'
                    ELSE status
                END,
                role = CASE WHEN ? = 1 THEN 'admin' ELSE role END
            WHERE telegram_id = ?
            """,
            (username, full_name, now, int(bootstrap_admin), int(bootstrap_admin), telegram_id),
        )
        await self.db.commit()
        user = await self.get_user_by_telegram(telegram_id)
        assert user is not None
        user["just_created"] = False
        user["became_admin"] = False
        user["reopened_request"] = existing["status"] == "denied" and user["status"] == "pending"
        return user

    async def get_user_by_telegram(self, telegram_id: int) -> dict | None:
        cursor = await self.db.execute(
            "SELECT * FROM users WHERE telegram_id = ?",
            (telegram_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_user(self, user_id: int) -> dict | None:
        cursor = await self.db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def count_admins(self) -> int:
        cursor = await self.db.execute(
            "SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND status = 'approved'"
        )
        row = await cursor.fetchone()
        return int(row["n"]) if row else 0

    async def list_admins(self) -> list[dict]:
        cursor = await self.db.execute(
            "SELECT * FROM users WHERE role = 'admin' AND status = 'approved'"
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def list_users(self) -> list[dict]:
        cursor = await self.db.execute("SELECT * FROM users ORDER BY id")
        return [dict(r) for r in await cursor.fetchall()]

    async def list_pending(self) -> list[dict]:
        cursor = await self.db.execute(
            "SELECT * FROM users WHERE status = 'pending' ORDER BY id"
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def list_approved(self) -> list[dict]:
        cursor = await self.db.execute(
            "SELECT * FROM users WHERE status = 'approved'"
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def set_bp_reminders(self, user_id: int, enabled: bool) -> dict | None:
        await self.db.execute(
            "UPDATE users SET bp_reminders = ?, updated_at = ? WHERE id = ?",
            (1 if enabled else 0, iso(now_utc()), user_id),
        )
        await self.db.commit()
        return await self.get_user(user_id)

    async def set_bp_time(self, user_id: int, slot: str, hhmm: str) -> dict | None:
        if slot not in {"morning", "evening"}:
            return await self.get_user(user_id)
        column = "bp_morning" if slot == "morning" else "bp_evening"
        await self.db.execute(
            f"UPDATE users SET {column} = ?, updated_at = ? WHERE id = ?",
            (hhmm, iso(now_utc()), user_id),
        )
        await self.db.commit()
        return await self.get_user(user_id)

    async def set_onboarding(
        self, telegram_id: int, intro: str, referral_source: str | None
    ) -> dict | None:
        await self.db.execute(
            "UPDATE users SET intro = ?, referral_source = ?, updated_at = ? WHERE telegram_id = ?",
            (intro.strip(), (referral_source or "").strip() or None, iso(now_utc()), telegram_id),
        )
        await self.db.commit()
        return await self.get_user_by_telegram(telegram_id)

    async def set_access(self, telegram_id: int, status: str) -> dict | None:
        await self.db.execute(
            "UPDATE users SET status = ?, updated_at = ? WHERE telegram_id = ?",
            (status, iso(now_utc()), telegram_id),
        )
        await self.db.commit()
        return await self.get_user_by_telegram(telegram_id)

    async def add_bp(
        self, user_id: int, systolic: int, diastolic: int, pulse: int
    ) -> dict:
        now = iso(now_utc())
        cursor = await self.db.execute(
            """
            INSERT INTO bp_readings (user_id, systolic, diastolic, pulse, measured_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, systolic, diastolic, pulse, now, now),
        )
        await self.db.commit()
        return {
            "id": cursor.lastrowid,
            "systolic": systolic,
            "diastolic": diastolic,
            "pulse": pulse,
            "measured_at": now,
        }

    async def list_bp(
        self, user_id: int, limit: int = 10, offset: int = 0
    ) -> list[dict]:
        cursor = await self.db.execute(
            """
            SELECT * FROM bp_readings
            WHERE user_id = ?
            ORDER BY measured_at DESC
            LIMIT ? OFFSET ?
            """,
            (user_id, limit, offset),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def count_bp(self, user_id: int) -> int:
        cursor = await self.db.execute(
            "SELECT COUNT(*) AS n FROM bp_readings WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        return int(row["n"]) if row else 0

    async def bp_for_date(self, user_id: int, day: str) -> list[dict]:
        start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=MSK)
        end = start + timedelta(days=1)
        cursor = await self.db.execute(
            """
            SELECT * FROM bp_readings
            WHERE user_id = ? AND measured_at >= ? AND measured_at < ?
            ORDER BY measured_at
            """,
            (user_id, iso(start), iso(end)),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def add_med(
        self, user_id: int, name: str, times: list[str], dosage: str = ""
    ) -> dict:
        cursor = await self.db.execute(
            """
            INSERT INTO medications (user_id, name, dosage, times, is_active, created_at)
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (
                user_id,
                name.strip(),
                dosage.strip(),
                json.dumps(times, ensure_ascii=False),
                iso(now_utc()),
            ),
        )
        await self.db.commit()
        return {
            "id": cursor.lastrowid,
            "name": name.strip(),
            "dosage": dosage.strip(),
            "times": times,
        }

    async def update_med_dosage(self, med_id: int, user_id: int, dosage: str) -> bool:
        cursor = await self.db.execute(
            "UPDATE medications SET dosage = ? WHERE id = ? AND user_id = ? AND is_active = 1",
            (dosage.strip(), med_id, user_id),
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def list_meds(self, user_id: int, active_only: bool = True) -> list[dict]:
        sql = "SELECT * FROM medications WHERE user_id = ?"
        params: list = [user_id]
        if active_only:
            sql += " AND is_active = 1"
        sql += " ORDER BY id"
        cursor = await self.db.execute(sql, params)
        result = []
        for row in await cursor.fetchall():
            item = dict(row)
            item["times"] = json.loads(item["times"])
            result.append(item)
        return result

    async def get_med(self, med_id: int) -> dict | None:
        cursor = await self.db.execute("SELECT * FROM medications WHERE id = ?", (med_id,))
        row = await cursor.fetchone()
        if not row:
            return None
        item = dict(row)
        item["times"] = json.loads(item["times"])
        return item

    async def deactivate_med(self, med_id: int, user_id: int) -> bool:
        cursor = await self.db.execute(
            "UPDATE medications SET is_active = 0 WHERE id = ? AND user_id = ?",
            (med_id, user_id),
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def get_or_create_pill_log(
        self, user_id: int, medication_id: int, day: str, time_hhmm: str
    ) -> dict:
        cursor = await self.db.execute(
            """
            SELECT * FROM pill_logs
            WHERE user_id = ? AND medication_id = ? AND scheduled_date = ? AND scheduled_time = ?
            """,
            (user_id, medication_id, day, time_hhmm),
        )
        row = await cursor.fetchone()
        if row:
            return dict(row)
        try:
            await self.db.execute(
                """
                INSERT INTO pill_logs (
                    user_id, medication_id, scheduled_date, scheduled_time, status
                ) VALUES (?, ?, ?, ?, 'pending')
                """,
                (user_id, medication_id, day, time_hhmm),
            )
            await self.db.commit()
        except aiosqlite.IntegrityError:
            await self.db.rollback()
        cursor = await self.db.execute(
            """
            SELECT * FROM pill_logs
            WHERE user_id = ? AND medication_id = ? AND scheduled_date = ? AND scheduled_time = ?
            """,
            (user_id, medication_id, day, time_hhmm),
        )
        row = await cursor.fetchone()
        assert row is not None
        return dict(row)

    async def get_pill_log(self, log_id: int) -> dict | None:
        cursor = await self.db.execute("SELECT * FROM pill_logs WHERE id = ?", (log_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def update_pill_log(self, log_id: int, **fields: object) -> None:
        if not fields:
            return
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values()) + [log_id]
        await self.db.execute(
            f"UPDATE pill_logs SET {assignments} WHERE id = ?",
            values,
        )
        await self.db.commit()

    async def mark_pill_reminded(self, log_id: int, reminded_at: str) -> bool:
        """Отметить напоминание отправленным, только если пользователь ещё не решил."""
        cursor = await self.db.execute(
            """
            UPDATE pill_logs
            SET status = 'pending', reminded_at = ?, snooze_until = NULL
            WHERE id = ? AND status IN ('pending', 'snoozed')
            """,
            (reminded_at, log_id),
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def pill_logs_for_date(self, user_id: int, day: str) -> list[dict]:
        cursor = await self.db.execute(
            """
            SELECT pill_logs.*, medications.name AS med_name, medications.dosage AS med_dosage
            FROM pill_logs
            JOIN medications ON medications.id = pill_logs.medication_id
            WHERE pill_logs.user_id = ? AND pill_logs.scheduled_date = ?
            ORDER BY pill_logs.scheduled_time
            """,
            (user_id, day),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def list_all_pill_logs(self, user_id: int) -> list[dict]:
        cursor = await self.db.execute(
            """
            SELECT pill_logs.*, medications.name AS med_name, medications.dosage AS med_dosage
            FROM pill_logs
            JOIN medications ON medications.id = pill_logs.medication_id
            WHERE pill_logs.user_id = ?
            ORDER BY pill_logs.scheduled_date, pill_logs.scheduled_time
            """,
            (user_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def mark_reminder_sent(self, user_id: int, kind: str, slot: str, day: str) -> bool:
        try:
            await self.db.execute(
                """
                INSERT INTO reminder_sends (user_id, kind, slot, sent_date)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, kind, slot, day),
            )
            await self.db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def was_reminder_sent(self, user_id: int, kind: str, slot: str, day: str) -> bool:
        cursor = await self.db.execute(
            """
            SELECT 1 FROM reminder_sends
            WHERE user_id = ? AND kind = ? AND slot = ? AND sent_date = ?
            """,
            (user_id, kind, slot, day),
        )
        return await cursor.fetchone() is not None

    async def reminder_kinds_for_date(self, user_id: int, day: str) -> set[tuple[str, str]]:
        """Все отправленные сегодня напоминания пользователя одним запросом."""
        cursor = await self.db.execute(
            "SELECT kind, slot FROM reminder_sends WHERE user_id = ? AND sent_date = ?",
            (user_id, day),
        )
        return {(row["kind"], row["slot"]) for row in await cursor.fetchall()}

    async def set_bot_blocked(self, user_id: int, blocked: bool) -> None:
        await self.db.execute(
            "UPDATE users SET bot_blocked = ?, updated_at = ? WHERE id = ?",
            (1 if blocked else 0, iso(now_utc()), user_id),
        )
        await self.db.commit()

    # --- обратная связь ---

    async def add_feedback(self, user_id: int, message: str) -> int:
        cursor = await self.db.execute(
            "INSERT INTO feedback (user_id, message, created_at) VALUES (?, ?, ?)",
            (user_id, message.strip(), iso(now_utc())),
        )
        await self.db.commit()
        return int(cursor.lastrowid)

    async def get_feedback(self, feedback_id: int) -> dict | None:
        cursor = await self.db.execute(
            """
            SELECT feedback.*, users.full_name, users.username, users.telegram_id
            FROM feedback JOIN users ON users.id = feedback.user_id
            WHERE feedback.id = ?
            """,
            (feedback_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def set_feedback_reply(self, feedback_id: int, reply: str) -> None:
        await self.db.execute(
            "UPDATE feedback SET reply = ?, replied_at = ? WHERE id = ?",
            (reply.strip(), iso(now_utc()), feedback_id),
        )
        await self.db.commit()

    async def count_feedback(self, user_id: int) -> int:
        cursor = await self.db.execute(
            "SELECT COUNT(*) AS n FROM feedback WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        return int(row["n"]) if row else 0

    # --- статистика для админа ---

    async def user_status_counts(self) -> dict[str, int]:
        cursor = await self.db.execute(
            "SELECT status, COUNT(*) AS n FROM users GROUP BY status"
        )
        counts = {"approved": 0, "pending": 0, "denied": 0}
        for row in await cursor.fetchall():
            counts[row["status"]] = int(row["n"])
        return counts

    async def bp_stats(self, user_id: int, days: int) -> dict:
        cutoff = iso(now_utc() - timedelta(days=days))
        cursor = await self.db.execute(
            """
            SELECT COUNT(*) AS n,
                   AVG(systolic) AS avg_sys,
                   AVG(diastolic) AS avg_dia,
                   AVG(pulse) AS avg_pulse,
                   MAX(measured_at) AS last_at
            FROM bp_readings
            WHERE user_id = ? AND measured_at >= ?
            """,
            (user_id, cutoff),
        )
        row = await cursor.fetchone()
        result = dict(row) if row else {}
        result["n"] = int(result.get("n") or 0)
        if result["n"]:
            cursor = await self.db.execute(
                "SELECT measured_at FROM bp_readings WHERE user_id = ? AND measured_at >= ?",
                (user_id, cutoff),
            )
            days_with = {
                parse_iso(r["measured_at"]).astimezone(MSK).date()
                for r in await cursor.fetchall()
            }
            result["active_days"] = len(days_with)
        else:
            result["active_days"] = 0
            result["last_at"] = None
        return result

    async def pill_stats(self, user_id: int, days: int) -> dict:
        cutoff = (now_msk() - timedelta(days=days)).strftime("%Y-%m-%d")
        cursor = await self.db.execute(
            """
            SELECT status, COUNT(*) AS n FROM pill_logs
            WHERE user_id = ? AND scheduled_date >= ? AND status IN ('taken', 'skipped')
            GROUP BY status
            """,
            (user_id, cutoff),
        )
        result = {"taken": 0, "skipped": 0}
        for row in await cursor.fetchall():
            result[row["status"]] = int(row["n"])
        return result

    async def last_bp_at(self, user_id: int) -> str | None:
        cursor = await self.db.execute(
            "SELECT MAX(measured_at) AS last_at FROM bp_readings WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        return row["last_at"] if row else None

    async def bot_birthday(self) -> str | None:
        cursor = await self.db.execute("SELECT MIN(created_at) AS first_at FROM users")
        row = await cursor.fetchone()
        return row["first_at"] if row else None

    async def total_readings(self) -> int:
        cursor = await self.db.execute("SELECT COUNT(*) AS n FROM bp_readings")
        row = await cursor.fetchone()
        return int(row["n"]) if row else 0

    async def bp_streak_days(self, user_id: int) -> int:
        """Сколько дней подряд (включая сегодня) у пользователя есть замеры.

        Читает записи от новых к старым и останавливается на первом пропуске.
        """
        cursor = await self.db.execute(
            "SELECT measured_at FROM bp_readings WHERE user_id = ? ORDER BY measured_at DESC",
            (user_id,),
        )
        streak = 0
        expected = now_msk().date()
        seen: set = set()
        async for row in cursor:
            day = parse_iso(row["measured_at"]).astimezone(MSK).date()
            if day in seen:
                continue
            if day != expected:
                break
            seen.add(day)
            streak += 1
            expected -= timedelta(days=1)
        return streak


db = Database(settings.db_path)


def due_within(scheduled_hhmm: str, now: datetime, window_hours: float) -> bool:
    hour, minute = map(int, scheduled_hhmm.split(":"))
    scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now < scheduled:
        return False
    return now - scheduled <= timedelta(hours=window_hours)
