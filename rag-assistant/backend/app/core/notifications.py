import httpx
import time
import logging
from app.config import settings

logger = logging.getLogger(__name__)

_last_alert_time: dict[str, float] = {}

async def notify_admin(alert_type: str, message: str):
    """Send alert via Telegram bot. Cooldown of 10 min per alert type."""
    now = time.time()
    if now - _last_alert_time.get(alert_type, 0) < settings.NOTIFICATION_COOLDOWN_SECONDS:
        logger.debug(f"Alert '{alert_type}' suppressed (cooldown active)")
        return
    _last_alert_time[alert_type] = now
    
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        logger.warning(f"Telegram not configured, alert not sent: {alert_type}: {message}")
        return
    
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": settings.TELEGRAM_CHAT_ID, "text": f"[RAG Assistant] {alert_type}: {message}"},
                timeout=5.0,
            )
        logger.info(f"Admin notified: {alert_type}")
    except Exception as e:
        logger.error(f"Failed to send Telegram notification: {e}")
