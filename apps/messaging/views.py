"""
Messaging Module – Views.

The single entry point for WhatsApp messages. All policy decisions live
either here (the routing layer) or in apps.authz.services (the
authorization decision). Keep them separated.

Flow:
  1. Bridge POSTs a message to /api/messaging/webhook/.
  2. We persist a raw `IncomingMessage` record (audit trail).
  3. We run the authorization check (apps.authz.check_authorization).
     - Core operators are authorized everywhere (DM and any group).
     - Non-core users are authorized only inside a group where one of
       the core operators has previously delegated access to them.
  4. Unauthorized messages are silently dropped (per SRS §3.1.1).
  5. If the message is itself an authorization-management command
     ("authorize @newperson", "revoke @oldperson", "list members"),
     we handle it in-place and return.
  6. Otherwise we treat it as a confirmation response (if one is
     pending) or a fresh task instruction.
"""

import json
import logging

from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from apps.authz.services import (
    AuthCommand,
    check_authorization,
    grant_group_access,
    list_group_members,
    parse_auth_command,
    record_denied_message,
    revoke_group_access,
)
from apps.confirmation.models import ConfirmationStatus
from apps.confirmation.services import process_confirmation_response
from apps.messaging.dispatcher import dispatch_confirmed
from apps.messaging.models import IncomingMessage
from apps.messaging.whatsapp_client import get_wa_client

logger = logging.getLogger("etaa")


@method_decorator(csrf_exempt, name="dispatch")
class WebhookView(View):
    """
    Receives POST events from the WhatsApp bridge.

    Expected JSON body (all keys optional except message_id, sender_phone,
    body):

        {
          "message_id":   "abc",
          "sender_phone": "8801712345678",
          "sender_name":  "Zihad",
          "group_jid":    "120363...@g.us",
          "is_group":     true,
          "body":         "rank these CVs ...",
          "media_url":    "",
          "quoted_phone": "8801987654321",   // when message is a reply
          "quoted_name":  "Karim"
        }
    """

    def post(self, request):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "invalid json"}, status=400)

        sender_phone = data.get("sender_phone", "").replace("+", "").strip()
        sender_name  = data.get("sender_name", "")
        group_jid    = data.get("group_jid", "")
        is_group     = bool(data.get("is_group", bool(group_jid)))
        body         = data.get("body", "").strip()
        message_id   = data.get("message_id", "")
        media_url    = data.get("media_url", "")
        quoted_phone = data.get("quoted_phone", "")
        quoted_name  = data.get("quoted_name", "")

        # ── Persist raw message (audit trail) ──────────────────────────
        if message_id and not IncomingMessage.objects.filter(
            message_id=message_id
        ).exists():
            IncomingMessage.objects.create(
                sender_phone=sender_phone,
                sender_name=sender_name,
                group_jid=group_jid,
                message_id=message_id,
                body=body,
                media_url=media_url,
                # is_authorized is filled in below
            )

        # ── Authorization check ────────────────────────────────────────
        decision = check_authorization(
            sender_phone=sender_phone,
            sender_name=sender_name,
            group_jid=group_jid,
            is_group=is_group,
        )

        # Persist the decision on the IncomingMessage record
        if message_id:
            IncomingMessage.objects.filter(message_id=message_id).update(
                is_authorized=decision.authorized
            )

        if not decision.authorized:
            # SRS §3.1.1: silently discard. Audit-log it though.
            record_denied_message(
                sender_phone=sender_phone,
                sender_name=sender_name,
                group_jid=group_jid,
                body=body,
            )
            logger.info(
                "Discarded message from unauthorized sender %s (%s)",
                sender_phone, decision.reason or "no reason",
            )
            return JsonResponse({"ok": True, "action": "discarded_unauthorized"})

        op_name = decision.display_name

        # ── Authorization-management commands ──────────────────────────
        # These are handled BEFORE confirmation responses and BEFORE the
        # generic intent parser, because they're cheap to detect, free
        # (no LLM call) and need core-operator rights to execute.
        auth_cmd = parse_auth_command(
            text=body,
            quoted_phone=quoted_phone,
            quoted_name=quoted_name,
        )
        if auth_cmd is not None:
            self._handle_auth_command(
                cmd=auth_cmd,
                speaker=decision,
                speaker_phone=sender_phone,
                group_jid=group_jid,
                is_group=is_group,
            )
            return JsonResponse({"ok": True, "action": "auth_command"})

        # ── Confirmation response? ─────────────────────────────────────
        resolved = process_confirmation_response(sender_phone, body)
        if resolved is not None:
            wa = get_wa_client()
            reply_jid = group_jid or (sender_phone + "@c.us")
            if resolved.status == ConfirmationStatus.APPROVED:
                wa.send_text("✅ Confirmed! Starting task now…", jid=reply_jid)
                dispatch_confirmed(resolved)
            elif resolved.status == ConfirmationStatus.DENIED:
                wa.send_text("🚫 Task cancelled.", jid=reply_jid)
            return JsonResponse({"ok": True, "action": "confirmation_handled"})

        if not body:
            return JsonResponse({"ok": True, "action": "empty_body"})

        # ── Fresh task instruction ─────────────────────────────────────
        # Acknowledge immediately and offload the slow stuff (LLM intent
        # classification + dispatch) to a Celery worker so the bridge's
        # webhook timeout never bites us.
        wa = get_wa_client()
        reply_jid = group_jid or (sender_phone + "@c.us")
        wa.send_text("⏳ Got it — processing your request…", jid=reply_jid)

        from apps.messaging.tasks import classify_and_dispatch_task
        classify_and_dispatch_task.delay(
            body=body,
            sender_phone=sender_phone,
            operator_name=op_name,
            reply_jid=reply_jid,
        )

        return JsonResponse({"ok": True, "action": "dispatched"})

    # ── Helpers ───────────────────────────────────────────────────────

    def _handle_auth_command(
        self,
        cmd: AuthCommand,
        speaker,                     # AuthDecision
        speaker_phone: str,
        group_jid: str,
        is_group: bool,
    ) -> None:
        """Execute an `authorize`/`revoke`/`list` command.

        Only core operators may grant or revoke. Authorization is always
        scoped to the group the command was issued in – it cannot be
        granted from a DM (per the user's spec: "if any one of the 3
        authorizes that new person, that person will be considered
        authorized—but only within the group, not individually").
        """
        wa = get_wa_client()
        reply_jid = group_jid if is_group else (speaker_phone + "@c.us")

        if cmd.action == "list":
            if not is_group:
                wa.send_text(
                    "ℹ️ Membership listing is only available inside a group.",
                    jid=reply_jid,
                )
                return
            members = list_group_members(group_jid)
            if not members:
                wa.send_text(
                    "ℹ️ No delegated members in this group yet. "
                    "Only the three core operators can issue instructions here.",
                    jid=reply_jid,
                )
                return
            lines = ["*Delegated members in this group:*"]
            for m in members:
                lines.append(
                    f"• {m.member_name or '(unnamed)'} — "
                    f"`{m.member_phone}` "
                    f"(by {m.granted_by}, {m.granted_at:%Y-%m-%d})"
                )
            wa.send_text("\n".join(lines), jid=reply_jid)
            return

        # grant / revoke require core-operator status
        if not speaker.is_core_op:
            wa.send_text(
                "⚠️ Only the three core operators may grant or revoke "
                "group access. Your message was not actioned.",
                jid=reply_jid,
            )
            return

        # grant / revoke require a group context
        if not is_group:
            wa.send_text(
                "⚠️ Authorization can only be granted inside a group. "
                "It cannot be granted in a 1-on-1 chat.",
                jid=reply_jid,
            )
            return

        if not cmd.target_phone:
            wa.send_text(
                "⚠️ I couldn't tell which person you want me to "
                f"{cmd.action}. Either include their phone number, "
                "or reply to one of their messages with the command.",
                jid=reply_jid,
            )
            return

        if cmd.action == "grant":
            membership = grant_group_access(
                group_jid=group_jid,
                member_phone=cmd.target_phone,
                granted_by_phone=speaker_phone,
                member_name=cmd.target_name,
            )
            wa.send_text(
                f"✅ Authorized *{membership.member_name or membership.member_phone}* "
                f"to issue instructions in this group.\n"
                f"_(Authorization is scoped to this group only, "
                f"granted by {speaker.display_name}.)_",
                jid=reply_jid,
            )
        else:
            ok = revoke_group_access(
                group_jid=group_jid,
                member_phone=cmd.target_phone,
                revoked_by_phone=speaker_phone,
            )
            if ok:
                wa.send_text(
                    f"🛑 Revoked access for `{cmd.target_phone}` in this group.",
                    jid=reply_jid,
                )
            else:
                wa.send_text(
                    f"ℹ️ `{cmd.target_phone}` did not have active access "
                    "in this group. Nothing changed.",
                    jid=reply_jid,
                )