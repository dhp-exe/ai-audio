"""Static catalog of the TTS engines: models, voices and how they are billed.

The web client, the Voice IP form, the engine and the casting helpers all read this so a
provider/model/voice choice means the same thing everywhere.

    gemini      Gemini TTS: 30 prebuilt voices addressed by name; multi-speaker scene batching.
    elevenlabs  ElevenLabs direct: account voices (premade, library, cloned) by voice_id.
    wavespeed   WaveSpeed.ai gateway: one key, model path picks the vendor (ElevenLabs v3 accepts
                any ElevenLabs voice id; MiniMax accepts system and cloned voice ids; Gemini 3.8
                TTS takes the Gemini prebuilt voice names and two-speaker dialogue requests).
    mock        Offline tone generator for tests and the demo. Never shown unless enabled.
"""

from __future__ import annotations

from typing import TypedDict

PROVIDER_NAMES: tuple[str, ...] = ("gemini", "elevenlabs", "wavespeed", "mock")
REAL_PROVIDERS: tuple[str, ...] = ("gemini", "elevenlabs", "wavespeed")


class ModelInfo(TypedDict):
    id: str
    label: str
    tags: bool  # accepts [audio tags] inline
    note: str


class VoiceInfo(TypedDict):
    id: str
    gender: str  # female | male
    character: str


ELEVENLABS_MODELS: list[ModelInfo] = [
    {"id": "eleven_v3", "label": "Eleven v3", "tags": True,
     "note": "Most expressive; audio tags; stability 0.0/0.5/1.0; 1 credit per character."},
    {"id": "eleven_multilingual_v2", "label": "Multilingual v2", "tags": False,
     "note": "Stable, continuous stability/style, no tags; 1 credit per character."},
    {"id": "eleven_flash_v2_5", "label": "Flash v2.5", "tags": False,
     "note": "Fastest; 0.5 credit per character; least expressive."},
]

GEMINI_MODELS: list[ModelInfo] = [
    {"id": "gemini-3.1-flash-tts-preview", "label": "Gemini 3.1 Flash TTS", "tags": False,
     "note": "Default. Newest voices; style by natural-language direction; 10 requests per day per model without billing."},
    {"id": "gemini-2.5-flash-preview-tts", "label": "Gemini 2.5 Flash TTS", "tags": False,
     "note": "Previous generation voices; 10 requests per day per model without billing."},
    {"id": "gemini-2.5-pro-preview-tts", "label": "Gemini 2.5 Pro TTS", "tags": False,
     "note": "Highest quality of the Gemini line; requires billing on the Gemini project."},
]

# The 30 prebuilt Gemini voices (same set on Gemini API and Chirp 3 HD). Gender and character
# from Google's voice table. All are multilingual and speak Vietnamese.
GEMINI_VOICES: list[VoiceInfo] = [
    {"id": "Zephyr", "gender": "female", "character": "bright"},
    {"id": "Kore", "gender": "female", "character": "firm"},
    {"id": "Leda", "gender": "female", "character": "youthful"},
    {"id": "Aoede", "gender": "female", "character": "breezy"},
    {"id": "Callirrhoe", "gender": "female", "character": "easy-going"},
    {"id": "Autonoe", "gender": "female", "character": "bright"},
    {"id": "Despina", "gender": "female", "character": "smooth"},
    {"id": "Erinome", "gender": "female", "character": "clear"},
    {"id": "Laomedeia", "gender": "female", "character": "upbeat"},
    {"id": "Achernar", "gender": "female", "character": "soft"},
    {"id": "Gacrux", "gender": "female", "character": "mature"},
    {"id": "Pulcherrima", "gender": "female", "character": "forward"},
    {"id": "Vindemiatrix", "gender": "female", "character": "gentle"},
    {"id": "Sulafat", "gender": "female", "character": "warm"},
    {"id": "Puck", "gender": "male", "character": "upbeat"},
    {"id": "Charon", "gender": "male", "character": "informative"},
    {"id": "Fenrir", "gender": "male", "character": "excitable"},
    {"id": "Orus", "gender": "male", "character": "firm"},
    {"id": "Enceladus", "gender": "male", "character": "breathy"},
    {"id": "Iapetus", "gender": "male", "character": "clear"},
    {"id": "Umbriel", "gender": "male", "character": "easy-going"},
    {"id": "Algieba", "gender": "male", "character": "smooth"},
    {"id": "Algenib", "gender": "male", "character": "gravelly"},
    {"id": "Rasalgethi", "gender": "male", "character": "informative"},
    {"id": "Alnilam", "gender": "male", "character": "firm"},
    {"id": "Schedar", "gender": "male", "character": "even"},
    {"id": "Achird", "gender": "male", "character": "friendly"},
    {"id": "Zubenelgenubi", "gender": "male", "character": "casual"},
    {"id": "Sadachbia", "gender": "male", "character": "lively"},
    {"id": "Sadaltager", "gender": "male", "character": "knowledgeable"},
]

# WaveSpeed model paths (POST https://api.wavespeed.ai/api/v3/<path>). `python -m emvoox doctor` lists
# what the key can reach; any other path can be typed into a voice entry.
WAVESPEED_MODELS: list[ModelInfo] = [
    {"id": "elevenlabs/eleven-v3", "label": "ElevenLabs v3 (via WaveSpeed)", "tags": True,
     "note": "Same engine as Eleven v3; voice = preset name or any ElevenLabs voice id (cloned voices included). Billed per character by WaveSpeed."},
    {"id": "minimax/speech-2.6-hd", "label": "MiniMax Speech 2.6 HD (via WaveSpeed)", "tags": False,
     "note": "emotion / speed / pitch / volume parameters; voice = system voice id or a voice cloned with minimax/voice-clone."},
    {"id": "google/gemini-3.8-flash/text-to-speech", "label": "Gemini 3.8 Flash TTS (via WaveSpeed)", "tags": False,
     "note": "Gemini prebuilt voices (each actor's Gemini voice), style instructions, two-speaker dialogue batching. "
             "Billed $0.05 per request per started 1,000 characters, so batching matters; no cloned voices."},
    {"id": "google/gemini-3.8-flash-lite/text-to-speech", "label": "Gemini 3.8 Flash-Lite TTS (via WaveSpeed)", "tags": False,
     "note": "Same request shape as Gemini 3.8 Flash TTS at $0.04 per request per started 1,000 characters."},
]
MOCK_MODELS: list[ModelInfo] = [
    {"id": "mock-tone", "label": "Offline tone (no API)", "tags": False, "note": "Synthetic tones instead of speech. For tests and the demo only."},
]

DEFAULT_MODEL = {"elevenlabs": "eleven_v3", "gemini": "gemini-3.1-flash-tts-preview", "wavespeed": "elevenlabs/eleven-v3", "mock": "mock-tone"}
MODELS = {"elevenlabs": ELEVENLABS_MODELS, "gemini": GEMINI_MODELS, "wavespeed": WAVESPEED_MODELS, "mock": MOCK_MODELS}
PROVIDER_LABEL = {"elevenlabs": "ElevenLabs", "gemini": "Gemini TTS", "wavespeed": "WaveSpeed", "mock": "Offline mock"}
BILLING = {"elevenlabs": "credits per character", "gemini": "requests per day on the free tier, then per audio token",
           "wavespeed": "USD per character, prepaid balance", "mock": "free"}
KEY_ENV = {"elevenlabs": "ELEVENLABS_API_KEY", "gemini": "GEMINI_API_KEY", "wavespeed": "WAVESPEED_API_KEY", "mock": ""}


def model_ids(provider: str) -> list[str]:
    return [m["id"] for m in MODELS.get(provider, [])]


def voice_family(provider: str, model_id: str | None = None) -> str:
    """Whose voice ids (and delivery controls) a provider/model speaks: 'gemini' (prebuilt voice names,
    style direction), 'elevenlabs' (account voice ids), or the provider itself. WaveSpeed follows the
    vendor of its model path."""
    if provider != "wavespeed":
        return provider
    vendor = (model_id or DEFAULT_MODEL["wavespeed"]).split("/")[0]
    return {"google": "gemini", "elevenlabs": "elevenlabs"}.get(vendor, "wavespeed")


def supports_scene_batching(provider: str, model_id: str | None = None) -> bool:
    """Multi-speaker conversation requests (one request for a run of lines). For WaveSpeed pass the model."""
    return provider == "gemini" or (provider == "wavespeed" and model_id is not None and voice_family(provider, model_id) == "gemini")


def supports_tags(provider: str, model_id: str) -> bool:
    """True when the model reads [audio tags] inline instead of speaking them."""
    return (provider == "elevenlabs" and model_id == "eleven_v3") or (provider == "wavespeed" and model_id.startswith("elevenlabs/"))


def gemini_voice(voice_id: str) -> VoiceInfo | None:
    return next((v for v in GEMINI_VOICES if v["id"].lower() == voice_id.lower()), None)


def gemini_voices(gender: str | None = None) -> list[VoiceInfo]:
    return [v for v in GEMINI_VOICES if gender is None or v["gender"] == gender]


def catalog(include_mock: bool = False) -> dict:
    """JSON-ready description for the web client."""
    return {
        "providers": [
            {"id": p, "label": PROVIDER_LABEL[p], "models": MODELS[p], "default_model": DEFAULT_MODEL[p],
             "voices": GEMINI_VOICES if p == "gemini" else None, "billing": BILLING[p], "key_env": KEY_ENV[p],
             "scene_batching": any(supports_scene_batching(p, m["id"]) for m in MODELS[p]), "free_voice_id": p != "gemini"}
            for p in PROVIDER_NAMES if include_mock or p != "mock"
        ]
    }
