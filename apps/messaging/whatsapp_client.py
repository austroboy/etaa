"""
WhatsApp Bridge Client.

Talks to the local whatsapp-web.js / Baileys bridge service.

This version prints a token fingerprint at init time and a more
verbose message on 401 errors, so you can see at a glance whether
the Django side and the bridge side disagree on WHATSAPP_API_TOKEN.
"""

import logging
from typing import Optional

import requests
from django.conf import settings

logger = logging.getLogger("etaa")


def _fingerprint(token: str) -> str:
    """Short, log-safe representation of a token for debugging."""
    if not token:
        return "(empty)"
    if len(token) <= 6:
        return f'"{token}" (len={len(token)})'
    return f'"{token[:3]}…{token[-3:]}" (len={len(token)})'


class WhatsAppClient:
    """HTTP client for the local WhatsApp bridge (whatsapp-web.js / Baileys)."""

    def __init__(self):
        self.base_url  = settings.WHATSAPP_BRIDGE_URL.rstrip("/")
        self.token     = settings.WHATSAPP_API_TOKEN
        self.group_jid = settings.WHATSAPP_GROUP_JID
        self.headers   = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type":  "application/json",
        }
        logger.info(
            "WhatsAppClient init | bridge=%s | token fingerprint=%s",
            self.base_url, _fingerprint(self.token),
        )

    # ── Send helpers ────────────────────────────────────────────────────────

    def send_text(self, text: str, jid: Optional[str] = None) -> bool:
        target = jid or self.group_jid
        return self._post("/api/send/text", {"jid": target, "text": text})

    def send_image(self, image_path: str, caption: str = "",
                   jid: Optional[str] = None) -> bool:
        target = jid or self.group_jid
        try:
            with open(image_path, "rb") as f:
                resp = requests.post(
                    f"{self.base_url}/api/send/image",
                    headers={"Authorization": f"Bearer {self.token}"},
                    files={"file": f},
                    data={"jid": target, "caption": caption},
                    timeout=60,
                )
            resp.raise_for_status()
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("WhatsApp send_image failed: %s", exc)
            return False

    def send_file(self, file_path: str, caption: str = "",
                  jid: Optional[str] = None) -> bool:
        target = jid or self.group_jid
        try:
            with open(file_path, "rb") as f:
                resp = requests.post(
                    f"{self.base_url}/api/send/file",
                    headers={"Authorization": f"Bearer {self.token}"},
                    files={"file": f},
                    data={"jid": target, "caption": caption},
                    timeout=120,
                )
            resp.raise_for_status()
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("WhatsApp send_file failed: %s", exc)
            return False

    # ── Private ─────────────────────────────────────────────────────────────

    def _post(self, path: str, payload: dict) -> bool:
        try:
            resp = requests.post(
                f"{self.base_url}{path}",
                json=payload,
                headers=self.headers,
                timeout=30,
            )
            if resp.status_code == 401:
                # The single most common cause of a 401 is a
                # WHATSAPP_API_TOKEN mismatch between Django and the
                # Node bridge. Print the fingerprint of the token we
                # used so the user can compare it against the
                # bridge's "expected=… received=…" log line.
                logger.error(
                    "WhatsApp POST %s -> 401 Unauthorized. "
                    "Django used token fingerprint=%s. "
                    "Compare with the bridge's [ETAA Bridge] 401 log line "
                    "to locate the mismatch.",
                    path, _fingerprint(self.token),
                )
                return False
            resp.raise_for_status()
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("WhatsApp POST %s failed: %s", path, exc)
            return False


_client: Optional[WhatsAppClient] = None


def get_wa_client() -> WhatsAppClient:
    global _client
    if _client is None:
        _client = WhatsAppClient()
    return _client
