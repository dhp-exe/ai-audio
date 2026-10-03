"""Render Plan: which lines go out in which TTS request.

A *chunk* is a maximal run of consecutive spoken lines inside one scene that can share a single
multi-speaker request: every line is voiced on an engine with scene batching (Gemini) and the run
uses at most two actors. A pause line, a third actor, or a line voiced on another engine closes
the chunk. Typical 60 s episodes come out at 1 to 3 chunks, which is what keeps a run inside the
per-day request quota without billing. Every other line is rendered on its own.

The chunk's text is a labelled transcript ("Ngan: ...") and its direction header carries the
per-line acting notes (emotion, intensity, pace, volume, tags, acoustic direction) as a numbered
guide the model is told not to read aloud. Speaker labels are ASCII derived from actor ids so the
label in the transcript and the label in the request config always match.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from emvoox.contracts.cast import CastMember, ResolvedCast
from emvoox.contracts.production import EpisodeScript, Line, LineType
from emvoox.delivery.compile import gemini_style, text_for_provider

MAX_SPEAKERS = 2


@dataclass
class Chunk:
    chunk_id: str  # ep01_sc02_c01
    scene_id: str
    scene_index: int  # 0-based
    index: int  # 1-based within the scene
    lines: list[Line] = field(default_factory=list)
    actors: list[str] = field(default_factory=list)  # order of first appearance, <= MAX_SPEAKERS

    @property
    def line_ids(self) -> list[str]:
        return [ln.line_id for ln in self.lines]

    @property
    def pause_after_ms(self) -> int:
        return self.lines[-1].pause_after_ms if self.lines else 0


def chunk_episode(script: EpisodeScript, max_speakers: int = MAX_SPEAKERS,
                  can_batch: Callable[[Line], bool] | None = None) -> list[Chunk]:
    """Chunks of the episode. Lines for which ``can_batch`` is false are left out (and close the
    current chunk): the planner renders those one by one."""
    chunks: list[Chunk] = []
    for si, scene in enumerate(script.scenes):
        current: Chunk | None = None
        n = 0

        def close() -> None:
            nonlocal current
            if current and current.lines:
                chunks.append(current)
            current = None

        for line in scene.lines:
            if line.type == LineType.pause or (can_batch is not None and not can_batch(line)):
                close()
                continue
            if current is not None and line.character_id not in current.actors and len(current.actors) >= max_speakers:
                close()
            if current is None:
                n += 1
                current = Chunk(chunk_id=f"ep{script.episode_number:02d}_{scene.scene_id}_c{n:02d}", scene_id=scene.scene_id, scene_index=si, index=n)
            if line.character_id not in current.actors:
                current.actors.append(line.character_id)
            current.lines.append(line)
        close()
    return chunks


def speaker_label(actor_id: str) -> str:
    """'minh-khoi' -> 'MinhKhoi': ASCII, no separators, safe as a Gemini speaker name."""
    return "".join(part.capitalize() for part in re.split(r"[^a-z0-9]+", actor_id.lower()) if part) or "Speaker"


def _who(m: CastMember, role: str | None) -> str:
    return role or m.role_name or m.display_name or m.actor_id


def build_transcript(chunk: Chunk, cast: ResolvedCast, model_id: str, *, normalize: bool = True,
                     descriptions: dict[str, str] | None = None) -> tuple[str, str, tuple[tuple[str, str], ...]]:
    """Returns (direction header, transcript text, speakers) for one chunk.

    speakers = ((label, voice name), ...). For a single actor the transcript has no labels and the
    caller renders it in single-speaker mode. ``descriptions`` maps actor id -> voice description."""
    labels = {a: speaker_label(a) for a in chunk.actors}
    speakers = tuple((labels[a], cast.member(a).voice_id) for a in chunk.actors)
    multi = len(chunk.actors) > 1
    descriptions = descriptions or {}

    cast_bits = []
    for a in chunk.actors:
        m = cast.member(a)
        role = next((ln.role_name for ln in chunk.lines if ln.character_id == a and ln.role_name), None)
        who = f"{labels[a]} = {_who(m, role)}" if multi else _who(m, role)
        desc = descriptions.get(a, "")
        cast_bits.append(f"{who}: {desc}" if desc else who)
    guide = "\n".join(f"{i}. {labels[ln.character_id] + ': ' if multi else ''}{gemini_style(ln)}" for i, ln in enumerate(chunk.lines, start=1))
    header = (
        ("Đọc đoạn hội thoại tiếng Việt sau" if multi else "Đọc các câu thoại tiếng Việt sau của cùng một nhân vật")
        + ". Diễn xuất theo chỉ dẫn từng câu bên dưới; KHÔNG đọc tên người nói, số thứ tự hay chỉ dẫn. "
        "Giữa các câu ngắt nghỉ tự nhiên khoảng nửa giây.\n"
        + "Nhân vật:\n" + "\n".join(cast_bits) + "\n"
        + "Chỉ dẫn diễn xuất theo thứ tự câu:\n" + guide + "\n"
        + ("Hội thoại" if multi else "Lời thoại")
    )
    lines_text = []
    for ln in chunk.lines:
        t = text_for_provider(ln, "gemini", model_id, normalize=normalize)
        lines_text.append(f"{labels[ln.character_id]}: {t}" if multi else t)
    return header, "\n".join(lines_text), speakers
