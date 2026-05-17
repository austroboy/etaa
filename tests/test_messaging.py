"""Tests – Messaging Module (webhook routing, intent classification)."""

import json
from unittest.mock import MagicMock, patch

from django.test import Client, TestCase, override_settings


_OPS = {"8801700000001": "Op One", "8801700000002": "Op Two"}


@override_settings(AUTHORIZED_OPERATORS=_OPS)
class TestWebhookAuth(TestCase):
    """The webhook layer enforces the two-tier auth model:

    * Core operators are authorized everywhere (DM and any group).
    * Non-core senders are only authorized inside groups where they
      have an active GroupMembership.
    """

    def setUp(self):
        self.client = Client()
        self.url = "/api/messaging/webhook/"

    def _post(self, **overrides):
        body = {
            "message_id":   overrides.get("message_id", "msg-x"),
            "sender_phone": overrides.get("sender_phone", "8801700000001"),
            "sender_name":  overrides.get("sender_name", "Op One"),
            "group_jid":    overrides.get("group_jid", "abc@g.us"),
            "is_group":     overrides.get("is_group", True),
            "body":         overrides.get("body", "Send email to a@b.com"),
        }
        return self.client.post(
            self.url, data=json.dumps(body),
            content_type="application/json",
        )

    @patch("apps.messaging.tasks.classify_and_dispatch_task.delay")
    @patch("apps.messaging.views.get_wa_client")
    def test_core_operator_in_group_is_dispatched(
        self, mock_wa, mock_task,
    ):
        resp = self._post(sender_phone="8801700000001")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["action"], "dispatched")
        mock_task.assert_called_once()

    @patch("apps.messaging.tasks.classify_and_dispatch_task.delay")
    @patch("apps.messaging.views.get_wa_client")
    def test_core_operator_in_dm_is_dispatched(
        self, mock_wa, mock_task,
    ):
        """Core ops are also authorized in 1-on-1 chats with the bot."""
        resp = self._post(
            sender_phone="8801700000001", group_jid="", is_group=False,
        )
        self.assertEqual(resp.json()["action"], "dispatched")
        mock_task.assert_called_once()

    def test_non_core_in_dm_is_silently_dropped(self):
        """Non-core senders cannot DM the bot. No authz, no dispatch."""
        resp = self._post(
            sender_phone="8809999999999",
            group_jid="", is_group=False, body="hi",
        )
        self.assertEqual(resp.json()["action"], "discarded_unauthorized")

    def test_non_core_in_group_without_membership_is_dropped(self):
        """A stranger added to a group cannot speak until authorized."""
        resp = self._post(sender_phone="8809999999999", body="rank cvs")
        self.assertEqual(resp.json()["action"], "discarded_unauthorized")

    @patch("apps.messaging.tasks.classify_and_dispatch_task.delay")
    @patch("apps.messaging.views.get_wa_client")
    def test_non_core_in_group_with_membership_is_authorized(
        self, mock_wa, mock_task,
    ):
        """A delegated member can issue instructions inside their group."""
        from apps.authz.services import grant_group_access

        grant_group_access(
            group_jid="abc@g.us",
            member_phone="8809999999999",
            granted_by_phone="8801700000001",
            member_name="Delegate",
        )
        resp = self._post(
            sender_phone="8809999999999", body="send the offer email",
        )
        self.assertEqual(resp.json()["action"], "dispatched")
        mock_task.assert_called_once()

    def test_delegated_member_cannot_dm_the_bot(self):
        """Per spec: group authorization does NOT extend to DMs."""
        from apps.authz.services import grant_group_access

        grant_group_access(
            group_jid="abc@g.us",
            member_phone="8809999999999",
            granted_by_phone="8801700000001",
        )
        # Same user, but messaging in a DM — must be rejected.
        resp = self._post(
            sender_phone="8809999999999",
            group_jid="", is_group=False, body="send the offer email",
        )
        self.assertEqual(resp.json()["action"], "discarded_unauthorized")

    def test_delegated_member_in_other_group_is_dropped(self):
        """Per spec: group authorization is scoped to one group only."""
        from apps.authz.services import grant_group_access

        grant_group_access(
            group_jid="group-a@g.us",
            member_phone="8809999999999",
            granted_by_phone="8801700000001",
        )
        # Same user speaking in a *different* group — must be rejected.
        resp = self._post(
            sender_phone="8809999999999",
            group_jid="group-b@g.us",
            body="rank cvs",
        )
        self.assertEqual(resp.json()["action"], "discarded_unauthorized")


@override_settings(AUTHORIZED_OPERATORS=_OPS)
class TestAuthorizationCommands(TestCase):
    """The webhook recognises authorize / revoke / list commands."""

    def setUp(self):
        self.client = Client()
        self.url = "/api/messaging/webhook/"

    @patch("apps.messaging.views.get_wa_client")
    def test_core_op_grants_in_group(self, mock_wa):
        from apps.authz.models import GroupMembership

        body = {
            "message_id":   "auth-1",
            "sender_phone": "8801700000001",   # core op
            "sender_name":  "Op One",
            "group_jid":    "team@g.us",
            "is_group":     True,
            "body":         "authorize +880 1888-555000",
        }
        resp = self.client.post(self.url, data=json.dumps(body),
                                content_type="application/json")
        self.assertEqual(resp.json()["action"], "auth_command")
        m = GroupMembership.objects.get(group_jid="team@g.us")
        self.assertEqual(m.member_phone, "8801888555000")
        self.assertEqual(m.granted_by, "8801700000001")

    @patch("apps.messaging.views.get_wa_client")
    def test_grant_via_quoted_reply(self, mock_wa):
        """A core op can authorize someone by replying to their message."""
        from apps.authz.models import GroupMembership

        body = {
            "message_id":   "auth-2",
            "sender_phone": "8801700000001",
            "sender_name":  "Op One",
            "group_jid":    "team@g.us",
            "is_group":     True,
            "body":         "authorize this person",
            "quoted_phone": "8801555111222",
            "quoted_name":  "New Hire",
        }
        resp = self.client.post(self.url, data=json.dumps(body),
                                content_type="application/json")
        self.assertEqual(resp.json()["action"], "auth_command")
        m = GroupMembership.objects.get(group_jid="team@g.us")
        self.assertEqual(m.member_phone, "8801555111222")
        self.assertEqual(m.member_name, "New Hire")

    @patch("apps.messaging.views.get_wa_client")
    def test_non_core_cannot_grant(self, mock_wa):
        """A delegated member cannot promote others — only core ops can."""
        from apps.authz.models import GroupMembership
        from apps.authz.services import grant_group_access

        # First: core op delegates Bob.
        grant_group_access(
            group_jid="team@g.us",
            member_phone="8801555111222",
            granted_by_phone="8801700000001",
        )
        # Now Bob tries to promote Carol — must be rejected.
        body = {
            "message_id":   "auth-3",
            "sender_phone": "8801555111222",   # delegated, not core
            "sender_name":  "Bob",
            "group_jid":    "team@g.us",
            "is_group":     True,
            "body":         "authorize +880 1444-000999",
        }
        resp = self.client.post(self.url, data=json.dumps(body),
                                content_type="application/json")
        self.assertEqual(resp.json()["action"], "auth_command")
        # No new membership created.
        self.assertEqual(
            GroupMembership.objects.filter(member_phone="8801444000999").count(),
            0,
        )

    @patch("apps.messaging.views.get_wa_client")
    def test_grant_in_dm_is_refused(self, mock_wa):
        """Authorization can only be granted inside a group, never in a DM."""
        from apps.authz.models import GroupMembership

        body = {
            "message_id":   "auth-4",
            "sender_phone": "8801700000001",
            "sender_name":  "Op One",
            "group_jid":    "",
            "is_group":     False,
            "body":         "authorize +880 1444-000999",
        }
        resp = self.client.post(self.url, data=json.dumps(body),
                                content_type="application/json")
        self.assertEqual(resp.json()["action"], "auth_command")
        self.assertEqual(GroupMembership.objects.count(), 0)

    @patch("apps.messaging.views.get_wa_client")
    def test_revoke_command(self, mock_wa):
        from apps.authz.models import MembershipStatus
        from apps.authz.services import grant_group_access

        grant_group_access(
            group_jid="team@g.us",
            member_phone="8801555111222",
            granted_by_phone="8801700000001",
        )
        body = {
            "message_id":   "auth-5",
            "sender_phone": "8801700000001",
            "sender_name":  "Op One",
            "group_jid":    "team@g.us",
            "is_group":     True,
            "body":         "revoke +880 1555-111222",
        }
        resp = self.client.post(self.url, data=json.dumps(body),
                                content_type="application/json")
        self.assertEqual(resp.json()["action"], "auth_command")
        from apps.authz.models import GroupMembership
        m = GroupMembership.objects.get(member_phone="8801555111222")
        self.assertEqual(m.status, MembershipStatus.REVOKED)


class TestIntentParser(TestCase):
    """Intent classification falls back to the dynamic agent on failure."""

    @patch("apps.messaging.intent_parser.get_llm_client")
    def test_valid_intent_parsed(self, mock_llm_factory):
        from apps.messaging.intent_parser import parse_intent

        mock_llm = MagicMock()
        mock_llm.complete.return_value = json.dumps({
            "task_type": "email_outbound",
            "params": {"recipient_email": "a@b.com",
                       "template_hint": "offer"},
            "is_ambiguous": False,
            "clarification_question": None,
        })
        mock_llm_factory.return_value = mock_llm

        intent = parse_intent("Send an offer email to a@b.com for 50000 BDT")
        self.assertEqual(intent["task_type"], "email_outbound")
        self.assertFalse(intent["is_ambiguous"])

    @patch("apps.messaging.intent_parser.get_llm_client")
    def test_llm_failure_falls_back_to_dynamic(self, mock_llm_factory):
        """When the classifier LLM crashes, hand the raw instruction to
        the dynamic agent rather than rejecting outright."""
        from apps.messaging.intent_parser import parse_intent

        mock_llm = MagicMock()
        mock_llm.complete.side_effect = RuntimeError("LLM down")
        mock_llm_factory.return_value = mock_llm

        intent = parse_intent("Find email titled X and download CVs")
        self.assertEqual(intent["task_type"], "dynamic")
        self.assertFalse(intent["is_ambiguous"])
        self.assertIn("instruction", intent["params"])