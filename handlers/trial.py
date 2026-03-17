"""
handlers/trial.py — выдача пробной подписки.
"""

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

import config
import database as db
import panel

logger = logging.getLogger(__name__)
router = Router()


def _trial_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="✅ Получить пробную подписку",
            callback_data="trial_confirm",
        )
    ]])


@router.message(Command("trial"))
async def cmd_trial(message: Message) -> None:
    tg_id = message.from_user.id

    user_record = await db.get_user(tg_id)
    if user_record and user_record.get("panel_uuid"):
        await message.answer("У тебя уже есть подписка. Зайди в /cabinet чтобы посмотреть детали.")
        return

    if await db.has_used_trial(tg_id):
        await message.answer(
            "😔 Пробная подписка может быть выдана только один раз.\n"
            "Воспользуйся /pay чтобы приобрести полноценную подписку."
        )
        return

    await message.answer(
        f"🎁 <b>Пробная подписка на {config.TRIAL_DAYS} дней</b>\n\n"
        "Ты получишь доступ к VPN абсолютно бесплатно.\n"
        "Подписка выдаётся <b>один раз</b> на аккаунт.\n\n"
        "Нажми кнопку ниже чтобы активировать:",
        reply_markup=_trial_keyboard(),
    )


@router.callback_query(lambda c: c.data == "trial_confirm")
async def callback_trial_confirm(callback: CallbackQuery) -> None:
    tg_id = callback.from_user.id
    tg_username = callback.from_user.username or f"user{tg_id}"

    await callback.answer()

    # Повторная проверка (защита от двойного нажатия)
    if await db.has_used_trial(tg_id):
        await callback.message.edit_text("😔 Пробная подписка уже была выдана этому аккаунту.")
        return

    user_record = await db.get_user(tg_id)
    if user_record and user_record.get("panel_uuid"):
        await callback.message.edit_text("У тебя уже есть активная подписка. Смотри /cabinet.")
        return

    await callback.message.edit_text("⏳ Создаю подписку, подожди секунду...")

    panel_username = f"tg{tg_id}"
    result = await panel.create_user(
        panel_username=panel_username,
        expire_days=config.TRIAL_DAYS,
        tg_username=tg_username,
    )

    if result is None:
        await callback.message.edit_text(
            "❌ Не удалось создать подписку — панель временно недоступна.\n"
            "Попробуй ещё раз через несколько минут."
        )
        return

    user_data = panel._user_data(result)
    panel_uuid = user_data.get("uuid")
    panel_uname = user_data.get("username", panel_username)

    await db.upsert_user(
        telegram_id=tg_id,
        username=tg_username,
        panel_uuid=panel_uuid,
        panel_username=panel_uname,
    )
    await db.mark_trial_used(tg_id)

    sub_link = panel._extract_sub_link(result)
    days_left = panel._days_left(user_data.get("expireAt"))

    await callback.message.edit_text(
        f"🎉 <b>Пробная подписка активирована!</b>\n\n"
        f"⏳ Срок: <b>{days_left} дней</b>\n\n"
        f"🔗 <b>Ссылка на подписку:</b>\n<code>{sub_link}</code>\n\n"
        "Скопируй ссылку и вставь её в своё VPN-приложение.\n"
        "Посмотреть детали всегда можно в /cabinet.",
    )
    logger.info("Пробная подписка выдана: tg_id=%d, panel_uuid=%s", tg_id, panel_uuid)
