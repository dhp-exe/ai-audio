"""Mocked tests for pipeline.llm.gemini_client (no network)."""

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from pipeline.llm import gemini_client as gc


class Out(BaseModel):
    a: int
    b: str


def _resp(text, finish="STOP", block=None):
    return SimpleNamespace(
        text=text,
        candidates=[SimpleNamespace(finish_reason=finish)],
        prompt_feedback=SimpleNamespace(block_reason=block),
        usage_metadata=SimpleNamespace(prompt_token_count=10, candidates_token_count=5, thoughts_token_count=0),
    )


class FakeModels:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def generate_content(self, **kw):
        self.calls += 1
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture
def fake(monkeypatch):
    holder = {}

    def _client():
        return SimpleNamespace(models=holder["models"])

    monkeypatch.setattr(gc, "_client", _client)
    monkeypatch.setattr(gc.time, "sleep", lambda *_: None)
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    return holder


def test_success(fake):
    fake["models"] = FakeModels([_resp('{"a": 1, "b": "ok"}')])
    obj, usage = gc.generate_structured(system="s", user="u", schema=Out, model="m")
    assert obj == Out(a=1, b="ok")
    assert usage.prompt_tokens == 10 and usage.model == "m"


def test_truncated(fake):
    fake["models"] = FakeModels([_resp('{"a": 1', finish="MAX_TOKENS")])
    with pytest.raises(gc.LlmTruncated):
        gc.generate_structured(system="s", user="u", schema=Out, model="m")


def test_blocked(fake):
    fake["models"] = FakeModels([_resp(None, finish="SAFETY")])
    with pytest.raises(gc.LlmBlocked):
        gc.generate_structured(system="s", user="u", schema=Out, model="m")


def test_schema_error(fake):
    fake["models"] = FakeModels([_resp('{"a": "not-int", "b": 1}')])
    with pytest.raises(gc.LlmSchemaError):
        gc.generate_structured(system="s", user="u", schema=Out, model="m")


def test_retry_on_429(fake):
    from google.genai import errors

    err = errors.APIError(429, {"error": {"message": "rate"}})
    fake["models"] = FakeModels([err, _resp('{"a": 2, "b": "second"}')])
    obj, _ = gc.generate_structured(system="s", user="u", schema=Out, model="m", retries=2)
    assert obj.a == 2 and fake["models"].calls == 2
