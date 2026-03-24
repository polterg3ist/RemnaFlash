"""
database.py — работа с локальной SQLite базой.

Таблицы:
  users      — telegram-пользователи бота
  trial_used — факт использования пробной подписки (бот)
  payments   — история платежей ЮКассы
  web_users  — пользователи веб-сайта
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

from config import DB_PATH

logger = logging.getLogger(__name__)


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id     INTEGER PRIMARY KEY,
                username        TEXT NOT NULL,
                panel_uuid      TEXT,
                panel_username  TEXT,
                created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS trial_used (
                telegram_id  INTEGER PRIMARY KEY,
                used_at      TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                payment_id    TEXT PRIMARY KEY,
                telegram_id   INTEGER NOT NULL,
                plan_id       TEXT NOT NULL,
                amount        INTEGER NOT NULL,
                status        TEXT NOT NULL DEFAULT 'pending',
                created_at    TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS web_users (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                email          TEXT NOT NULL UNIQUE,
                password_hash  TEXT NOT NULL,
                panel_uuid     TEXT,
                trial_used     INTEGER NOT NULL DEFAULT 0,
                created_at     TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.commit()
    logger.info("БД инициализирована: %s", DB_PATH)


# ---------------------------------------------------------------------------
# Telegram-пользователи
# ---------------------------------------------------------------------------

async def get_user(telegram_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def upsert_user(
    telegram_id: int,
    username: str,
    panel_uuid: Optional[str] = None,
    panel_username: Optional[str] = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users (telegram_id, username, panel_uuid, panel_username, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username        = excluded.username,
                panel_uuid      = COALESCE(excluded.panel_uuid, panel_uuid),
                panel_username  = COALESCE(excluded.panel_username, panel_username),
                updated_at      = excluded.updated_at
        """, (telegram_id, username, panel_uuid, panel_username, now, now))
        await db.commit()


# ---------------------------------------------------------------------------
# Пробная подписка (бот)
# ---------------------------------------------------------------------------

async def has_used_trial(telegram_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM trial_used WHERE telegram_id = ?", (telegram_id,)
        ) as cursor:
            return await cursor.fetchone() is not None


async def mark_trial_used(telegram_id: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO trial_used (telegram_id, used_at) VALUES (?, ?)",
            (telegram_id, now),
        )
        await db.commit()
    logger.info("Пробная подписка (бот) выдана: telegram_id=%d", telegram_id)


# ---------------------------------------------------------------------------
# Платежи
# ---------------------------------------------------------------------------

async def create_payment(
    payment_id: str,
    telegram_id: int,
    plan_id: str,
    amount: int,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR IGNORE INTO payments
                (payment_id, telegram_id, plan_id, amount, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'pending', ?, ?)
        """, (payment_id, telegram_id, plan_id, amount, now, now))
        await db.commit()
    logger.info("Платёж создан: %s tg_id=%d plan=%s", payment_id, telegram_id, plan_id)


async def get_payment(payment_id: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM payments WHERE payment_id = ?", (payment_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def update_payment_status(payment_id: str, status: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE payments SET status = ?, updated_at = ? WHERE payment_id = ?",
            (status, now, payment_id),
        )
        await db.commit()
    logger.info("Статус платежа %s -> %s", payment_id, status)


# ---------------------------------------------------------------------------
# Веб-пользователи (сайт)
# ---------------------------------------------------------------------------

async def create_web_user(email: str, password_hash: str) -> int:
    """Создаёт веб-пользователя. Возвращает его id."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO web_users (email, password_hash) VALUES (?, ?)",
            (email, password_hash),
        )
        await db.commit()
        return cursor.lastrowid


async def get_web_user_by_email(email: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM web_users WHERE email = ?", (email,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_web_user_by_id(user_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM web_users WHERE id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def update_web_user_panel(user_id: int, panel_uuid: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE web_users SET panel_uuid = ? WHERE id = ?",
            (panel_uuid, user_id),
        )
        await db.commit()


async def has_used_trial_web(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT trial_used FROM web_users WHERE id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return bool(row and row[0])


async def mark_trial_used_web(user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE web_users SET trial_used = 1 WHERE id = ?", (user_id,)
        )
        await db.commit()
    logger.info("Пробная подписка (web) выдана: web_user_id=%d", user_id)