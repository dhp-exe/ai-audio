"""Storage keys and stem names. Every artifact has one deterministic key; never hand-build them.

A *key* is a POSIX path relative to the storage root (``./data`` locally). The same key addresses
a JSON document in the ``DocumentStore`` or a file in the ``BlobStore``, so a key written to local
disk today is the document id / object name on ``v1ron_db`` / MinIO tomorrow.

Underscore is the field separator in stem names, so no field may contain an underscore.
"""

from __future__ import annotations

import re

_STEM_RE = re.compile(
    r"^ep(?P<ep>\d{2})_sc(?P<sc>\d{2})_l(?P<line>\d{3})_(?P<char>[a-z0-9-]+)_"
    r"(?P<type>dialogue|monologue)\.wav$"
)
STEM_TYPES = ("dialogue", "monologue")


def _check_field(value: str, name: str) -> str:
    if "_" in value or "/" in value or not value:
        raise ValueError(f"{name} may not be empty or contain '_' or '/': {value!r}")
    return value


def ep(n: int) -> str:
    return f"ep{n:02d}"


# ---- assets (global, shared by every series) ------------------------------------------

REGISTRY = "assets/voice_registry.json"
PREVIEWS = "assets/previews"
AUDITIONS = "assets/auditions"
BGM = "assets/bgm"
SFX = "assets/sfx"
TREND_SEEDS = "inputs/trends"
MARKET_SOURCES = "inputs/market_sources.json"
BRIEFS = "research/briefs"
SCANS = "research/scans"
SERIES = "series"
APPROVED = "outputs/approved_masters"
RUN_LOG = "telemetry/run_log.jsonl"
VENDOR_EVENTS = "telemetry/usage_events.jsonl"


def preview(name: str) -> str:
    return f"{PREVIEWS}/{name}"


def audition(name: str) -> str:
    return f"{AUDITIONS}/{name}"


def bgm_dir(mood: str) -> str:
    return f"{BGM}/{_check_field(mood, 'mood')}"


def sfx(tag: str) -> str:
    return f"{SFX}/{_check_field(tag, 'sfx tag')}.wav"


def brief(brief_id: str) -> str:
    return f"{BRIEFS}/{brief_id}.json"


def scan(scan_id: str) -> str:
    return f"{SCANS}/{_check_field(scan_id, 'scan id')}.json"


def scan_shot(scan_id: str, name: str) -> str:
    """Screenshot of one scanned page; ``name`` is a file name like 'dramabox-1.jpg'."""
    if not re.fullmatch(r"[a-z0-9-]+\.jpg", name):
        raise ValueError(f"invalid screenshot name {name!r}")
    return f"{SCANS}/{_check_field(scan_id, 'scan id')}/{name}"


# ---- series ----------------------------------------------------------------------------


def series_root(series_id: str) -> str:
    return f"{SERIES}/{_check_field(series_id, 'series_id')}"


def story(series_id: str) -> str:
    """Sectioned story input (StoryInput)."""
    return f"{series_root(series_id)}/story.json"


def story_raw(series_id: str) -> str:
    return f"{series_root(series_id)}/story_raw.txt"


def trend_brief(series_id: str) -> str:
    """The TrendBrief this series was written from, when it came from the Market Research Agent."""
    return f"{series_root(series_id)}/trend_brief.json"


def bible(series_id: str) -> str:
    return f"{series_root(series_id)}/series.json"


def cast(series_id: str) -> str:
    """ResolvedCast: role -> actor -> engine/voice table from the Casting Agent."""
    return f"{series_root(series_id)}/cast.json"


def raw_script(series_id: str, episode: int) -> str:
    return f"{series_root(series_id)}/scripts/raw/{ep(episode)}.txt"


def parsed_script(series_id: str, episode: int) -> str:
    return f"{series_root(series_id)}/scripts/parsed/{ep(episode)}.json"


def cliffhanger_check(series_id: str, episode: int) -> str:
    return f"{series_root(series_id)}/scripts/checks/{ep(episode)}.json"


def directed(series_id: str, episode: int) -> str:
    """DirectedConversationUnits: the Director's handoff to the Sound Engineer."""
    return f"{series_root(series_id)}/directed/{ep(episode)}.json"


def stems_dir(series_id: str, episode: int) -> str:
    return f"{series_root(series_id)}/stems/{ep(episode)}"


def stem(series_id: str, episode: int, name: str) -> str:
    return f"{stems_dir(series_id, episode)}/{name}"


def render_manifest(series_id: str, episode: int) -> str:
    return f"{stems_dir(series_id, episode)}/render.json"


def timeline(series_id: str, episode: int) -> str:
    return f"{series_root(series_id)}/timelines/{ep(episode)}_timeline.json"


def master(series_id: str, episode: int, ext: str = "wav") -> str:
    return f"{series_root(series_id)}/masters/{ep(episode)}_master.{ext}"


def mastered(series_id: str, episode: int) -> str:
    """MasteredEpisode sidecar next to the master files."""
    return f"{series_root(series_id)}/masters/{ep(episode)}_master.json"


def qa_report(series_id: str, episode: int) -> str:
    return f"{series_root(series_id)}/qa/{ep(episode)}_report.json"


def release(series_id: str, episode: int) -> str:
    """ReleasePackage: human gate state + publishing metadata."""
    return f"{series_root(series_id)}/release/{ep(episode)}.json"


def series_run_log(series_id: str) -> str:
    return f"{series_root(series_id)}/run.log.jsonl"


def run_state(series_id: str) -> str:
    return f"{series_root(series_id)}/pipeline_run.json"


def run_events(series_id: str) -> str:
    return f"{series_root(series_id)}/logs/events.jsonl"


def step_log(series_id: str, step_id: str) -> str:
    return f"{series_root(series_id)}/logs/{step_id}.log"


def approved_dir(series_id: str) -> str:
    return f"{APPROVED}/{_check_field(series_id, 'series_id')}"


def approved_file(series_id: str, episode: int, ext: str) -> str:
    return f"{approved_dir(series_id)}/{ep(episode)}.{ext}"


def meta(key: str) -> str:
    """Sidecar with provider, settings, content hash, cost. Used for idempotent regeneration."""
    return key + ".meta.json"


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
    e, sc, ln = (int(x) for x in m.groups())
    return stem_name(e, sc, ln, character_id, line_type)


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


def chunk_stem_name(episode: int, scene: int, chunk: int) -> str:
    """Scene-batched render unit (multi-speaker request): several lines of one scene in one file."""
    return f"ep{episode:02d}_sc{scene:02d}_c{chunk:02d}_chunk.wav"


def chunk_stem_name_from_id(chunk_id: str) -> str:
    m = re.match(r"^ep(\d{2})_sc(\d{2})_c(\d{2})$", chunk_id)
    if not m:
        raise ValueError(f"bad chunk_id {chunk_id!r}")
    e, sc, c = (int(x) for x in m.groups())
    return chunk_stem_name(e, sc, c)


def sfx_stem_name(line_id: str, tag: str) -> str:
    _check_field(tag, "sfx tag")
    return f"{line_id}_sfx_{tag}.wav"
