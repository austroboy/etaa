"""Tests – Confirmation Module."""

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.confirmation.models import PendingConfirmation, ConfirmationStatus
from apps.confirmation.services import (
    create_confirmation,
    process_confirmation_response,
    expire_stale_confirmations,
)


class TestConfirmationService(TestCase):

    def _make_confirmation(self, phone="8801700000001", expired=False):
        expires = timezone.now() + timedelta(seconds=-1 if expired else 300)
        return PendingConfirmation.objects.create(
            task_type="email_outbound",
            description="Send an offer email",
            payload={"test": True},
            operator_phone=phone,
            expires_at=expires,
        )

    def test_create_confirmation(self):
        c = create_confirmation(
            task_type="email_outbound",
            description="Test action",
            payload={"x": 1},
            operator_phone="8801700000001",
            operator_name="Test Op",
        )
        self.assertEqual(c.status, ConfirmationStatus.PENDING)
        self.assertEqual(c.task_type, "email_outbound")

    def test_affirmative_response_approves(self):
        self._make_confirmation()
        result = process_confirmation_response("8801700000001", "yes")
        self.assertIsNotNone(result)
        self.assertEqual(result.status, ConfirmationStatus.APPROVED)

    def test_negative_response_denies(self):
        self._make_confirmation()
        result = process_confirmation_response("8801700000001", "no")
        self.assertIsNotNone(result)
        self.assertEqual(result.status, ConfirmationStatus.DENIED)

    def test_unrelated_message_returns_none(self):
        self._make_confirmation()
        result = process_confirmation_response("8801700000001", "hello world how are you")
        self.assertIsNone(result)

    def test_expired_confirmation_not_resolved(self):
        self._make_confirmation(expired=True)
        result = process_confirmation_response("8801700000001", "yes")
        self.assertIsNone(result)

    def test_expire_stale_confirmations(self):
        self._make_confirmation(expired=True)
        self._make_confirmation(expired=True)
        self._make_confirmation(expired=False)  # should NOT be expired
        count = expire_stale_confirmations()
        self.assertEqual(count, 2)

    def test_no_pending_confirmation_returns_none(self):
        result = process_confirmation_response("8809999999999", "yes")
        self.assertIsNone(result)
