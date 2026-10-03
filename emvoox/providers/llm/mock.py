"""Offline LLM: deterministic, schema-valid answers built from the ``context`` each agent passes.

It exists so the whole pipeline (and the demo script) runs with no API key and no network. It is
not a language model: the story it writes is a fixed Vietnamese template. Selected with
``EMVOOX_LLM_PROVIDER=mock`` or ``--llm mock``.
"""

from __future__ import annotations

from emvoox.providers.llm.base import LlmSchemaError, T, Usage

_BEATS = [
    ("phát hiện một bằng chứng bất ngờ", "Nhưng người đưa nó cho tôi... lại là người tôi tin nhất."),
    ("đối mặt trực tiếp với kẻ đứng sau", "Anh ta mỉm cười: \"Cô nghĩ mình là người đầu tiên tìm ra sao?\""),
    ("một đồng minh đổi phe", "Điện thoại rung. Tin nhắn chỉ có ba chữ: \"Chạy ngay đi.\""),
    ("kế hoạch phản công bắt đầu", "Cánh cửa mở ra. Người bước vào là người đã chết ba năm trước."),
    ("cái giá phải trả lộ diện", "Bản hợp đồng có chữ ký thứ hai. Chữ ký của mẹ tôi."),
]


def _tokens(*texts: str) -> int:
    return max(1, sum(len(t) for t in texts) // 4)


def _outline(ctx: dict) -> dict:
    roles = ctx.get("roles") or [{"name": "Linh", "description": "nữ chính"}, {"name": "Khôi", "description": "nam chính"}]
    count = int(ctx.get("count", 3))
    title = ctx.get("title") or "Câu chuyện mẫu"
    types = ["protagonist", "antagonist", "supporting", "minor"]
    return {
        "title": title, "logline": f"{roles[0]['name']} buộc phải giành lại quyền quyết định cuộc đời mình.",
        "premise": ctx.get("premise") or f"{roles[0]['name']} phát hiện bí mật phía sau một thỏa thuận và phải trả giá để công bố nó.",
        "tone": "căng thẳng, nội tâm, đô thị", "genre": [g.strip() for g in (ctx.get("genre") or "đô thị").split(",") if g.strip()][:4] or ["đô thị"],
        "protagonist_role": roles[0]["name"],
        "roles": [{"role_name": r["name"], "role_type": types[min(i, 3)], "description": r.get("description", ""), "actor_id": None,
                   "assigned_by": "ai", "reason": ""} for i, r in enumerate(roles)],
        "episodes": [{"number": n, "title": _BEATS[(n - 1) % len(_BEATS)][0].capitalize(),
                      "logline": f"{roles[0]['name']} {_BEATS[(n - 1) % len(_BEATS)][0]}.",
                      "key_beats": ["mở đầu bằng một bước ngoặt", _BEATS[(n - 1) % len(_BEATS)][0], "kết bằng cliffhanger"],
                      "cliffhanger": _BEATS[(n - 1) % len(_BEATS)][1], "source_span": ""} for n in range(1, count + 1)],
    }


def _draft(ctx: dict) -> dict:
    n = int(ctx.get("episode", 1))
    roles: list[str] = ctx.get("roles") or ["Linh", "Khôi"]
    prot = ctx.get("protagonist_role") or roles[0]
    other = next((r for r in roles if r != prot), prot)
    third = next((r for r in roles if r not in (prot, other)), None)
    beat, cliff = _BEATS[(n - 1) % len(_BEATS)]
    cliff = ctx.get("cliffhanger") or cliff
    lines1 = [
        {"speaker": prot, "internal": True, "direction": "", "text": "Ba năm rồi. Tôi cứ nghĩ mình đã quên được cái đêm hôm ấy."},
        {"speaker": other, "internal": False, "direction": "lạnh, chậm", "text": "Em đến trễ mười phút. Người như em không có quyền trễ."},
        {"speaker": prot, "internal": False, "direction": "bình tĩnh", "text": "Tôi đến đúng lúc anh cần nghe sự thật. Tập hồ sơ này, anh giải thích đi."},
        {"speaker": other, "internal": False, "direction": "khẽ, mỉa mai", "text": "Em nghĩ một tờ giấy có thể thay đổi được điều gì sao?"},
    ]
    lines2 = [
        {"speaker": prot, "internal": True, "direction": "", "text": f"Tôi {beat}. Tim tôi đập nhanh đến mức không thở nổi."},
        {"speaker": third or other, "internal": False, "direction": "gấp, lo lắng", "text": "Chị phải đi ngay. Họ biết chị đang ở đây rồi."},
        {"speaker": prot, "internal": False, "direction": "run nhưng dứt khoát", "text": "Không. Lần này tôi không chạy nữa."},
        {"speaker": prot, "internal": True, "direction": "", "text": cliff},
    ]
    extra = int(ctx.get("pad", 0))
    for i in range(extra):
        lines1.insert(3, {"speaker": other if i % 2 else prot, "internal": False, "direction": "",
                          "text": "Chuyện này không đơn giản như em tưởng, và tôi sẽ nói rõ từng điều một."})
    words = sum(len(ln["text"].split()) for ln in lines1 + lines2)
    return {"episode_number": n, "title": ctx.get("title") or f"Tập {n}", "estimated_duration_sec": max(20, round(words / 3.3)),
            "scenes": [{"heading": "Văn phòng tầng ba mươi. Đêm.", "atmosphere": "tiếng mưa ngoài kính", "lines": lines1},
                       {"heading": "Hành lang tối. Đêm.", "atmosphere": "", "lines": lines2}]}


def _market(ctx: dict) -> dict:
    refs = [o.get("title") or o.get("source", "") for o in (ctx.get("observations") or [])][:3]
    def cand(topic, theme, hook, a, m, p):
        genre = {"urban_ceo": "Tổng tài - hôn nhân hợp đồng", "rebirth_butterfly_effect": "Trọng sinh - lội ngược dòng"}.get(theme, "Vả mặt - phản công")
        return {"genre": genre, "evidence": "Xuất hiện trong: " + (", ".join(r for r in refs if r) or "ghi chú"), "platforms": ["local"], "topic": topic, "theme_category": theme, "target_audience": "Nữ 18-34, nghe truyện audio buổi tối, thích xung đột rõ và phản công",
                "hook": hook, "premise": (f"{topic}. Nhân vật chính có mục tiêu rõ và phải trả giá cho từng lựa chọn. Phản diện có lý do riêng, luôn đi trước "
                                          "một bước. Bước ngoặt đầu tiên đến trong ba mươi giây đầu, mỗi tập kết bằng một câu hỏi buộc người nghe mở tập sau. "
                                          "Bằng chứng được cài từ sớm, và phần kết giải quyết xung đột chính."),
                "anti_trope_angle": "Phản diện không ngu ngốc: họ có động cơ hợp lý và người nghe hiểu vì sao họ làm vậy.",
                "reference_titles": refs, "audience_fit": a, "momentum": m, "production_fit": p, "score": 0, "rationale": "mẫu ngoại tuyến"}
    return {"insights": [{"title": r or "seed", "platform": "local", "genre": "đô thị", "hook": "bí mật sau một thỏa thuận", "pacing": "bước ngoặt trong 30 giây",
                          "tropes": ["tổng tài", "hợp đồng hôn nhân"]} for r in refs] or [],
            "candidates": [
                cand("Ngày tôi phản công: người bị vu oan tìm bằng chứng", "intellectual_slap_anti_trope", "Cô bị đuổi việc vì một lỗi không phải của mình, và có 30 ngày để chứng minh.", 9, 8, 9),
                cand("Sau lớp hào quang: cuộc hôn nhân che giấu thỏa thuận thừa kế", "urban_ceo", "Đêm tân hôn, cô tìm thấy bản hợp đồng có tên mình trong két sắt của chồng.", 8, 8, 8),
                cand("Viết lại số phận: sống lại và phát hiện ký ức cũ không hoàn toàn chính xác", "rebirth_butterfly_effect", "Cô sống lại đúng ngày bị phản bội, nhưng lần này kẻ phản bội là người khác.", 8, 7, 7),
            ]}


def _adaptation(ctx: dict) -> dict:
    b = ctx.get("brief") or {}
    topic = b.get("topic", "Câu chuyện mẫu")
    return {"title": topic.split(":")[0][:60], "genre": {"urban_ceo": "Đô thị, tổng tài", "rebirth_butterfly_effect": "Tái sinh, lội ngược dòng",
                                                         "intellectual_slap_anti_trope": "Vả mặt, phản công"}.get(b.get("theme_category", ""), "Đô thị"),
            "setting": "Hiện đại, thành phố lớn",
            "roles": [{"name": "Hạ Vy", "description": "Nữ 26 tuổi, kế toán, bình tĩnh, sắc sảo; muốn minh oan cho mình.", "actor_id": None},
                      {"name": "Trình Khang", "description": "Nam 31 tuổi, giám đốc tài chính, điềm tĩnh, toan tính; che giấu một khoản thâm hụt để bảo vệ gia đình.", "actor_id": None},
                      {"name": "Mai", "description": "Nữ 24 tuổi, đồng nghiệp, tốt bụng nhưng sợ mất việc; biết nhiều hơn những gì cô nói.", "actor_id": None}],
            "treatment": (b.get("premise") or topic) + " Hồi một: Hạ Vy bị đổ lỗi và mất việc, nhưng giữ lại được một bản sao lưu. Hồi hai: cô lần theo "
                         "dòng tiền, phát hiện Trình Khang không phải kẻ chủ mưu duy nhất, và Mai buộc phải chọn phe. Hồi ba: cô công bố bằng chứng, trả giá "
                         "bằng một mối quan hệ, và người đứng sau cuối cùng lộ diện. Mỗi tập mở bằng một bước ngoặt và kết bằng một câu hỏi."}


def _casting(ctx: dict) -> dict:
    roster = list(ctx.get("roster") or [])
    out = []
    for r in ctx.get("roles") or []:
        pick = next((a for a in roster if a.get("gender") == r.get("gender")), None) or (roster[0] if roster else None)
        if pick:
            roster.remove(pick)
        out.append({"role_name": r["name"], "actor_id": pick["id"] if pick else None, "reason": "khớp giới tính và chất giọng (mẫu ngoại tuyến)"})
    return {"assignments": out or [{"role_name": "?", "actor_id": None, "reason": ""}]}


def _episode_script(ctx: dict) -> dict:
    from emvoox.delivery.screenplay import parse_screenplay

    return parse_screenplay(ctx["raw"], series_id=ctx["series_id"], episode_number=ctx["episode"], target_duration_sec=ctx["target_duration_sec"],
                            role_to_actor=ctx["role_to_actor"], cliffhanger=ctx.get("cliffhanger", "")).model_dump(mode="json")


def _cliffhanger(ctx: dict) -> dict:
    return {"episode_number": int(ctx.get("episode", 1)), "hook_score": int(ctx.get("force_score", 8)), "twist_within_30s": True,
            "antagonist_is_smart": True, "independent_motivations": True, "issues": [], "suggestion": "", "checked_by": "llm", "passed": True}


def _metadata(ctx: dict) -> dict:
    title = f"{ctx.get('series_title', 'Series')} | Tập {ctx.get('episode', 1)}: {ctx.get('title', '')}".strip(": ")[:100]
    return {"title": title, "description": f"{ctx.get('logline', '')}\n\nTruyện audio by Emvoox. Giọng đọc được tạo bằng AI.",
            "tags": ["truyện audio", "truyện ngắn", "Emvoox", "Mặc Khải"], "hashtags": ["#truyenaudio", "#MacKhai"],
            "playlist_title": ctx.get("series_title", ""), "thumbnail_text": (ctx.get("title") or "")[:40], "generated_by": "llm"}


HANDLERS = {
    "SeriesOutline": _outline, "EpisodeDraft": _draft, "MarketAnalysis": _market, "StoryAdaptation": _adaptation,
    "CastingProposal": _casting, "EpisodeScript": _episode_script, "CliffhangerCheck": _cliffhanger, "PublishMetadata": _metadata,
}


class MockLlm:
    name = "mock"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def generate_structured(self, *, system: str, user: str, schema: type[T], model: str | None = None,
                            temperature: float | None = None, max_output_tokens: int = 65_536,
                            context: dict | None = None) -> tuple[T, Usage]:
        handler = HANDLERS.get(schema.__name__)
        if handler is None:
            raise LlmSchemaError(f"mock LLM has no template for {schema.__name__}")
        self.calls.append(schema.__name__)
        payload = handler(context or {})
        instance = schema.model_validate(payload)
        return instance, Usage(model="mock-llm", prompt_tokens=_tokens(system, user),
                               output_tokens=_tokens(instance.model_dump_json()), thinking_tokens=0, elapsed_s=0.0, provider="mock")

    def transcribe(self, audio, *, model: str | None = None, language: str = "vi") -> tuple[str, Usage]:
        return "", Usage(model="mock-llm", prompt_tokens=0, output_tokens=0, thinking_tokens=0, elapsed_s=0.0, provider="mock")
