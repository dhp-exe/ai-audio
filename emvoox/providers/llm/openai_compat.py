"""OpenAI-compatible Chat Completions adapter: WaveSpeed LLM, OpenAI, or any gateway speaking the same protocol.

WaveSpeed LLM (https://llm.wavespeed.ai/v1) serves 90+ models from 30+ providers behind one
key; model ids are ``vendor/model`` (for example ``google/...``, ``anthropic/...``,
``openai/...``). List what your key can use with ``python -m emvoox doctor``.

Structured output: the request uses JSON mode (``response_format: json_object``, the common
denominator across gateways) with the JSON Schema in the prompt; the reply is validated with
Pydantic and, on a contract violation, sent back once with the validation errors for repair.
"""

from __future__ import annotations

import json
import time

import httpx
from pydantic import ValidationError

from emvoox.config import get_settings
from emvoox.contracts.agentic import ChatMessage, ChatReply, ToolCall, ToolSpec
from emvoox.providers.llm.base import LlmBlocked, LlmError, LlmSchemaError, LlmTruncated, T, Usage, extract_json, schema_instructions

ENDPOINTS = {
    "wavespeed": ("https://llm.wavespeed.ai/v1", "wavespeed_api_key"),
    "openai": ("https://api.openai.com/v1", "openai_api_key"),
}
RETRY_STATUSES = {408, 409, 429, 500, 502, 503, 504}
REQUEST_TIMEOUT_S = 180.0


def _wire(m: ChatMessage) -> dict:
    """A session message in Chat Completions form."""
    if m.role == "tool":
        return {"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content}
    if m.role == "assistant" and m.tool_calls:
        return {"role": "assistant", "content": m.content or None,
                "tool_calls": [{"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.args, ensure_ascii=False)}}
                               for c in m.tool_calls]}
    return {"role": m.role, "content": m.content}


class OpenAICompatLlm:
    def __init__(self, name: str = "wavespeed", *, base_url: str | None = None, api_key: str | None = None,
                 client: httpx.Client | None = None):
        if name not in ENDPOINTS and not base_url:
            raise ValueError(f"unknown OpenAI-compatible endpoint {name!r}; pass base_url")
        self.name = name
        default_url, self._key_setting = ENDPOINTS.get(name, (base_url, ""))
        self.base_url = (base_url or default_url or "").rstrip("/")
        self._api_key = api_key
        self._client = client

    def _key(self) -> str:
        return self._api_key or get_settings().require(self._key_setting)

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=REQUEST_TIMEOUT_S)
        return self._client

    def _post(self, payload: dict, retries: int) -> dict:
        last: Exception | None = None
        for attempt in range(retries + 1):
            try:
                r = self._http().post(f"{self.base_url}/chat/completions", json=payload,
                                      headers={"Authorization": f"Bearer {self._key()}", "Content-Type": "application/json"})
            except httpx.HTTPError as e:  # TLS resets, timeouts, DNS blips
                last = e
                if attempt < retries:
                    time.sleep(2 * (2 ** attempt))
                    continue
                raise LlmError(f"{self.name}: network error after {retries} retries: {e}") from e
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                from emvoox.telemetry.events import record_event

                record_event(self.name, payload.get("model", "?"), "rate_limit", status=429, message=r.text[:200])
            if r.status_code in RETRY_STATUSES and attempt < retries:
                time.sleep(2 * (2 ** attempt))
                continue
            raise LlmError(f"{self.name} {r.status_code}: {r.text[:400]}")
        raise LlmError(str(last))  # pragma: no cover

    def generate_structured(self, *, system: str, user: str, schema: type[T], model: str | None = None,
                            temperature: float | None = None, max_output_tokens: int = 16_384,
                            context: dict | None = None, retries: int = 3) -> tuple[T, Usage]:
        settings = get_settings()
        model = model or settings.llm_model
        messages = [{"role": "system", "content": system + schema_instructions(schema)}, {"role": "user", "content": user}]
        payload: dict = {"model": model, "messages": messages, "response_format": {"type": "json_object"},
                         "max_tokens": min(max_output_tokens, 16_384)}
        temp = settings.llm_temperature if temperature is None else temperature
        if temp is not None:
            payload["temperature"] = temp
        t0 = time.time()
        tokens_in = tokens_out = 0
        error: ValidationError | None = None
        for attempt in range(2):  # the call, then one repair round on a contract violation
            data = self._post(payload, retries)
            usage = data.get("usage") or {}
            tokens_in += int(usage.get("prompt_tokens") or 0)
            tokens_out += int(usage.get("completion_tokens") or 0)
            choice = (data.get("choices") or [{}])[0]
            finish = str(choice.get("finish_reason") or "")
            text = ((choice.get("message") or {}).get("content") or "").strip()
            if finish == "content_filter":
                raise LlmBlocked(f"{self.name}: response blocked by the content filter")
            if finish == "length":
                raise LlmTruncated(f"{self.name}: response truncated at max_tokens={payload['max_tokens']}")
            if not text:
                raise LlmError(f"{self.name}: empty response (finish_reason={finish or 'unknown'})")
            try:
                instance = schema.model_validate_json(extract_json(text))
                return instance, Usage(model=model, prompt_tokens=tokens_in, output_tokens=tokens_out, thinking_tokens=0,
                                       elapsed_s=round(time.time() - t0, 2), provider=self.name)
            except ValidationError as e:
                error = e
                if attempt == 0:
                    payload["messages"] = [*messages, {"role": "assistant", "content": text},
                                           {"role": "user", "content": "That JSON does not satisfy the schema:\n" + str(e)[:1500]
                                            + "\nReturn the corrected JSON object only."}]
        raise LlmSchemaError(str(error))

    def chat(self, *, system: str, messages: list[ChatMessage], tools: list[ToolSpec], model: str | None = None,
             max_output_tokens: int = 8192, context: dict | None = None, retries: int = 3) -> tuple[ChatReply, Usage]:
        """One turn of a tool loop over Chat Completions function calling."""
        settings = get_settings()
        model = model or settings.llm_model
        payload: dict = {"model": model, "messages": [{"role": "system", "content": system}, *(_wire(m) for m in messages)],
                         "max_tokens": min(max_output_tokens, 16_384)}
        if tools:
            payload["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}} for t in tools]
        if settings.llm_temperature is not None:
            payload["temperature"] = settings.llm_temperature
        t0 = time.time()
        data = self._post(payload, retries)
        usage = data.get("usage") or {}
        choice = (data.get("choices") or [{}])[0]
        finish = str(choice.get("finish_reason") or "")
        if finish == "content_filter":
            raise LlmBlocked(f"{self.name}: response blocked by the content filter")
        msg = choice.get("message") or {}
        calls = []
        for i, c in enumerate(msg.get("tool_calls") or []):
            fn = c.get("function") or {}
            raw = fn.get("arguments") or "{}"
            try:
                args, error = (json.loads(raw) if isinstance(raw, str) else raw), None
                if not isinstance(args, dict):
                    args, error = {}, f"arguments must be a JSON object, got: {str(raw)[:200]}"
            except json.JSONDecodeError as e:
                args, error = {}, f"arguments are not valid JSON ({e}): {raw[:200]}"
            calls.append(ToolCall(id=c.get("id") or f"call_{i}", name=fn.get("name") or "", args=args, error=error))
        text = (msg.get("content") or "").strip()
        if finish == "length" and not calls:
            raise LlmTruncated(f"{self.name}: response truncated at max_tokens={payload['max_tokens']}")
        if not text and not calls:
            raise LlmError(f"{self.name}: empty response (finish_reason={finish or 'unknown'})")
        return ChatReply(text=text, tool_calls=calls, stop_reason=finish), Usage(
            model=model, prompt_tokens=int(usage.get("prompt_tokens") or 0), output_tokens=int(usage.get("completion_tokens") or 0),
            thinking_tokens=0, elapsed_s=round(time.time() - t0, 2), provider=self.name)

    def list_models(self) -> list[str]:
        r = self._http().get(f"{self.base_url}/models", headers={"Authorization": f"Bearer {self._key()}"})
        r.raise_for_status()
        return sorted(m.get("id", "") for m in (r.json().get("data") or []) if m.get("id"))
