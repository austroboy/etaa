"""Tests – Dynamic Agent Module (tools, dispatcher routing, runner)."""

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings


# ─── Tool registry ──────────────────────────────────────────────────────────

class TestToolRegistry(TestCase):

    def test_tools_are_registered(self):
        from apps.agent.tools import _REGISTRY

        # The set of tools the agent must always have available.
        expected = {
            "list_directory", "ensure_directory", "zip_files",
            "search_email_threads", "download_attachments_from_thread",
            "send_email", "send_whatsapp_text", "send_whatsapp_file",
            "rank_cvs", "download_from_google_drive",
            "move_file", "delete_file", "finish",
        }
        self.assertTrue(expected.issubset(set(_REGISTRY.keys())))

    def test_dangerous_tools_are_flagged(self):
        from apps.agent.tools import is_dangerous

        self.assertTrue(is_dangerous("send_email"))
        self.assertTrue(is_dangerous("delete_file"))
        self.assertTrue(is_dangerous("move_file"))

        self.assertFalse(is_dangerous("list_directory"))
        self.assertFalse(is_dangerous("zip_files"))
        self.assertFalse(is_dangerous("send_whatsapp_text"))
        self.assertFalse(is_dangerous("finish"))

    def test_schemas_have_correct_format(self):
        """Schemas must be valid for both OpenAI and Anthropic APIs."""
        from apps.agent.tools import (
            get_tool_schemas,
            get_tool_schemas_anthropic,
        )

        openai_schemas = get_tool_schemas()
        for s in openai_schemas:
            self.assertEqual(s["type"], "function")
            self.assertIn("name", s["function"])
            self.assertIn("parameters", s["function"])

        anthropic_schemas = get_tool_schemas_anthropic()
        for s in anthropic_schemas:
            self.assertIn("name", s)
            self.assertIn("input_schema", s)


# ─── Filesystem tools ───────────────────────────────────────────────────────


@override_settings(
    OUTPUT_DIR="/tmp/etaa_test_outputs",
    CV_TEMP_DIR="/tmp/etaa_test_cvs",
    CODE_OUT_DIR="/tmp/etaa_test_code",
)
class TestFilesystemTools(TestCase):

    def test_zip_files_bundles_files(self):
        from apps.agent.tools import zip_files

        with tempfile.TemporaryDirectory() as td:
            f1 = os.path.join(td, "a.txt"); open(f1, "w").write("alpha")
            f2 = os.path.join(td, "b.txt"); open(f2, "w").write("beta")
            zip_path = os.path.join(td, "out.zip")

            result = zip_files([f1, f2], zip_path)

            self.assertTrue(result["ok"])
            self.assertEqual(result["files_added"], 2)
            self.assertTrue(os.path.isfile(zip_path))

    def test_zip_files_skips_missing(self):
        from apps.agent.tools import zip_files

        with tempfile.TemporaryDirectory() as td:
            f1 = os.path.join(td, "a.txt"); open(f1, "w").write("alpha")
            zip_path = os.path.join(td, "out.zip")

            result = zip_files(
                [f1, os.path.join(td, "missing.txt")],
                zip_path,
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["files_added"], 1)
            self.assertEqual(len(result["files_skipped"]), 1)

    def test_list_directory_returns_items(self):
        from apps.agent.tools import list_directory

        with tempfile.TemporaryDirectory() as td:
            open(os.path.join(td, "x.txt"), "w").close()
            open(os.path.join(td, "y.pdf"), "w").close()
            os.makedirs(os.path.join(td, "subdir"))

            result = list_directory(td)
            names = {item["name"] for item in result["items"]}
            self.assertEqual(names, {"x.txt", "y.pdf", "subdir"})

    def test_list_directory_pattern_filter(self):
        from apps.agent.tools import list_directory

        with tempfile.TemporaryDirectory() as td:
            open(os.path.join(td, "x.txt"), "w").close()
            open(os.path.join(td, "y.pdf"), "w").close()

            result = list_directory(td, pattern="*.pdf")
            names = {item["name"] for item in result["items"]}
            self.assertEqual(names, {"y.pdf"})

    def test_ensure_directory_creates_path(self):
        from apps.agent.tools import ensure_directory

        with tempfile.TemporaryDirectory() as td:
            target = os.path.join(td, "deeply", "nested", "path")
            result = ensure_directory(target)
            self.assertTrue(result["ok"])
            self.assertTrue(os.path.isdir(target))

    def test_path_allowed_blocks_system_paths(self):
        from apps.agent.tools import ensure_directory

        result = ensure_directory("/etc/test_etaa_should_fail")
        self.assertFalse(result["ok"])
        self.assertIn("not allowed", result["error"])


# ─── call_tool dispatcher ──────────────────────────────────────────────────


class TestCallTool(TestCase):

    def test_unknown_tool_returns_error(self):
        from apps.agent.tools import call_tool

        result = call_tool("nonexistent_tool", {})
        self.assertFalse(result["ok"])
        self.assertIn("Unknown tool", result["error"])

    def test_bad_arguments_returns_error(self):
        from apps.agent.tools import call_tool

        # `zip_files` requires file_paths and output_zip_path
        result = call_tool("zip_files", {})
        self.assertFalse(result["ok"])

    def test_finish_returns_summary(self):
        from apps.agent.tools import call_tool

        result = call_tool("finish", {"summary": "all done"})
        self.assertTrue(result["ok"])
        self.assertTrue(result["final"])
        self.assertEqual(result["summary"], "all done")


# ─── Dispatcher routing ────────────────────────────────────────────────────


class TestDispatcherRoutesDynamic(TestCase):
    """The dispatcher must hand free-form tasks to the agent runner."""

    @patch("apps.agent.tasks.run_agent_task")
    def test_dynamic_intent_routes_to_agent(self, mock_run):
        from apps.messaging.dispatcher import dispatch

        mock_run.delay = MagicMock()
        intent = {
            "task_type": "dynamic",
            "params": {
                "instruction":            "find email thread X and zip CVs",
                "needs_dangerous_tools":  False,
            },
            "is_ambiguous": False,
        }
        with patch("apps.messaging.dispatcher.get_wa_client"):
            dispatch(
                intent=intent,
                operator_phone="8801700000001",
                operator_name="Op One",
                raw_instruction="find email thread X and zip CVs",
                reply_jid="team@g.us",
            )
        mock_run.delay.assert_called_once()
        call_kwargs = mock_run.delay.call_args.kwargs
        self.assertEqual(
            call_kwargs["instruction"],
            "find email thread X and zip CVs",
        )
        self.assertEqual(call_kwargs["reply_jid"], "team@g.us")
        self.assertFalse(call_kwargs["allow_dangerous"])

    @patch("apps.messaging.dispatcher.create_confirmation")
    def test_dynamic_with_dangerous_flag_requires_confirmation(self, mock_conf):
        from apps.messaging.dispatcher import dispatch

        mock_conf.return_value = MagicMock(pk=42)
        intent = {
            "task_type": "dynamic",
            "params": {
                "instruction":            "delete all junk files in /tmp",
                "needs_dangerous_tools":  True,
            },
            "is_ambiguous": False,
        }
        with patch("apps.messaging.dispatcher.get_wa_client") as mock_wa, \
             patch("apps.agent.tasks.run_agent_task") as mock_run:
            mock_run.delay = MagicMock()
            dispatch(
                intent=intent,
                operator_phone="8801700000001",
                operator_name="Op One",
                raw_instruction=intent["params"]["instruction"],
                reply_jid="team@g.us",
            )
            # Confirmation requested, agent NOT yet invoked.
            mock_conf.assert_called_once()
            mock_run.delay.assert_not_called()
            mock_wa.return_value.send_text.assert_called()

    @patch("apps.agent.tasks.run_agent_task")
    def test_dispatch_confirmed_runs_agent_with_dangerous_allowed(self, mock_run):
        """After approval, the agent runs with allow_dangerous=True."""
        from apps.messaging.dispatcher import dispatch_confirmed

        mock_run.delay = MagicMock()
        confirmation = MagicMock()
        confirmation.payload = {
            "intent": {
                "task_type": "dynamic",
                "params": {
                    "instruction":           "delete junk in /tmp",
                    "needs_dangerous_tools": True,
                },
            },
            "log_id": 1,
            "operator_phone": "8801700000001",
            "reply_jid": "team@g.us",
        }
        confirmation.operator_name = "Op One"

        with patch("apps.messaging.dispatcher.get_wa_client"):
            dispatch_confirmed(confirmation)

        mock_run.delay.assert_called_once()
        self.assertTrue(mock_run.delay.call_args.kwargs["allow_dangerous"])


# ─── Runner: mocked end-to-end ─────────────────────────────────────────────


@override_settings(PRIMARY_LLM_PROVIDER="openai", OPENAI_API_KEY="sk-test")
class TestAgentRunnerOpenAI(TestCase):
    """Verify the OpenAI tool-use loop drives a multi-step task to
    completion, blocks dangerous tools without confirmation, and
    truly executes the tool calls the LLM requests."""

    def _make_response(self, tool_calls=None, content=""):
        """Build a fake OpenAI ChatCompletion response."""
        msg = MagicMock()
        msg.tool_calls = tool_calls or []
        msg.content = content
        choice = MagicMock(); choice.message = msg
        resp = MagicMock(); resp.choices = [choice]
        return resp

    def _make_tool_call(self, call_id, name, args):
        tc = MagicMock()
        tc.id = call_id
        tc.function = MagicMock()
        tc.function.name = name
        tc.function.arguments = json.dumps(args)
        return tc

    @patch("openai.OpenAI")
    def test_two_step_task_completes_and_calls_finish(self, mock_openai_cls):
        """The agent should: (1) zip files, (2) call finish."""
        from apps.agent.runner import run_agent

        # Build two scripted responses: zip_files, then finish
        with tempfile.TemporaryDirectory() as td:
            f1 = os.path.join(td, "a.txt"); open(f1, "w").write("a")
            zip_path = os.path.join(td, "out.zip")

            tc1 = self._make_tool_call(
                "call_1", "zip_files",
                {"file_paths": [f1], "output_zip_path": zip_path},
            )
            tc2 = self._make_tool_call(
                "call_2", "finish",
                {"summary": "Zipped one file."},
            )
            client = MagicMock()
            client.chat.completions.create.side_effect = [
                self._make_response(tool_calls=[tc1]),
                self._make_response(tool_calls=[tc2]),
            ]
            mock_openai_cls.return_value = client

            run = run_agent(
                instruction="zip a.txt to out.zip then finish",
                operator_name="Op One",
                allow_dangerous=False,
            )

            self.assertEqual(run.status, "success")
            self.assertEqual(run.final_answer, "Zipped one file.")
            self.assertEqual(run.iterations, 2)
            # The agent actually made the zip:
            self.assertTrue(os.path.isfile(zip_path))

            # Both steps were recorded:
            steps = list(run.steps.all())
            self.assertEqual([s.tool_name for s in steps],
                             ["zip_files", "finish"])

    @patch("openai.OpenAI")
    def test_dangerous_tool_blocked_without_confirmation(self, mock_openai_cls):
        """When allow_dangerous=False, send_email returns an error
        instead of being executed. The LLM observes the error and is
        expected to ask the operator for confirmation (we simulate
        that by then calling finish)."""
        from apps.agent.runner import run_agent

        tc1 = self._make_tool_call(
            "call_1", "send_email",
            {
                "to_address": "x@y.com",
                "subject": "test",
                "body_html": "<p>hi</p>",
            },
        )
        tc2 = self._make_tool_call(
            "call_2", "finish",
            {"summary": "Asked operator to confirm before sending."},
        )
        client = MagicMock()
        client.chat.completions.create.side_effect = [
            self._make_response(tool_calls=[tc1]),
            self._make_response(tool_calls=[tc2]),
        ]
        mock_openai_cls.return_value = client

        with patch("apps.email_module.services.send_email") as mock_send:
            run = run_agent(
                instruction="email x@y.com",
                allow_dangerous=False,
            )
            # The actual SMTP send must NOT have happened.
            mock_send.assert_not_called()

        self.assertEqual(run.status, "success")
        # First step recorded the refusal.
        first = run.steps.get(step_number=1)
        self.assertEqual(first.tool_name, "send_email")
        self.assertFalse(first.success)
        self.assertIn("sensitive", first.error.lower())

    @patch("openai.OpenAI")
    def test_dangerous_tool_runs_when_allow_dangerous_true(self, mock_openai_cls):
        """After operator confirmation, send_email is allowed through."""
        from apps.agent.runner import run_agent

        tc1 = self._make_tool_call(
            "call_1", "send_email",
            {"to_address": "x@y.com", "subject": "t", "body_html": "<p>hi</p>"},
        )
        tc2 = self._make_tool_call(
            "call_2", "finish", {"summary": "Email sent."},
        )
        client = MagicMock()
        client.chat.completions.create.side_effect = [
            self._make_response(tool_calls=[tc1]),
            self._make_response(tool_calls=[tc2]),
        ]
        mock_openai_cls.return_value = client

        with patch("apps.email_module.services.send_email",
                   return_value=True) as mock_send:
            run = run_agent(instruction="email x@y.com", allow_dangerous=True)
            mock_send.assert_called_once()

        self.assertEqual(run.status, "success")
        first = run.steps.get(step_number=1)
        self.assertEqual(first.tool_name, "send_email")
        self.assertTrue(first.success)


@override_settings(PRIMARY_LLM_PROVIDER="openai", OPENAI_API_KEY="sk-test")
class TestAgentReplyJidContext(TestCase):
    """The send_whatsapp_text tool should default to the current run's
    reply_jid via the contextvar — so a task issued in group A gets its
    status updates posted back to group A, not the default group."""

    @patch("apps.messaging.whatsapp_client.get_wa_client")
    @patch("openai.OpenAI")
    def test_send_whatsapp_text_uses_context_reply_jid(
        self, mock_openai_cls, mock_wa,
    ):
        from apps.agent.runner import run_agent

        wa_client = MagicMock()
        wa_client.send_text.return_value = True
        mock_wa.return_value = wa_client

        tc1 = MagicMock()
        tc1.id = "c1"
        tc1.function = MagicMock()
        tc1.function.name = "send_whatsapp_text"
        tc1.function.arguments = json.dumps({"text": "status update"})
        tc2 = MagicMock()
        tc2.id = "c2"
        tc2.function = MagicMock()
        tc2.function.name = "finish"
        tc2.function.arguments = json.dumps({"summary": "ok"})

        msg1 = MagicMock(); msg1.tool_calls = [tc1]; msg1.content = ""
        msg2 = MagicMock(); msg2.tool_calls = [tc2]; msg2.content = ""
        choice1 = MagicMock(); choice1.message = msg1
        choice2 = MagicMock(); choice2.message = msg2
        resp1 = MagicMock(); resp1.choices = [choice1]
        resp2 = MagicMock(); resp2.choices = [choice2]

        client = MagicMock()
        client.chat.completions.create.side_effect = [resp1, resp2]
        mock_openai_cls.return_value = client

        run_agent(
            instruction="say hi",
            reply_jid="caller-group@g.us",
        )

        # The tool received NO explicit jid, but contextvar steered it
        # to caller-group@g.us.
        wa_client.send_text.assert_called_once()
        kwargs = wa_client.send_text.call_args.kwargs
        self.assertEqual(kwargs.get("jid"), "caller-group@g.us")
