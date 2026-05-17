"""Tests – Email Module."""

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.email_module.services import (
    load_templates,
    render_template,
    select_template,
)


class TestEmailTemplates(TestCase):

    def setUp(self):
        # Create a temporary template directory
        self.tmp_dir = tempfile.mkdtemp()
        self.template_data = {
            "name": "test_offer",
            "keywords": ["offer", "proposal"],
            "subject": "Offer for {{recipient_name}} | {{company_name}}",
            "body": "<p>Dear {{recipient_name}}, price is {{price}}</p>",
        }
        with open(os.path.join(self.tmp_dir, "test_offer.json"), "w") as f:
            json.dump(self.template_data, f)

    @patch("apps.email_module.services.settings")
    def test_load_templates(self, mock_settings):
        mock_settings.EMAIL_TEMPLATES_DIR = self.tmp_dir
        templates = load_templates()
        self.assertIn("test_offer", templates)

    @patch("apps.email_module.services.settings")
    def test_select_template_by_keyword(self, mock_settings):
        mock_settings.EMAIL_TEMPLATES_DIR = self.tmp_dir
        templates = load_templates()
        tmpl = select_template("send an offer email", templates)
        self.assertIsNotNone(tmpl)
        self.assertEqual(tmpl["name"], "test_offer")

    @patch("apps.email_module.services.settings")
    def test_select_template_fallback(self, mock_settings):
        mock_settings.EMAIL_TEMPLATES_DIR = self.tmp_dir
        templates = load_templates()
        tmpl = select_template("some unrelated instruction", templates)
        # Should return first template as fallback
        self.assertIsNotNone(tmpl)

    def test_render_template(self):
        fields = {
            "recipient_name": "Karim Hossain",
            "price": "50,000",
        }
        with patch("apps.email_module.services.settings") as ms:
            ms.COMPANY_NAME = "Zihad IT"
            subject, body = render_template(self.template_data, fields)

        self.assertIn("Karim Hossain", subject)
        self.assertIn("Zihad IT", subject)
        self.assertIn("50,000", body)
        self.assertIn("Karim Hossain", body)

    def test_render_template_missing_field_leaves_empty(self):
        fields = {"recipient_name": "Ali"}  # price not provided
        with patch("apps.email_module.services.settings") as ms:
            ms.COMPANY_NAME = "Test Co"
            _, body = render_template(self.template_data, fields)
        # {{price}} placeholder should be replaced with empty string
        self.assertNotIn("{{price}}", body)


class TestEmailSend(TestCase):

    @patch("apps.email_module.services.smtplib.SMTP")
    def test_send_email_success(self, mock_smtp_cls):
        from apps.email_module.services import send_email

        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        with patch("apps.email_module.services.settings") as ms:
            ms.EMAIL_HOST = "smtp.gmail.com"
            ms.EMAIL_PORT = 587
            ms.EMAIL_HOST_USER = "test@gmail.com"
            ms.EMAIL_HOST_PASSWORD = "pass"
            ms.DEFAULT_FROM_EMAIL = "test@gmail.com"

            result = send_email("recipient@test.com", "Test Subject", "<p>Body</p>")

        # Should return True when no exception
        self.assertTrue(result)
