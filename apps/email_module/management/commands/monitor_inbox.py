"""
Management command: monitor_inbox
Polls the configured email inbox for unread messages and auto-replies.
Run continuously: python manage.py monitor_inbox
"""

import logging
import time

from django.core.management.base import BaseCommand

logger = logging.getLogger("etaa")


class Command(BaseCommand):
    help = "Continuously monitors the inbox and auto-replies to incoming emails."

    def add_arguments(self, parser):
        parser.add_argument(
            "--interval",
            type=int,
            default=60,
            help="Polling interval in seconds (default: 60)",
        )

    def handle(self, *args, **options):
        interval = options["interval"]
        self.stdout.write(f"[ETAA] Inbox monitor started. Polling every {interval}s.")

        while True:
            try:
                from apps.email_module.tasks import process_inbox_task
                from apps.logger_module.services import log_action

                log = log_action(
                    instruction_text="[auto] inbox monitor poll",
                    task_type="email_inbound",
                    status="pending",
                    operator_name="system",
                )
                process_inbox_task.delay(log.pk)
                self.stdout.write(f"[ETAA] Inbox check dispatched (log #{log.pk}).")

            except Exception as exc:  # noqa: BLE001
                logger.error("Inbox monitor error: %s", exc)
                self.stderr.write(f"[ETAA] Monitor error: {exc}")

            time.sleep(interval)
