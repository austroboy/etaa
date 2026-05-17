"""
Email Module – Services
Handles outbound email composition/delivery and inbound email monitoring.
"""

import imaplib
import json
import logging
import os
import smtplib
from email import message_from_bytes
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import List, Optional

from django.conf import settings

from apps.llm_client import get_llm_client

logger = logging.getLogger("etaa")

# ── Template helpers ──────────────────────────────────────────────────────────


def load_templates() -> dict:
    """Load all email templates from the EMAIL_TEMPLATES_DIR directory."""
    tmpl_dir = Path(settings.EMAIL_TEMPLATES_DIR)
    templates = {}
    if not tmpl_dir.exists():
        logger.warning("Email templates directory not found: %s", tmpl_dir)
        return templates

    for f in tmpl_dir.glob("*.json"):
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
            templates[f.stem] = data
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to load template %s: %s", f, exc)
    return templates


def select_template(hint: str, templates: dict) -> Optional[dict]:
    """Choose the best matching template based on a keyword hint.

    Returns the matching template, or None if NO keyword matches.
    Caller decides what to do on no-match (e.g. fall back to LLM
    composition rather than blindly sending the wrong template).
    """
    hint_lower = (hint or "").lower()
    if not hint_lower:
        return None
    for name, tmpl in templates.items():
        if any(kw in hint_lower for kw in tmpl.get("keywords", [])):
            return tmpl
    return None


def render_template(template: dict, fields: dict) -> tuple[str, str]:
    """
    Substitute placeholders in template subject and body.

    Supports two syntaxes the existing JSON templates use:
      * ``{{ key }}`` simple substitution; blank if missing.
      * ``{% if key %}...{% endif %}`` conditional block; the entire
        block is dropped if `key` is empty/missing, otherwise the
        markers are stripped and the inner content is kept.

    Unfilled tokens are stripped so junk like ``Agreed Amount: BDT``
    never reaches the recipient.
    Returns (subject, html_body).
    """
    import re as _re

    subject = template.get("subject", "") or ""
    body    = template.get("body", "")    or ""

    values = dict(fields or {})
    values.setdefault("company_name", settings.COMPANY_NAME)

    def _has_value(key: str) -> bool:
        v = values.get(key)
        if v is None:
            return False
        if isinstance(v, str) and not v.strip():
            return False
        return True

    # 1. Resolve {% if KEY %}...{% endif %} blocks.
    if_block_re = _re.compile(
        r"\{%\s*if\s+(\w+)\s*%\}(.*?)\{%\s*endif\s*%\}",
        _re.DOTALL,
    )

    def _resolve_if(match):
        key, inner = match.group(1), match.group(2)
        return inner if _has_value(key) else ""

    subject = if_block_re.sub(_resolve_if, subject)
    body    = if_block_re.sub(_resolve_if, body)

    # 2. Substitute {{key}} (also tolerate {{ key }} with whitespace).
    spaced_re = _re.compile(r"\{\{\s*(\w+)\s*\}\}")

    def _resolve_var(match):
        key = match.group(1)
        v = values.get(key)
        return str(v) if v not in (None, "") else ""

    subject = spaced_re.sub(_resolve_var, subject)
    body    = spaced_re.sub(_resolve_var, body)

    # 3. Tidy artefacts: orphan label lines (e.g. "Agreed Amount: BDT"
    #    with no value), and triple-blank lines.
    body = _re.sub(r"^\s*[\w\s]+:\s*BDT\s*$", "", body, flags=_re.MULTILINE)
    body = _re.sub(r"\n{3,}", "\n\n", body)

    return subject.strip(), body.strip()


def compose_email_with_llm(
    instruction: str,
    recipient_name: str = "",
    sender_name: str = "",
) -> tuple[str, str]:
    """
    Use the LLM to write a complete subject + HTML body from the
    operator's natural-language instruction. Used when no template
    keyword matches — much better than silently sending the first
    template's wording.

    Returns (subject, html_body). Never raises – falls back to a
    simple plain-paragraph email on any LLM error.
    """
    sender  = sender_name or settings.COMPANY_NAME
    company = settings.COMPANY_NAME

    system = (
        f"You are a professional business correspondence writer at {company}. "
        "Write polite, well-structured business emails in British English.\n\n"
        "RESPECT THE OPERATOR'S DIRECTIVES PRECISELY. The operator may "
        "specify any of: TONE (formal/casual/urgent/collaborative), "
        "LENGTH (concise/detailed), CONSTRAINTS (must include X, must "
        "not include Y, deadline-driven), STRUCTURE (bullet points, "
        "specific sections), ATTACHMENTS (real or placeholders like "
        "[Link]). Follow these exactly. Cover every point they ask "
        "for. Skip every point they don't.\n\n"
        "TONE GUIDANCE:\n"
        "  • Internal summons (\"come to the office today\") → brief, direct, 2-3 lines\n"
        "  • Negotiation / counter-proposal → diplomatic but firm, lead with appreciation, then the ask\n"
        "  • Status update → factual, structured, no fluff\n"
        "  • Thank-you / acknowledgement → warm, specific\n"
        "  • Quotation request → polite, specific about quantities/specs\n"
        "  • Reminder → friendly first time, firmer if escalating\n\n"
        "RULES:\n"
        "  • Do NOT add boilerplate phrases like \"Thank you for your "
        "interest in our services\" unless the instruction actually "
        "warrants them.\n"
        "  • Do NOT recycle generic offer-letter language for non-offer emails.\n"
        "  • Subject line must be specific to the actual content (NOT "
        "the entire instruction text — a real subject line is 5–12 words).\n"
        "  • Use <p> tags for paragraphs, <ul><li> for bullet lists, "
        "<strong> for emphasis. No Markdown. No <html> or <body> wrapper.\n"
        "  • Sign off as " + sender + ".\n"
        "  • If the operator mentions an attachment placeholder like "
        "\"[Link]\" or \"[file]\", include it verbatim where they "
        "indicated; do not invent a URL.\n\n"
        "OUTPUT FORMAT:\n"
        "Return ONLY a JSON object with EXACTLY these two keys:\n"
        "  - subject: 5–12 word subject line, specific to the content.\n"
        "  - body:    well-formed HTML email body (paragraphs, optional bullets).\n"
        "No preamble, no Markdown fences, no explanation."
    )
    user_prompt = (
        f"Recipient: {recipient_name or '(not specified — use a polite generic salutation like \"Hello team,\" or \"Dear Sir/Madam,\")'}\n"
        f"Sender / company: {company}\n\n"
        f"Operator's instruction (follow it precisely):\n{instruction}"
    )

    try:
        raw = get_llm_client().complete(
            user_prompt, system=system,
            max_tokens=1200, temperature=0.4,
        )
        import json as _json
        data = _json.loads(raw)
        subject = (data.get("subject") or "").strip()
        body    = (data.get("body") or "").strip()
        if not subject or not body:
            raise ValueError("LLM returned empty subject or body")
        # Hard safety net: an LLM that ignored the prompt could return
        # a paragraph as the "subject". Cap it at 120 chars and strip
        # any newlines so we never ship a giant subject line.
        subject = subject.replace("\n", " ").strip()
        if len(subject) > 120:
            subject = subject[:117] + "…"
        html_body = (
            "<div style=\"font-family: Arial, sans-serif; color: #333; "
            "max-width: 620px; line-height: 1.5;\">"
            f"{body}</div>"
        )
        return subject, html_body
    except Exception as exc:  # noqa: BLE001
        logger.error("compose_email_with_llm failed: %s", exc)
        salutation = f"Dear {recipient_name}," if recipient_name else "Dear Sir/Madam,"
        body = (
            f"<p>{salutation}</p>"
            f"<p>{instruction}</p>"
            f"<p>Kind regards,<br>{sender}<br>{company}</p>"
        )
        return f"Message from {company}", body


# ── Sending ───────────────────────────────────────────────────────────────────


def send_email(
    to_address: str,
    subject: str,
    body: str,
    attachments: Optional[List[str]] = None,
    cc: Optional[List[str]] = None,
) -> bool:
    """Send an email via SMTP. Returns True on success."""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = settings.DEFAULT_FROM_EMAIL
        msg["To"]      = to_address
        if cc:
            msg["Cc"] = ", ".join(cc)

        msg.attach(MIMEText(body, "html"))

        if attachments:
            for path in attachments:
                if os.path.isfile(path):
                    with open(path, "rb") as f:
                        part = MIMEApplication(f.read(), Name=os.path.basename(path))
                    part["Content-Disposition"] = f'attachment; filename="{os.path.basename(path)}"'
                    msg.attach(part)

        all_recipients = [to_address] + (cc or [])

        with smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
            server.sendmail(settings.DEFAULT_FROM_EMAIL, all_recipients, msg.as_string())

        logger.info("Email sent to %s | subject: %s", to_address, subject)
        return True

    except Exception as exc:  # noqa: BLE001
        logger.error("Email send failed to %s: %s", to_address, exc)
        return False


# ── Inbound monitoring ────────────────────────────────────────────────────────


def fetch_unread_emails(limit: int = 20) -> list:
    """Connect via IMAP and fetch unread messages. Returns list of email dicts."""
    emails = []
    try:
        mail = imaplib.IMAP4_SSL(settings.IMAP_HOST, settings.IMAP_PORT)
        mail.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
        mail.select("inbox")

        _, data = mail.search(None, "UNSEEN")
        msg_ids = data[0].split()[-limit:]  # take at most `limit` unread

        for mid in msg_ids:
            _, raw = mail.fetch(mid, "(RFC822)")
            msg = message_from_bytes(raw[0][1])
            body = _extract_body(msg)
            emails.append({
                "id": mid.decode(),
                "from": msg.get("From", ""),
                "subject": msg.get("Subject", ""),
                "body": body,
            })
        mail.logout()
    except Exception as exc:  # noqa: BLE001
        logger.error("IMAP fetch failed: %s", exc)
    return emails


def _extract_body(msg) -> str:
    """Extract plain text body from an email message."""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain":
                return part.get_payload(decode=True).decode(errors="replace")
    else:
        return msg.get_payload(decode=True).decode(errors="replace")
    return ""


def classify_and_reply(email_dict: dict) -> Optional[str]:
    """
    Use LLM to classify an inbound email and generate a professional reply.
    Returns the reply body string, or None if no reply needed.
    """
    llm = get_llm_client()
    prompt = f"""You are the email assistant for {settings.COMPANY_NAME}.
Analyze the following incoming email and produce a professional, formal reply.
If the email is an offer acceptance (e.g. "We will proceed at X BDT"), write a formal acceptance confirmation.
If it is an inquiry, write a helpful response. If it is a complaint, write an empathetic resolution response.

Return ONLY the reply email body (HTML), nothing else.

From: {email_dict['from']}
Subject: {email_dict['subject']}

Body:
{email_dict['body'][:3000]}
"""
    try:
        reply = llm.complete(prompt, max_tokens=1500)
        return reply
    except Exception as exc:  # noqa: BLE001
        logger.error("LLM reply generation failed: %s", exc)
        return None