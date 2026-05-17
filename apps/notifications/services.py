"""
Notifications Module – Services
Centralised service for sending status updates back to the WhatsApp group.
"""

import logging
from typing import Optional

logger = logging.getLogger("etaa")


def notify(text: str, jid: Optional[str] = None) -> bool:
    """Send a plain-text notification to the WhatsApp group."""
    from apps.messaging.whatsapp_client import get_wa_client
    wa = get_wa_client()
    return wa.send_text(text, jid=jid)


def notify_success(task_type: str, detail: str = "") -> bool:
    msg = f"✅ *{task_type}* completed successfully."
    if detail:
        msg += f"\n{detail}"
    return notify(msg)


def notify_failure(task_type: str, error: str = "") -> bool:
    msg = f"❌ *{task_type}* failed."
    if error:
        msg += f"\nError: {error}"
    return notify(msg)


def notify_progress(task_type: str, step: str) -> bool:
    return notify(f"⏳ *{task_type}*: {step}")
