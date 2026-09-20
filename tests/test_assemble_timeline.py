import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

from pipeline.schema import EpisodeScript

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".claude/skills/assemble-audio/scripts/assemble_audio.py"

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")


def _load_module():
    spec = importlib.util.spec_from_file_location("assemble_audio", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _silent_stems(script: EpisodeScript, stems: Path, sec: float = 1.0) -> None:
    from pipeline import naming

    stems.mkdir(parents=True)
    for _, ln in script.all_lines():
        if ln.type.value == "pause":
            continue
        out = stems / naming.stem_name_from_line_id(ln.line_id, ln.character_id, ln.type.value)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
                        "-t", str(sec), "-ac", "1", str(out)], check=True)


def test_timeline_is_sequential_with_clamped_padding(tmp_path):
    mod = _load_module()
    script = EpisodeScript.model_validate_json((ROOT / "tests/fixtures/episode.json").read_text(encoding="utf-8"))
    stems = tmp_path / "stems"
    _silent_stems(script, stems)
    tl = mod.build_timeline(script, stems, padding_ms=400, padding_min=300, padding_max=500,
                            use_director_pauses=True, scene_gap_ms=800)
    stem_clips = [c for c in tl.clips if c.kind == "stem"]
    assert len(stem_clips) == len([ln for _, ln in script.all_lines() if ln.type.value != "pause"])
    by_id = {ln.line_id: ln for _, ln in script.all_lines()}
    for a, b in zip(stem_clips, stem_clips[1:], strict=False):
        gap = b.start_ms - (a.start_ms + a.duration_ms)
        expected = max(300, min(500, by_id[a.line_id].pause_after_ms))
        if a.scene_id != b.scene_id:
            expected += 800  # scene gap
        assert gap == expected, (a.line_id, gap, expected)
    assert tl.total_duration_ms == stem_clips[-1].start_ms + stem_clips[-1].duration_ms + mod.TAIL_MS


def test_render_voice_only_produces_stereo_master_near_target(tmp_path):
    mod = _load_module()
    script = EpisodeScript.model_validate_json((ROOT / "tests/fixtures/episode.json").read_text(encoding="utf-8"))
    stems = tmp_path / "stems"
    _silent_stems(script, stems, sec=0.5)
    tl = mod.build_timeline(script, stems, padding_ms=400, padding_min=300, padding_max=500,
                            use_director_pauses=False, scene_gap_ms=800)
    wav, mp3 = tmp_path / "m.wav", tmp_path / "m.mp3"
    mod.render_voice_only(tl, wav, mp3, lufs=-16.0, tp=-1.5, mp3_bitrate="192k")
    assert wav.exists() and mp3.exists()
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=channels:format=duration", "-of", "csv=p=0", str(wav)],
                           capture_output=True, text=True, check=True).stdout
    assert "2" in probe.splitlines()[0]
    duration = float(probe.strip().splitlines()[-1])
    assert abs(duration * 1000 - tl.total_duration_ms) < 150
