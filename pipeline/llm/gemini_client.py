"""Google Gemini client with Pydantic structured output (decision D10).

Uses the official ``google-genai`` SDK. One entry point, ``generate_structured``, returns a
validated Pydantic instance plus token usage. All LLM-calling skills (episodize, parse-script)
go through here so retries, model selection and cost logging live in one place.

Model comes from ``AI_AUDIO_LLM_MODEL`` (default ``gemini-3.1-flash-lite``). ``gemini-3.6-flash``
or any other model id can be set in ``.env`` without code changes. Thinking is left at the model
default (dynamic for 2.5 Flash); pass ``thinking_budget`` to override.

Notes on schema conversion: the SDK converts the Pydantic model to Gemini's JSON-schema subset.
Enums, nullable fields, nested objects, arrays and numeric min/max are supported. Regex ``pattern``
and cross-field rules are NOT expressible in the schema; they run client-side via Pydantic
validators when we call ``model_validate_json`` on the response text.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from pipeline.config import get_settings

T = TypeVar("T", bound=BaseModel)


class LlmError(RuntimeError):
    """Base class for LLM failures the caller should surface."""


class LlmTruncated(LlmError):
    """Response hit max_output_tokens; split the input or raise the limit."""


class LlmBlocked(LlmError):
    """Prompt or response blocked by safety filters."""


class LlmSchemaError(LlmError):
    """Model returned JSON that does not satisfy the Pydantic contract."""


@dataclass(frozen=True)
class Usage:
    model: str
    prompt_tokens: int
    output_tokens: int
    thinking_tokens: int
    elapsed_s: float

    def as_dict(self) -> dict:
        return self.__dict__.copy()


REQUEST_TIMEOUT_MS = 180_000  # a hung call was observed in the wild; never wait forever


def _client():
    from google import genai
    from google.genai import types

    key = get_settings().require("gemini_api_key")
    client_args: dict = {}
    if os.getenv("AI_AUDIO_FORCE_IPV4", "true").strip().lower() in ("1", "true", "yes", "on"):
        # httpx does not do happy-eyeballs; on networks with a broken IPv6 path the TLS handshake
        # dies with "UNEXPECTED_EOF_WHILE_READING". Binding the local address forces IPv4.
        client_args["transport"] = httpx.HTTPTransport(local_address="0.0.0.0", retries=2)
    return genai.Client(api_key=key, http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS, client_args=client_args))


def generate_structured(
    *,
    system: str,
    user: str,
    schema: type[T],
    model: str | None = None,
    temperature: float | None = None,
    max_output_tokens: int = 65_536,
    thinking_budget: int | None = None,
    retries: int = 3,
) -> tuple[T, Usage]:
    """Call Gemini with a Pydantic response schema and return (instance, usage).

    Retries on 429/500/503 with exponential backoff. Raises LlmTruncated, LlmBlocked,
    LlmSchemaError, or the SDK's APIError for anything else.
    """
    from google.genai import errors, types

    settings = get_settings()
    model = model or settings.llm_model
    temperature = settings.llm_temperature if temperature is None else temperature

    config_kwargs: dict = dict(
        system_instruction=system,
        response_mime_type="application/json",
        response_schema=schema,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )
    if thinking_budget is not None:
        config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=thinking_budget)

    client = _client()
    t0 = time.time()
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = client.models.generate_content(
                model=model,
                contents=user,
                config=types.GenerateContentConfig(**config_kwargs),
            )
            break
        except errors.APIError as e:
            last_err = e
            if getattr(e, "code", None) in (429, 500, 503) and attempt < retries:
                time.sleep(2 * (2**attempt))
                continue
            raise
        except (httpx.HTTPError, ConnectionError, TimeoutError) as e:  # TLS resets, timeouts, DNS blips
            last_err = e
            if attempt < retries:
                time.sleep(2 * (2**attempt))
                continue
            raise LlmError(f"network error after {retries} retries: {e}") from e
    else:  # pragma: no cover
        raise LlmError(str(last_err))

    elapsed = time.time() - t0

    # Prompt-level block
    pf = getattr(resp, "prompt_feedback", None)
    if pf is not None and getattr(pf, "block_reason", None):
        raise LlmBlocked(f"prompt blocked: {pf.block_reason}")

    cand = resp.candidates[0] if resp.candidates else None
    finish = str(getattr(cand, "finish_reason", "") or "")
    if "MAX_TOKENS" in finish:
        raise LlmTruncated(f"response truncated at max_output_tokens={max_output_tokens}")
    if "SAFETY" in finish or "PROHIBITED" in finish or "BLOCKLIST" in finish:
        raise LlmBlocked(f"response blocked: {finish}")

    text = resp.text
    if not text:
        raise LlmError(f"empty response (finish_reason={finish or 'unknown'})")

    try:
        instance = schema.model_validate_json(text)
    except ValidationError as e:
        raise LlmSchemaError(str(e)) from e

    um = getattr(resp, "usage_metadata", None)
    usage = Usage(
        model=model,
        prompt_tokens=int(getattr(um, "prompt_token_count", 0) or 0),
        output_tokens=int(getattr(um, "candidates_token_count", 0) or 0),
        thinking_tokens=int(getattr(um, "thoughts_token_count", 0) or 0),
        elapsed_s=round(elapsed, 2),
    )
    return instance, usage
