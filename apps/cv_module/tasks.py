"""CV Module – Celery Tasks."""

import logging
import os
import tempfile

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from apps.cv_module.models import CVCandidate, CVRankingJob
from apps.cv_module.services import (
    collect_cvs_from_drive,
    collect_cvs_from_local,
    package_results,
    rank_all_cvs,
    upsert_candidate_profile,
)
from apps.logger_module.services import update_log
from apps.messaging.whatsapp_client import get_wa_client

logger = logging.getLogger("etaa")


@shared_task(bind=True, time_limit=900)
def rank_cvs_task(self, params: dict, log_id: int, reply_jid: str = ""):
    """
    Collect CVs, rank them, save Excel to outputs/, upsert CandidateProfiles.

    CHANGED from original:
    - Only sends text score summary via WhatsApp (no file attachments).
    - Excel saved to disk once, not duplicated.
    - No ZIP created or sent.
    - CandidateProfile upserted (dedup by email/phone) for each ranked CV.
    """
    wa = get_wa_client()
    say = lambda text: wa.send_text(text, jid=reply_jid or None)  # noqa: E731

    source          = params.get("source", "local")
    source_path     = params.get("source_path", "")
    requirements    = params.get("job_requirements", "")
    requested_top_n = int(params.get("top_n", 30))

    if not requirements:
        say("❌ Job requirements are missing. Please provide them.")
        update_log(log_id, status="failed", error_detail="Missing job_requirements")
        return

    job = CVRankingJob.objects.create(
        job_requirements=requirements,
        source_type=source,
        source_path=source_path,
        top_n=requested_top_n,
        status="in_progress",
    )

    try:
        say(f"📂 Collecting CVs from {source}…")

        if source == "google_drive":
            tmp_dir = tempfile.mkdtemp(prefix="etaa_cvs_")
            file_paths = collect_cvs_from_drive(source_path, tmp_dir)
        else:
            file_paths = collect_cvs_from_local(source_path)

        if not file_paths:
            say("❌ No CV files found at the specified location.")
            job.status = "failed"
            job.save(update_fields=["status"])
            update_log(log_id, status="failed", error_detail="No CVs found")
            return

        total_cvs    = len(file_paths)
        actual_top_n = min(requested_top_n, total_cvs)

        job.total_cvs = total_cvs
        job.save(update_fields=["total_cvs"])

        say(f"📊 Found {total_cvs} CVs. Starting LLM-based scoring…")
        ranked = rank_all_cvs(file_paths, requirements)

        scored_ok = sum(
            1 for r in ranked
            if r["match_score"] > 0 or r["candidate_name"]
        )

        # ── Persist CVCandidate rows + upsert global CandidateProfiles ───────
        for entry in ranked:
            CVCandidate.objects.create(
                job=job,
                file_name=entry["file_name"],
                candidate_name=entry["candidate_name"],
                match_score=entry["match_score"],
                key_qualifications=entry["key_qualifications"],
                rank=entry["rank"],
                current_designation=entry.get("current_designation", ""),
                current_company=entry.get("current_company", ""),
                years_experience=entry.get("years_experience", 0),
                relevant_industries=entry.get("relevant_industries", ""),
                email=entry.get("email", ""),
                phone=entry.get("phone", ""),
                location=entry.get("location", ""),
                summary=entry.get("summary", ""),
            )
            # Upsert global deduplicated profile
            try:
                upsert_candidate_profile(entry, job)
            except Exception as exc:  # noqa: BLE001
                logger.warning("upsert_candidate_profile failed for %s: %s",
                               entry.get("candidate_name"), exc)

        # ── Save Excel (once, to outputs/) ───────────────────────────────────
        out_dir  = os.path.join(settings.OUTPUT_DIR, "cv_rankings")
        xlsx_path = package_results(
            ranked, actual_top_n, out_dir, job.pk,
            job_requirements=requirements,
        )

        # ── WhatsApp: text-only summary ───────────────────────────────────────
        preview_n = min(10, actual_top_n)
        summary_lines = [
            f"🏆 *Ranking complete – {total_cvs} CV(s) processed.*",
        ]
        if scored_ok < total_cvs:
            summary_lines.append(
                f"_(LLM scored {scored_ok}/{total_cvs}; the rest had "
                "unreadable text or scoring errors.)_"
            )
        summary_lines.append("")
        summary_lines.append(f"*Top {preview_n}:*")

        for r in ranked[:preview_n]:
            name  = r["candidate_name"] or "(name not detected)"
            desig = r.get("current_designation") or ""
            yrs   = r.get("years_experience") or 0
            tail  = []
            if desig:
                tail.append(desig)
            if yrs:
                tail.append(f"{yrs} yrs")
            tail_str = " · ".join(tail)
            line = f"#{r['rank']} {name} — *{r['match_score']}/100*"
            if tail_str:
                line += f"\n   _{tail_str}_"
            summary_lines.append(line)

        summary_lines.append("")
        summary_lines.append(
            f"✅ Excel summary saved to server outputs (Job #{job.pk})."
        )
        say("\n".join(summary_lines))

        job.status     = "success"
        job.output_zip = xlsx_path   # field reused to store xlsx path
        job.completed_at = timezone.now()
        job.save(update_fields=["status", "output_zip", "completed_at"])

        update_log(log_id, status="success", output_location=xlsx_path)

    except Exception as exc:  # noqa: BLE001
        logger.error("rank_cvs_task error: %s", exc)
        say(f"❌ CV ranking failed: {exc}")
        job.status = "failed"
        job.save(update_fields=["status"])
        update_log(log_id, status="failed", error_detail=str(exc))
        raise