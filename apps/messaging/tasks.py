"""
Messaging Module – Celery Tasks.

A thin async wrapper that runs intent classification + dispatch in a
Celery worker rather than the webhook request handler. This is critical
because:

  * Intent classification involves an LLM call. With long instructions
    and the Anthropic API on a slow day, that can take 30+ seconds.
  * The Node bridge POSTs to /api/messaging/webhook/ with a 90 s axios
    timeout, but a synchronous LLM call there blocks the entire
    webhook worker thread and risks the bridge timing out anyway.
  * If anything in the dispatch chain crashes, doing it async means
    the webhook still responds 200 OK to the bridge — no retries,
    no duplicate processing.

The webhook now does the cheap stuff (auth check, command parsing,
confirmation handling) inline, and pushes anything that needs an LLM
to this task.
"""

import logging

from celery import shared_task

logger = logging.getLogger("etaa")


@shared_task(bind=True, time_limit=300, max_retries=0)
def classify_and_dispatch_task(
    self,
    body: str,
    sender_phone: str,
    operator_name: str,
    reply_jid: str,
):
    """Run intent classification + dispatch in the background.

    Crashes here are logged and reported to the operator on WhatsApp
    instead of bubbling up to Celery's retry machinery (max_retries=0).
    """
    from apps.messaging.dispatcher import dispatch
    from apps.messaging.intent_parser import parse_intent
    from apps.messaging.whatsapp_client import get_wa_client

    try:
        intent = parse_intent(body)
        dispatch(
            intent=intent,
            operator_phone=sender_phone,
            operator_name=operator_name,
            raw_instruction=body,
            reply_jid=reply_jid,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("classify_and_dispatch_task crashed: %s", exc)
        try:
            get_wa_client().send_text(
                f"❌ Could not process your request: {exc}",
                jid=reply_jid or None,
            )
        except Exception:  # noqa: BLE001
            pass