"""Timeline: absolute placement of every stem, computed from measured stem durations (D9).

Sequential, no overlap. Director pauses are clamped to the padding window, `pause` units keep
their full length, scenes are separated by a fixed gap and the episode ends on a fixed tail.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from emvoox.audio.ffmpeg import duration_ms
from emvoox.contracts.direction import DirectedConversationUnits
from emvoox.contracts.production import Timeline, TimelineClip

TAIL_MS = 500  # silence after the last line so players don't clip the final word


class MissingStems(RuntimeError):
    def __init__(self, missing: list[str]):
        super().__init__(f"missing stems for {len(missing)} unit(s) (run Generate Voice): {missing[:5]}{'...' if len(missing) > 5 else ''}")
        self.missing = missing


def build_timeline(directed: DirectedConversationUnits, stem_path: Callable[[str], Path], *, padding_ms: int = 400,
                   padding_min: int = 300, padding_max: int = 500, use_director_pauses: bool = True, scene_gap_ms: int = 800,
                   measure: Callable[[Path], int] = duration_ms) -> Timeline:
    """``stem_path(name)`` maps a stem file name to its local path."""
    clips: list[TimelineClip] = []
    missing: list[str] = []
    cursor = 0
    placed: set[str] = set()
    by_unit = {uid: r for r in directed.render_plan for uid in r.unit_ids}

    def add_silence(ms: int, scene_id: str, line_id: str | None = None) -> None:
        nonlocal cursor
        if ms <= 0:
            return
        clips.append(TimelineClip(kind="silence", start_ms=cursor, duration_ms=ms, line_id=line_id, scene_id=scene_id))
        cursor += ms

    scene = None
    for u in directed.units:
        if scene is not None and u.scene_id != scene:
            add_silence(scene_gap_ms, u.scene_id)
        scene = u.scene_id
        if not u.is_spoken():
            add_silence(u.pause_after_ms, u.scene_id, u.unit_id)
            continue
        r = by_unit[u.unit_id]
        if r.id in placed:
            continue  # already covered by its conversation chunk
        placed.add(r.id)
        stem = stem_path(r.stem)
        if not stem.exists():
            missing.append(r.id)
            continue
        d = measure(stem)
        clips.append(TimelineClip(kind="stem", path=str(stem), start_ms=cursor, duration_ms=d, line_id=r.id, scene_id=u.scene_id))
        cursor += d
        gap = max(padding_min, min(padding_max, r.pause_after_ms)) if use_director_pauses else padding_ms
        add_silence(gap, u.scene_id, r.id)

    if missing:
        raise MissingStems(missing)
    # replace the trailing gap with a fixed tail
    if clips and clips[-1].kind == "silence":
        cursor -= clips[-1].duration_ms
        clips.pop()
    add_silence(TAIL_MS, directed.units[-1].scene_id)
    return Timeline(series_id=directed.series_id, episode_number=directed.episode_number, total_duration_ms=cursor, clips=clips)


def unit_offsets(tl: Timeline) -> dict[str, int]:
    """Render unit id -> start position in the master (ms)."""
    return {c.line_id: c.start_ms for c in tl.clips if c.kind == "stem" and c.line_id}
