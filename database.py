"""
database.py — работа с локальной SQLite базой.

Таблицы:
  users      — пользователи бота с привязкой к панели
  trial_used — факт использования пробной подписки
  payments   — история платежей ЮКассы
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
                payment_id    TEXT PRIMARY KEY,   -- UUID от ЮКассы
                telegram_id   INTEGER NOT NULL,
                plan_id       TEXT NOT NULL,      -- '1m', '3m', '6m', '12m'
                amount        INTEGER NOT NULL,   -- рублей
                status        TEXT NOT NULL DEFAULT 'pending',  -- pending/succeeded/canceled
                created_at    TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.commit()
    logger.info("БД инициализирована: %s", DB_PATH)


# ---------------------------------------------------------------------------
# Пользователи
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
# Пробная подписка
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
    logger.info("Пробная подписка выдана: telegram_id=%d", telegram_id)


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
    logger.info("Статус платежа %s → %s", payment_id, status)