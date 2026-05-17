"""
Management command: run_agent

Run a free-form instruction through the dynamic agent loop directly from
the shell – useful for local testing without going through WhatsApp.

    python manage.py run_agent "list /tmp"
    python manage.py run_agent "find emails with subject 'Backend Hire' \\
        and download every CV attachment to /tmp/cvs, then zip to /tmp/cvs.zip" \\
        --allow-dangerous
"""

import json

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run an instruction through the dynamic agent and print the result."

    def add_arguments(self, parser):
        parser.add_argument("instruction", type=str)
        parser.add_argument(
            "--allow-dangerous",
            action="store_true",
            help="Permit sensitive tool calls (send_email, delete_file, etc.).",
        )
        parser.add_argument(
            "--operator",
            default="cli",
            help="Operator name to record on the AgentRun.",
        )

    def handle(self, *args, **options):
        from apps.agent.services import execute_instruction

        run = execute_instruction(
            instruction=options["instruction"],
            operator_name=options["operator"],
            allow_dangerous=options["allow_dangerous"],
        )

        self.stdout.write(self.style.SUCCESS(
            f"AgentRun #{run.pk} – status={run.status} "
            f"iterations={run.iterations}"
        ))
        if run.final_answer:
            self.stdout.write(f"\nFinal answer:\n  {run.final_answer}")
        if run.error_detail:
            self.stderr.write(f"\nError: {run.error_detail}")

        self.stdout.write("\nSteps:")
        for s in run.steps.all():
            self.stdout.write(
                f"  {s.step_number:>2}. {s.tool_name}"
                f"  args={json.dumps(s.tool_input)[:120]}"
                f"  -> ok={s.success}"
            )
