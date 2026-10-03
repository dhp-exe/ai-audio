"""LLM adapters and the telemetry-aware client the agents use."""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, ValidationError

from emvoox.config import DEFAULT_LLM_MODEL, LLM_PROVIDERS, get_settings
from emvoox.providers.llm.base import LlmBlocked, LlmError, LlmProvider, LlmSchemaError, LlmTruncated, T, Usage
from emvoox.telemetry.ledger import Ledger

_factories: dict[str, Callable[[], LlmProvider]] = {}


def register_llm(name: str, factory: Callable[[], LlmProvider]) -> None:
    """Plug in another LLM backend (e.g. the V1RON API provider) without touching the agents."""
    _factories[name] = factory


def get_llm_provider(name: str | None = None) -> LlmProvider:
    name = (name or get_settings().llm_provider).lower()
    if name in _factories:
        return _factories[name]()
    if name == "gemini":
        from emvoox.providers.llm.gemini import GeminiLlm

        return GeminiLlm()
    if name in ("wavespeed", "openai"):
        from emvoox.providers.llm.openai_compat import OpenAICompatLlm

        return OpenAICompatLlm(name)
    if name == "anthropic":
        from emvoox.providers.llm.anthropic_llm import AnthropicLlm

        return AnthropicLlm()
    if name == "mock":
        from emvoox.providers.llm.mock import MockLlm

        return MockLlm()
    raise ValueError(f"unknown LLM provider {name!r}; expected one of {LLM_PROVIDERS}")


class LlmClient:
    """What an agent holds: one provider, one model, every call validated and logged."""

    def __init__(self, provider: LlmProvider, ledger: Ledger | None = None, *, model: str | None = None):
        self.provider = provider
        self.ledger = ledger
        settings = get_settings()
        self.model = model or (settings.llm_model if provider.name == settings.llm_provider else DEFAULT_LLM_MODEL.get(provider.name, settings.llm_model))
        self.last_usage: Usage | None = None

    @property
    def name(self) -> str:
        return self.provider.name

    def structured(self, *, agent: str, skill: str, system: str, user: str, schema: type[T], episode: int | None = None,
                   temperature: float | None = None, context: dict | None = None, max_output_tokens: int = 65_536) -> T:
        """Call the model and return a validated ``schema`` instance. Raises ``LlmError`` subclasses."""
        try:
            instance, usage = self.provider.generate_structured(
                system=system, user=user, schema=schema, model=self.model, temperature=temperature,
                max_output_tokens=max_output_tokens, context=context)
        except LlmError as e:
            if self.ledger:
                self.ledger.llm(agent=agent, skill=skill, provider=self.provider.name, model=self.model, tokens_in=0, tokens_out=0,
                                elapsed_s=0.0, episode=episode, ok=False, note=f"{type(e).__name__}: {str(e)[:160]}")
            raise
        # A provider may hand back an instance built without validation; the contract is checked here once more.
        try:
            instance = schema.model_validate(instance.model_dump() if isinstance(instance, BaseModel) else instance)
        except ValidationError as e:
            raise LlmSchemaError(str(e)) from e
        self.last_usage = usage
        if self.ledger:
            self.ledger.llm(agent=agent, skill=skill, provider=self.provider.name, model=usage.model, tokens_in=usage.prompt_tokens,
                            tokens_out=usage.output_tokens + usage.thinking_tokens, elapsed_s=usage.elapsed_s, episode=episode)
        return instance

    def can_transcribe(self) -> bool:
        return callable(getattr(self.provider, "transcribe", None))

    def transcribe(self, audio, *, agent: str, skill: str, episode: int | None = None) -> str:
        text, usage = self.provider.transcribe(audio)  # type: ignore[attr-defined]
        if self.ledger:
            self.ledger.llm(agent=agent, skill=skill, provider=self.provider.name, model=usage.model, tokens_in=usage.prompt_tokens,
                            tokens_out=usage.output_tokens, elapsed_s=usage.elapsed_s, episode=episode)
        return text


__all__ = ["LlmBlocked", "LlmClient", "LlmError", "LlmProvider", "LlmSchemaError", "LlmTruncated", "Usage", "get_llm_provider", "register_llm"]
