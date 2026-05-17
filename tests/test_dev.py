"""Tests – Dev Module (SRS analysis, code generation, git push)."""

import os
import tempfile
from unittest.mock import MagicMock, patch, call

from django.test import TestCase


class TestSRSAnalysis(TestCase):

    @patch("apps.dev_module.services.get_llm_client")
    def test_analyze_srs_returns_plan(self, mock_llm_factory):
        import json
        from apps.dev_module.services import analyze_srs

        plan = {
            "project_name": "test_project",
            "description": "A test app",
            "tech_stack": "django",
            "apps": [
                {
                    "name": "core",
                    "models": ["User: name CharField, email EmailField"],
                    "views": ["UserListView: list all users"],
                    "endpoints": ["GET /api/users/ – list users"],
                }
            ],
            "additional_features": [],
            "requirements": ["django>=4.2"],
        }
        mock_llm = MagicMock()
        mock_llm.complete.return_value = json.dumps(plan)
        mock_llm_factory.return_value = mock_llm

        result = analyze_srs("This SRS describes a user management system.")
        self.assertEqual(result["project_name"], "test_project")
        self.assertEqual(len(result["apps"]), 1)

    @patch("apps.dev_module.services.get_llm_client")
    def test_analyze_srs_llm_failure_raises(self, mock_llm_factory):
        from apps.dev_module.services import analyze_srs

        mock_llm = MagicMock()
        mock_llm.complete.side_effect = RuntimeError("LLM down")
        mock_llm_factory.return_value = mock_llm

        with self.assertRaises(ValueError):
            analyze_srs("some srs text")


class TestProjectGeneration(TestCase):

    @patch("apps.dev_module.services.get_llm_client")
    def test_generate_project_creates_files(self, mock_llm_factory):
        from apps.dev_module.services import generate_project

        mock_llm = MagicMock()
        mock_llm.complete.return_value = "# Generated file content\npass\n"
        mock_llm_factory.return_value = mock_llm

        plan = {
            "project_name": "my_test_app",
            "description": "A test application",
            "tech_stack": "django",
            "apps": [
                {
                    "name": "tasks",
                    "models": ["Task: title CharField, done BooleanField"],
                    "views": ["TaskListView: list tasks"],
                    "endpoints": ["GET /api/tasks/ – list"],
                }
            ],
            "requirements": ["django>=4.2"],
        }

        with tempfile.TemporaryDirectory() as tmp:
            project_dir = generate_project(plan, "srs text here", tmp)

            # Key files should exist
            self.assertTrue(os.path.isdir(project_dir))
            self.assertTrue(os.path.isfile(os.path.join(project_dir, "requirements.txt")))
            self.assertTrue(os.path.isfile(os.path.join(project_dir, "manage.py")))
            self.assertTrue(os.path.isfile(os.path.join(project_dir, "README.md")))
            self.assertTrue(os.path.isfile(os.path.join(project_dir, "Dockerfile")))
            self.assertTrue(os.path.isfile(os.path.join(project_dir, ".env.example")))

            # App files
            app_dir = os.path.join(project_dir, "apps", "tasks")
            self.assertTrue(os.path.isfile(os.path.join(app_dir, "models.py")))
            self.assertTrue(os.path.isfile(os.path.join(app_dir, "views.py")))
            self.assertTrue(os.path.isfile(os.path.join(app_dir, "urls.py")))
            self.assertTrue(os.path.isfile(os.path.join(app_dir, "serializers.py")))
            self.assertTrue(os.path.isfile(os.path.join(app_dir, "admin.py")))


class TestGitPush(TestCase):

    @patch("apps.dev_module.services.subprocess.run")
    def test_git_push_success(self, mock_run):
        from apps.dev_module.services import git_push

        mock_run.return_value = MagicMock(returncode=0, stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            result = git_push(tmp, "https://github.com/test/repo.git")
        self.assertTrue(result)

    @patch("apps.dev_module.services.subprocess.run")
    def test_git_push_failure_returns_false(self, mock_run):
        from apps.dev_module.services import git_push

        # Simulate commit success but push failure
        def side_effect(cmd, **kwargs):
            m = MagicMock()
            if "push" in cmd:
                m.returncode = 1
                m.stderr = "remote: Permission denied"
            else:
                m.returncode = 0
                m.stderr = ""
            return m

        mock_run.side_effect = side_effect

        with tempfile.TemporaryDirectory() as tmp:
            result = git_push(tmp, "https://github.com/test/repo.git")
        self.assertFalse(result)
