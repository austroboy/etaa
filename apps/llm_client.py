"""
ETAA LLM Client.

Unified interface to OpenAI GPT-4 and Anthropic Claude with automatic
failover. Both provider responses are de-fenced before returning so
downstream JSON-parsing code (intent classifier, agent runner, SRS
analyzer) doesn't trip over Markdown ``` blocks the model sometimes
wraps its output in.
"""

import logging
import re
import time
from typing import Optional

from django.conf import settings

logger = logging.getLogger("etaa")


def _strip_code_fence(text: str) -> str:
    """
    If the model wrapped its reply in ```json ... ``` (or just ```...```),
    return the inner content. Otherwise return the text unchanged.

    Handles all the common variants:
        ```json\n{...}\n```
        ```\n{...}\n```
        plain "{...}"
        leading prose then a fenced JSON block
    """
    text = text.strip()
    if "```" not in text:
        return text

    # Match the first fenced block, with or without a language tag.
    m = re.search(r"```(?:json|JSON)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        return m.group(1).strip()

    # Unbalanced fence – best-effort: drop fences and language tag.
    cleaned = re.sub(r"^```(?:json|JSON)?\s*", "", text)
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    return cleaned.strip()


class LLMClient:
    """Unified LLM client supporting OpenAI and Anthropic with fallback.

    Per-call model override: pass ``model=LLMClient.ANTHROPIC_HAIKU_MODEL``
    to use Haiku for cost-sensitive bulk work like CV scoring while
    keeping Sonnet for accuracy-critical tasks like intent classification.
    """

    OPENAI_MODEL          = "gpt-4o"
    ANTHROPIC_MODEL       = "claude-sonnet-4-5-20250929"  # default, accuracy-first
    ANTHROPIC_HAIKU_MODEL = "claude-haiku-4-5-20251001"   # 3x cheaper, ~95% as accurate

    def __init__(self):
        self.primary  = settings.PRIMARY_LLM_PROVIDER
        self.oai_key  = settings.OPENAI_API_KEY
        self.anth_key = settings.ANTHROPIC_API_KEY

    # ── public interface ────────────────────────────────────────────────────

    def complete(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.3,
        model: str = "",
        cache_system: bool = False,
    ) -> str:
        """
        Send a completion request, falling back to the secondary provider
        if the primary fails. Returns the text response (with any
        Markdown code fences stripped).

        :param model: Optional model override (e.g. ANTHROPIC_HAIKU_MODEL).
                      Only honoured when the active provider is Anthropic.
                      OpenAI calls always use OPENAI_MODEL.
        :param cache_system: When True and provider is Anthropic, marks the
                      system prompt as cacheable. After the first call,
                      subsequent calls within ~5 min that share the exact
                      same system prompt pay 90% less for those tokens.
                      Useful for bulk CV scoring where the system prompt
                      is identical across hundreds of calls.
        """
        providers = (
            [self._openai, self._anthropic]
            if self.primary == "openai"
            else [self._anthropic, self._openai]
        )

        last_error: Optional[Exception] = None
        for provider_fn in providers:
            try:
                return provider_fn(prompt, system, max_tokens, temperature,
                                   model=model, cache_system=cache_system)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "LLM provider %s failed: %s",
                    getattr(provider_fn, "__name__", "?"), exc,
                )
                last_error = exc
                time.sleep(1)

        raise RuntimeError(
            f"All LLM providers failed. Last error: {last_error}"
        ) from last_error

    # ── private methods ─────────────────────────────────────────────────────

    def _openai(self, prompt: str, system: str,
                max_tokens: int, temperature: float,
                model: str = "", cache_system: bool = False) -> str:
        # OpenAI ignores the model override (we keep one OpenAI model
        # for simplicity) and ignores cache_system (Anthropic-specific).
        del model, cache_system  # unused for OpenAI path
        import openai  # imported lazily to keep startup fast

        client = openai.OpenAI(api_key=self.oai_key)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = client.chat.completions.create(
            model=self.OPENAI_MODEL,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        text = response.choices[0].message.content or ""
        logger.info(
            "OpenAI usage – prompt_tokens=%s completion_tokens=%s",
            response.usage.prompt_tokens,
            response.usage.completion_tokens,
        )
        return _strip_code_fence(text)

    def _anthropic(self, prompt: str, system: str,
                   max_tokens: int, temperature: float,
                   model: str = "", cache_system: bool = False) -> str:
        import anthropic  # imported lazily

        client = anthropic.Anthropic(api_key=self.anth_key)
        kwargs = {
            "model":       model or self.ANTHROPIC_MODEL,
            "max_tokens":  max_tokens,
            "temperature": temperature,
            "messages":    [{"role": "user", "content": prompt}],
        }
        if system:
            if cache_system:
                # Mark the system prompt as cacheable. Anthropic caches
                # it for ~5 min; subsequent calls with the same system
                # text pay 90% less for those tokens.
                kwargs["system"] = [{
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }]
            else:
                kwargs["system"] = system

        response = client.messages.create(**kwargs)
        text = response.content[0].text if response.content else ""

        # Log usage including cache hit/miss when caching was requested.
        usage = response.usage
        cache_read    = getattr(usage, "cache_read_input_tokens",     None)
        cache_create  = getattr(usage, "cache_creation_input_tokens", None)
        if cache_read is not None or cache_create is not None:
            logger.info(
                "Anthropic usage – input=%s output=%s "
                "cache_read=%s cache_create=%s model=%s",
                usage.input_tokens, usage.output_tokens,
                cache_read or 0, cache_create or 0,
                kwargs["model"],
            )
        else:
            logger.info(
                "Anthropic usage – input_tokens=%s output_tokens=%s model=%s",
                usage.input_tokens, usage.output_tokens, kwargs["model"],
            )
        logger.debug("Anthropic raw response: %r", text[:200])
        return _strip_code_fence(text)


# Module-level singleton
_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client