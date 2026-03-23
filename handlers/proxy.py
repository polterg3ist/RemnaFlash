"""
handlers/proxy.py — бесплатное MTProto прокси для Telegram.
"""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

router = Router()

PROXY_LINK = "https://t.me/proxy?server=193.109.79.228&port=443&secret=a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"


@router.message(Command("proxy"))
async def cmd_proxy(message: Message) -> None:
    await message.answer(
        "🔒 <b>Бесплатное MTProto прокси для Telegram</b>\n\n"
        "Если Telegram заблокирован — нажми кнопку ниже, "
        "прокси добавится автоматически:\n\n"
        f"<a href=\"{PROXY_LINK}\">⚡ Подключить прокси</a>\n\n"
        "Или скопируй ссылку вручную:\n"
        f"<code>{PROXY_LINK}</code>\n\n"
        "━━━━━━━━━━━━━━━━━\n"
        "Для полноценной защиты и обхода блокировок используй VPN — /trial",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="⚡ Подключить прокси", url=PROXY_LINK),
        ]]),
    )