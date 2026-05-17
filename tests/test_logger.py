"""Tests – Logger Module."""

from django.test import TestCase

from apps.logger_module.models import ActionLog, TaskType, TaskStatus
from apps.logger_module.services import log_action, update_log


class TestLoggerService(TestCase):

    def test_log_action_creates_record(self):
        log = log_action(
            instruction_text="Send email to client@example.com",
            task_type=TaskType.EMAIL_OUTBOUND,
            status=TaskStatus.PENDING,
            operator_name="Zihad",
            operator_phone="8801700000001",
        )
        self.assertIsNotNone(log.pk)
        self.assertEqual(log.task_type, TaskType.EMAIL_OUTBOUND)
        self.assertEqual(log.status, TaskStatus.PENDING)
        self.assertEqual(log.operator_name, "Zihad")

    def test_update_log_changes_status(self):
        log = log_action(
            instruction_text="Test task",
            task_type=TaskType.CV_RANKING,
            status=TaskStatus.PENDING,
        )
        update_log(log.pk, status=TaskStatus.SUCCESS, output_location="/tmp/results.zip")
        refreshed = ActionLog.objects.get(pk=log.pk)
        self.assertEqual(refreshed.status, TaskStatus.SUCCESS)
        self.assertEqual(refreshed.output_location, "/tmp/results.zip")

    def test_log_with_extra_data(self):
        log = log_action(
            instruction_text="Code gen",
            task_type=TaskType.CODE_GEN,
            status=TaskStatus.IN_PROGRESS,
            extra_data={"project_name": "test_app", "apps_count": 3},
        )
        self.assertEqual(log.extra_data["project_name"], "test_app")

    def test_log_list_api(self):
        from django.test import Client
        log_action("Test", TaskType.EMAIL_OUTBOUND, TaskStatus.SUCCESS)
        c = Client()
        resp = c.get("/api/logs/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("logs", data)
        self.assertGreaterEqual(len(data["logs"]), 1)
