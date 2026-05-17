"""Tests – Job Post Module."""

from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.job_post_module.services import generate_job_description


class TestJobDescriptionGeneration(TestCase):

    @patch("apps.job_post_module.services.get_llm_client")
    def test_generate_job_description_returns_html(self, mock_llm_factory):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = "<h2>Software Engineer</h2><p>We are hiring...</p>"
        mock_llm_factory.return_value = mock_llm

        result = generate_job_description(
            job_title="Software Engineer",
            department="Engineering",
            responsibilities="Build Django APIs",
            qualifications="3+ years Python",
            salary_range="50,000-80,000 BDT",
        )
        self.assertIn("Software Engineer", result)
        mock_llm.complete.assert_called_once()

    @patch("apps.job_post_module.services.get_llm_client")
    def test_generate_job_description_passes_correct_fields(self, mock_llm_factory):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = "<p>Job description</p>"
        mock_llm_factory.return_value = mock_llm

        generate_job_description(
            job_title="Data Analyst",
            department="Analytics",
            responsibilities="Analyze data",
            qualifications="SQL, Python",
            salary_range="40,000 BDT",
            company_info="Zihad IT Ltd",
        )

        call_args = mock_llm.complete.call_args
        prompt = call_args[0][0] if call_args[0] else call_args[1].get("prompt", "")
        self.assertIn("Data Analyst", prompt)
        self.assertIn("Zihad IT Ltd", prompt)


class TestCanvaClient(TestCase):

    @patch("apps.job_post_module.services.requests.post")
    @patch("apps.job_post_module.services.settings")
    def test_create_design_returns_id(self, mock_settings, mock_post):
        from apps.job_post_module.services import CanvaClient

        mock_settings.CANVA_API_KEY = "test-key"
        mock_settings.CANVA_TEMPLATE_ID = "tmpl-123"

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"design": {"id": "design-abc-123"}}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        client = CanvaClient()
        design_id = client.create_design_from_template("Software Engineer", "Job desc text")
        self.assertEqual(design_id, "design-abc-123")

    @patch("apps.job_post_module.services.settings")
    def test_create_design_without_api_key_returns_none(self, mock_settings):
        from apps.job_post_module.services import CanvaClient

        mock_settings.CANVA_API_KEY = ""
        mock_settings.CANVA_TEMPLATE_ID = ""

        client = CanvaClient()
        result = client.create_design_from_template("Test", "text")
        self.assertIsNone(result)
