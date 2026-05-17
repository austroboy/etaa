"""Tests – LLM Client (failover logic)."""

from unittest.mock import MagicMock, patch, PropertyMock

from django.test import TestCase

from apps.llm_client import LLMClient


class TestLLMClientFailover(TestCase):

    def _make_client(self, primary="openai"):
        client = LLMClient.__new__(LLMClient)
        client.primary = primary
        client.oai_key = "sk-test"
        client.anth_key = "sk-ant-test"
        return client

    @patch.object(LLMClient, "_openai", return_value="OpenAI response")
    def test_openai_primary_succeeds(self, mock_openai):
        client = self._make_client(primary="openai")
        result = client.complete("test prompt")
        self.assertEqual(result, "OpenAI response")
        mock_openai.assert_called_once()

    @patch.object(LLMClient, "_anthropic", return_value="Anthropic response")
    @patch.object(LLMClient, "_openai", side_effect=RuntimeError("OpenAI down"))
    def test_openai_fails_falls_back_to_anthropic(self, mock_openai, mock_anthropic):
        client = self._make_client(primary="openai")
        result = client.complete("test prompt")
        self.assertEqual(result, "Anthropic response")
        mock_openai.assert_called_once()
        mock_anthropic.assert_called_once()

    @patch.object(LLMClient, "_anthropic", side_effect=RuntimeError("Anthropic down"))
    @patch.object(LLMClient, "_openai", side_effect=RuntimeError("OpenAI down"))
    def test_both_fail_raises_runtime_error(self, mock_openai, mock_anthropic):
        client = self._make_client(primary="openai")
        with self.assertRaises(RuntimeError) as ctx:
            client.complete("test prompt")
        self.assertIn("All LLM providers failed", str(ctx.exception))

    @patch.object(LLMClient, "_openai", return_value="OpenAI response")
    @patch.object(LLMClient, "_anthropic", return_value="Anthropic response")
    def test_anthropic_primary_tries_anthropic_first(self, mock_anthropic, mock_openai):
        client = self._make_client(primary="anthropic")
        result = client.complete("test prompt")
        self.assertEqual(result, "Anthropic response")
        mock_anthropic.assert_called_once()
        mock_openai.assert_not_called()


class TestFenceStripping(TestCase):
    """The intent classifier and SRS analyzer expect bare JSON. The
    LLM sometimes wraps its reply in Markdown code fences. The client
    must strip them so downstream json.loads doesn't blow up."""

    def test_plain_text_passes_through(self):
        from apps.llm_client import _strip_code_fence
        self.assertEqual(_strip_code_fence("hello world"), "hello world")
        self.assertEqual(_strip_code_fence('{"a": 1}'), '{"a": 1}')

    def test_strips_json_fence(self):
        from apps.llm_client import _strip_code_fence
        text = '```json\n{"task_type": "email_outbound"}\n```'
        self.assertEqual(
            _strip_code_fence(text),
            '{"task_type": "email_outbound"}',
        )

    def test_strips_bare_fence(self):
        from apps.llm_client import _strip_code_fence
        text = '```\n{"x": 42}\n```'
        self.assertEqual(_strip_code_fence(text), '{"x": 42}')

    def test_strips_fence_with_leading_prose(self):
        from apps.llm_client import _strip_code_fence
        text = "Sure, here you go:\n\n```json\n{\"ok\": true}\n```"
        self.assertEqual(_strip_code_fence(text), '{"ok": true}')

    def test_handles_unbalanced_opening_fence(self):
        from apps.llm_client import _strip_code_fence
        # No closing fence – best-effort strip the opener.
        text = '```json\n{"x": 1}'
        result = _strip_code_fence(text)
        self.assertEqual(result, '{"x": 1}')
