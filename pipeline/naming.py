"""Deterministic paths and stem names. See CLAUDE.md "Naming standard for audio stems".

Underscore is the field separator, so no field may contain an underscore.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

REPO_ROOT = Path(os.environ.get("AI_AUDIO_ROOT", Path(__file__).resolve().parent.parent))
SERIES_DIR = REPO_ROOT / "series"
LIBRARY_DIR = REPO_ROOT / "library"

_STEM_RE = re.compile(
    r"^ep(?P<ep>\d{2})_sc(?P<sc>\d{2})_l(?P<line>\d{3})_(?P<char>[a-z0-9-]+)_"
    r"(?P<type>dialogue|monologue)\.wav$"
)
STEM_TYPES = ("dialogue", "monologue")


def _check_field(value: str, name: str) -> str:
    if "_" in value or not value:
        raise ValueError(f"{name} may not be empty or contain '_': {value!r}")
    return value


# ---- global library ----------------------------------------------------------------


def registry_path() -> Path:
    """The single, locked Voice IP registry shared by all series (D7)."""
    return LIBRARY_DIR / "voice-ips.json"


def bgm_library_dir(mood: str) -> Path:
    return LIBRARY_DIR / "bgm" / _check_field(mood, "mood")


def sfx_library_path(tag: str) -> Path:
    return LIBRARY_DIR / "sfx" / f"{_check_field(tag, 'sfx tag')}.wav"


def ambience_library_path(tag: str) -> Path:
    return LIBRARY_DIR / "ambience" / f"{_check_field(tag, 'ambience tag')}.wav"


# ---- series-level paths ----------------------------------------------------------------


def series_root(series_id: str) -> Path:
    return SERIES_DIR / _check_field(series_id, "series_id")


def story_raw_path(series_id: str) -> Path:
    """Plain-text story (legacy input, or rendered from story.json)."""
    return series_root(series_id) / "story_raw.txt"


def story_json_path(series_id: str) -> Path:
    """Sectioned story input (StoryInput): overview, roles with optional actor assignment, script."""
    return series_root(series_id) / "story.json"


def auditions_dir() -> Path:
    return LIBRARY_DIR / "auditions"


def previews_dir() -> Path:
    """Cached ~5 s voice previews for the Characters page: <actor>_<provider>.wav (+ .meta.json)."""
    return LIBRARY_DIR / "previews"


def series_bible_path(series_id: str) -> Path:
    return series_root(series_id) / "series.json"


def raw_script_path(series_id: str, episode: int) -> Path:
    return series_root(series_id) / "scripts" / "raw" / f"ep{episode:02d}.txt"


def parsed_script_path(series_id: str, episode: int) -> Path:
    return series_root(series_id) / "scripts" / "parsed" / f"ep{episode:02d}.json"


def stems_dir(series_id: str, episode: int) -> Path:
    return series_root(series_id) / "stems" / f"ep{episode:02d}"


def timeline_path(series_id: str, episode: int) -> Path:
    return series_root(series_id) / "timelines" / f"ep{episode:02d}_timeline.json"


def master_path(series_id: str, episode: int, ext: str = "wav") -> Path:
    return series_root(series_id) / "masters" / f"ep{episode:02d}_master.{ext}"


def qa_report_path(series_id: str, episode: int) -> Path:
    return series_root(series_id) / "qa" / f"ep{episode:02d}_report.json"


def run_log_path(series_id: str) -> Path:
    return series_root(series_id) / "run.log.jsonl"


# ---- stem names ------------------------------------------------------------------------


def stem_name(episode: int, scene: int, line: int, character_id: str, line_type: str) -> str:
    _check_field(character_id, "character_id")
    if line_type not in STEM_TYPES:
        raise ValueError(f"line_type must be one of {STEM_TYPES}, got {line_type!r}")
    return f"ep{episode:02d}_sc{scene:02d}_l{line:03d}_{character_id}_{line_type}.wav"


def stem_name_from_line_id(line_id: str, character_id: str, line_type: str) -> str:
    m = re.match(r"^ep(\d{2})_sc(\d{2})_l(\d{3})$", line_id)
    if not m:
        raise ValueError(f"bad line_id {line_id!r}")
    ep, sc, ln = (int(x) for x in m.groups())
    return stem_name(ep, sc, ln, character_id, line_type)


def parse_stem_name(filename: str) -> dict:
    m = _STEM_RE.match(filename)
    if not m:
        raise ValueError(f"not a stem filename: {filename!r}")
    d = m.groupdict()
    return {
        "episode": int(d["ep"]),
        "scene": int(d["sc"]),
        "line": int(d["line"]),
        "character_id": d["char"],
        "type": d["type"],
        "line_id": f"ep{d['ep']}_sc{d['sc']}_l{d['line']}",
    }


def sfx_stem_name(line_id: str, tag: str) -> str:
    _check_field(tag, "sfx tag")
    return f"{line_id}_sfx_{tag}.wav"


def bgm_stem_name(episode: int, scene: int, mood: str) -> str:
    _check_field(mood, "mood")
    return f"ep{episode:02d}_sc{scene:02d}_bgm_{mood}.wav"


def ambience_stem_name(episode: int, scene: int, tag: str) -> str:
    _check_field(tag, "ambience tag")
    return f"ep{episode:02d}_sc{scene:02d}_amb_{tag}.wav"


def chunk_stem_name(episode: int, scene: int, chunk: int) -> str:
    """Scene-batched render unit (Gemini multi-speaker): several lines of one scene in one file."""
    return f"ep{episode:02d}_sc{scene:02d}_c{chunk:02d}_chunk.wav"


def chunk_stem_name_from_id(chunk_id: str) -> str:
    m = re.match(r"^ep(\d{2})_sc(\d{2})_c(\d{2})$", chunk_id)
    if not m:
        raise ValueError(f"bad chunk_id {chunk_id!r}")
    ep, sc, c = (int(x) for x in m.groups())
    return chunk_stem_name(ep, sc, c)


def render_manifest_path(series_id: str, episode: int) -> Path:
    """Written by generate-voice: which render units (lines or chunks) make up the episode."""
    return stems_dir(series_id, episode) / "render.json"


def meta_path(stem: Path) -> Path:
    """Sidecar with provider, settings, content hash, cost. Used for idempotent regeneration."""
    return stem.with_suffix(stem.suffix + ".meta.json")
