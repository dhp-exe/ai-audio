"""Claude adapter through the official Anthropic SDK (optional: ``pip install -e .[claude]``).

Uses ``client.messages.parse(..., output_format=<Pydantic model>)``, which constrains the reply to
the schema and returns a validated instance. Current Claude models reject sampling parameters, so
``temperature`` is not sent. A refusal (``stop_reason == "refusal"``) is raised as ``LlmBlocked``;
there is no automatic model fallback here, the engine surfaces the failure on the step.
"""

from __future__ import annotations

import time

from emvoox.config import get_settings
from emvoox.contracts.agentic import ChatMessage, ChatReply, ToolCall, ToolSpec
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

    def chat(self, *, system: str, messages: list[ChatMessage], tools: list[ToolSpec], model: str | None = None,
             max_output_tokens: int = 8192, context: dict | None = None) -> tuple[ChatReply, Usage]:
        """One turn of a tool loop over the Messages API (tool_use / tool_result blocks)."""
        import anthropic

        settings = get_settings()
        model = model or (settings.llm_model if settings.llm_provider == "anthropic" else DEFAULT_MODEL)
        wire: list[dict] = []
        for m in messages:
            if m.role == "tool":  # the results of one turn travel together in one user message
                block = {"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content}
                if wire and wire[-1]["role"] == "user" and isinstance(wire[-1]["content"], list):
                    wire[-1]["content"].append(block)
                else:
                    wire.append({"role": "user", "content": [block]})
            elif m.role == "assistant":
                blocks = ([{"type": "text", "text": m.content}] if m.content else []) + [
                    {"type": "tool_use", "id": c.id, "name": c.name, "input": c.args} for c in m.tool_calls]
                wire.append({"role": "assistant", "content": blocks or [{"type": "text", "text": "..."}]})
            else:
                wire.append({"role": "user", "content": m.content})
        t0 = time.time()
        try:
            response = self._get_client().messages.create(
                model=model, max_tokens=min(max_output_tokens, MAX_TOKENS), system=system, messages=wire,
                tools=[{"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools])
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
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        calls = [ToolCall(id=b.id, name=b.name, args=dict(b.input or {})) for b in response.content if b.type == "tool_use"]
        if not text and not calls:
            raise LlmError(f"anthropic: empty response (stop_reason={response.stop_reason})")
        usage = Usage(model=model, prompt_tokens=int(response.usage.input_tokens or 0), output_tokens=int(response.usage.output_tokens or 0),
                      thinking_tokens=0, elapsed_s=round(time.time() - t0, 2), provider="anthropic")
        return ChatReply(text=text, tool_calls=calls, stop_reason=str(response.stop_reason or "")), usage

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
