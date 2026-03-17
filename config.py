import os
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise ValueError(f"Обязательная переменная окружения {key!r} не задана")
    return value


# Telegram
BOT_TOKEN: str = _require("BOT_TOKEN")

# Remnawave
REMNAWAVE_BASE_URL: str = _require("REMNAWAVE_BASE_URL").rstrip("/")
REMNAWAVE_TOKEN: str = _require("REMNAWAVE_TOKEN")
REMNAWAVE_SQUAD_UUID: str = _require("REMNAWAVE_SQUAD_UUID")

# Кука Caddy (если панель установлена скриптом с caddy-защитой)
# Оставь пустым если не используется
CADDY_COOKIE: str = os.getenv("CADDY_COOKIE", "")

# Подписка
TRIAL_DAYS: int = int(os.getenv("TRIAL_DAYS", "14"))
SUBSCRIPTION_DAYS: int = int(os.getenv("SUBSCRIPTION_DAYS", "30"))

# БД
DB_PATH: str = os.getenv("DB_PATH", "bot_data.db")

# Лимиты
HWID_DEVICE_LIMIT: int = int(os.getenv("HWID_DEVICE_LIMIT", "5"))