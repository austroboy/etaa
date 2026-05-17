"""
Agent Module – Tool Registry.

Each tool is a Python callable wrapped with a JSON-schema description that the
LLM can use to decide *when* to call it and *what arguments* to pass.

Tools are intentionally small, composable building blocks. The LLM chains them
together to fulfil free-form operator instructions like:

    "Find the email thread titled 'Backend Hiring Q2', download every CV in
     that thread, ZIP them up and save the archive to /home/me/hires/"

The agent runner (runner.py) is what actually drives the OpenAI / Anthropic
function-calling loop using these definitions.

Adding new capabilities to the agent is a matter of writing a new function
here and decorating it with @tool – no change to dispatcher or intent parser
required.
"""

from __future__ import annotations

import imaplib
import json
import logging
import os
import re
import shutil
import tempfile
import zipfile
from email import message_from_bytes
from email.header import decode_header
from email.utils import parseaddr
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from django.conf import settings

logger = logging.getLogger("etaa")


# ─── Tool registry plumbing ──────────────────────────────────────────────────

#: name -> {"fn": callable, "schema": json-schema dict, "danger": bool}
_REGISTRY: Dict[str, Dict[str, Any]] = {}


def tool(name: str, description: str, parameters: dict, danger: bool = False):
    """
    Decorator that registers a Python callable as a tool the agent can invoke.

    `parameters` follows JSON-Schema (the same format used by both the
    OpenAI and Anthropic function-calling APIs).

    `danger=True` flags the tool as a sensitive operation that requires
    explicit operator confirmation before the agent is allowed to call it
    (e.g. sending email, deleting files, pushing to Git).
    """

    def decorator(fn: Callable):
        _REGISTRY[name] = {
            "fn": fn,
            "description": description,
            "parameters": parameters,
            "danger": danger,
        }
        return fn

    return decorator


def get_tool_schemas() -> List[dict]:
    """Return tool definitions in the OpenAI 'tools' format."""
    schemas = []
    for name, meta in _REGISTRY.items():
        schemas.append({
            "type": "function",
            "function": {
                "name": name,
                "description": meta["description"],
                "parameters": meta["parameters"],
            },
        })
    return schemas


def get_tool_schemas_anthropic() -> List[dict]:
    """Return tool definitions in the Anthropic 'tools' format."""
    schemas = []
    for name, meta in _REGISTRY.items():
        schemas.append({
            "name": name,
            "description": meta["description"],
            "input_schema": meta["parameters"],
        })
    return schemas


def is_dangerous(tool_name: str) -> bool:
    meta = _REGISTRY.get(tool_name)
    return bool(meta and meta.get("danger"))


def call_tool(tool_name: str, arguments: dict) -> dict:
    """
    Execute a registered tool. Always returns a dict so it can be JSON-encoded
    back to the LLM – even in the failure case.
    """
    meta = _REGISTRY.get(tool_name)
    if meta is None:
        return {"ok": False, "error": f"Unknown tool: {tool_name}"}
    try:
        result = meta["fn"](**(arguments or {}))
        if isinstance(result, dict):
            result.setdefault("ok", True)
            return result
        return {"ok": True, "result": result}
    except TypeError as exc:
        return {"ok": False, "error": f"Bad arguments to {tool_name}: {exc}"}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Tool %s failed: %s", tool_name, exc)
        return {"ok": False, "error": str(exc)}


# ─── Filesystem tools ────────────────────────────────────────────────────────

def _is_path_allowed(path: str) -> bool:
    """
    Allow any path that lives inside the configured workspace directories
    or under the operator's home directory. Block writes to system paths.
    """
    abspath = os.path.abspath(os.path.expanduser(path))
    allowed_roots = [
        os.path.abspath(settings.OUTPUT_DIR),
        os.path.abspath(getattr(settings, "CV_TEMP_DIR", "/tmp")),
        os.path.abspath(getattr(settings, "CODE_OUT_DIR", "/tmp")),
        os.path.abspath(os.path.expanduser("~")),
        "/tmp",
    ]
    return any(abspath.startswith(root) for root in allowed_roots)


@tool(
    name="list_directory",
    description="List files and subdirectories under a local path. "
                "Use this to discover what files exist before doing further work.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute or ~user path."},
            "pattern": {"type": "string", "description": "Optional glob filter (e.g. '*.pdf')."},
        },
        "required": ["path"],
    },
)
def list_directory(path: str, pattern: str = "*") -> dict:
    p = Path(os.path.expanduser(path))
    if not p.exists():
        return {"ok": False, "error": f"Path does not exist: {path}"}
    if not p.is_dir():
        return {"ok": False, "error": f"Not a directory: {path}"}
    items = []
    for item in p.glob(pattern):
        items.append({
            "name": item.name,
            "is_dir": item.is_dir(),
            "size": item.stat().st_size if item.is_file() else None,
        })
    return {"ok": True, "items": items[:200], "truncated": len(items) > 200}


@tool(
    name="ensure_directory",
    description="Make sure a directory exists, creating it (and parents) if necessary. "
                "Idempotent – safe to call on existing paths.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
        },
        "required": ["path"],
    },
)
def ensure_directory(path: str) -> dict:
    abspath = os.path.abspath(os.path.expanduser(path))
    if not _is_path_allowed(abspath):
        return {"ok": False, "error": f"Path not allowed: {path}"}
    os.makedirs(abspath, exist_ok=True)
    return {"ok": True, "path": abspath}


@tool(
    name="zip_files",
    description="Bundle a list of files into a single .zip archive at the given output path. "
                "Returns the absolute archive path on success.",
    parameters={
        "type": "object",
        "properties": {
            "file_paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Absolute paths of files to include in the archive.",
            },
            "output_zip_path": {
                "type": "string",
                "description": "Where to write the resulting .zip file.",
            },
        },
        "required": ["file_paths", "output_zip_path"],
    },
)
def zip_files(file_paths: List[str], output_zip_path: str) -> dict:
    output_zip_path = os.path.abspath(os.path.expanduser(output_zip_path))
    if not _is_path_allowed(output_zip_path):
        return {"ok": False, "error": f"Output path not allowed: {output_zip_path}"}
    os.makedirs(os.path.dirname(output_zip_path), exist_ok=True)
    added = 0
    skipped = []
    with zipfile.ZipFile(output_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for fp in file_paths:
            fp = os.path.expanduser(fp)
            if os.path.isfile(fp):
                zf.write(fp, arcname=os.path.basename(fp))
                added += 1
            else:
                skipped.append(fp)
    return {
        "ok": True,
        "zip_path": output_zip_path,
        "files_added": added,
        "files_skipped": skipped,
        "size_bytes": os.path.getsize(output_zip_path),
    }


@tool(
    name="extract_zip",
    description="Extract a .zip archive into a local directory. "
                "Use this when the operator mentions that CVs (or other files) "
                "are inside a ZIP file – extract first, then operate on the extracted "
                "files. If extract_to is omitted, a sibling folder is created "
                "with the same name as the zip (without the .zip extension).",
    parameters={
        "type": "object",
        "properties": {
            "zip_path": {
                "type": "string",
                "description": "Absolute path of the .zip file to extract.",
            },
            "extract_to": {
                "type": "string",
                "description": "Destination folder. Defaults to a sibling of "
                               "the zip, named after it.",
            },
        },
        "required": ["zip_path"],
    },
)
def extract_zip(zip_path: str, extract_to: str = "") -> dict:
    zip_path = os.path.abspath(os.path.expanduser(zip_path))
    if not os.path.isfile(zip_path):
        return {"ok": False, "error": f"ZIP not found: {zip_path}"}
    if not zipfile.is_zipfile(zip_path):
        return {"ok": False, "error": f"Not a valid ZIP file: {zip_path}"}

    if not extract_to:
        # Sibling folder, e.g. /a/b/cv.zip -> /a/b/cv
        parent = os.path.dirname(zip_path)
        stem   = os.path.splitext(os.path.basename(zip_path))[0]
        extract_to = os.path.join(parent, stem)

    extract_to = os.path.abspath(os.path.expanduser(extract_to))
    if not _is_path_allowed(extract_to):
        return {"ok": False, "error": f"Destination not allowed: {extract_to}"}

    os.makedirs(extract_to, exist_ok=True)
    extracted = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in zf.namelist():
            # Skip directories and skip path-traversal attempts.
            if name.endswith("/") or ".." in name.split("/"):
                continue
            target = os.path.normpath(os.path.join(extract_to, name))
            if not target.startswith(extract_to):
                continue  # zip-slip protection
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(name) as src, open(target, "wb") as dst:
                dst.write(src.read())
            extracted.append(target)
    return {
        "ok": True,
        "extract_to": extract_to,
        "files_extracted": len(extracted),
        "files": extracted[:50],  # truncate for LLM context
        "truncated": len(extracted) > 50,
    }


@tool(
    name="move_file",
    description="Move (or rename) a file from one location to another. "
                "Marked sensitive – will only run after operator confirmation.",
    parameters={
        "type": "object",
        "properties": {
            "src": {"type": "string"},
            "dst": {"type": "string"},
        },
        "required": ["src", "dst"],
    },
    danger=True,
)
def move_file(src: str, dst: str) -> dict:
    src = os.path.abspath(os.path.expanduser(src))
    dst = os.path.abspath(os.path.expanduser(dst))
    if not (_is_path_allowed(src) and _is_path_allowed(dst)):
        return {"ok": False, "error": "Path not allowed."}
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(src, dst)
    return {"ok": True, "moved_to": dst}


@tool(
    name="delete_file",
    description="Delete a file. Sensitive – requires operator confirmation.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
    danger=True,
)
def delete_file(path: str) -> dict:
    abspath = os.path.abspath(os.path.expanduser(path))
    if not _is_path_allowed(abspath):
        return {"ok": False, "error": f"Path not allowed: {path}"}
    if not os.path.isfile(abspath):
        return {"ok": False, "error": "Not a file or does not exist."}
    os.remove(abspath)
    return {"ok": True, "deleted": abspath}


# ─── Email / IMAP tools ──────────────────────────────────────────────────────

CV_MIMES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
CV_EXTENSIONS = {".pdf", ".doc", ".docx"}


def _decode_header_str(value: Optional[str]) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    out = []
    for raw, enc in parts:
        if isinstance(raw, bytes):
            try:
                out.append(raw.decode(enc or "utf-8", errors="replace"))
            except (LookupError, UnicodeDecodeError):
                out.append(raw.decode("utf-8", errors="replace"))
        else:
            out.append(raw)
    return "".join(out)


@tool(
    name="search_email_threads",
    description="Search the inbox for emails matching a subject keyword or sender. "
                "Returns a list of message metadata: id, from, subject, date. "
                "Use this to find a specific thread before downloading attachments.",
    parameters={
        "type": "object",
        "properties": {
            "subject_contains": {"type": "string",
                "description": "Match emails whose subject contains this text (case-insensitive)."},
            "from_contains": {"type": "string",
                "description": "Match emails whose From header contains this text."},
            "limit": {"type": "integer", "default": 50,
                "description": "Maximum number of messages to return (default 50)."},
            "folder": {"type": "string", "default": "INBOX",
                "description": "IMAP folder/mailbox to search (default INBOX)."},
        },
        "required": [],
    },
)
def search_email_threads(
    subject_contains: str = "",
    from_contains: str = "",
    limit: int = 50,
    folder: str = "INBOX",
) -> dict:
    try:
        mail = imaplib.IMAP4_SSL(settings.IMAP_HOST, settings.IMAP_PORT)
        mail.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
        mail.select(folder)

        criteria_parts = []
        if subject_contains:
            criteria_parts.append(f'(SUBJECT "{subject_contains}")')
        if from_contains:
            criteria_parts.append(f'(FROM "{from_contains}")')
        criterion = " ".join(criteria_parts) if criteria_parts else "ALL"

        _, data = mail.search(None, criterion)
        msg_ids = data[0].split()[-limit:]

        messages = []
        for mid in msg_ids:
            _, raw = mail.fetch(mid, "(BODY.PEEK[HEADER])")
            msg = message_from_bytes(raw[0][1])
            messages.append({
                "id": mid.decode(),
                "from": _decode_header_str(msg.get("From", "")),
                "subject": _decode_header_str(msg.get("Subject", "")),
                "date": msg.get("Date", ""),
                "message_id_header": msg.get("Message-ID", ""),
            })
        mail.logout()
        return {"ok": True, "messages": messages, "count": len(messages)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"IMAP search failed: {exc}"}


@tool(
    name="download_attachments_from_thread",
    description="Download every attachment from emails matching a subject filter "
                "(or a specific list of message IDs). Saves files to a directory and "
                "returns the list of downloaded paths. Optionally filters to CV-like "
                "attachments only (PDF/DOC/DOCX).",
    parameters={
        "type": "object",
        "properties": {
            "subject_contains": {"type": "string",
                "description": "Subject filter to find the thread."},
            "message_ids": {"type": "array", "items": {"type": "string"},
                "description": "Optional explicit list of IMAP message IDs."},
            "destination_dir": {"type": "string",
                "description": "Local directory to save attachments. Created if missing."},
            "cvs_only": {"type": "boolean", "default": False,
                "description": "If true, keep only PDF/DOC/DOCX attachments."},
            "folder": {"type": "string", "default": "INBOX"},
        },
        "required": ["destination_dir"],
    },
)
def download_attachments_from_thread(
    destination_dir: str,
    subject_contains: str = "",
    message_ids: Optional[List[str]] = None,
    cvs_only: bool = False,
    folder: str = "INBOX",
) -> dict:
    dest = os.path.abspath(os.path.expanduser(destination_dir))
    if not _is_path_allowed(dest):
        return {"ok": False, "error": f"Destination not allowed: {destination_dir}"}
    os.makedirs(dest, exist_ok=True)

    downloaded: List[str] = []
    skipped: List[str] = []

    try:
        mail = imaplib.IMAP4_SSL(settings.IMAP_HOST, settings.IMAP_PORT)
        mail.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
        mail.select(folder)

        ids: List[bytes] = []
        if message_ids:
            ids = [m.encode() if isinstance(m, str) else m for m in message_ids]
        else:
            criterion = f'(SUBJECT "{subject_contains}")' if subject_contains else "ALL"
            _, data = mail.search(None, criterion)
            ids = data[0].split()

        for mid in ids:
            _, raw = mail.fetch(mid, "(RFC822)")
            msg = message_from_bytes(raw[0][1])
            for part in msg.walk():
                if part.get_content_maintype() == "multipart":
                    continue
                cd = part.get("Content-Disposition", "") or ""
                if "attachment" not in cd.lower() and not part.get_filename():
                    continue
                filename = _decode_header_str(part.get_filename() or "")
                if not filename:
                    continue
                ext = os.path.splitext(filename)[1].lower()
                ctype = part.get_content_type()
                if cvs_only and ext not in CV_EXTENSIONS and ctype not in CV_MIMES:
                    skipped.append(filename)
                    continue
                # avoid name collisions
                save_name = filename
                save_path = os.path.join(dest, save_name)
                counter = 1
                while os.path.exists(save_path):
                    base, ext2 = os.path.splitext(filename)
                    save_path = os.path.join(dest, f"{base}_{counter}{ext2}")
                    counter += 1
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                with open(save_path, "wb") as f:
                    f.write(payload)
                downloaded.append(save_path)

        mail.logout()
        return {
            "ok": True,
            "destination_dir": dest,
            "downloaded": downloaded,
            "downloaded_count": len(downloaded),
            "skipped_non_cv": skipped if cvs_only else [],
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Download failed: {exc}"}


@tool(
    name="send_email",
    description="Send an email. Sensitive – requires operator confirmation. "
                "Use the dedicated email_outbound flow when a company template is appropriate; "
                "use this tool when the agent needs to send an ad-hoc email composed on the fly.",
    parameters={
        "type": "object",
        "properties": {
            "to_address": {"type": "string"},
            "subject": {"type": "string"},
            "body_html": {"type": "string"},
            "attachments": {"type": "array", "items": {"type": "string"}, "default": []},
            "cc": {"type": "array", "items": {"type": "string"}, "default": []},
        },
        "required": ["to_address", "subject", "body_html"],
    },
    danger=True,
)
def send_email_tool(
    to_address: str,
    subject: str,
    body_html: str,
    attachments: Optional[List[str]] = None,
    cc: Optional[List[str]] = None,
) -> dict:
    from apps.email_module.services import send_email
    ok = send_email(to_address, subject, body_html,
                    attachments=attachments or [], cc=cc or [])
    return {"ok": ok, "to": to_address, "subject": subject}


# ─── WhatsApp tools ──────────────────────────────────────────────────────────

@tool(
    name="send_whatsapp_text",
    description="Send a plain-text message back to the operator's chat "
                "(the same WhatsApp group or DM the original instruction "
                "came from). Use this for status updates, partial results, "
                "or asking the operator a clarifying question mid-task.",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "jid": {"type": "string",
                    "description": "Optional override JID. Leave empty to "
                                   "reply to the operator's chat."},
        },
        "required": ["text"],
    },
)
def send_whatsapp_text(text: str, jid: str = "") -> dict:
    from apps.agent.runner import current_reply_jid
    from apps.messaging.whatsapp_client import get_wa_client
    target = jid or current_reply_jid.get("") or None
    ok = get_wa_client().send_text(text, jid=target)
    return {"ok": ok, "sent_to": target or "(default group)"}


@tool(
    name="send_whatsapp_file",
    description="Send a local file to the operator's chat as a document.",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "caption":   {"type": "string", "default": ""},
            "jid":       {"type": "string",
                          "description": "Optional override JID."},
        },
        "required": ["file_path"],
    },
)
def send_whatsapp_file(file_path: str, caption: str = "", jid: str = "") -> dict:
    from apps.agent.runner import current_reply_jid
    from apps.messaging.whatsapp_client import get_wa_client
    abspath = os.path.abspath(os.path.expanduser(file_path))
    if not os.path.isfile(abspath):
        return {"ok": False, "error": f"File not found: {file_path}"}
    target = jid or current_reply_jid.get("") or None
    ok = get_wa_client().send_file(abspath, caption=caption, jid=target)
    return {"ok": ok, "file_path": abspath, "sent_to": target or "(default)"}


# ─── CV ranking pipeline (callable as a single high-level tool) ─────────────

@tool(
    name="rank_cvs",
    description=(
        "Run the LLM-based CV ranking pipeline against a local directory of CV files. "
        "Scores every CV against the job requirements and returns a ranked summary plus "
        "paths to an Excel scoring sheet and a ZIP of the top-N CVs. "
        "IMPORTANT: job_requirements must be a detailed string describing the role. "
        "If the operator only gave a job title, expand it into full requirements yourself "
        "covering: experience level, key skills, relevant industries, and qualifications. "
        "Never call this tool with job_requirements containing only a job title."
    ),
    parameters={
        "type": "object",
        "properties": {
            "cv_directory":    {"type": "string", "description": "Absolute path to folder containing CV files."},
            "job_requirements": {"type": "string", "description": "Full job requirements text (NOT just a title). Infer from context if not given."},
            "top_n":           {"type": "integer", "default": 30, "description": "Number of top CVs to include in the ZIP."},
            "output_dir":      {"type": "string", "description": "Optional output directory for ZIP and Excel."},
        },
        "required": ["cv_directory", "job_requirements"],
    },
)
def rank_cvs_tool(
    cv_directory: str,
    job_requirements: str,
    top_n: int = 30,
    output_dir: str = "",
) -> dict:
    from apps.cv_module.services import (
        collect_cvs_from_local,
        rank_all_cvs,
        package_results,
        _build_excel_summary,
    )
    paths = collect_cvs_from_local(cv_directory)
    if not paths:
        return {"ok": False, "error": "No CV files found in directory."}
    ranked = rank_all_cvs(paths, job_requirements)
    out_dir = output_dir or os.path.join(settings.OUTPUT_DIR, "cv_rankings")
    os.makedirs(out_dir, exist_ok=True)

    actual_top = min(top_n, len(ranked))
    zip_path = package_results(ranked, actual_top, out_dir, job_id=0,
                               job_requirements=job_requirements)

    # Build standalone Excel for direct WhatsApp delivery
    xlsx_path = os.path.join(out_dir, f"CV_Ranking_{actual_top}.xlsx")
    _build_excel_summary(ranked, job_requirements, xlsx_path)

    summary = [
        {"rank": r["rank"], "name": r["candidate_name"],
         "score": r["match_score"], "designation": r.get("current_designation",""),
         "experience_yrs": r.get("years_experience", 0), "file": r["file_name"]}
        for r in ranked[:actual_top]
    ]
    return {
        "ok": True,
        "zip_path": zip_path,
        "excel_path": xlsx_path,
        "ranking": summary,
        "total_processed": len(ranked),
        "top_n": actual_top,
    }


# ─── Drive download (for completeness) ───────────────────────────────────────

@tool(
    name="download_from_google_drive",
    description="Download all files from a Google Drive folder link to a local directory.",
    parameters={
        "type": "object",
        "properties": {
            "folder_link": {"type": "string"},
            "destination_dir": {"type": "string"},
        },
        "required": ["folder_link", "destination_dir"],
    },
)
def download_from_google_drive(folder_link: str, destination_dir: str) -> dict:
    from apps.cv_module.services import collect_cvs_from_drive
    dest = os.path.abspath(os.path.expanduser(destination_dir))
    if not _is_path_allowed(dest):
        return {"ok": False, "error": f"Destination not allowed: {destination_dir}"}
    paths = collect_cvs_from_drive(folder_link, dest)
    return {"ok": True, "downloaded": paths, "count": len(paths)}


# ─── Final-answer sentinel ────────────────────────────────────────────────────

@tool(
    name="finish",
    description="Call this when the task is fully complete. Provide a short summary "
                "of what was done that will be relayed back to the operator.",
    parameters={
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
        },
        "required": ["summary"],
    },
)
def finish(summary: str) -> dict:
    return {"ok": True, "final": True, "summary": summary}