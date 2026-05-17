"""
Task Dispatcher.

Routes a parsed intent to the correct handler and manages the
confirmation flow. All WhatsApp responses go to `reply_jid` – the chat
the original instruction came from – so a message issued in group A
gets its confirmation prompt and result delivered back to group A, not
to the default group.
"""

import logging

from apps.confirmation.services import create_confirmation
from apps.logger_module.services import log_action, update_log
from apps.messaging.whatsapp_client import get_wa_client

logger = logging.getLogger("etaa")

# Tasks that always require explicit operator confirmation before execution.
# `dynamic` is added conditionally when the LLM's intent classification
# flags `needs_dangerous_tools=True`.
CONFIRMATION_REQUIRED = {
    "email_outbound",
    "code_gen",   # gated specifically when git_push is requested
    "git_push",
}


def dispatch(
    intent: dict,
    operator_phone: str,
    operator_name: str,
    raw_instruction: str,
    reply_jid: str = "",
) -> None:
    """Route a parsed intent to confirmation or direct execution."""
    task_type = intent.get("task_type", "unknown")
    params    = intent.get("params", {})
    wa        = get_wa_client()

    # Always make the operator's raw instruction available to downstream
    # tasks – the email composer in particular uses it to write a real
    # email instead of falling back to a wrong template.
    if isinstance(params, dict):
        params.setdefault("original_instruction", raw_instruction)
        # Re-pack the intent so confirmation payloads carry the same.
        intent["params"] = params

    if intent.get("is_ambiguous"):
        question = intent.get("clarification_question",
                              "Could you clarify your instruction?")
        wa.send_text(f"❓ {question}", jid=reply_jid or None)
        return

    # Capability question -> show what the bot can do.
    if task_type == "help":
        wa.send_text(_build_help_text(), jid=reply_jid or None)
        return

    # Plain greeting -> friendly reply, no task to log.
    if task_type == "greeting":
        text = params.get("greeting_text") or (
            "👋 Hi! I'm ETAA. I can send emails, rank CVs, create job "
            "posts, generate code, monitor your inbox, and run free-form "
            "multi-step tasks. Type *help* to see what I can do."
        )
        wa.send_text(text, jid=reply_jid or None)
        return

    if task_type == "unknown":
        wa.send_text(
            "⚠️ I'm not sure what you want me to do. "
            "Type *help* to see what I can do, or rephrase your request "
            "as an action (e.g. \"send an email to ...\", \"rank these "
            "CVs ...\", \"find the email thread titled ...\").",
            jid=reply_jid or None,
        )
        return

    log = log_action(
        instruction_text=raw_instruction,
        task_type=task_type,
        status="pending",
        operator_name=operator_name,
        operator_phone=operator_phone,
    )

    needs_confirmation = (
        task_type in CONFIRMATION_REQUIRED
        or (task_type == "code_gen" and params.get("git_push"))
        or (task_type == "dynamic" and params.get("needs_dangerous_tools"))
    )

    if needs_confirmation:
        desc = _describe_action(task_type, params)
        confirmation = create_confirmation(
            task_type=task_type,
            description=desc,
            payload={
                "intent":         intent,
                "log_id":         log.pk,
                "operator_phone": operator_phone,
                "reply_jid":      reply_jid,
            },
            operator_phone=operator_phone,
            operator_name=operator_name,
        )
        wa.send_text(
            f"⚠️ *Confirmation Required* (ID #{confirmation.pk})\n\n"
            f"{desc}\n\n"
            f"Reply *Yes* to confirm or *No* to cancel.",
            jid=reply_jid or None,
        )
    else:
        _execute_task(
            task_type, params, log.pk,
            operator_phone=operator_phone,
            operator_name=operator_name,
            reply_jid=reply_jid,
            allow_dangerous=False,
        )


def dispatch_confirmed(confirmation) -> None:
    """Run a task whose confirmation has just been approved."""
    payload   = confirmation.payload or {}
    intent    = payload.get("intent", {}) or {}
    log_id    = payload.get("log_id")
    op_phone  = payload.get("operator_phone", "")
    reply_jid = payload.get("reply_jid", "")
    task_type = intent.get("task_type", "unknown")
    params    = intent.get("params", {})

    _execute_task(
        task_type, params, log_id,
        operator_phone=op_phone,
        operator_name=confirmation.operator_name,
        reply_jid=reply_jid,
        allow_dangerous=True,  # confirmed -> agent may use sensitive tools
    )


def _execute_task(
    task_type: str,
    params: dict,
    log_id: int,
    operator_phone: str = "",
    operator_name: str = "",
    reply_jid: str = "",
    allow_dangerous: bool = False,
) -> None:
    """Import and fire the appropriate Celery task."""
    wa = get_wa_client()
    try:
        if task_type == "email_outbound":
            from apps.email_module.tasks import send_email_task
            send_email_task.delay(params, log_id, reply_jid)

        elif task_type == "email_inbound_reply":
            from apps.email_module.tasks import process_inbox_task
            process_inbox_task.delay(log_id, reply_jid)

        elif task_type == "cv_ranking":
            from apps.cv_module.tasks import rank_cvs_task
            rank_cvs_task.delay(params, log_id, reply_jid)

        elif task_type == "job_post":
            from apps.job_post_module.tasks import create_job_post_task
            create_job_post_task.delay(params, log_id, reply_jid)

        elif task_type == "code_gen":
            from apps.dev_module.tasks import generate_code_task
            generate_code_task.delay(params, log_id, reply_jid)

        elif task_type == "dynamic":
            # Hand off to the LLM-driven agent loop. It composes tool
            # calls (IMAP search, file zip, WhatsApp send, …) to fulfil
            # arbitrary multi-step instructions.
            from apps.agent.tasks import run_agent_task
            instruction = (params.get("instruction", "")
                           or params.get("raw", ""))
            run_agent_task.delay(
                instruction=instruction,
                operator_phone=operator_phone,
                operator_name=operator_name,
                log_id=log_id,
                reply_jid=reply_jid,
                allow_dangerous=allow_dangerous,
            )

        else:
            wa.send_text(
                f"❓ Unknown task type: {task_type}",
                jid=reply_jid or None,
            )

    except Exception as exc:  # noqa: BLE001
        logger.error("Task dispatch failed for %s: %s", task_type, exc)
        wa.send_text(
            f"❌ Failed to start task `{task_type}`: {exc}",
            jid=reply_jid or None,
        )
        update_log(log_id, status="failed", error_detail=str(exc))


def _describe_action(task_type: str, params: dict) -> str:
    if task_type == "email_outbound":
        instr = params.get("original_instruction", "") or ""
        # Trim very long instructions for the confirmation message.
        if len(instr) > 250:
            instr = instr[:247] + "…"
        lines = [
            f"Send an email to *{params.get('recipient_email', '(unknown)')}*",
            f"Recipient: {params.get('recipient_name', '(not given)')}",
        ]
        if instr:
            lines.append(f"\n_About:_ {instr}")
        return "\n".join(lines)
    if task_type == "code_gen" and params.get("git_push"):
        return (
            f"Generate code and push to Git repository: "
            f"{params.get('repo_url', '(TBD)')}\n"
            f"Tech stack: {params.get('tech_stack', 'django')}"
        )
    if task_type == "dynamic":
        instr = params.get("instruction") or params.get("raw") or ""
        return (
            "Run a multi-step task that may use sensitive tools "
            "(send email, move/delete files, push to git):\n\n"
            f"_{instr[:400]}_"
        )
    return f"Execute task: *{task_type}*"


def _build_help_text() -> str:
    """Capability summary shown in response to 'help' / 'what can you do?'."""
    return (
        "🤖 *ETAA – What I can do*\n"
        "\n"
        "*Specialised pipelines*\n"
        "• 📧 *Send email* – \"Send an offer email to rahim@client.com "
        "for the web project at 50,000 BDT\"\n"
        "• 📥 *Process inbox* – \"Check our inbox and reply to any new emails\"\n"
        "• 📄 *Rank CVs* – \"Rank the CVs in /home/me/cvs against this "
        "job: senior backend engineer, 5+ yrs Django, top 20\"\n"
        "• 📝 *Create job post* – \"Create a job post for a Senior "
        "Software Engineer in the Engineering department\"\n"
        "• 💻 *Generate code* – \"Generate a Django project from this SRS\"\n"
        "\n"
        "*Free-form multi-step tasks* (the dynamic agent figures it out)\n"
        "• \"Find the email thread titled 'Q2 Hiring' and download every "
        "CV attachment to ~/hires/, then zip them up\"\n"
        "• \"Search my drive for last quarter's report and send it to "
        "alice@example.com\"\n"
        "• \"List the files in /tmp/cvs and tell me which ones are PDFs\"\n"
        "\n"
        "*Group access management* (only the 3 core operators)\n"
        "• `authorize +880 1xxxxxxxxx` – give a group member access\n"
        "• `revoke +880 1xxxxxxxxx` – remove their access\n"
        "• `show authorized members` – list delegated members\n"
        "\n"
        "*Confirmation*\n"
        "Sensitive actions (sending email, pushing code, deleting "
        "files) ask for *Yes* / *No* before running.\n"
        "\n"
        "_Just describe what you want in plain language – I'll work "
        "out how to do it._"
    )