"""Small builders shared by tests (imported as a plain module; pytest puts tests/ on sys.path)."""

from __future__ import annotations

from emvoox.contracts import CastMember, EnginePolicy, EngineRef, EpisodeScript, ResolvedCast


def make_cast_and_script() -> tuple[EpisodeScript, ResolvedCast]:
    """Two scenes, two actors on per-line engines (mock), five spoken lines."""
    lines = {
        "sc01": [("linh", "Ba năm rồi, tôi vẫn nhớ cái đêm hôm ấy."), ("khoi", "Em đến trễ mười phút rồi đấy."),
                 ("linh", "Tập hồ sơ này, anh giải thích đi, từng trang một, ngay bây giờ.")],
        "sc02": [("linh", "Tôi không chạy nữa."), ("khoi", "Vậy thì em sẽ phải trả giá.")],
    }
    scenes = []
    for sc, ls in lines.items():
        scenes.append({"scene_id": sc, "title": sc, "location": "x", "time_of_day": "night", "lines": [
            {"line_id": f"ep01_{sc}_l{i:03d}", "type": "dialogue", "character_id": a, "role_name": a.title(), "text": t, "tts_text": t,
             "emotion": "neutral", "emotional_intensity": 4, "acoustic_direction": "", "pause_after_ms": 400}
            for i, (a, t) in enumerate(ls, start=1)]})
    script = EpisodeScript.model_validate({"series_id": "t", "episode_number": 1, "title": "Tập 1", "logline": "l", "cliffhanger": "c",
                                           "target_duration_sec": 30, "characters_used": ["khoi", "linh"], "scenes": scenes})
    cast = ResolvedCast(series_id="t", engine_policy=EnginePolicy(default=EngineRef(provider="mock")), protagonist_id="linh", members=[
        CastMember(role_name="Linh", role_type="protagonist", actor_id="linh", provider="mock", model_id="mock-tone", voice_id="mock-female-1"),
        CastMember(role_name="Khoi", role_type="antagonist", actor_id="khoi", provider="mock", model_id="mock-tone", voice_id="mock-male-1")])
    return script, cast
