"""
api_server.py — REST API для веб-сайта FlashLink.

Запуск:
    uvicorn api_server:app --host 127.0.0.1 --port 8001

Endpoints:
    GET  /api/plans              — тарифные планы (публичный)
    POST /api/auth/register      — регистрация
    POST /api/auth/login         — вход
    GET  /api/cabinet            — данные подписки (авторизованный)
    POST /api/trial              — активировать пробный период
    POST /api/payment/create     — создать платёж ЮКасса
"""

import logging
import sys
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from typing import Optional

import jwt
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
import uuid
from yookassa import Configuration, Payment as YKPayment

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
    fh = RotatingFileHandler("api.log", maxBytes=5*1024*1024, backupCount=3, encoding="utf-8")
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
# Auth утилиты
# ---------------------------------------------------------------------------

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

JWT_SECRET = config.JWT_SECRET
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = 30


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_token(user_id: int, email: str) -> str:
    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Токен истёк, войдите снова")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Недействительный токен")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    payload = decode_token(credentials.credentials)
    user = await db.get_web_user_by_id(int(payload["sub"]))
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    return user

# ---------------------------------------------------------------------------
# FastAPI
# ---------------------------------------------------------------------------

app = FastAPI(title="FlashLink API", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # в проде замени на свой домен
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    await db.init_db()
    logger.info("API сервер запущен")


@app.on_event("shutdown")
async def shutdown() -> None:
    await panel.close()

# ---------------------------------------------------------------------------
# Pydantic схемы
# ---------------------------------------------------------------------------

class AuthRequest(BaseModel):
    email: EmailStr
    password: str


class PaymentRequest(BaseModel):
    plan_id: str

# ---------------------------------------------------------------------------
# Маршруты
# ---------------------------------------------------------------------------

@app.get("/api/plans")
async def get_plans():
    """Возвращает тарифные планы — используется фронтендом для рендера."""
    return {"plans": config.PLANS}


@app.post("/api/auth/register", status_code=201)
async def register(body: AuthRequest):
    existing = await db.get_web_user_by_email(body.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email уже зарегистрирован")

    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Пароль должен быть не менее 8 символов")

    hashed = hash_password(body.password)
    user_id = await db.create_web_user(email=body.email, password_hash=hashed)
    token = create_token(user_id, body.email)
    logger.info("Новый пользователь: %s", body.email)
    return {"access_token": token}


@app.post("/api/auth/login")
async def login(body: AuthRequest):
    user = await db.get_web_user_by_email(body.email)
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Неверный email или пароль")
    token = create_token(user["id"], user["email"])
    return {"access_token": token}


@app.get("/api/cabinet")
async def cabinet(current_user: dict = Depends(get_current_user)):
    """Данные подписки для личного кабинета."""
    panel_uuid = current_user.get("panel_uuid")

    if not panel_uuid:
        return {
            "email": current_user["email"],
            "has_subscription": False,
            "has_used_trial": await db.has_used_trial_web(current_user["id"]),
        }

    result = await panel.get_user_by_uuid(panel_uuid)
    if not result:
        raise HTTPException(status_code=503, detail="Панель временно недоступна")

    user_data = panel._user_data(result)
    days_left = panel._days_left(user_data.get("expireAt"))
    traffic_bytes = (user_data.get("userTraffic") or {}).get("usedTrafficBytes") or 0

    def fmt_traffic(b):
        if not b: return "0 МБ"
        gb = b / 1024**3
        return f"{gb:.2f} ГБ" if gb >= 1 else f"{b/1024**2:.1f} МБ"

    return {
        "email": current_user["email"],
        "has_subscription": True,
        "status": user_data.get("status", ""),
        "days_left": days_left,
        "traffic_used": fmt_traffic(traffic_bytes),
        "subscription_url": panel._extract_sub_link(result),
    }


@app.post("/api/trial", status_code=201)
async def activate_trial(current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]

    if current_user.get("panel_uuid"):
        raise HTTPException(status_code=400, detail="Подписка уже активна")

    if await db.has_used_trial_web(user_id):
        raise HTTPException(status_code=400, detail="Пробный период уже был использован")

    panel_username = f"web{user_id}"
    result = await panel.create_user(
        panel_username=panel_username,
        expire_days=config.TRIAL_DAYS,
        tg_username=current_user["email"],
    )
    if not result:
        raise HTTPException(status_code=503, detail="Не удалось создать подписку, попробуй позже")

    user_data = panel._user_data(result)
    await db.update_web_user_panel(
        user_id=user_id,
        panel_uuid=user_data.get("uuid"),
    )
    await db.mark_trial_used_web(user_id)

    logger.info("Пробный период выдан: web_user_id=%d", user_id)
    return {"ok": True}


@app.post("/api/payment/create")
async def create_payment(
    body: PaymentRequest,
    current_user: dict = Depends(get_current_user),
):
    plan = config.PLANS_BY_ID.get(body.plan_id)
    if not plan:
        raise HTTPException(status_code=400, detail="Неизвестный тариф")

    user_id = current_user["id"]
    idempotency_key = str(uuid.uuid4())

    try:
        payment = YKPayment.create({
            "amount": {"value": str(plan["price"]), "currency": "RUB"},
            "confirmation": {
                "type": "redirect",
                "return_url": config.SITE_URL,
            },
            "capture": True,
            "description": f"FlashLink VPN — {plan['label']} (web:{user_id})",
            "metadata": {
                "web_user_id": str(user_id),
                "plan_id": body.plan_id,
                "source": "web",
            },
        }, idempotency_key)
    except Exception as exc:
        logger.error("Ошибка создания платежа ЮКасса: %s", exc, exc_info=True)
        raise HTTPException(status_code=503, detail="Ошибка платёжного сервиса")

    await db.create_payment(
        payment_id=payment.id,
        telegram_id=user_id,  # здесь web_user_id, поле переиспользуем
        plan_id=body.plan_id,
        amount=plan["price"],
    )

    logger.info("Платёж создан: %s web_user_id=%d", payment.id, user_id)
    return {"confirmation_url": payment.confirmation.confirmation_url}


# ---------------------------------------------------------------------------
# Статика — отдаём сайт
# ---------------------------------------------------------------------------

app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
