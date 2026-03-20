"""
webhook_server.py — FastAPI сервер для приёма уведомлений от ЮКассы.

Запускается ОТДЕЛЬНО от бота:
    uvicorn webhook_server:app --host 0.0.0.0 --port 8000

Nginx проксирует входящие запросы на этот порт.
ЮКасса шлёт POST на YOOKASSA_WEBHOOK_URL при каждом изменении статуса платежа.
"""

import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI, Request, HTTPException
from yookassa import Configuration
from yookassa.domain.notification import WebhookNotificationFactory

import config
import database as db
import panel

# ---------------------------------------------------------------------------
# Логирование
# ---------------------------------------------------------------------------

def setup_logging() -> None:
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    formatter = logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(formatter)
    root.addHandler(ch)
    fh = RotatingFileHandler("webhook.log", maxBytes=5*1024*1024, backupCount=3, encoding="utf-8")
    fh.setFormatter(formatter)
    root.addHandler(fh)

setup_logging()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ЮКасса
# ---------------------------------------------------------------------------

Configuration.account_id = config.YOOKASSA_SHOP_ID
Configuration.secret_key = config.YOOKASSA_API_KEY

# ---------------------------------------------------------------------------
# Telegram бот (только для отправки уведомлений пользователю)
# ---------------------------------------------------------------------------

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

_bot: Bot | None = None

def get_bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(
            token=config.BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
    return _bot

# ---------------------------------------------------------------------------
# FastAPI
# ---------------------------------------------------------------------------

app = FastAPI(docs_url=None, redoc_url=None)  # docs отключены в проде


@app.on_event("startup")
async def startup() -> None:
    await db.init_db()
    logger.info("Вебхук-сервер запущен")


@app.on_event("shutdown")
async def shutdown() -> None:
    await panel.close()
    bot = get_bot()
    await bot.session.close()


@app.post("/webhook/yookassa")
async def yookassa_webhook(request: Request) -> dict:
    body = await request.body()

    try:
        import json
        body_dict = json.loads(body)
        notification = WebhookNotificationFactory().create(body_dict)
    except Exception as exc:
        logger.warning("Не удалось распарсить уведомление ЮКассы: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid notification")

    payment_obj = notification.object
    payment_id = payment_obj.id
    status = payment_obj.status  # 'succeeded' | 'canceled' | 'waiting_for_capture' | ...

    logger.info("Уведомление ЮКассы: payment_id=%s status=%s", payment_id, status)

    # Получаем запись из нашей БД
    payment_record = await db.get_payment(payment_id)
    if not payment_record:
        # Неизвестный платёж — игнорируем, возвращаем 200 (иначе ЮКасса будет повторять)
        logger.warning("Неизвестный payment_id=%s — игнорируем", payment_id)
        return {"ok": True}

    # Уже обработан?
    if payment_record["status"] == "succeeded":
        return {"ok": True}

    await db.update_payment_status(payment_id, status)

    if status == "succeeded":
        await _handle_successful_payment(payment_record)
    elif status == "canceled":
        await _notify_user(
            payment_record["telegram_id"],
            "❌ Платёж отменён. Если это ошибка — попробуй снова через /pay."
        )

    return {"ok": True}


async def _handle_successful_payment(payment_record: dict) -> None:
    tg_id = int(payment_record["telegram_id"])
    plan_id = payment_record["plan_id"]
    plan = config.PLANS_BY_ID.get(plan_id)

    if not plan:
        logger.error("Неизвестный plan_id=%s для payment_id=%s", plan_id, payment_record["payment_id"])
        return

    user_record = await db.get_user(tg_id)

    # Нет подписки — создаём новую
    if not user_record or not user_record.get("panel_uuid"):
        tg_username = user_record.get("username") if user_record else f"user{tg_id}"
        result = await panel.create_user(
            panel_username=f"tg{tg_id}",
            expire_days=plan["days"],
            tg_username=tg_username,
        )
        if result is None:
            logger.error("Не удалось создать подписку после оплаты: tg_id=%d", tg_id)
            await _notify_user(tg_id,
                "✅ Оплата прошла успешно, но возникла ошибка при создании подписки.\n"
                "Напиши администратору — тебе помогут в течение 5 минут."
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
        days_left = panel._days_left(user_data.get("expireAt"))

        await _notify_user(tg_id,
            f"✅ <b>Оплата прошла! Подписка активирована.</b>\n\n"
            f"📦 Тариф: <b>{plan['label']}</b>\n"
            f"⏳ Дней: <b>{days_left}</b>\n\n"
            f"🔗 <b>Ссылка на подписку:</b>\n<code>{sub_link}</code>\n\n"
            "Вставь ссылку в своё VPN-приложение. Подробности — /cabinet"
        )

    # Есть подписка — продлеваем
    else:
        result = await panel.extend_user_subscription(
            panel_uuid=user_record["panel_uuid"],
            days=plan["days"],
        )
        if result is None:
            logger.error("Не удалось продлить подписку после оплаты: tg_id=%d", tg_id)
            await _notify_user(tg_id,
                "✅ Оплата прошла успешно, но возникла ошибка при продлении подписки.\n"
                "Напиши администратору — тебе помогут в течение 5 минут."
            )
            return

        user_data = panel._user_data(result)
        days_left = panel._days_left(user_data.get("expireAt"))

        await _notify_user(tg_id,
            f"✅ <b>Оплата прошла! Подписка продлена.</b>\n\n"
            f"📦 Тариф: <b>{plan['label']}</b>\n"
            f"⏳ Осталось дней: <b>{days_left}</b>\n\n"
            "Подробности — /cabinet"
        )

    logger.info(
        "Подписка успешно выдана/продлена: tg_id=%d plan=%s payment_id=%s",
        tg_id, plan_id, payment_record["payment_id"],
    )


async def _notify_user(telegram_id: int, text: str) -> None:
    try:
        await get_bot().send_message(telegram_id, text)
    except Exception as exc:
        logger.warning("Не удалось отправить уведомление tg_id=%d: %s", telegram_id, exc)