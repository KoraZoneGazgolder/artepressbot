from __future__ import annotations

import csv
from io import StringIO

from datetime import datetime

from app.db import fmt_day, fmt_time

PILL_STATUS = {
    "taken": "выпил",
    "skipped": "пропуск",
    "snoozed": "позже",
    "pending": "не отмечено",
}


def _csv_bytes(rows: list[list[object]]) -> bytes:
    buffer = StringIO()
    buffer.write("\ufeff")
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def pressure_csv(readings: list[dict]) -> bytes:
    lines: list[list[object]] = [["Дата", "Время", "Верхнее", "Нижнее", "Пульс"]]
    for row in reversed(readings):
        lines.append(
            [
                fmt_day(row["measured_at"]),
                fmt_time(row["measured_at"]),
                row["systolic"],
                row["diastolic"],
                row["pulse"],
            ]
        )
    return _csv_bytes(lines)


def pills_csv(logs: list[dict]) -> bytes:
    lines: list[list[object]] = [["Дата", "Время", "Препарат", "Статус"]]
    for row in logs:
        lines.append(
            [
                datetime.strptime(row["scheduled_date"], "%Y-%m-%d").strftime("%d.%m.%Y"),
                row["scheduled_time"],
                row.get("med_name") or "",
                PILL_STATUS.get(row["status"], row["status"]),
            ]
        )
    return _csv_bytes(lines)
