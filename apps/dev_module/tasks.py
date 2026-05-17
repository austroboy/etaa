"""Dev Module – Celery Tasks."""

import logging
import os
import zipfile

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from apps.dev_module.models import CodeGenerationJob
from apps.dev_module.services import analyze_srs, generate_project, git_push
from apps.logger_module.services import update_log
from apps.messaging.whatsapp_client import get_wa_client

logger = logging.getLogger("etaa")


@shared_task(bind=True, time_limit=1200)
def generate_code_task(self, params: dict, log_id: int, reply_jid: str = ""):
    """Analyze SRS, generate full project, optionally push to Git."""
    wa = get_wa_client()
    say       = lambda text: wa.send_text(text, jid=reply_jid or None)
    send_file = lambda path, caption="": wa.send_file(
        path, caption=caption, jid=reply_jid or None,
    )

    srs_text      = params.get("srs_text", "")
    srs_file_path = params.get("srs_file_path", "")
    tech_stack    = params.get("tech_stack", "django")
    do_git_push   = params.get("git_push", False)
    repo_url      = params.get("repo_url", "")

    if not srs_text and srs_file_path:
        try:
            if srs_file_path.endswith(".pdf"):
                from pypdf import PdfReader
                reader = PdfReader(srs_file_path)
                srs_text = "\n".join(p.extract_text() or "" for p in reader.pages)
            else:
                import docx2txt
                srs_text = docx2txt.process(srs_file_path)
        except Exception as exc:  # noqa: BLE001
            say(f"❌ Could not read SRS file: {exc}")
            update_log(log_id, status="failed", error_detail=str(exc))
            return

    if not srs_text:
        say("❌ No SRS content provided. Please attach an SRS file or "
            "paste the text.")
        update_log(log_id, status="failed", error_detail="No SRS text")
        return

    job = CodeGenerationJob.objects.create(
        srs_text=srs_text[:5000],
        tech_stack=tech_stack,
        status="in_progress",
        repo_url=repo_url,
    )

    try:
        say("🔍 Analyzing SRS document…")
        plan = analyze_srs(srs_text)
        project_name = plan.get("project_name", "generated_project")

        say(
            f"📐 Plan ready!\n"
            f"Project: *{project_name}*\n"
            f"Apps: {', '.join(a['name'] for a in plan.get('apps', []))}\n"
            f"Stack: {tech_stack}\n\n"
            f"⚙️ Generating code (this may take several minutes)…"
        )

        out_base = os.path.join(settings.CODE_OUT_DIR)
        os.makedirs(out_base, exist_ok=True)
        project_dir = generate_project(plan, srs_text, out_base, tech_stack)

        zip_path = project_dir + ".zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(project_dir):
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for file in files:
                    fp = os.path.join(root, file)
                    arcname = os.path.relpath(fp, out_base)
                    zf.write(fp, arcname)

        job.output_dir = project_dir
        job.status = "success"
        job.completed_at = timezone.now()
        job.save(update_fields=["output_dir", "status", "completed_at"])

        say(
            f"✅ Code generation complete!\n"
            f"📁 Project: `{project_name}`\n"
            f"📦 Sending ZIP archive…"
        )
        send_file(zip_path, caption=f"Generated project: {project_name}.zip")

        update_log(log_id, status="success", output_location=project_dir)

        if do_git_push and repo_url:
            say(f"🚀 Pushing to Git repository: {repo_url}…")
            ssh_key = settings.GIT_SSH_KEY_PATH
            success = git_push(project_dir, repo_url, ssh_key_path=ssh_key)
            if success:
                job.git_pushed = True
                job.save(update_fields=["git_pushed"])
                say(f"✅ Code pushed to {repo_url}")
            else:
                say("⚠️ Git push failed. Check server logs and "
                    "repository credentials.")

    except Exception as exc:  # noqa: BLE001
        logger.error("generate_code_task error: %s", exc)
        say(f"❌ Code generation failed: {exc}")
        job.status = "failed"
        job.error_detail = str(exc)
        job.save(update_fields=["status", "error_detail"])
        update_log(log_id, status="failed", error_detail=str(exc))
        raise
