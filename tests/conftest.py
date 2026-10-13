"""Every test runs against a throwaway data directory with deterministic settings; nothing touches ./data or the network."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from emvoox.config import reset_settings
from emvoox.providers.tts.mock import MockTtsProvider
from emvoox.repositories import get_repositories, reset_repositories
from emvoox.telemetry import pricing

ROOT = Path(__file__).resolve().parents[1]
HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe not on PATH")

BASE_ENV = {
    "EMVOOX_LLM_PROVIDER": "gemini", "EMVOOX_LLM_MODEL": "gemini-3.1-flash-lite", "EMVOOX_TTS_PROVIDER": "gemini", "EMVOOX_TTS_MODEL": "",
    "EMVOOX_TTS_BATCHING": "auto", "EMVOOX_QA_TRANSCRIBE": "false", "EMVOOX_AUTO_APPROVE": "false", "EMVOOX_HALT_ON_QA_FAIL": "true",
    "EMVOOX_QA_MAX_RETRIES": "3", "EMVOOX_CLIFFHANGER_CHECK": "true", "EMVOOX_PREFER_CLONED_VOICES": "true", "EMVOOX_STORAGE": "local",
    "EMVOOX_DOC_STORE": "json", "ENABLE_BGM": "false", "ENABLE_SFX": "false", "EMVOOX_RESEARCH_USE_BROWSER": "false", "EMVOOX_ENABLE_MOCK": "true",
    "EMVOOX_MOCK_TTS_FAULTS": "", "GEMINI_API_KEY": "test-gemini", "ELEVENLABS_API_KEY": "test-eleven", "EMVOOX_SKIP_DOTENV": "1",
    "EMVOOX_QUEUE": "memory", "EMVOOX_TENANT": "default", "EMVOOX_EMBEDDED_WORKER": "true", "EMVOOX_DATABASE_URL": "",
}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Vendor SDKs must never reach the network from a test: any outbound connection fails loudly."""
    import socket

    real = socket.socket.connect

    def guarded(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if isinstance(host, str) and host not in ("127.0.0.1", "localhost", "::1") and not host.startswith("/"):
            raise RuntimeError(f"tests may not open network connections (tried {address!r})")
        return real(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setenv("EMVOOX_DATA_DIR", str(data))
    for k, v in BASE_ENV.items():
        monkeypatch.setenv(k, v)
    for k in ("WAVESPEED_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    reset_settings()
    reset_repositories()
    pricing.reset_overrides()
    MockTtsProvider.reset()
    restart_workers()
    yield data
    restart_workers()
    MockTtsProvider.reset()
    reset_settings()
    reset_repositories()
    pricing.reset_overrides()


def restart_workers() -> None:
    """Stop the worker thread inside this process and forget the queue, like a server restart (jobs in memory are lost)."""
    from emvoox.worker import reset_queue, stop_embedded_worker

    stop_embedded_worker()
    reset_queue()


@pytest.fixture
def repos(sandbox):
    return get_repositories()


TEST_DATABASE_URL = os.getenv("EMVOOX_TEST_DATABASE_URL", "postgresql://127.0.0.1:5432/emvoox_test")
TEST_REDIS_URL = os.getenv("EMVOOX_TEST_REDIS_URL", "redis://127.0.0.1:6379/15")


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    """A local PostgreSQL test database (createdb emvoox_test); tests that need one are skipped without it."""
    try:
        import psycopg

        psycopg.connect(TEST_DATABASE_URL, connect_timeout=2).close()
    except Exception as e:  # noqa: BLE001 - no driver or no server: skip, never fail
        pytest.skip(f"no PostgreSQL test database at {TEST_DATABASE_URL} ({type(e).__name__})")
    return TEST_DATABASE_URL


@pytest.fixture
def redis_url() -> str:
    """A local Redis (database 15, emptied before and after); tests that need one are skipped without it."""
    try:
        import redis

        client = redis.Redis.from_url(TEST_REDIS_URL, socket_connect_timeout=2)
        client.flushdb()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"no Redis at {TEST_REDIS_URL} ({type(e).__name__})")
    yield TEST_REDIS_URL
    client.flushdb()
    client.close()


def seed_registry(data: Path, actors: list[dict] | None = None) -> None:
    """A small registry: two IP actors with ElevenLabs + Gemini voices."""
    actors = actors or [
        {"character_id": "ngan", "display_name": "Ngân", "persona": "dễ thương", "voice_description": "nữ, trong trẻo", "gender": "female", "age": "23",
         "providers": {"elevenlabs": {"voice_id": "a3", "model_id": "eleven_v3", "source": "library", "fallback_voice_id": "cgS"},
                       "gemini": {"voice_id": "Leda", "model_id": "gemini-3.1-flash-tts-preview", "source": "prebuilt"}}},
        {"character_id": "duong", "display_name": "Dương", "persona": "tổng giám đốc", "voice_description": "nam, trầm", "gender": "male", "age": "30",
         "providers": {"elevenlabs": {"voice_id": "u5", "model_id": "eleven_v3", "source": "library"},
                       "gemini": {"voice_id": "Orus", "model_id": "gemini-3.1-flash-tts-preview", "source": "prebuilt"}}},
    ]
    p = data / "assets" / "voice_registry.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"locked": True, "default_provider": "gemini", "characters": actors, "changelog": []}, ensure_ascii=False))


def tone(path: Path, seconds: float = 1.0, freq: int = 440, volume: float = 0.3) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=44100", "-t", str(seconds),
                    "-af", f"volume={volume}", "-ac", "1", str(path)], check=True)
    return path
