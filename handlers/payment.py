"""
handlers/payment.py — раздел оплаты подписки.

⚠️  ВРЕМЕННАЯ ЗАГЛУШКА: вместо реальной оплаты через ЮМани подписка
    продлевается бесплатно. Скелет для будущей интеграции уже здесь.
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

PRICE_RUB = 199


def _pay_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"💳 Оплатить {PRICE_RUB} ₽",
            callback_data="pay_confirm",
        )],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="pay_cancel")],
    ])


@router.message(Command("pay"))
async def cmd_pay(message: Message) -> None:
    tg_id = message.from_user.id
    user_record = await db.get_user(tg_id)
    has_sub = user_record and user_record.get("panel_uuid")

    action_text = (
        f"🔄 Продлить подписку на <b>{config.SUBSCRIPTION_DAYS} дней</b>"
        if has_sub
        else f"🚀 Купить подписку на <b>{config.SUBSCRIPTION_DAYS} дней</b>"
    )

    await message.answer(
        f"💳 <b>Оплата подписки</b>\n\n"
        f"{action_text}\n\n"
        f"Стоимость: <b>{PRICE_RUB} ₽</b>\n\n"
        "⚠️ <i>Сейчас действует тестовый режим — подписка продлевается бесплатно.</i>",
        reply_markup=_pay_keyboard(),
    )


@router.callback_query(lambda c: c.data == "pay_confirm")
async def callback_pay_confirm(callback: CallbackQuery) -> None:
    tg_id = callback.from_user.id
    tg_username = callback.from_user.username or f"user{tg_id}"

    await callback.answer()
    await callback.message.edit_text("⏳ Обрабатываю, подожди секунду...")

    user_record = await db.get_user(tg_id)

    # Нет подписки — создаём новую
    if not user_record or not user_record.get("panel_uuid"):
        result = await panel.create_user(
            panel_username=f"tg{tg_id}",
            expire_days=config.SUBSCRIPTION_DAYS,
            tg_username=tg_username,
        )
        if result is None:
            await callback.message.edit_text(
                "❌ Не удалось создать подписку — панель временно недоступна.\n"
                "Попробуй ещё раз через несколько минут."
            )
            return

        user_data = panel._user_data(result)
        await db.upsert_user(
            telegram_id=tg_id,
            username=tg_username,
            panel_uuid=user_data.get("uuid"),
            panel_username=user_data.get("username"),
        )

        sub_link = panel._extract_sub_link(result)
        await callback.message.edit_text(
            f"✅ <b>Подписка активирована!</b>\n\n"
            f"⏳ Срок: <b>{config.SUBSCRIPTION_DAYS} дней</b>\n\n"
            f"🔗 <b>Ссылка на подписку:</b>\n<code>{sub_link}</code>",
        )
        logger.info("[STUB] Подписка создана: tg_id=%d", tg_id)
        return

    # Есть подписка — продлеваем
    result = await panel.extend_user_subscription(
        panel_uuid=user_record["panel_uuid"],
        days=config.SUBSCRIPTION_DAYS,
    )
    if result is None:
        await callback.message.edit_text(
            "❌ Не удалось продлить подписку — панель временно недоступна.\n"
            "Попробуй ещё раз через несколько минут."
        )
        return

    user_data = panel._user_data(result)
    days_left = panel._days_left(user_data.get("expireAt"))

    await callback.message.edit_text(
        f"✅ <b>Подписка продлена!</b>\n\n"
        f"⏳ Осталось дней: <b>{days_left}</b>\n\n"
        "Подробности смотри в /cabinet.",
    )
    logger.info("[STUB] Подписка продлена: tg_id=%d", tg_id)


@router.callback_query(lambda c: c.data == "pay_cancel")
async def callback_pay_cancel(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text("Операция отменена.")
