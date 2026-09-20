"""Static catalog of the two supported TTS engines: models, voices and how they are billed.

The web client, the Characters form, the orchestrator and the casting helpers all read this so a
provider/model/voice choice means the same thing everywhere. ElevenLabs voices are account-specific
(voice_id from the user's My Voices), so only the models are listed; Gemini TTS ships a fixed set
of 30 prebuilt voices that every account has, addressed by name.
"""

from __future__ import annotations

from typing import TypedDict

PROVIDER_NAMES: tuple[str, ...] = ("elevenlabs", "gemini")


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

DEFAULT_MODEL = {"elevenlabs": "eleven_v3", "gemini": "gemini-3.1-flash-tts-preview"}
MODELS = {"elevenlabs": ELEVENLABS_MODELS, "gemini": GEMINI_MODELS}
PROVIDER_LABEL = {"elevenlabs": "ElevenLabs", "gemini": "Gemini TTS"}


def model_ids(provider: str) -> list[str]:
    return [m["id"] for m in MODELS.get(provider, [])]


def gemini_voice(voice_id: str) -> VoiceInfo | None:
    return next((v for v in GEMINI_VOICES if v["id"].lower() == voice_id.lower()), None)


def gemini_voices(gender: str | None = None) -> list[VoiceInfo]:
    return [v for v in GEMINI_VOICES if gender is None or v["gender"] == gender]


def catalog() -> dict:
    """JSON-ready description for the web client."""
    return {
        "providers": [
            {"id": p, "label": PROVIDER_LABEL[p], "models": MODELS[p], "default_model": DEFAULT_MODEL[p],
             "voices": GEMINI_VOICES if p == "gemini" else None,
             "billing": "credits per character" if p == "elevenlabs" else "requests per day, then per audio token"}
            for p in PROVIDER_NAMES
        ]
    }
