"""Email Module – Celery Tasks.

Each task accepts an optional `reply_jid` argument so its WhatsApp
status updates land in the same chat the original instruction came
from (group A's request gets group A's reply, not the default group).
"""

import logging

from celery import shared_task
from django.conf import settings

from apps.email_module.models import EmailRecord
from apps.email_module.services import (
    classify_and_reply,
    fetch_unread_emails,
    load_templates,
    render_template,
    select_template,
    send_email,
)
from apps.logger_module.services import update_log
from apps.messaging.whatsapp_client import get_wa_client

logger = logging.getLogger("etaa")


@shared_task(bind=True, max_retries=2)
def send_email_task(self, params: dict, log_id: int, reply_jid: str = ""):
    """Compose and send an outbound email based on parsed params.

    Routing:
      * If `template_hint` matches a template by keyword AND the params
        contain enough structured data for it (e.g. price/deadline for
        an offer template), use the template + render_template.
      * Otherwise, ask the LLM to compose a complete subject + body
        from `original_instruction`. This avoids the
        "send 'come to office' but get an Acceptance-of-Agreement
        letter" failure mode.
    """
    wa  = get_wa_client()
    say = lambda text: wa.send_text(text, jid=reply_jid or None)

    try:
        recipient = params.get("recipient_email", "")
        if not recipient:
            say("❌ Recipient email address is missing. Please provide it.")
            update_log(log_id, status="failed",
                       error_detail="Missing recipient_email")
            return

        templates    = load_templates()
        hint         = params.get("template_hint", "")
        template     = select_template(hint, templates)
        instruction  = params.get("original_instruction", "")
        recipient_nm = params.get("recipient_name", "")
        sender_nm    = params.get("sender_name", settings.COMPANY_NAME)

        # Decide path: template-based render vs LLM composition.
        #
        # Templates work for SHORT structured requests like
        # "send offer email for website at BDT 50,000". They fail for
        # rich, multi-constraint instructions where the operator wants
        # specific tone, urgency, multiple points covered, etc.
        #
        # We bypass the template (use LLM) when ANY of these hold:
        #   1. No template matched the hint (already None).
        #   2. The operator's instruction is long-form (>200 chars) –
        #      strong signal they're not asking for a boilerplate offer.
        #   3. Structured fields needed by the template are missing.
        #   4. The "structured field" provided is suspiciously long
        #      (>120 chars) – means the intent parser dumped the whole
        #      instruction into offer_details, which would render badly.
        use_template = template is not None
        if use_template:
            # 2. Long-form instruction → LLM
            if instruction and len(instruction) > 200:
                use_template = False

        if use_template:
            looks_offer_like = any(
                k in (template.get("body", "") or "")
                for k in ("{{offer_details}}", "{{price}}", "{{deadline}}")
            )
            structured_fields_provided = any(
                params.get(k) for k in ("offer_details", "price", "deadline")
            )
            # 3. Template needs offer fields but we have none → LLM
            if looks_offer_like and not structured_fields_provided and instruction:
                use_template = False
            # 4. offer_details obviously stuffed with the whole instruction → LLM
            offer_field = (params.get("offer_details") or "").strip()
            if len(offer_field) > 120:
                logger.info(
                    "offer_details length %d > 120 — instruction likely "
                    "stuffed into the field; routing to LLM composer.",
                    len(offer_field),
                )
                use_template = False

        if use_template:
            fields = {
                "recipient_name": recipient_nm,
                "price":          params.get("price", ""),
                "offer_details":  params.get("offer_details", ""),
                "deadline":       params.get("deadline", ""),
                "sender_name":    sender_nm,
            }
            subject, body = render_template(template, fields)
            template_name = template.get("name", "")
        else:
            # LLM-driven composition.
            from apps.email_module.services import compose_email_with_llm
            compose_input = instruction or (
                f"Subject hint: {hint}. Recipient: {recipient_nm}. "
                f"Other context: {params.get('offer_details', '')}"
            )
            subject, body = compose_email_with_llm(
                instruction=compose_input,
                recipient_name=recipient_nm,
                sender_name=sender_nm,
            )
            template_name = "(llm_composed)"

        attachments = params.get("attachments", [])
        # Final safety net before sending: cap subject length, strip
        # newlines. An LLM or a misrendered template could otherwise
        # ship a paragraph-length subject line.
        subject = (subject or "").replace("\n", " ").strip()
        if len(subject) > 120:
            subject = subject[:117] + "…"

        success = send_email(recipient, subject, body, attachments=attachments)

        record = EmailRecord.objects.create(
            direction=EmailRecord.Direction.OUTBOUND,
            to_address=recipient,
            subject=subject,
            body_preview=body[:500],
            template_used=template_name,
            success=success,
        )

        if success:
            say(f"✅ Email sent to *{recipient}*\n📧 Subject: {subject}")
            update_log(log_id, status="success",
                       output_location=f"email_record#{record.pk}")
        else:
            say(f"❌ Failed to send email to {recipient}. Check server logs.")
            update_log(log_id, status="failed",
                       error_detail="SMTP send failed")

    except Exception as exc:  # noqa: BLE001
        logger.error("send_email_task error: %s", exc)
        say(f"❌ Email task failed: {exc}")
        update_log(log_id, status="failed", error_detail=str(exc))
        raise self.retry(exc=exc, countdown=30)


@shared_task(bind=True, max_retries=1)
def process_inbox_task(self, log_id: int, reply_jid: str = ""):
    """Fetch unread emails and auto-reply to each."""
    wa = get_wa_client()
    say = lambda text: wa.send_text(text, jid=reply_jid or None)
    try:
        emails = fetch_unread_emails(limit=20)
        if not emails:
            say("📭 No unread emails found in the inbox.")
            update_log(log_id, status="success")
            return

        replied = 0
        for em in emails:
            reply_body = classify_and_reply(em)
            if reply_body:
                from_raw = em.get("from", "")
                if "<" in from_raw:
                    reply_addr = from_raw.split("<")[1].rstrip(">").strip()
                else:
                    reply_addr = from_raw.strip()

                subject = f"Re: {em.get('subject', '')}"
                ok = send_email(reply_addr, subject, reply_body)
                EmailRecord.objects.create(
                    direction=EmailRecord.Direction.INBOUND_REPLY,
                    to_address=reply_addr,
                    subject=subject,
                    body_preview=reply_body[:500],
                    success=ok,
                )
                if ok:
                    replied += 1

        say(f"✅ Inbox processed: {len(emails)} emails read, "
            f"{replied} auto-replies sent.")
        update_log(log_id, status="success")

    except Exception as exc:  # noqa: BLE001
        logger.error("process_inbox_task error: %s", exc)
        say(f"❌ Inbox processing failed: {exc}")
        update_log(log_id, status="failed", error_detail=str(exc))