"""
handlers/cabinet.py — личный кабинет пользователя.
"""

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

import database as db
import panel

logger = logging.getLogger(__name__)
router = Router()


def _format_traffic(bytes_used: int) -> str:
    if not bytes_used:
        return "0 МБ"
    gb = bytes_used / (1024 ** 3)
    if gb >= 1:
        return f"{gb:.2f} ГБ"
    return f"{bytes_used / (1024 ** 2):.1f} МБ"


@router.message(Command("cabinet"))
async def cmd_cabinet(message: Message) -> None:
    tg_id = message.from_user.id

    user_record = await db.get_user(tg_id)
    if not user_record or not user_record.get("panel_uuid"):
        await message.answer(
            "У тебя пока нет подписки.\n\n"
            "👉 /trial — получить бесплатную пробную подписку на 14 дней\n"
            "👉 /pay — купить подписку"
        )
        return

    await message.answer("🔄 Загружаю данные подписки...")

    result = await panel.get_user_by_uuid(user_record["panel_uuid"])
    if result is None:
        await message.answer(
            "❌ Не удалось получить данные подписки — панель временно недоступна.\n"
            "Попробуй позже."
        )
        return

    user_data = panel._user_data(result)

    sub_link = panel._extract_sub_link(result)
    days_left = panel._days_left(user_data.get("expireAt"))
    used_traffic_bytes = (user_data.get("userTraffic") or {}).get("usedTrafficBytes") or 0
    used_traffic = _format_traffic(used_traffic_bytes)

    status_active = str(user_data.get("status", "")).upper() == "ACTIVE" and days_left > 0
    status_emoji = "🟢 Активна" if status_active else "🔴 Истекла"

    await message.answer(
        f"📋 <b>Личный кабинет — FlashLink VPN</b>\n\n"
        f"Статус: {status_emoji}\n"
        f"⏳ Дней до конца: <b>{days_left}</b>\n"
        f"📊 Использован трафик: <b>{used_traffic}</b>\n\n"
        "━━━━━━━━━━━━━━━━━\n\n"
        "📲 Нажми на ссылку ниже, чтобы перейти на страницу подписки — "
        "там ты найдёшь инструкцию по подключению и сможешь добавить VPN "
        "в приложение в один клик:\n\n"
        f"🔗 <a href=\"{sub_link}\">Открыть страницу подписки</a>\n\n"
        "━━━━━━━━━━━━━━━━━\n\n"
        "❓ <b>Ссылка не открывается?</b>\n"
        "Скопируй её и добавь вручную в своё VPN-приложение "
        "(Hiddify, V2RayNG, Streisand и другие):\n\n"
        f"<code>{sub_link}</code>\n\n"
        "━━━━━━━━━━━━━━━━━\n"
        "🔄 Продлить подписку — /pay",
    )