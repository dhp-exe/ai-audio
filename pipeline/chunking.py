"""Scene batching for Gemini TTS: render a run of lines in one request instead of one request per line.

Gemini's multi-speaker mode accepts a transcript with up to two speakers per request. A *chunk* is a
maximal run of consecutive spoken lines inside one scene that uses at most two actors; a pause line
or a third actor closes the chunk. Typical 60 s episodes come out at 1 to 3 chunks, which is what
keeps a run inside the per-day request quota without billing.

The chunk's text is a labelled transcript ("Ngan: ...") and its direction header carries the
per-line acting notes (emotion, intensity, pace, volume, tags, acoustic direction) as a numbered
guide the model is told not to read aloud. Speaker labels are ASCII derived from actor ids so the
label in the transcript and the label in the request config always match.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pipeline.providers.mapping import gemini_style, text_for_provider
from pipeline.schema import EpisodeScript, Line, LineType, VoiceRegistry

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


def chunk_episode(script: EpisodeScript, max_speakers: int = MAX_SPEAKERS) -> list[Chunk]:
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
            if line.type == LineType.pause:
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


def build_transcript(chunk: Chunk, registry: VoiceRegistry, model_id: str, *, normalize: bool = True) -> tuple[str, str, tuple[tuple[str, str], ...]]:
    """Returns (direction header, transcript text, speakers) for one chunk.

    speakers = ((label, gemini voice name), ...). For a single actor the transcript has no labels
    and the caller renders it in single-speaker mode."""
    labels = {a: speaker_label(a) for a in chunk.actors}
    speakers = tuple((labels[a], registry.get(a).providers["gemini"].voice_id) for a in chunk.actors)
    multi = len(chunk.actors) > 1

    cast_bits = []
    for a in chunk.actors:
        c = registry.get(a)
        role = next((ln.role_name for ln in chunk.lines if ln.character_id == a and ln.role_name), None)
        who = f"{labels[a]} = {role or c.display_name}" if multi else (role or c.display_name)
        cast_bits.append(f"{who} ({'nữ' if c.gender == 'female' else 'nam' if c.gender == 'male' else ''}{', ' + c.age + ' tuổi' if c.age else ''}): {c.voice_description}")
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
