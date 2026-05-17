"""Agent Module – Celery Tasks."""

import logging

from celery import shared_task

from apps.logger_module.services import update_log
from apps.messaging.whatsapp_client import get_wa_client

logger = logging.getLogger("etaa")


@shared_task(bind=True, time_limit=900)
def run_agent_task(
    self,
    instruction: str,
    operator_phone: str,
    operator_name: str,
    log_id: int,
    reply_jid: str = "",
    allow_dangerous: bool = False,
):
    """Run a free-form instruction through the dynamic agent loop."""
    from apps.agent.services import execute_instruction

    wa = get_wa_client()
    say = lambda text: wa.send_text(text, jid=reply_jid or None)

    try:
        run = execute_instruction(
            instruction=instruction,
            operator_phone=operator_phone,
            operator_name=operator_name,
            log_id=log_id,
            reply_jid=reply_jid,
            allow_dangerous=allow_dangerous,
        )
        if run.status == "success":
            say(
                f"✅ Done.\n{run.final_answer or '(no summary)'}\n\n"
                f"_Agent run #{run.pk}, {run.iterations} step(s)._"
            )
            update_log(log_id, status="success",
                       output_location=f"agent_run#{run.pk}")
        else:
            say(
                f"❌ Agent task failed: {run.error_detail or 'unknown error'}"
                f"\n_Run #{run.pk}_"
            )
            update_log(log_id, status="failed",
                       error_detail=run.error_detail or "agent failed")
    except Exception as exc:  # noqa: BLE001
        logger.exception("run_agent_task crashed: %s", exc)
        say(f"❌ Agent crashed: {exc}")
        update_log(log_id, status="failed", error_detail=str(exc))
        raise
