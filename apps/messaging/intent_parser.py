"""
Intent Parser.

Uses an LLM to classify operator instructions into task types and
extract parameters. The classifier strongly prefers actionable task
types (`dynamic` for anything multi-step or novel) over the catch-all
`unknown`, and explicitly recognises `help` / capability questions so
the bot can list what it can do instead of saying "I don't understand".
"""

import json
import logging

from apps.llm_client import get_llm_client

logger = logging.getLogger("etaa")

INTENT_SYSTEM_PROMPT = """You are the intent-classification layer of an Enterprise Task Automation Agent (ETAA).
Your job is to read a natural-language instruction from an authorized operator and return a JSON object.

Return ONLY a valid JSON object – no markdown, no explanation.

Schema:
{
  "task_type": "<one of: email_outbound | email_inbound_reply | cv_ranking | job_post | code_gen | dynamic | help | greeting | unknown>",
  "params": { ... task-specific parameters ... },
  "is_ambiguous": <true|false>,
  "clarification_question": "<string if is_ambiguous else null>"
}

CHOOSING task_type — read these rules in order; first match wins:

1. `help` — the operator is asking what the bot can do, what tasks
   are available, how to use it, what commands exist, etc.
   Examples: "what can you do", "how many tasks can you perform",
   "list your capabilities", "help", "what tasks", "show commands",
   "how do I use you".

2. `greeting` — the operator just said hello, hi, salam, kemon acho,
   thanks, ok cool, good morning, etc. with no actual task.

3. `email_outbound` — the operator wants to compose and send an email.

4. `email_inbound_reply` — explicitly asks to read the inbox and
   reply to messages there.

5. `cv_ranking` — wants CVs ranked against a job spec.

6. `job_post` — wants a job posting, recruitment poster, hiring
   announcement, social media post for hiring, Canva design for a
   role, or any visual/text artifact announcing an open position.
   STRONG indicators (any one is enough):
     * "create a Canva design for [position/job/role/...]"
     * "make a social media post for hiring/recruiting/..."
     * "design a job post / recruitment poster / hiring banner"
     * "post for LinkedIn/Facebook" combined with a job description
     * Any instruction containing role description with "Position
       Overview", "Key Requirements", "Core Responsibilities",
       "Job Title", or similar HR/recruitment headings.
   Even if the operator says "social media post" instead of "job
   post", route to job_post when the content is clearly a hiring
   announcement.

7. `code_gen` — wants code/a project generated, possibly from an SRS.

8. `dynamic` — ANY other actionable, multi-step, or novel task that
   doesn't cleanly fit one of the specialised pipelines. The dynamic
   agent has access to filesystem, IMAP search, attachment download,
   ZIP creation, Google Drive, WhatsApp send, email send, and the
   CV-ranking pipeline as composable tools. Be GENEROUS in choosing
   `dynamic` — if the operator clearly wants the bot to DO something,
   even if you're not sure how, route it here. Examples:
     - "find the email thread titled X and download all CVs in it"
     - "check the inbox for invoices today and forward them to ..."
     - "list the files in /tmp/cvs and zip them"
     - "search my drive for the Q3 report"

CRITICAL AMBIGUITY RULES — is_ambiguous MUST be false in ALL of these cases:
- CV ranking request with only a job title (infer requirements from the title)
- Any message with a clear action verb + file path or location
- Any message where you know WHAT to do, even if details are sparse
- is_ambiguous should almost always be FALSE
- ONLY set is_ambiguous=true if you literally cannot determine what action to take at all
- NEVER set is_ambiguous=true just because job requirements, email body, or other details were not fully specified — infer them or use sensible defaults

9. `unknown` — only when the message is genuinely incomprehensible.
   Capability questions, greetings, and borderline-actionable
   instructions are NOT `unknown`.

Task-specific param schemas:

email_outbound:
  template_hint: <string>, recipient_email: <string>, recipient_name: <string>,
  price: <string|null>, offer_details: <string|null>, deadline: <string|null>,
  attachments: [<file paths>]

email_inbound_reply:
  (no params needed – system reads inbox automatically)

cv_ranking:
  source: <"google_drive" | "local">, source_path: <string>,
  job_requirements: <INFER from job title if not explicitly provided — generate detailed requirements covering experience level, key skills, relevant industries, and qualifications. NEVER leave blank. NEVER ask for clarification just because job_requirements were not spelled out.>,
  top_n: <int default 30>

job_post:
  job_title: <REQUIRED string. INFER from the instruction context — look
             for headings like "Position Overview", "Role:", a bolded
             title, or derive from the responsibilities. NEVER leave
             blank — pick the most likely title from the body.>,
  department: <string|"" — leave empty if not stated>,
  responsibilities: <string — copy the operator's full responsibilities
             section verbatim (bullets, multiple lines OK)>,
  qualifications: <string — copy the operator's full requirements/
             qualifications section verbatim>,
  salary_range: <string|"" — only if explicitly stated>,
  company_info: <string|"" — only if explicitly stated>,
  tagline: <string|"" — a short one-line tagline for the poster
             (e.g. "Driving business growth across modern trade"). If
             the operator didn't supply one, leave "" and the system
             will skip the tagline.>,
  location: <string default "Dhaka, Bangladesh" — only override if
             explicitly stated>,
  deadline: <string default "Open until filled" — only override if
             explicitly stated>

code_gen:
  srs_text: <string|null>, srs_file_path: <string|null>,
  tech_stack: <string default "django">,
  git_push: <bool default false>, repo_url: <string|null>

dynamic:
  instruction: <verbatim original instruction text>,
  needs_dangerous_tools: <bool – true if the instruction will require sending
                         email, deleting/moving files, pushing to git, etc.>

help:
  (no params)

greeting:
  greeting_text: <a short friendly response in the same language as the
                  operator – Bengali if they wrote in Bengali, English
                  if English, etc.>

unknown:
  raw: <original instruction text>
"""


def _quick_local_classify(instruction: str) -> dict | None:
    """Fast-path classifier for very common, unambiguous patterns.
    Returns an intent dict if matched, otherwise None (let the LLM
    handle it). Saves an LLM round-trip for trivial inputs."""
    import re as _re

    t = (instruction or "").strip().lower()
    if not t:
        return None

    # Capability questions
    help_patterns = [
        r"^help$",
        r"^/help$",
        r"^what can (you|u) do",
        r"^what (do you|can you) (do|perform)",
        r"^how many (tasks?|things?|workers?) can (you|u) (do|perform|handle)",
        r"^list (your )?(capabilities|commands|tasks)",
        r"^show (your )?(capabilities|commands|tasks|menu)",
        r"^how (do i|to) use (you|this)",
        r"^what (tasks?|commands?) (are )?(available|do you)",
        r"^/start$",
    ]
    for pat in help_patterns:
        if _re.search(pat, t):
            return {
                "task_type": "help",
                "params": {},
                "is_ambiguous": False,
                "clarification_question": None,
            }

    # Plain greetings
    greeting_patterns = [
        r"^(hi|hello|hey|salam|assalamu? alaikum|hola|yo|sup)\b[\s.!?]*$",
        r"^(good (morning|afternoon|evening|night))\b[\s.!?]*$",
        r"^(thanks|thank you|thx|ty)\b[\s.!?]*$",
        r"^(ok|okay|cool|nice|great)\b[\s.!?]*$",
        r"^(kemon acho|kemon achen|valo achi)\b[\s.!?]*$",
    ]
    for pat in greeting_patterns:
        if _re.search(pat, t):
            return {
                "task_type": "greeting",
                "params": {"greeting_text":
                    "👋 Hi! Type *help* to see what I can do."},
                "is_ambiguous": False,
                "clarification_question": None,
            }

    return None


def parse_intent(instruction: str) -> dict:
    """Classify an operator instruction. Falls back to `dynamic` if the
    LLM crashes (so the agent at least gets a chance to handle it)
    rather than rejecting outright."""
    # Cheap local pre-classification for very common patterns – saves
    # an LLM round-trip on greetings and "what can you do".
    local = _quick_local_classify(instruction)
    if local is not None:
        logger.info("Parsed intent (local fast-path): task_type=%s",
                    local.get("task_type"))
        return local

    llm = get_llm_client()
    try:
        raw = llm.complete(
            prompt=instruction,
            system=INTENT_SYSTEM_PROMPT,
            max_tokens=1024,
            temperature=0.0,
        )
        intent = json.loads(raw)
        logger.info(
            "Parsed intent: task_type=%s ambiguous=%s",
            intent.get("task_type"), intent.get("is_ambiguous"),
        )
        return intent
    except (json.JSONDecodeError, Exception) as exc:  # noqa: BLE001
        logger.warning(
            "Intent parsing failed; falling back to dynamic agent: %s", exc,
        )
        return {
            "task_type": "dynamic",
            "params": {
                "instruction": instruction,
                "needs_dangerous_tools": False,
            },
            "is_ambiguous": False,
            "clarification_question": None,
        }