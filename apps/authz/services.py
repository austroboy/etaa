"""
Authorization Module – Services.

Pure-function policy decisions and helpers for the messaging layer.

The single source of truth for "is this message allowed to issue an
instruction?" is `check_authorization()`. Everything else
(intent_parser, dispatcher, agent runner) trusts its verdict.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from django.conf import settings

from apps.authz.models import (
    AuthorizationEvent,
    GroupMembership,
    MembershipStatus,
)

logger = logging.getLogger("etaa")


# ─── Policy decision ────────────────────────────────────────────────────────


@dataclass
class AuthDecision:
    """Result of an authorization check.

    - `authorized`   : may this sender issue any instruction here?
    - `is_core_op`   : is the sender one of the three configured operators?
    - `is_delegated` : is the sender authorized only because of a
                       per-group GroupMembership?
    - `display_name` : the most useful name for logs / WhatsApp replies.
    - `reason`       : human-readable explanation if `authorized=False`.
    """
    authorized:    bool
    is_core_op:    bool
    is_delegated:  bool
    display_name:  str
    reason:        str = ""


def normalize_phone(phone: str) -> str:
    """Strip '+', whitespace and any other non-digit characters."""
    if not phone:
        return ""
    return re.sub(r"\D", "", phone)


def is_core_operator(phone: str) -> bool:
    return normalize_phone(phone) in {
        normalize_phone(p) for p in settings.AUTHORIZED_OPERATORS.keys()
    }


def core_operator_name(phone: str) -> Optional[str]:
    np = normalize_phone(phone)
    for p, name in settings.AUTHORIZED_OPERATORS.items():
        if normalize_phone(p) == np:
            return name
    return None


def check_authorization(
    sender_phone: str,
    sender_name: str = "",
    group_jid: str = "",
    is_group: bool = False,
) -> AuthDecision:
    """
    Decide whether a sender may issue instructions.

    Rules:
      * Core operators are always authorized – DM or group, anywhere.
      * Non-core operators are authorized **only** when they:
          (a) are messaging inside a group (not a DM), AND
          (b) have an ACTIVE GroupMembership for that group_jid.
      * 1-on-1 chats from non-core users: never authorized.
    """
    sender_phone = normalize_phone(sender_phone)

    # Layer 1: core operators
    if is_core_operator(sender_phone):
        return AuthDecision(
            authorized=True,
            is_core_op=True,
            is_delegated=False,
            display_name=core_operator_name(sender_phone) or sender_name or sender_phone,
        )

    # Non-core. Group context required.
    if not is_group or not group_jid:
        return AuthDecision(
            authorized=False,
            is_core_op=False,
            is_delegated=False,
            display_name=sender_name or sender_phone,
            reason="Not a core operator and not messaging in an authorized group.",
        )

    # Layer 2: group-delegated authorization
    membership = (
        GroupMembership.objects
        .filter(
            group_jid=group_jid,
            member_phone=sender_phone,
            status=MembershipStatus.ACTIVE,
        )
        .first()
    )
    if membership:
        return AuthDecision(
            authorized=True,
            is_core_op=False,
            is_delegated=True,
            display_name=(membership.member_name
                          or sender_name
                          or sender_phone),
        )

    return AuthDecision(
        authorized=False,
        is_core_op=False,
        is_delegated=False,
        display_name=sender_name or sender_phone,
        reason="No active group membership for this group.",
    )


# ─── Group-membership management ─────────────────────────────────────────────


def grant_group_access(
    group_jid: str,
    member_phone: str,
    granted_by_phone: str,
    member_name: str = "",
    note: str = "",
) -> GroupMembership:
    """
    Grant `member_phone` permission to issue instructions in `group_jid`.

    Pre-condition: caller must already have validated that
    `granted_by_phone` is a core operator and is messaging in `group_jid`.
    """
    member_phone = normalize_phone(member_phone)
    granted_by_phone = normalize_phone(granted_by_phone)

    # Idempotent: re-activate an existing record rather than fail.
    existing = GroupMembership.objects.filter(
        group_jid=group_jid, member_phone=member_phone
    ).first()
    if existing:
        if existing.status == MembershipStatus.REVOKED:
            existing.reactivate(by_phone=granted_by_phone)
            kind = AuthorizationEvent.Kind.REACTIVATED
        else:
            kind = None  # already active – record nothing
        if member_name and not existing.member_name:
            existing.member_name = member_name
            existing.save(update_fields=["member_name"])
        if note:
            existing.note = note
            existing.save(update_fields=["note"])
        if kind:
            AuthorizationEvent.objects.create(
                kind=kind,
                actor_phone=granted_by_phone,
                actor_name=core_operator_name(granted_by_phone) or "",
                target_phone=member_phone,
                target_name=member_name,
                group_jid=group_jid,
                detail=note,
            )
        return existing

    membership = GroupMembership.objects.create(
        group_jid=group_jid,
        member_phone=member_phone,
        member_name=member_name,
        granted_by=granted_by_phone,
        note=note,
    )
    AuthorizationEvent.objects.create(
        kind=AuthorizationEvent.Kind.GRANTED,
        actor_phone=granted_by_phone,
        actor_name=core_operator_name(granted_by_phone) or "",
        target_phone=member_phone,
        target_name=member_name,
        group_jid=group_jid,
        detail=note,
    )
    logger.info(
        "Granted group access | group=%s member=%s by=%s",
        group_jid[-20:], member_phone, granted_by_phone,
    )
    return membership


def revoke_group_access(
    group_jid: str,
    member_phone: str,
    revoked_by_phone: str,
) -> bool:
    """Revoke a previously-granted group membership. Returns True on success."""
    member_phone = normalize_phone(member_phone)
    revoked_by_phone = normalize_phone(revoked_by_phone)

    membership = GroupMembership.objects.filter(
        group_jid=group_jid,
        member_phone=member_phone,
        status=MembershipStatus.ACTIVE,
    ).first()
    if not membership:
        return False

    membership.revoke(by_phone=revoked_by_phone)
    AuthorizationEvent.objects.create(
        kind=AuthorizationEvent.Kind.REVOKED,
        actor_phone=revoked_by_phone,
        actor_name=core_operator_name(revoked_by_phone) or "",
        target_phone=member_phone,
        target_name=membership.member_name,
        group_jid=group_jid,
    )
    logger.info(
        "Revoked group access | group=%s member=%s by=%s",
        group_jid[-20:], member_phone, revoked_by_phone,
    )
    return True


def list_group_members(group_jid: str, active_only: bool = True):
    qs = GroupMembership.objects.filter(group_jid=group_jid)
    if active_only:
        qs = qs.filter(status=MembershipStatus.ACTIVE)
    return list(qs.order_by("granted_at"))


def record_denied_message(
    sender_phone: str,
    sender_name: str = "",
    group_jid: str = "",
    body: str = "",
):
    """Audit-log a message that was rejected by the authorization layer."""
    AuthorizationEvent.objects.create(
        kind=AuthorizationEvent.Kind.DENIED_MESSAGE,
        actor_phone=normalize_phone(sender_phone),
        actor_name=sender_name,
        group_jid=group_jid,
        detail=body[:200],
    )


# ─── Authorization command parser ──────────────────────────────────────────


# Match phone numbers in many forms: +880 1712-345678, 8801712345678,
# +1 (415) 555-9999, etc. Returns the digits-only string.
_PHONE_RE = re.compile(r"\+?\d[\d\s().\-]{7,}\d")

# Trigger phrases. Word-boundary anchored. Case-insensitive.
_GRANT_PATTERNS = [
    re.compile(r"\bauthorize\b", re.I),
    re.compile(r"\bauthorise\b", re.I),
    re.compile(r"\bgrant\s+access\b", re.I),
    re.compile(r"\bgive\s+access\b", re.I),
    re.compile(r"\badd\s+(?:as\s+)?(?:operator|member)\b", re.I),
    re.compile(r"\bapprove\b", re.I),
]
_REVOKE_PATTERNS = [
    re.compile(r"\brevoke\b", re.I),
    re.compile(r"\bremove\s+access\b", re.I),
    re.compile(r"\bunauthorize\b", re.I),
    re.compile(r"\bunauthorise\b", re.I),
    re.compile(r"\bremove\s+(?:operator|member)\b", re.I),
]
_LIST_PATTERNS = [
    re.compile(r"\b(?:list|show)\s+(?:authorized|authorised|members|operators)\b", re.I),
    re.compile(r"\bwho('?s|\s+is)\s+authori[sz]ed\b", re.I),
]


@dataclass
class AuthCommand:
    action:        str              # "grant" | "revoke" | "list"
    target_phone:  str = ""         # digits only; empty for list
    target_name:   str = ""
    raw_text:      str = ""


def parse_auth_command(
    text: str,
    quoted_phone: str = "",
    quoted_name: str = "",
) -> Optional[AuthCommand]:
    """
    Detect whether `text` is an authorization-management command.

    Returns an AuthCommand or None. The caller (the messaging webhook)
    then decides whether the speaker is allowed to execute it.

    `quoted_phone` / `quoted_name` are populated by the WhatsApp bridge
    when the message is a reply – in that case, the user can simply say
    "authorize this person" without typing the number.
    """
    if not text:
        return None
    t = text.strip()

    # The grant/revoke patterns may all coexist with normal task instructions
    # ("authorize a refund" is NOT an auth command). Therefore we require:
    #   - a recognized verb, AND
    #   - either a phone number in the message, OR a quoted reply.
    is_grant  = any(p.search(t) for p in _GRANT_PATTERNS)
    is_revoke = any(p.search(t) for p in _REVOKE_PATTERNS)
    is_list   = any(p.search(t) for p in _LIST_PATTERNS)

    if is_list and not (is_grant or is_revoke):
        return AuthCommand(action="list", raw_text=text)

    if not (is_grant or is_revoke):
        return None

    target_phone = ""
    target_name = quoted_name

    # 1. explicit phone number in the message text
    m = _PHONE_RE.search(t)
    if m:
        candidate = normalize_phone(m.group(0))
        # require minimum sensible length to avoid matching e.g. order numbers
        if 7 <= len(candidate) <= 15:
            target_phone = candidate

    # 2. quoted reply – use the replied-to author's phone
    if not target_phone and quoted_phone:
        target_phone = normalize_phone(quoted_phone)

    if not target_phone:
        # We saw a verb but couldn't identify a target – treat as
        # ambiguous so the dispatcher can ask for clarification.
        return AuthCommand(
            action="grant" if is_grant else "revoke",
            target_phone="",
            target_name=target_name,
            raw_text=text,
        )

    return AuthCommand(
        action="grant" if is_grant else "revoke",
        target_phone=target_phone,
        target_name=target_name,
        raw_text=text,
    )
