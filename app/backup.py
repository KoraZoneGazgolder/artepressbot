import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from app.config import settings
from app.db import db

log = logging.getLogger(__name__)


async def backup_db() -> Path | None:
    """Онлайн-бэкап SQLite в BACKUP_DIR с ротацией до BACKUP_KEEP файлов."""
    if db._db is None:
        return None
    backup_dir = Path(settings.backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / f"diary-{datetime.now().strftime('%Y-%m-%d')}.db"
    target = sqlite3.connect(dest)
    try:
        await db.db.backup(target)
    finally:
        target.close()
    _prune(backup_dir, settings.backup_keep)
    log.info("DB backup saved: %s", dest)
    return dest


def _prune(backup_dir: Path, keep: int) -> None:
    files = sorted(backup_dir.glob("diary-*.db"))
    for old in files[:-keep]:
        old.unlink(missing_ok=True)
        log.info("DB backup rotated out: %s", old)
