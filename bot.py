"""
bot.py — точка входа Telegram-бота.

Запуск:
    python bot.py

Структура проекта:
    config.py           — настройки из .env
    database.py         — работа с SQLite
    panel.py            — обёртка над Remnawave SDK
    handlers/
        trial.py        — /trial, пробная подписка
        cabinet.py      — /cabinet, личный кабинет
        payment.py      — /pay, оплата (пока заглушка)
"""

import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

import config
import database as db
import panel
from handlers import trial, cabinet, payment


# ---------------------------------------------------------------------------
# Логирование
# ---------------------------------------------------------------------------

def setup_logging() -> None:
    """Настраивает логирование в консоль и в файл bot.log."""
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_fmt = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(fmt, datefmt=date_fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Консоль
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    # Файл (ротация по 5 МБ, хранить 3 файла)
    file_handler = RotatingFileHandler(
        "bot.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # Уменьшаем шум от httpx и aiogram внутренностей
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Хэндлеры стартовой команды и помощи
# ---------------------------------------------------------------------------

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

core_router = Router()


@core_router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    tg_id = message.from_user.id
    username = message.from_user.username or f"user{tg_id}"
    await db.upsert_user(telegram_id=tg_id, username=username)

    # Формируем строки тарифов из config — любое изменение цен отразится здесь
    plans_text = "\n".join(
        f"  • {p['label']} — <b>{p['price']} ₽</b>"
        for p in config.PLANS
    )

    await message.answer(
        "⚡ <b>FlashLink VPN</b>\n\n"
        "Быстрый, надёжный и безопасный VPN.\n"
        "Работает на всех устройствах: iOS, Android, Windows, macOS.\n\n"
        "━━━━━━━━━━━━━━━━━\n"
        f"🎁 Новым пользователям — <b>14 дней бесплатно</b>\n\n"
        f"💳 Тарифы:\n{plans_text}\n"
        "━━━━━━━━━━━━━━━━━\n\n"
        "<b>Команды:</b>\n"
        "🎁 /trial — бесплатная пробная подписка\n"
        "📋 /cabinet — личный кабинет\n"
        "💳 /pay — купить или продлить подписку\n"
        "ℹ️ /help — помощь"
    )


@core_router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "ℹ️ <b>Помощь</b>\n\n"
        "/start — начало работы\n"
        "/trial — получить пробную подписку (1 раз)\n"
        "/cabinet — посмотреть свою подписку\n"
        "/pay — купить или продлить подписку\n\n"
        "Если возникли проблемы — напиши администратору.",
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------

async def main() -> None:
    setup_logging()
    logger.info("Запуск бота...")

    # Инициализируем БД
    await db.init_db()

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # Регистрируем роутеры
    dp.include_router(core_router)
    dp.include_router(trial.router)
    dp.include_router(cabinet.router)
    dp.include_router(payment.router)

    logger.info("Бот запущен. Polling...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
        await panel.close()
        logger.info("Бот остановлен.")


if __name__ == "__main__":
    asyncio.run(main())