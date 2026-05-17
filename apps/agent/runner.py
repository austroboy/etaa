"""
Agent Module – Runner.

Implements the core agent loop: an LLM is given the operator's free-form
instruction and the registered tool catalogue, and decides – iteratively –
which tools to call until the task is done.

Two LLM backends are supported (matching the rest of ETAA):
  * OpenAI's function-calling
  * Anthropic's tool-use

The provider is chosen from settings.PRIMARY_LLM_PROVIDER with automatic
failover to the other if the primary errors.

The current operator's reply JID is stored in a contextvar so that
tools like `send_whatsapp_text` can route their output back to the
right chat without every tool signature having to carry it.
"""

from __future__ import annotations

import contextvars
import json
import logging
from typing import Optional

from django.conf import settings
from django.utils import timezone

from apps.agent.models import AgentRun, AgentRunStatus, AgentStep
from apps.agent.tools import (
    call_tool,
    get_tool_schemas,
    get_tool_schemas_anthropic,
    is_dangerous,
)

logger = logging.getLogger("etaa")


# Context variable that tools can read to find the JID to reply to.
# Set by run_agent() at the start of each run.
current_reply_jid: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_reply_jid", default=""
)


SYSTEM_PROMPT = """You are Robi, ETAA's intelligent enterprise automation agent. You work for a Bangladesh-based company and serve authorised operators via WhatsApp. You are highly capable, proactive, and complete tasks end-to-end like a skilled human assistant would.

═══════════════════════════════════════════
CORE BEHAVIOUR
═══════════════════════════════════════════

1. PLAN THEN ACT. Think step-by-step before calling any tool. Announce your plan briefly via send_whatsapp_text before starting long tasks.

2. NEVER ASK FOR INFORMATION YOU CAN INFER. If a job title is given (e.g. "Senior Executive", "Regional Sales Manager", "Business Development Manager"), infer reasonable job requirements yourself based on the title and industry context. Do NOT ask the operator to repeat information they already gave. Do NOT ask for clarification unless the instruction is truly impossible to execute without it.

3. USE THE MOST SPECIFIC TOOL. Prefer rank_cvs for CV tasks, search_email_threads for email tasks. Use filesystem tools for everything else.

4. COMPLETE THE FULL TASK. Do not stop halfway. If the operator says "rank CVs and send results", do ALL of: rank → send WhatsApp summary → send Excel file → send ZIP.

5. KEEP THE OPERATOR UPDATED. For tasks taking more than 30 seconds, send progress updates via send_whatsapp_text (e.g. "📊 Found 45 CVs. Scoring now — this will take ~2 minutes…").

6. SENSITIVE OPERATIONS need confirmation. If a tool returns an error saying confirmation is required, ask the operator via send_whatsapp_text, then call finish.

7. ALWAYS call finish when done. Pass a one-line summary of what was accomplished.

═══════════════════════════════════════════
CV RANKING — DETAILED RULES
═══════════════════════════════════════════

When asked to rank, shortlist, or evaluate CVs:

A) INFER JOB REQUIREMENTS if not provided. Based on the job title, generate a comprehensive requirement string covering: key responsibilities, required experience level, relevant industries, skills, and qualifications. Examples:

   "Senior Executive" →
   "Position: Senior Executive. Requirements: 5+ years experience in relevant field, strong leadership and communication skills, proven track record of target achievement, ability to manage teams and client relationships, MBA or relevant degree preferred."

   "Regional Sales Manager" →
   "Position: Regional Sales Manager. Requirements: 7+ years sales experience, experience managing regional territory, B2B sales background, experience in FMCG/paint/cement/steel/ceramics/electronics industries preferred, strong negotiation and team leadership skills, Bachelor's degree minimum."

   "Business Development Manager" →
   "Position: Business Development Manager. Requirements: 5+ years in business development or sales, experience identifying new market opportunities, client acquisition and relationship management, strong analytical and presentation skills, MBA preferred, experience in relevant industry."

B) ALWAYS send the WhatsApp ranking summary FIRST (top 10 inline with scores).

C) THEN send the Excel file separately (directly openable, not just inside ZIP).

D) THEN send the ZIP containing all shortlisted CV files.

E) File naming in WhatsApp messages: mention job title and number shortlisted.

F) If the CV directory path has spaces or special characters, use it exactly as given — do not modify the path.

G) top_n defaults to 30 unless the operator specifies a number (e.g. "shortlist 25" → top_n=25).

═══════════════════════════════════════════
EMAIL TASKS — RULES
═══════════════════════════════════════════

When asked to search, read, or act on emails:
- Use search_email_threads with relevant keywords.
- Summarise findings clearly via send_whatsapp_text.
- If asked to send an email, use send_email. Always confirm recipient and subject before sending (sensitive operation).
- If asked to download attachments, use download_attachments_from_thread.

═══════════════════════════════════════════
GOOGLE DRIVE TASKS — RULES
═══════════════════════════════════════════

When CVs or files are on Google Drive:
- Use download_from_google_drive first to download to a local temp directory.
- Then proceed with local tools (rank_cvs, list_directory, etc.).
- Report how many files were downloaded before proceeding.

═══════════════════════════════════════════
GENERAL FILE TASKS — RULES
═══════════════════════════════════════════

- Use list_directory to explore paths before acting on them.
- Use zip_files when the operator asks to bundle files.
- Use send_whatsapp_file to deliver files to the operator.
- Paths with parentheses, spaces, or Bengali characters: pass them EXACTLY as given.

═══════════════════════════════════════════
TONE & LANGUAGE
═══════════════════════════════════════════

- Respond in the same language the operator uses (Bengali or English).
- Use emojis appropriately for status updates (⏳ processing, ✅ done, ❌ error, 📊 data, 📦 file).
- Be concise but informative. Never leave the operator wondering what is happening.
- Never say "I cannot do that" for tasks within your tool capabilities. Find a way.

═══════════════════════════════════════════
AVAILABLE CAPABILITIES SUMMARY
═══════════════════════════════════════════

You can:
✅ Rank and shortlist CVs from local folders or Google Drive
✅ Search and read emails (IMAP)
✅ Send emails
✅ Send WhatsApp messages and files
✅ Browse and manage local filesystem
✅ Download files from Google Drive
✅ Create ZIP archives
✅ Deliver Excel + ZIP output files to the operator

You CANNOT (require operator confirmation):
⚠️  Send emails (confirm recipient first)
⚠️  Delete or move files
⚠️  Any irreversible action"""


MAX_ITERATIONS = 25
MAX_TOOL_OUTPUT_LEN = 4000


def _truncate_for_llm(value) -> str:
    s = json.dumps(value, default=str)
    if len(s) > MAX_TOOL_OUTPUT_LEN:
        s = s[:MAX_TOOL_OUTPUT_LEN] + f"... [truncated, {len(s)} chars total]"
    return s


def run_agent(
    instruction: str,
    operator_phone: str = "",
    operator_name: str = "",
    log_id: Optional[int] = None,
    reply_jid: str = "",
    allow_dangerous: bool = False,
) -> AgentRun:
    """Drive the agent loop to completion (or failure) and return the run."""
    run = AgentRun.objects.create(
        instruction=instruction,
        operator_phone=operator_phone,
        operator_name=operator_name,
        status=AgentRunStatus.RUNNING,
        log_id=log_id,
    )

    token = current_reply_jid.set(reply_jid)
    try:
        provider = settings.PRIMARY_LLM_PROVIDER
        try:
            if provider == "anthropic":
                _run_anthropic_loop(run, instruction, allow_dangerous)
            else:
                _run_openai_loop(run, instruction, allow_dangerous)
        except Exception as exc:  # noqa: BLE001
            # Decide whether to attempt failover to the other provider.
            # Skip if the other provider has no API key configured —
            # otherwise the user just gets two stack traces.
            other_provider = "openai" if provider == "anthropic" else "anthropic"
            other_key = (settings.OPENAI_API_KEY if other_provider == "openai"
                         else settings.ANTHROPIC_API_KEY)

            if not other_key:
                logger.error(
                    "Primary LLM (%s) failed: %s. Fallback (%s) has no "
                    "API key configured – aborting.",
                    provider, exc, other_provider,
                )
                run.status = AgentRunStatus.FAILED
                run.error_detail = (
                    f"{provider} failed: {exc}. "
                    f"Fallback {other_provider.upper()}_API_KEY is not "
                    "configured in .env, so no fallback was attempted."
                )
            else:
                logger.warning(
                    "Primary LLM (%s) failed: %s. Trying %s fallback.",
                    provider, exc, other_provider,
                )
                try:
                    if other_provider == "anthropic":
                        _run_anthropic_loop(run, instruction, allow_dangerous)
                    else:
                        _run_openai_loop(run, instruction, allow_dangerous)
                except Exception as exc2:  # noqa: BLE001
                    logger.exception("Both LLM providers failed.")
                    run.status = AgentRunStatus.FAILED
                    run.error_detail = (
                        f"primary ({provider}): {exc}; "
                        f"fallback ({other_provider}): {exc2}"
                    )
    finally:
        current_reply_jid.reset(token)
        run.completed_at = timezone.now()
        run.save()
    return run


# ─── OpenAI function-calling loop ────────────────────────────────────────────


def _run_openai_loop(run: AgentRun, instruction: str, allow_dangerous: bool):
    import openai

    from apps.llm_client import LLMClient

    client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
    tools = get_tool_schemas()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": instruction},
    ]

    for step_no in range(1, MAX_ITERATIONS + 1):
        run.iterations = step_no
        run.save(update_fields=["iterations"])

        response = client.chat.completions.create(
            model=LLMClient.OPENAI_MODEL,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.2,
        )
        msg = response.choices[0].message

        if not msg.tool_calls:
            run.final_answer = msg.content or ""
            run.status = AgentRunStatus.SUCCESS
            return

        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name":      tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ],
        })

        for tc in msg.tool_calls:
            tool_name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            if is_dangerous(tool_name) and not allow_dangerous:
                tool_result = {
                    "ok": False,
                    "error": f"Tool '{tool_name}' is sensitive and requires "
                             "operator confirmation. Ask the operator on "
                             "WhatsApp before retrying.",
                }
            else:
                tool_result = call_tool(tool_name, args)

            AgentStep.objects.create(
                run=run, step_number=step_no, tool_name=tool_name,
                tool_input=args, tool_output=tool_result,
                success=bool(tool_result.get("ok", False)),
                error=tool_result.get("error", "") or "",
            )

            messages.append({
                "role":         "tool",
                "tool_call_id": tc.id,
                "content":      _truncate_for_llm(tool_result),
            })

            if tool_name == "finish":
                run.final_answer = tool_result.get("summary", "")
                run.status = AgentRunStatus.SUCCESS
                return

    run.status = AgentRunStatus.FAILED
    run.error_detail = f"Agent exceeded MAX_ITERATIONS ({MAX_ITERATIONS})"


# ─── Anthropic tool-use loop ─────────────────────────────────────────────────


def _run_anthropic_loop(run: AgentRun, instruction: str, allow_dangerous: bool):
    import anthropic

    from apps.llm_client import LLMClient

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    tools = get_tool_schemas_anthropic()

    messages = [{"role": "user", "content": instruction}]

    for step_no in range(1, MAX_ITERATIONS + 1):
        run.iterations = step_no
        run.save(update_fields=["iterations"])

        response = client.messages.create(
            model=LLMClient.ANTHROPIC_MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=tools,
            temperature=0.2,
        )

        assistant_blocks = response.content
        messages.append({"role": "assistant", "content": assistant_blocks})

        tool_uses = [b for b in assistant_blocks
                     if getattr(b, "type", "") == "tool_use"]

        if not tool_uses:
            text_blocks = [b for b in assistant_blocks
                           if getattr(b, "type", "") == "text"]
            run.final_answer = "\n".join(getattr(b, "text", "")
                                         for b in text_blocks)
            run.status = AgentRunStatus.SUCCESS
            return

        tool_results_msg_content = []
        finished = False
        finish_summary = ""

        for tu in tool_uses:
            tool_name = tu.name
            args = tu.input or {}

            if is_dangerous(tool_name) and not allow_dangerous:
                result = {
                    "ok": False,
                    "error": f"Tool '{tool_name}' is sensitive and requires "
                             "operator confirmation.",
                }
            else:
                result = call_tool(tool_name, args)

            AgentStep.objects.create(
                run=run, step_number=step_no, tool_name=tool_name,
                tool_input=args, tool_output=result,
                success=bool(result.get("ok", False)),
                error=result.get("error", "") or "",
            )

            tool_results_msg_content.append({
                "type":         "tool_result",
                "tool_use_id":  tu.id,
                "content":      _truncate_for_llm(result),
            })

            if tool_name == "finish":
                finished = True
                finish_summary = result.get("summary", "")

        messages.append({"role": "user", "content": tool_results_msg_content})

        if finished:
            run.final_answer = finish_summary
            run.status = AgentRunStatus.SUCCESS
            return

    run.status = AgentRunStatus.FAILED
    run.error_detail = f"Agent exceeded MAX_ITERATIONS ({MAX_ITERATIONS})"