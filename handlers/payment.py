"""
handlers/payment.py — выбор тарифного плана и создание платежа ЮКасса.

Флоу:
  /pay → выбор плана → создание платежа в ЮКасса → ссылка на оплату
  После оплаты ЮКасса шлёт уведомление на вебхук (webhook_server.py),
  который продлевает подписку и уведомляет пользователя.
"""

import logging
import uuid

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from yookassa import Configuration, Payment

import config
import database as db

logger = logging.getLogger(__name__)
router = Router()

# Инициализация ЮКассы
Configuration.account_id = config.YOOKASSA_SHOP_ID
Configuration.secret_key = config.YOOKASSA_API_KEY


# ---------------------------------------------------------------------------
# Клавиатуры
# ---------------------------------------------------------------------------

def _plans_keyboard() -> InlineKeyboardMarkup:
    """Кнопки с тарифными планами — цены берутся из config.PLANS."""
    buttons = []
    for plan in config.PLANS:
        per_month = plan["price"] / (plan["days"] / 30)
        label = f"{plan['label']} — {plan['price']} ₽ (~{per_month:.0f} ₽/мес)"
        buttons.append([InlineKeyboardButton(
            text=label,
            callback_data=f"buy:{plan['id']}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ---------------------------------------------------------------------------
# Хэндлеры
# ---------------------------------------------------------------------------

@router.message(Command("pay"))
async def cmd_pay(message: Message) -> None:
    tg_id = message.from_user.id
    user_record = await db.get_user(tg_id)
    has_sub = user_record and user_record.get("panel_uuid")

    action = "продлить" if has_sub else "купить"

    await message.answer(
        f"💳 <b>Оплата подписки FlashLink VPN</b>\n\n"
        f"Выбери тариф чтобы {action} подписку:\n\n"
        "Чем дольше срок — тем выгоднее цена 🎯",
        reply_markup=_plans_keyboard(),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("buy:"))
async def callback_buy_plan(callback: CallbackQuery) -> None:
    plan_id = callback.data.split(":", 1)[1]
    plan = config.PLANS_BY_ID.get(plan_id)

    if not plan:
        await callback.answer("Неизвестный тариф", show_alert=True)
        return

    await callback.answer()

    tg_id = callback.from_user.id
    idempotency_key = str(uuid.uuid4())

    try:
        payment = Payment.create({
            "amount": {
                "value": str(plan["price"]),
                "currency": "RUB",
            },
            "confirmation": {
                "type": "redirect",
                "return_url": f"https://t.me/{(await callback.bot.get_me()).username}",
            },
            "capture": True,
            "description": f"FlashLink VPN — {plan['label']} (tg:{tg_id})",
            "metadata": {
                "telegram_id": str(tg_id),
                "plan_id": plan_id,
            },
        }, idempotency_key)

    except Exception as exc:
        logger.error("Ошибка создания платежа ЮКасса: %s", exc, exc_info=True)
        await callback.message.edit_text(
            "❌ Не удалось создать платёж. Попробуй позже или напиши администратору."
        )
        return

    # Сохраняем платёж в БД
    await db.create_payment(
        payment_id=payment.id,
        telegram_id=tg_id,
        plan_id=plan_id,
        amount=plan["price"],
    )

    pay_url = payment.confirmation.confirmation_url
    logger.info(
        "Платёж создан: %s tg_id=%d plan=%s amount=%d",
        payment.id, tg_id, plan_id, plan["price"],
    )

    await callback.message.edit_text(
        f"💳 <b>Оплата — {plan['label']}</b>\n\n"
        f"Сумма: <b>{plan['price']} ₽</b>\n\n"
        "Нажми кнопку ниже для перехода к оплате.\n"
        "После успешной оплаты подписка активируется автоматически ✅",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="💳 Перейти к оплате", url=pay_url),
        ]]),
    )