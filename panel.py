"""
panel.py — работа с Remnawave API через прямые httpx-запросы.

Не использует SDK — это устраняет все проблемы с версиями и именами полей.
Токен берётся из .env как REMNAWAVE_TOKEN (Bearer, из раздела API Tokens панели).

Все методы возвращают dict (распарсенный JSON) или None при ошибке.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HTTP-клиент (один на весь процесс, переиспользуем keep-alive соединения)
# ---------------------------------------------------------------------------

_client: Optional[httpx.AsyncClient] = None

# Заголовки переиспользуем, клиент держим открытым для keep-alive
_HEADERS: dict = {
    "Authorization": f"Bearer {config.REMNAWAVE_TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}
if config.CADDY_COOKIE:
    _HEADERS["Cookie"] = f"caddy={config.CADDY_COOKIE}"


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        # Без base_url — строим полный URL сами, чтобы избежать
        # проблем с URL-резолвингом httpx (RFC 3986 edge cases)
        async def _log_request(request: httpx.Request) -> None:
            logger.debug("→ %s %s", request.method, request.url)

        async def _log_response(response: httpx.Response) -> None:
            if response.status_code in (301, 302, 307, 308):
                logger.warning(
                    "Редирект %d: %s → %s",
                    response.status_code,
                    response.request.url,
                    response.headers.get("location", "?"),
                )
            else:
                logger.debug("← %d %s", response.status_code, response.url)

        _client = httpx.AsyncClient(
            headers=_HEADERS,
            timeout=15.0,
            follow_redirects=False,   # редиректы отключены — POST не превратится в GET
            event_hooks={
                "request": [_log_request],
                "response": [_log_response],
            },
        )
        logger.info("httpx.AsyncClient инициализирован")
    return _client


def _url(path: str) -> str:
    """Строит полный URL: base + path. path должен начинаться с /"""
    base = config.REMNAWAVE_BASE_URL.rstrip("/")
    path = "/" + path.lstrip("/")
    full = base + path
    logger.debug("→ %s", full)
    return full


async def _request(method: str, path: str, **kwargs) -> Optional[dict]:
    client = _get_client()
    url = _url(path)
    try:
        response = await client.request(method, url, **kwargs)

        # Если пришёл редирект — сообщаем явно (не следуем автоматически)
        if response.status_code in (301, 302, 307, 308):
            location = response.headers.get("location", "?")
            logger.error(
                "Панель вернула редирект %d: %s → %s  "
                "(проверь REMNAWAVE_BASE_URL в .env, возможно нужен другой протокол/путь)",
                response.status_code, url, location,
            )
            return None

        response.raise_for_status()
        if response.content:
            return response.json()
        return {}

    except httpx.HTTPStatusError as exc:
        logger.error(
            "HTTP ошибка %s %s: статус=%d тело=%r",
            method, url, exc.response.status_code, exc.response.text[:300],
        )
        return None
    except Exception as exc:
        logger.error("Ошибка запроса %s %s: %s", method, url, exc, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Вспомогательные функции (используются снаружи в handlers)
# ---------------------------------------------------------------------------

def _expire_iso(days: int) -> str:
    """ISO-строка даты истечения через `days` дней от сейчас (UTC)."""
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _days_left(expire_at) -> int:
    """Количество оставшихся дней подписки."""
    if not expire_at:
        return 0
    if isinstance(expire_at, str):
        expire_at = expire_at.replace("Z", "+00:00")
        expire_dt = datetime.fromisoformat(expire_at)
    else:
        expire_dt = expire_at
    if expire_dt.tzinfo is None:
        expire_dt = expire_dt.replace(tzinfo=timezone.utc)
    return max(0, (expire_dt - datetime.now(timezone.utc)).days)


def _extract_sub_link(user: dict) -> str:
    """
    Извлекает ссылку на подписку.
    По Swagger ответ содержит поле subscriptionUrl напрямую в response.
    """
    data = user.get("response", user)

    # Основное поле согласно Swagger
    sub_url = data.get("subscriptionUrl")
    if sub_url:
        return sub_url

    # Запасной вариант через shortUuid
    short_uuid = data.get("shortUuid")
    if short_uuid:
        return f"{config.REMNAWAVE_BASE_URL}/api/sub/{short_uuid}"

    return "Ссылка недоступна"


def _user_data(response: dict) -> dict:
    """Достаёт вложенный объект пользователя из {'response': {...}}."""
    return response.get("response", response) if response else {}


# ---------------------------------------------------------------------------
# Публичные методы
# ---------------------------------------------------------------------------

async def create_user(
    panel_username: str,
    expire_days: int = config.TRIAL_DAYS,
    tg_username: Optional[str] = None,
) -> Optional[dict]:
    """
    Создаёт пользователя в панели.
    Возвращает полный ответ API или None при ошибке.
    """
    description = f"Telegram: @{tg_username}" if tg_username else ""
    payload = {
        "username": panel_username,
        "status": "ACTIVE",
        "trafficLimitBytes": 0,
        "trafficLimitStrategy": "NO_RESET",
        "expireAt": _expire_iso(expire_days),
        "description": description,
        "hwidDeviceLimit": config.HWID_DEVICE_LIMIT,
        "activeInternalSquads": [config.REMNAWAVE_SQUAD_UUID],
    }

    result = await _request("POST", "/api/users", json=payload)
    if result is None:
        return None

    user = _user_data(result)
    logger.info(
        "Пользователь создан: %s (uuid=%s)",
        user.get("username"), user.get("uuid"),
    )
    return result


async def get_user_by_uuid(panel_uuid: str) -> Optional[dict]:
    """Получает пользователя по UUID. Возвращает полный ответ API или None."""
    return await _request("GET", f"/api/users/{panel_uuid}")


async def extend_user_subscription(
    panel_uuid: str,
    days: int = config.SUBSCRIPTION_DAYS,
) -> Optional[dict]:
    """
    Продлевает подписку: если активна — добавляет дни к текущей дате,
    если истекла — считает от сегодня.
    """
    current = await get_user_by_uuid(panel_uuid)
    if current is None:
        return None

    user_data = _user_data(current)
    try:
        expire_str = str(user_data.get("expireAt", "")).replace("Z", "+00:00")
        current_expire = datetime.fromisoformat(expire_str)
        if current_expire.tzinfo is None:
            current_expire = current_expire.replace(tzinfo=timezone.utc)
    except Exception:
        current_expire = datetime.now(timezone.utc)

    base = max(current_expire, datetime.now(timezone.utc))
    new_expire = (base + timedelta(days=days)).isoformat()

    payload = {
        "uuid": panel_uuid,
        "expireAt": new_expire,
        "status": "ACTIVE",
    }

    result = await _request("PATCH", "/api/users", json=payload)
    if result is None:
        return None

    logger.info("Подписка продлена: uuid=%s, новый expireAt=%s", panel_uuid, new_expire)
    return result


async def delete_user(panel_uuid: str) -> bool:
    """Удаляет пользователя. Возвращает True при успехе."""
    result = await _request("DELETE", f"/api/users/{panel_uuid}")
    if result is None:
        return False
    logger.info("Пользователь удалён: uuid=%s", panel_uuid)
    return True


async def close() -> None:
    """Закрывает HTTP-клиент при завершении работы бота."""
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None


__all__ = [
    "create_user",
    "get_user_by_uuid",
    "extend_user_subscription",
    "delete_user",
    "close",
    "_days_left",
    "_extract_sub_link",
    "_user_data",
]