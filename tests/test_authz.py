"""Tests – Authorization Module (two-tier auth + command parser)."""

from django.test import TestCase, override_settings

from apps.authz.models import (
    AuthorizationEvent,
    GroupMembership,
    MembershipStatus,
)
from apps.authz.services import (
    check_authorization,
    grant_group_access,
    list_group_members,
    normalize_phone,
    parse_auth_command,
    revoke_group_access,
)


_OPS = {
    "8801700000001": "Op One",
    "8801700000002": "Op Two",
    "8801700000003": "Op Three",
}


@override_settings(AUTHORIZED_OPERATORS=_OPS)
class TestPhoneNormalization(TestCase):
    def test_strips_plus_and_spaces(self):
        self.assertEqual(normalize_phone("+880 1700-000-001"), "8801700000001")
        self.assertEqual(normalize_phone("+1 (415) 555-9999"), "14155559999")
        self.assertEqual(normalize_phone(""), "")
        self.assertEqual(normalize_phone(None), "")


@override_settings(AUTHORIZED_OPERATORS=_OPS)
class TestCheckAuthorization(TestCase):
    """The decision function used by every webhook request."""

    def test_core_op_in_dm_is_authorized(self):
        d = check_authorization(
            sender_phone="8801700000001",
            sender_name="Anything",
            group_jid="",
            is_group=False,
        )
        self.assertTrue(d.authorized)
        self.assertTrue(d.is_core_op)
        self.assertFalse(d.is_delegated)
        # Display name comes from settings, not from the message header.
        self.assertEqual(d.display_name, "Op One")

    def test_core_op_in_any_group_is_authorized(self):
        d = check_authorization(
            sender_phone="+880-1700-000-002",
            group_jid="random-group@g.us",
            is_group=True,
        )
        self.assertTrue(d.authorized)
        self.assertTrue(d.is_core_op)

    def test_stranger_in_dm_is_rejected(self):
        d = check_authorization(
            sender_phone="8809999999999",
            group_jid="", is_group=False,
        )
        self.assertFalse(d.authorized)
        self.assertIn("Not a core operator", d.reason)

    def test_stranger_in_group_without_membership_is_rejected(self):
        d = check_authorization(
            sender_phone="8809999999999",
            group_jid="team@g.us", is_group=True,
        )
        self.assertFalse(d.authorized)
        self.assertIn("No active group membership", d.reason)

    def test_delegated_member_is_authorized_only_in_their_group(self):
        grant_group_access(
            group_jid="team@g.us",
            member_phone="8801555111222",
            granted_by_phone="8801700000001",
            member_name="Delegate",
        )
        # Inside the group: authorized.
        d_in = check_authorization(
            sender_phone="8801555111222",
            group_jid="team@g.us", is_group=True,
        )
        self.assertTrue(d_in.authorized)
        self.assertTrue(d_in.is_delegated)
        self.assertFalse(d_in.is_core_op)
        self.assertEqual(d_in.display_name, "Delegate")

        # Same person, different group: rejected.
        d_other = check_authorization(
            sender_phone="8801555111222",
            group_jid="other-group@g.us", is_group=True,
        )
        self.assertFalse(d_other.authorized)

        # Same person, DM: rejected.
        d_dm = check_authorization(
            sender_phone="8801555111222",
            group_jid="", is_group=False,
        )
        self.assertFalse(d_dm.authorized)

    def test_revoked_member_is_rejected(self):
        grant_group_access(
            group_jid="team@g.us",
            member_phone="8801555111222",
            granted_by_phone="8801700000001",
        )
        revoke_group_access(
            group_jid="team@g.us",
            member_phone="8801555111222",
            revoked_by_phone="8801700000001",
        )
        d = check_authorization(
            sender_phone="8801555111222",
            group_jid="team@g.us", is_group=True,
        )
        self.assertFalse(d.authorized)


@override_settings(AUTHORIZED_OPERATORS=_OPS)
class TestGrantRevokeFlow(TestCase):
    """End-to-end persistence and idempotency of the grant/revoke ops."""

    def test_grant_creates_membership_and_event(self):
        grant_group_access(
            group_jid="team@g.us",
            member_phone="+880 1555-111222",
            granted_by_phone="8801700000001",
            member_name="Bob",
        )
        m = GroupMembership.objects.get(group_jid="team@g.us")
        self.assertEqual(m.member_phone, "8801555111222")  # normalized
        self.assertEqual(m.member_name, "Bob")
        self.assertEqual(m.status, MembershipStatus.ACTIVE)

        ev = AuthorizationEvent.objects.get(
            kind=AuthorizationEvent.Kind.GRANTED,
        )
        self.assertEqual(ev.actor_phone, "8801700000001")
        self.assertEqual(ev.target_phone, "8801555111222")

    def test_grant_is_idempotent_on_active_member(self):
        """Re-granting an already-active member should not error."""
        grant_group_access(
            group_jid="team@g.us",
            member_phone="8801555111222",
            granted_by_phone="8801700000001",
        )
        grant_group_access(
            group_jid="team@g.us",
            member_phone="8801555111222",
            granted_by_phone="8801700000002",
            member_name="Bob (updated)",
        )
        self.assertEqual(GroupMembership.objects.count(), 1)

    def test_grant_reactivates_revoked_member(self):
        grant_group_access(
            group_jid="team@g.us",
            member_phone="8801555111222",
            granted_by_phone="8801700000001",
        )
        revoke_group_access(
            group_jid="team@g.us",
            member_phone="8801555111222",
            revoked_by_phone="8801700000001",
        )
        grant_group_access(
            group_jid="team@g.us",
            member_phone="8801555111222",
            granted_by_phone="8801700000002",
        )
        m = GroupMembership.objects.get(member_phone="8801555111222")
        self.assertEqual(m.status, MembershipStatus.ACTIVE)
        self.assertTrue(AuthorizationEvent.objects.filter(
            kind=AuthorizationEvent.Kind.REACTIVATED).exists())

    def test_revoke_unknown_member_returns_false(self):
        ok = revoke_group_access(
            group_jid="team@g.us",
            member_phone="8801555111222",
            revoked_by_phone="8801700000001",
        )
        self.assertFalse(ok)

    def test_list_group_members_filters_revoked(self):
        grant_group_access("team@g.us", "8801111000001", "8801700000001")
        grant_group_access("team@g.us", "8801111000002", "8801700000001")
        revoke_group_access("team@g.us", "8801111000001", "8801700000001")

        active = list_group_members("team@g.us", active_only=True)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].member_phone, "8801111000002")

        all_m = list_group_members("team@g.us", active_only=False)
        self.assertEqual(len(all_m), 2)


class TestAuthCommandParser(TestCase):
    """The text-level parser doesn't enforce policy — that's the
    webhook's job — but it must reliably identify command intent."""

    def test_authorize_with_phone_in_text(self):
        cmd = parse_auth_command("authorize +880 1444-555888")
        self.assertEqual(cmd.action, "grant")
        self.assertEqual(cmd.target_phone, "8801444555888")

    def test_authorize_with_quoted_reply(self):
        cmd = parse_auth_command(
            "authorize this person",
            quoted_phone="8801444555888",
            quoted_name="Carol",
        )
        self.assertEqual(cmd.action, "grant")
        self.assertEqual(cmd.target_phone, "8801444555888")
        self.assertEqual(cmd.target_name, "Carol")

    def test_revoke_command(self):
        cmd = parse_auth_command("revoke 8801444555888")
        self.assertEqual(cmd.action, "revoke")
        self.assertEqual(cmd.target_phone, "8801444555888")

    def test_list_command(self):
        cmd = parse_auth_command("show authorized members")
        self.assertEqual(cmd.action, "list")
        self.assertEqual(cmd.target_phone, "")

    def test_authorize_without_target_is_ambiguous(self):
        """Verb present but no number / no quoted reply -> action is set
        but target_phone is empty so the webhook can ask for clarification."""
        cmd = parse_auth_command("authorize the new hire")
        self.assertEqual(cmd.action, "grant")
        self.assertEqual(cmd.target_phone, "")

    def test_normal_instruction_is_not_an_auth_command(self):
        """The parser must not misclassify 'authorize a refund', etc."""
        self.assertIsNone(parse_auth_command("send the offer email to a@b.com"))
        self.assertIsNone(parse_auth_command(
            "find the email thread titled 'hiring' and download all CVs"))
        # Tricky: 'approve' is a grant-pattern verb, but without a phone
        # number or quoted reply we treat it as ambiguous and let the
        # webhook decide. Ensure it doesn't return None either.
        cmd = parse_auth_command("please approve and proceed")
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd.action, "grant")
        self.assertEqual(cmd.target_phone, "")

    def test_short_numbers_are_ignored(self):
        """Order numbers, prices, etc. should not be picked up as phone
        numbers when there's no 'authorize' verb."""
        self.assertIsNone(parse_auth_command(
            "send invoice INV-12345 to client@example.com"))
