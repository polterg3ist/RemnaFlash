import os
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise ValueError(f"Обязательная переменная окружения {key!r} не задана")
    return value


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
BOT_TOKEN: str = _require("BOT_TOKEN")

# ---------------------------------------------------------------------------
# Remnawave
# ---------------------------------------------------------------------------
REMNAWAVE_BASE_URL: str = _require("REMNAWAVE_BASE_URL").rstrip("/")
REMNAWAVE_TOKEN: str = _require("REMNAWAVE_TOKEN")
REMNAWAVE_SQUAD_UUID: str = _require("REMNAWAVE_SQUAD_UUID")

# Кука Caddy (если панель установлена скриптом с caddy-защитой)
CADDY_COOKIE: str = os.getenv("CADDY_COOKIE", "")

# ---------------------------------------------------------------------------
# Пробный период
# ---------------------------------------------------------------------------
TRIAL_DAYS: int = int(os.getenv("TRIAL_DAYS", "14"))

# ---------------------------------------------------------------------------
# Тарифные планы
# Структура: (название, дней, цена в рублях)
# Меняй цены здесь — они автоматически отразятся во всём боте
# ---------------------------------------------------------------------------
PLANS: list[dict] = [
    {
        "id":    "1m",
        "label": "1 месяц",
        "days":  30,
        "price": int(os.getenv("PRICE_1M", "199")),
    },
    {
        "id":    "3m",
        "label": "3 месяца",
        "days":  90,
        "price": int(os.getenv("PRICE_3M", "499")),   # ~166 ₽/мес
    },
    {
        "id":    "6m",
        "label": "6 месяцев",
        "days":  180,
        "price": int(os.getenv("PRICE_6M", "899")),   # ~150 ₽/мес
    },
    {
        "id":    "12m",
        "label": "12 месяцев",
        "days":  365,
        "price": int(os.getenv("PRICE_12M", "1499")), # ~125 ₽/мес
    },
]

# Быстрый доступ к плану по id
PLANS_BY_ID: dict = {p["id"]: p for p in PLANS}

# ---------------------------------------------------------------------------
# ЮКасса
# ---------------------------------------------------------------------------
YOOKASSA_SHOP_ID: str = _require("YOOKASSA_SHOP_ID")
YOOKASSA_API_KEY: str = _require("YOOKASSA_API_KEY")
# URL вебхука — куда ЮКасса будет слать уведомления об оплате
# Пример: https://pay.yourdomain.com/webhook/yookassa
YOOKASSA_WEBHOOK_URL: str = _require("YOOKASSA_WEBHOOK_URL")

# ---------------------------------------------------------------------------
# БД
# ---------------------------------------------------------------------------
DB_PATH: str = os.getenv("DB_PATH", "bot_data.db")

# ---------------------------------------------------------------------------
# Лимиты устройств
# ---------------------------------------------------------------------------
HWID_DEVICE_LIMIT: int = int(os.getenv("HWID_DEVICE_LIMIT", "5"))

# Веб-сайт
SITE_URL: str = os.getenv("SITE_URL", "https://site.poltergeist322.ru")

# JWT для веб-сайта
JWT_SECRET: str = _require("JWT_SECRET")