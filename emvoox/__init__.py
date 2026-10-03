"""Emvoox Engine: an event-driven multi-agent pipeline for Vietnamese AI audio micro-drama.

    contracts/      Pydantic v2 payloads every agent exchanges (the only thing that crosses agents)
    agents/         the seven Phase-1 audio agents and their skills
    engine/         state-machine orchestrator, event bus, retry loop, human gate
    repositories/   storage behind interfaces (local JSON/SQLite + disk now, v1ron_db + MinIO later)
    providers/      LLM and TTS adapters (Gemini, ElevenLabs, WaveSpeed, OpenAI-compatible, Claude, mock)
    delivery/       Director metadata -> engine text/settings, and the render plan
    audio/          FFmpeg helpers: stems, timeline, mixing, loudness, QA measurements
    telemetry/      usage ledger, cost estimates, vendor quota events
    api/            FastAPI JSON API serving the web client in web/
"""

__version__ = "1.0.0"
