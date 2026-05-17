"""Job Post Module – Celery Tasks.

Flow:
  1. Operator: "etaa, create a job post for <role> ..."
  2. Intent parser → job_post task type
  3. This task:
       a. Generate full job description (LLM)
       b. Send a TEXT summary to WhatsApp (no attachments)
       c. Render the branded poster JPG via poster.generate_job_poster
       d. Save to outputs/job_posts/<title>.jpg
       e. Tell the operator the file path — they open it locally
          and post to LinkedIn / Facebook themselves.

  No image is sent through WhatsApp. The poster module's output
  belongs on a desktop where it can be uploaded to social channels.
"""

import logging
import os
import re

from celery import shared_task
from django.conf import settings

from apps.job_post_module.models import JobPost
from apps.job_post_module.services import generate_job_description
from apps.logger_module.services import update_log
from apps.messaging.whatsapp_client import get_wa_client

logger = logging.getLogger("etaa")


def _html_to_plain(html: str) -> str:
    """Strip HTML tags to produce plain text for WhatsApp."""
    return re.sub(r"<[^>]+>", "", html or "").strip()


def _infer_job_title_from_text(text: str) -> str:
    """Pick a plausible job title from a free-form instruction.

    Fallback when the intent parser fails to set job_title despite
    being told in the schema to always do so. Looks for common
    "Position:" / "Role:" headers and capitalised role-noun phrases.
    """
    text = (text or "").strip()
    if not text:
        return ""

    patterns = [
        r"position\s*[:\-]\s*([^\n.]+)",
        r"role\s*[:\-]\s*([^\n.]+)",
        r"job\s*title\s*[:\-]\s*([^\n.]+)",
        r"hiring\s+(?:a\s+|an\s+)?([A-Z][\w &/\-]+(?:Manager|Officer|Executive|Lead|Engineer|Specialist|Director|Head))",
        r"(?:create|make|design)[\w\s]*(?:post|design|poster)[\w\s]*for\s+(?:the\s+)?(?:position\s+of\s+)?([A-Z][\w &/\-]+(?:Manager|Officer|Executive|Lead|Engineer|Specialist|Director|Head))",
    ]
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            title = m.group(1).strip().rstrip(":,.").strip()
            if 3 <= len(title) <= 80:
                return title
    return ""


@shared_task(bind=True, time_limit=300)
def create_job_post_task(self, params: dict, log_id: int, reply_jid: str = ""):
    """Generate job description text + branded poster image."""
    wa = get_wa_client()
    say = lambda text: wa.send_text(text, jid=reply_jid or None)

    job_title        = (params.get("job_title") or "").strip()
    department       = params.get("department", "")
    responsibilities = params.get("responsibilities", "")
    qualifications   = params.get("qualifications", "")
    salary_range     = params.get("salary_range", "")
    company_info     = params.get("company_info", "") or settings.COMPANY_NAME
    tagline          = params.get("tagline", "")
    location         = params.get("location", "Dhaka, Bangladesh")
    deadline         = params.get("deadline", "Open until filled")

    # If intent parser failed to set the title, try to infer it.
    if not job_title:
        instr = params.get("original_instruction", "")
        if instr:
            job_title = _infer_job_title_from_text(instr)
        if not job_title:
            say("❌ I couldn't determine the job title from your message. "
                "Please include the role name (e.g. 'Modern Trade Manager').")
            update_log(log_id, status="failed",
                       error_detail="Missing job_title")
            return

    post = JobPost.objects.create(
        job_title=job_title, department=department, status="in_progress",
    )

    try:
        say(f"📝 Generating job description for *{job_title}*…")

        html_desc = generate_job_description(
            job_title=job_title,
            department=department,
            responsibilities=responsibilities,
            qualifications=qualifications,
            salary_range=salary_range,
            company_info=company_info,
        )
        plain_desc = _html_to_plain(html_desc)
        post.description_text = html_desc
        post.save(update_fields=["description_text"])

        say(f"📋 *Job Description: {job_title}*\n\n{plain_desc[:2500]}")

        # ── Poster generation ───────────────────────────────────────
        say("🎨 Designing the recruitment poster…")
        from apps.job_post_module.poster import generate_job_poster
        jpg_path = generate_job_poster(
            job_title=job_title,
            company_name=company_info,
            requirements_text=qualifications,
            responsibilities_text=responsibilities,
            tagline=tagline,
            salary=salary_range or "Negotiable",
            location=location,
            deadline=deadline,
        )
        post.jpg_path = jpg_path or ""
        post.save(update_fields=["jpg_path"])

        # Don't send the image through WhatsApp — just tell the user
        # where it is.
        if jpg_path and os.path.isfile(jpg_path):
            try:
                rel_path = os.path.relpath(jpg_path, str(settings.BASE_DIR))
            except Exception:  # noqa: BLE001
                rel_path = jpg_path
            say(
                "✅ Poster ready!\n"
                f"📁 Saved to: `{rel_path}`\n\n"
                "Open it from your project folder and post to LinkedIn, "
                "Facebook, and your hiring groups along with the text above."
            )
        else:
            say("⚠️ Job description is ready, but the poster image could "
                "not be generated (see Celery log for the error).")

        post.status = "success"
        post.save(update_fields=["status"])
        update_log(log_id, status="success",
                   output_location=jpg_path or "text_only")

    except Exception as exc:  # noqa: BLE001
        logger.error("create_job_post_task error: %s", exc)
        say(f"❌ Job post creation failed: {exc}")
        post.status = "failed"
        post.save(update_fields=["status"])
        update_log(log_id, status="failed", error_detail=str(exc))
        raise