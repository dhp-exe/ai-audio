"""Market Research Agent: finds what audiences want next and hands the Script Writer a TrendBrief.

Skills
    Market Scan       collect raw observations: local trend seeds (inputs/trends/), notes pasted by a
                      human, and, when enabled, the visible text of public pages on DramaBox,
                      ReelShort, TikTok... through a headless browser (Playwright)
    Content Analyze   one LLM call: what the hits have in common (genre, hook, pacing, tropes) and
                      which story directions follow from it
    Trend Ranking     deterministic weighted score per candidate; the best one becomes the brief

The browser scan reads only what an anonymous visitor sees on a listing page and passes the text to
the model; there are no per-site selectors to maintain. It is optional (``pip install -e .[research]``
then ``playwright install chromium``) and off unless ``EMVOOX_RESEARCH_USE_BROWSER=true`` or the run
asks for it. Without it the agent works from local seeds, which is the supported path before V1RON
OS provides its browser automation fleet.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from emvoox.agents.base import Agent, AgentContext, AgentError, Skill
from emvoox.contracts.market import (
    THEME_LABEL_VI,
    FormatSpec,
    MarketAnalysis,
    MarketObservation,
    ThemeCategory,
    TrendBrief,
    TrendCandidate,
)
from emvoox.contracts.run import ResearchParams
from emvoox.providers.llm import LlmError
from emvoox.repositories import now_iso

# Public listing pages scanned when the browser is enabled. Extend or replace in inputs/market_sources.json:
#   [{"platform": "dramabox", "url": "https://..."}]
DEFAULT_SOURCES: list[dict] = [
    {"platform": "dramabox", "url": "https://www.dramabox.com/"},
    {"platform": "reelshort", "url": "https://www.reelshort.com/"},
    {"platform": "tiktok", "url": "https://www.tiktok.com/tag/shortdrama"},
]
MAX_TEXT_PER_SOURCE = 4000
WEIGHTS = {"audience_fit": 0.45, "momentum": 0.30, "production_fit": 0.25}

ANALYZE_SYSTEM = """Bạn là chuyên viên nghiên cứu thị trường của Emvoox, xưởng sản xuất micro-drama AUDIO tiếng Việt (kênh Mặc Khải).
Bạn nhận các ghi chú và văn bản thu thập từ các nền tảng phim ngắn (DramaBox, ReelShort, TikTok, Douyin, YouTube).

Nhiệm vụ:
1. insights[]: với mỗi tựa/chủ đề nổi bật trong dữ liệu, ghi thể loại, hook (vì sao người ta bấm xem), nhịp (bước ngoặt đầu đến nhanh thế nào, tập kết ra sao) và các mô-típ.
2. candidates[]: đề xuất 3-5 hướng truyện MỚI cho khán giả Việt, không sao chép tựa có sẵn. Mỗi hướng thuộc một tuyến nội dung:
   - urban_ceo: Đô thị - Tổng tài (địa vị, gia đình, quyền lực, bí mật)
   - intellectual_slap_anti_trope: Vả mặt - Ngược tra (xung đột, đối đầu, phản công bằng trí tuệ)
   - rebirth_butterfly_effect: Tái sinh - Lội ngược dòng (cơ hội mới, lựa chọn mới, hiệu ứng cánh bướm)
   Với mỗi hướng: topic, target_audience, hook một câu, premise 5-8 câu (ai muốn gì, ai cản và vì sao, bước ngoặt), anti_trope_angle (làm mới mô-típ thế nào), reference_titles.
   Chấm 1-10: audience_fit (hợp người nghe Việt), momentum (dữ liệu cho thấy xu hướng mạnh đến đâu), production_fit (hợp audio chỉ có thoại, 2-4 diễn viên cố định).

Quy tắc: chỉ dựa trên dữ liệu được cung cấp, không bịa số liệu. Nhân vật phải có động cơ riêng, phản diện thông minh, bước ngoặt đầu trong 30 giây. Viết bằng tiếng Việt; theme_category dùng đúng mã tiếng Anh ở trên. Để score = 0.
"""


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:24] or "brief"


class MarketResearchAgent(Agent):
    id = "market_research"
    title = "Market Research Agent"
    description = "Scans short-drama platforms and local trend notes, analyses what works and ranks story directions."
    skills = (
        Skill("market_scan", "Market Scan", "Collect observations from local trend seeds and, optionally, public platform pages via a headless browser."),
        Skill("content_analyze", "Content Analyze", "LLM analysis of hits: genre, hook, pacing, tropes; proposes story directions."),
        Skill("trend_ranking", "Trend Ranking", "Weighted score per candidate (audience fit, momentum, production fit); the top one becomes the brief."),
    )
    consumes = "ResearchParams"
    produces = TrendBrief

    # ---- skill: Market Scan
    def market_scan(self, ctx: AgentContext, params: ResearchParams) -> list[MarketObservation]:
        now = now_iso()
        obs: list[MarketObservation] = []
        if params.seeds.strip():
            obs.append(MarketObservation(platform="local", source="pasted notes", title="Ghi chú của biên tập", text=params.seeds.strip()[:MAX_TEXT_PER_SOURCE * 2], captured_at=now))
        for name, text in ctx.repos.research.seed_files():
            obs.append(MarketObservation(platform="local", source=name, title=name.rsplit(".", 1)[0], text=text[:MAX_TEXT_PER_SOURCE], captured_at=now))
        use_browser = ctx.settings.research_use_browser if params.use_browser is None else params.use_browser
        if use_browser:
            wanted = {p.lower() for p in params.platforms}
            sources = ctx.repos.research.market_sources() or DEFAULT_SOURCES
            for src in sources:
                if wanted and str(src.get("platform", "")).lower() not in wanted:
                    continue
                o = self._scan_page(ctx, src)
                if o:
                    obs.append(o)
        ctx.log(f"market scan: {len(obs)} observation(s) from {sorted({o.platform for o in obs}) or '[]'}")
        return obs

    def _scan_page(self, ctx: AgentContext, src: dict) -> MarketObservation | None:
        """Visible text of one public page. Any failure (package missing, blocked, timeout) is logged and skipped."""
        url, platform = str(src.get("url", "")), str(src.get("platform", "web"))
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            ctx.note("Browser scan skipped: Playwright is not installed (pip install -e '.[research]' && playwright install chromium).")
            return None
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                try:
                    page = browser.new_page(locale="vi-VN")
                    page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                    page.wait_for_timeout(2500)
                    title = page.title()
                    text = page.inner_text("body")
                finally:
                    browser.close()
        except Exception as e:  # noqa: BLE001 - a blocked or slow site must not fail the run
            ctx.log(f"market scan: {platform} {url} skipped ({type(e).__name__}: {str(e)[:120]})")
            return None
        text = re.sub(r"\n{2,}", "\n", text).strip()
        if len(text) < 80:
            ctx.log(f"market scan: {platform} returned almost no text (login wall or bot check); skipped")
            return None
        return MarketObservation(platform=platform, source=url, title=title[:120], text=text[:MAX_TEXT_PER_SOURCE], captured_at=now_iso(), via="browser")

    # ---- skill: Content Analyze
    def content_analyze(self, ctx: AgentContext, observations: list[MarketObservation], focus: str = "") -> MarketAnalysis:
        blocks = "\n\n".join(f"<source platform=\"{o.platform}\" name=\"{o.source}\">\n{o.text}\n</source>" for o in observations)
        user = (f"Trọng tâm biên tập: {focus or '(không có, cân bằng cả ba tuyến)'}\n\nDỮ LIỆU THU THẬP ({len(observations)} nguồn):\n{blocks}\n\n"
                "Hãy trả về MarketAnalysis.")
        return ctx.llm.structured(agent=self.id, skill="content_analyze", system=ANALYZE_SYSTEM, user=user, schema=MarketAnalysis,
                                  context={"observations": [o.model_dump() for o in observations], "focus": focus})

    # ---- skill: Trend Ranking
    def trend_ranking(self, candidates: list[TrendCandidate], focus: str = "") -> list[TrendCandidate]:
        """Weighted score per candidate. When the editor gave a focus, candidates on that line come first."""
        f = focus.lower().strip()

        def on_focus(c: TrendCandidate) -> bool:
            return bool(f) and (f in c.theme_category.value or f in THEME_LABEL_VI[c.theme_category].lower() or f in c.topic.lower())

        ranked = [c.model_copy(update={"score": round(sum(getattr(c, k) * w for k, w in WEIGHTS.items()), 2)}) for c in candidates]
        return sorted(ranked, key=lambda c: (not on_focus(c), -c.score, c.topic))

    # ---- agent entry point
    def run(self, ctx: AgentContext, params: ResearchParams, *, fmt: FormatSpec | None = None) -> TrendBrief:
        observations = self.market_scan(ctx, params)
        if not observations:
            raise AgentError("Market Scan found nothing to analyse: add trend notes under data/inputs/trends/, paste notes into the run, "
                             "or enable the browser scan (EMVOOX_RESEARCH_USE_BROWSER=true).")
        try:
            analysis = self.content_analyze(ctx, observations, params.focus)
        except LlmError as e:
            raise AgentError(f"Content Analyze failed: {e}", retryable=True) from e
        ranked = self.trend_ranking(analysis.candidates, params.focus)
        top = ranked[0]
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        brief = TrendBrief(
            brief_id=f"{slug(top.theme_category.value.split('_')[0] + '-' + stamp)}", created_at=now_iso(), topic=top.topic,
            target_audience=top.target_audience, format_spec=fmt or FormatSpec(), theme_category=ThemeCategory(top.theme_category),
            hook=top.hook, premise=top.premise, anti_trope_angle=top.anti_trope_angle, reference_titles=top.reference_titles,
            score=top.score, candidates=ranked, insights=analysis.insights, sources=[o.source for o in observations],
            platforms=sorted({o.platform for o in observations}), notes=params.focus)
        ctx.repos.research.save_brief(brief)
        ctx.log(f"trend ranking: {len(ranked)} candidate(s); brief {brief.brief_id} = {top.topic!r} ({top.theme_category.value}, score {top.score})")
        return brief
