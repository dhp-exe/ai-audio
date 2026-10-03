"""Claude adapter through the official Anthropic SDK (optional: ``pip install -e .[claude]``).

Uses ``client.messages.parse(..., output_format=<Pydantic model>)``, which constrains the reply to
the schema and returns a validated instance. Current Claude models reject sampling parameters, so
``temperature`` is not sent. A refusal (``stop_reason == "refusal"``) is raised as ``LlmBlocked``;
there is no automatic model fallback here, the engine surfaces the failure on the step.
"""

from __future__ import annotations

import time

from emvoox.config import get_settings
from emvoox.providers.llm.base import LlmBlocked, LlmError, LlmSchemaError, LlmTruncated, T, Usage

DEFAULT_MODEL = "claude-opus-5"
MAX_TOKENS = 16_000  # non-streaming ceiling that stays inside the SDK's HTTP timeout


class AnthropicLlm:
    name = "anthropic"

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError as e:  # pragma: no cover - optional dependency
                raise LlmError("the 'anthropic' package is not installed; run: pip install -e '.[claude]'") from e
            key = self._api_key or get_settings().anthropic_api_key
            self._client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
        return self._client

    def generate_structured(self, *, system: str, user: str, schema: type[T], model: str | None = None,
                            temperature: float | None = None, max_output_tokens: int = MAX_TOKENS,
                            context: dict | None = None) -> tuple[T, Usage]:
        import anthropic

        settings = get_settings()
        model = model or (settings.llm_model if settings.llm_provider == "anthropic" else DEFAULT_MODEL)
        client = self._get_client()
        t0 = time.time()
        try:
            response = client.messages.parse(
                model=model,
                max_tokens=min(max_output_tokens, MAX_TOKENS),
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=schema,
            )
        except anthropic.RateLimitError as e:
            from emvoox.telemetry.events import record_event

            record_event("anthropic", model, "rate_limit", status=429, message=str(e)[:200])
            raise LlmError(f"anthropic 429: {e}") from e
        except anthropic.APIStatusError as e:
            raise LlmError(f"anthropic {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise LlmError(f"anthropic network error: {e}") from e
        if response.stop_reason == "refusal":
            raise LlmBlocked("anthropic: the model declined this request")
        if response.stop_reason == "max_tokens":
            raise LlmTruncated(f"anthropic: response truncated at max_tokens={min(max_output_tokens, MAX_TOKENS)}")
        instance = response.parsed_output
        if instance is None:
            raise LlmSchemaError("anthropic: the reply did not parse against the schema")
        usage = Usage(model=model, prompt_tokens=int(response.usage.input_tokens or 0),
                      output_tokens=int(response.usage.output_tokens or 0), thinking_tokens=0,
                      elapsed_s=round(time.time() - t0, 2), provider="anthropic")
        return instance, usage
