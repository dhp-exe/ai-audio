import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from pipeline import naming
from pipeline.schema import PROTAGONIST_ALIAS, EpisodeScript, SeriesBible, VoiceRegistry

ROOT = Path(__file__).resolve().parents[1]


def load_demo() -> EpisodeScript:
    return EpisodeScript.model_validate_json((ROOT / "tests/fixtures/episode.json").read_text(encoding="utf-8"))


def test_demo_fixture_validates():
    s = load_demo()
    assert s.language == "vi-VN"
    assert len(s.all_lines()) == 11
    assert all(sc.bgm is None for sc in s.scenes)


def test_registry_and_bible_fixtures():
    reg = VoiceRegistry.model_validate_json((ROOT / "library/voice-ips.json").read_text(encoding="utf-8"))
    bible = SeriesBible.model_validate_json((ROOT / "series/demo/series.json").read_text(encoding="utf-8"))
    assert reg.locked
    assert bible.protagonist_id in bible.cast
    missing = set(bible.cast) - reg.ids()
    if missing:  # live data: an actor was deleted from the registry after the demo series was cast
        pytest.skip(f"demo series casts actors no longer in the registry: {sorted(missing)}")


def test_protagonist_alias_resolution():
    data = json.loads((ROOT / "tests/fixtures/episode.json").read_text(encoding="utf-8"))
    data["scenes"][0]["lines"][0]["character_id"] = "PROTAGONIST"  # model may upper-case it
    s = EpisodeScript.model_validate(data)
    assert s.scenes[0].lines[0].character_id == PROTAGONIST_ALIAS
    assert s.resolve_protagonist("linh") == 1
    assert s.scenes[0].lines[0].character_id == "linh"


def test_line_id_sequence_enforced():
    data = json.loads((ROOT / "tests/fixtures/episode.json").read_text(encoding="utf-8"))
    data["scenes"][0]["lines"][1]["line_id"] = "ep01_sc01_l009"
    with pytest.raises(ValidationError):
        EpisodeScript.model_validate(data)


def test_unapproved_tag_rejected():
    data = json.loads((ROOT / "tests/fixtures/episode.json").read_text(encoding="utf-8"))
    data["scenes"][0]["lines"][1]["tts_text"] = "[explodes] Anh đi đi."
    with pytest.raises(ValidationError):
        EpisodeScript.model_validate(data)


def test_stem_naming_roundtrip():
    name = naming.stem_name_from_line_id("ep01_sc02_l003", "minh-khoi", "monologue")
    assert name == "ep01_sc02_l003_minh-khoi_monologue.wav"
    parsed = naming.parse_stem_name(name)
    assert parsed["line_id"] == "ep01_sc02_l003" and parsed["character_id"] == "minh-khoi"
    with pytest.raises(ValueError):
        naming.stem_name(1, 1, 1, "bad_id", "dialogue")
