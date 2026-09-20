import json

import pytest

from pipeline import naming
from pipeline import registry as registry_io
from pipeline.casting import apply_role_tags, extract_actor_tag, guess_gender, parse_roles_text, placeholder_voice
from pipeline.registry import RegistryLocked
from pipeline.schema import CharacterProfile, ProviderVoice, RoleCast, SeriesBible, StoryRole, VoiceRegistry, slugify_id


@pytest.fixture
def reg(tmp_path, monkeypatch):
    monkeypatch.setattr(naming, "LIBRARY_DIR", tmp_path / "library")
    r = VoiceRegistry(characters=[
        CharacterProfile(character_id="ngan", display_name="Ngân", persona="cute", voice_description="nữ", gender="female",
                         providers={"elevenlabs": ProviderVoice(voice_id="a3", model_id="eleven_v3")}),
        CharacterProfile(character_id="duong", display_name="Dương", persona="ceo", voice_description="nam trầm", gender="male",
                         providers={"elevenlabs": ProviderVoice(voice_id="u5", model_id="eleven_v3")}),
    ])
    registry_io.save(r)
    return r


def test_slugify_vietnamese():
    assert slugify_id("Tô Mạn") == "to-man"
    assert slugify_id("Giang Thần") == "giang-than"
    assert slugify_id("Đặng Văn Đức") == "dang-van-duc"


def test_extract_tag_and_apply(reg):
    text, tag = extract_actor_tag("Giang Thần /duong", reg)
    assert text == "Giang Thần" and tag == "duong"
    text, tag = extract_actor_tag("24 tuổi, hoạt bát. #ngan", reg)
    assert tag == "ngan" and "#" not in text
    assert extract_actor_tag("no tag here", reg) == ("no tag here", None)
    assert extract_actor_tag("unknown /zzz", reg)[1] is None
    roles = apply_role_tags([StoryRole(name="Tô Mạn", description="… /ngan"), StoryRole(name="Lý Minh", description="trợ lý")], reg)
    assert roles[0].actor_id == "ngan" and roles[0].description.endswith("…") and roles[1].actor_id is None


def test_parse_roles_text():
    roles = parse_roles_text("Giang Thần (Nam chính): 28 tuổi, CEO\n- Tô Mạn (Nữ chính): 24 tuổi\nkhông có dấu hai chấm\n")
    assert [r.name for r in roles] == ["Giang Thần", "Tô Mạn"]
    assert roles[0].description.startswith("28")


def test_guess_gender_and_placeholder():
    assert guess_gender("Nữ, 23 tuổi, trong trẻo") == "female"
    assert guess_gender("Nam, trầm, tổng giám đốc") == "male"
    assert placeholder_voice("female", 0) != placeholder_voice("female", 1)


def test_registry_lock(reg):
    changed = CharacterProfile(character_id="ngan", display_name="Ngân", persona="cute", voice_description="nữ",
                               providers={"elevenlabs": ProviderVoice(voice_id="NEW", model_id="eleven_v3")})
    with pytest.raises(RegistryLocked):
        registry_io.upsert(changed)
    r, entry = registry_io.upsert(changed, unlock=True)
    assert r.get("ngan").providers["elevenlabs"].voice_id == "NEW" and "a3@eleven_v3 -> NEW@eleven_v3" in entry
    # non-voice edits never need unlock
    r, _ = registry_io.upsert(changed.model_copy(update={"persona": "sweet"}))
    assert r.get("ngan").persona == "sweet"
    with pytest.raises(RegistryLocked):
        registry_io.remove("ngan")


def test_bible_role_mapping():
    b = SeriesBible(series_id="s", title="t", premise="p", tone="t", protagonist_id="ngan", protagonist_role="Tô Mạn",
                    roles=[RoleCast(role_name="Tô Mạn", role_type="protagonist", actor_id="ngan"),
                           RoleCast(role_name="Giang Thần", role_type="antagonist", actor_id="duong", assigned_by="user")],
                    cast=["ngan", "duong"])
    m = b.role_to_actor()
    assert m["Tô Mạn"] == "ngan" and m["to-man"] == "ngan" and m["giang-than"] == "duong" and m["duong"] == "duong"
    assert b.actor_to_role()["duong"] == "Giang Thần"
    assert json.loads(b.model_dump_json())["roles"][1]["assigned_by"] == "user"
