"""Market Research Agent: finds what audiences want next and hands the Script Writer a TrendBrief.

Skills
    Market Scan       collect raw observations: local trend seeds (inputs/trends/), notes pasted by a
                      human, and, when enabled, the visible text of public pages on DramaBox,
                      ReelShort, TikTok, Google and YouTube through a headless browser (Playwright)
    Content Analyze   one LLM call: what the hits have in common (genre, hook, pacing, tropes), which
                      genres are trending and which story direction follows from each
    Trend Ranking     deterministic weighted score per genre; the three best are documented in the
                      brief and a human picks the one that goes to the Script Writer

The browser scan reads only what an anonymous visitor sees and passes the text to the model; there
are no per-site selectors to maintain. A robot check, login wall or error page is reported as
"blocked" and never worked around. Every source is recorded as a ScanStep (status, text excerpt,
screenshot) in a ScanState the web client polls, so the scan can be watched while it runs.
Needs ``pip install -e .[research]`` and ``playwright install chromium``; off unless
``EMVOOX_RESEARCH_USE_BROWSER=true`` or the run asks for it.
"""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime

from emvoox.agents.base import Agent, AgentContext, AgentError, Skill
from emvoox.contracts.market import (
    THEME_LABEL_VI,
    TOP_GENRES,
    FormatSpec,
    MarketAnalysis,
    MarketObservation,
    ScanState,
    ScanStep,
    ThemeCategory,
    TrendBrief,
    TrendCandidate,
)
from emvoox.contracts.run import ResearchParams
from emvoox.providers.llm import LlmError
from emvoox.repositories import now_iso

# Public pages scanned when the browser is enabled. Extend or replace in inputs/market_sources.json:
#   [{"platform": "dramabox", "label": "...", "url": "https://..."}]
DEFAULT_SOURCES: list[dict] = [
    {"platform": "dramabox", "label": "DramaBox home (tiếng Việt)", "url": "https://www.dramabox.com/vi"},
    {"platform": "dramabox", "label": "DramaBox home (English)", "url": "https://www.dramabox.com/"},
    {"platform": "reelshort", "label": "ReelShort home (tiếng Việt)", "url": "https://www.reelshort.com/vi"},
    {"platform": "tiktok", "label": "TikTok search: phim ngắn short drama", "url": "https://www.tiktok.com/search?q=phim%20ng%E1%BA%AFn%20short%20drama"},
    {"platform": "google", "label": "Google search: thể loại phim ngắn hot nhất",
     "url": "https://www.google.com/search?q=th%E1%BB%83+lo%E1%BA%A1i+phim+ng%E1%BA%AFn+short+drama+hot+nh%E1%BA%A5t&hl=vi"},
    {"platform": "youtube", "label": "YouTube search: short drama full episodes", "url": "https://www.youtube.com/results?search_query=short+drama+full+episodes"},
    {"platform": "youtube", "label": "YouTube search: phim ngắn tổng tài full", "url": "https://www.youtube.com/results?search_query=phim+ng%E1%BA%AFn+t%E1%BB%95ng+t%C3%A0i+full"},
]
MAX_TEXT_PER_SOURCE = 6000
MIN_USEFUL_CHARS = 400
WEIGHTS = {"audience_fit": 0.45, "momentum": 0.30, "production_fit": 0.25}
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
# Signs that the page is a robot check, an error or a login wall rather than content.
BLOCK_URL = ("/sorry/", "/captcha", "/login", "accounts.google.com")
BLOCK_TEXT = ("unusual traffic", "lưu lượng truy cập bất thường", "too many requests", "đã xảy ra lỗi", "verify you are human", "xác minh bạn là người")

ANALYZE_SYSTEM = """Bạn là chuyên viên nghiên cứu thị trường của Emvoox, xưởng sản xuất micro-drama AUDIO tiếng Việt (kênh Mặc Khải).
Bạn nhận các ghi chú và văn bản thu thập từ các nền tảng phim ngắn (DramaBox, ReelShort, TikTok, Google, YouTube).

Nhiệm vụ:
1. insights[]: với mỗi tựa/chủ đề nổi bật trong dữ liệu (tối đa 12), ghi nền tảng, thể loại, hook (vì sao người ta bấm xem), nhịp (bước ngoặt đầu đến nhanh thế nào, tập kết ra sao) và các mô-típ.
2. candidates[]: xác định ĐÚNG 3 THỂ LOẠI phim ngắn đang thịnh hành nhất trong dữ liệu, mỗi thể loại là một phần tử, khác nhau rõ rệt. Với mỗi thể loại:
   - genre: tên thể loại như khán giả vẫn gọi (ví dụ "Tổng tài - hôn nhân hợp đồng", "Trọng sinh báo thù").
   - evidence: bằng chứng từ dữ liệu: các tựa cụ thể, số tập/lượt xem nếu có, xuất hiện trên nền tảng nào. Chỉ nêu điều có trong dữ liệu.
   - platforms: mã các nền tảng có thể loại này (dramabox, reelshort, tiktok, google, youtube, local).
   - theme_category: tuyến nội dung Mặc Khải gần nhất: urban_ceo (Đô thị - Tổng tài), intellectual_slap_anti_trope (Vả mặt - Ngược tra), rebirth_butterfly_effect (Tái sinh - Lội ngược dòng), hoặc other.
   - Một hướng truyện MỚI cho khán giả Việt trong thể loại đó, không sao chép tựa có sẵn: topic, target_audience, hook một câu, premise 5-8 câu (ai muốn gì, ai cản và vì sao, bước ngoặt), anti_trope_angle (làm mới mô-típ thế nào), reference_titles (tựa trong dữ liệu).
   - Chấm 1-10: audience_fit (hợp người nghe Việt), momentum (dữ liệu cho thấy thể loại mạnh đến đâu: xuất hiện nhiều lần, trên nhiều nền tảng), production_fit (hợp audio chỉ có thoại, 2-4 diễn viên cố định). rationale: một câu giải thích điểm.

Quy tắc: chỉ dựa trên dữ liệu được cung cấp, không bịa số liệu. Làm theo "Hướng dẫn nghiên cứu" của biên tập nếu có. Nhân vật phải có động cơ riêng, phản diện thông minh, bước ngoặt đầu trong 30 giây. Viết bằng tiếng Việt; theme_category và platforms dùng đúng mã tiếng Anh ở trên. Để score = 0.
"""


class ScanRecorder:
    """Publishes the progress of one research run as a ScanState document the web client polls."""

    def __init__(self, ctx: AgentContext, params: ResearchParams, use_browser: bool, scan_id: str | None = None):
        self.ctx = ctx
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        self.state = ScanState(scan_id=scan_id or f"scan-{stamp}", created_at=now_iso(), guide=params.guide, focus=params.focus,
                               use_browser=use_browser, platforms=list(params.platforms))
        self.save()

    def save(self) -> None:
        self.ctx.repos.research.save_scan(self.state)

    def log(self, message: str) -> None:
        self.ctx.log(message)
        self.state.log.append(f"{datetime.now(UTC).strftime('%H:%M:%S')} {message}")
        self.save()

    def phase(self, phase: str, message: str) -> None:
        self.state.phase = phase  # type: ignore[assignment]
        self.log(message)

    def add(self, step: ScanStep) -> ScanStep:
        self.state.steps.append(step)
        self.save()
        return step

    def finish(self, *, brief_id: str | None = None, error: str | None = None) -> None:
        self.state.status = "failed" if error else "done"
        self.state.phase = "done" if not error else self.state.phase
        self.state.brief_id, self.state.error, self.state.finished_at = brief_id, error, now_iso()
        self.save()


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
    def sources_for(self, ctx: AgentContext, params: ResearchParams) -> list[dict]:
        wanted = {p.lower() for p in params.platforms}
        sources = ctx.repos.research.market_sources() or DEFAULT_SOURCES
        return [s for s in sources if not wanted or str(s.get("platform", "")).lower() in wanted]

    def market_scan(self, ctx: AgentContext, params: ResearchParams, rec: ScanRecorder | None = None) -> list[MarketObservation]:
        now = now_iso()
        use_browser = ctx.settings.research_use_browser if params.use_browser is None else params.use_browser
        rec = rec or ScanRecorder(ctx, params, use_browser)
        obs: list[MarketObservation] = []

        def local(source: str, title: str, text: str) -> None:
            obs.append(MarketObservation(platform="local", source=source, title=title, text=text, captured_at=now))
            rec.add(ScanStep(platform="local", label=source, status="ok", title=title, chars=len(text), excerpt=text[:600]))

        if params.seeds.strip():
            local("pasted notes", "Ghi chú của biên tập", params.seeds.strip()[:MAX_TEXT_PER_SOURCE * 2])
        for name, text in ctx.repos.research.seed_files():
            local(name, name.rsplit(".", 1)[0], text[:MAX_TEXT_PER_SOURCE])
        if use_browser:
            obs.extend(self._scan_pages(ctx, self.sources_for(ctx, params), rec))
        rec.log(f"market scan: {len(obs)} observation(s) from {sorted({o.platform for o in obs}) or '[]'}")
        return obs

    def _scan_pages(self, ctx: AgentContext, sources: list[dict], rec: ScanRecorder) -> list[MarketObservation]:
        """Visible text of each public page, one browser for the whole scan. A source that fails
        (blocked, timeout) is recorded and skipped; it never fails the run."""
        steps = [rec.add(ScanStep(platform=str(s.get("platform", "web")), url=str(s.get("url", "")), label=str(s.get("label") or s.get("url", ""))))
                 for s in sources]
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            msg = "Playwright is not installed (pip install -e '.[research]' && playwright install chromium)"
            for st in steps:
                st.status, st.detail = "error", msg
            rec.save()
            ctx.note(f"Browser scan skipped: {msg}.")
            return []
        out: list[MarketObservation] = []
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                try:
                    context = browser.new_context(locale="vi-VN", user_agent=USER_AGENT, viewport={"width": 1280, "height": 900})
                    for i, st in enumerate(steps, start=1):
                        if ctx.cancel.is_set():
                            break
                        o = self._scan_page(context, st, rec, i)
                        if o:
                            out.append(o)
                finally:
                    browser.close()
        except Exception as e:  # noqa: BLE001 - e.g. the browser binary is missing
            msg = f"{type(e).__name__}: {str(e)[:200]}"
            for st in steps:
                if st.status in ("pending", "running"):
                    st.status, st.detail = "error", msg
            rec.log(f"market scan: browser unavailable ({msg})")
        return out

    def _scan_page(self, context, st: ScanStep, rec: ScanRecorder, index: int) -> MarketObservation | None:
        t0 = time.time()
        st.status = "running"
        rec.log(f"market scan: opening {st.platform} {st.url}")
        page = context.new_page()
        try:
            response = page.goto(st.url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(3000)
            for _ in range(3):  # let lazy lists load, like a visitor scrolling
                page.mouse.wheel(0, 1500)
                page.wait_for_timeout(600)
            st.title = page.title()[:120]
            text = re.sub(r"\n{2,}", "\n", page.inner_text("body")).strip()
            shot = f"{st.platform}-{index}.jpg"
            try:
                page.screenshot(path=str(rec.ctx.repos.research.shot_path(rec.state.scan_id, shot)), type="jpeg", quality=55)
                st.screenshot = shot
            except Exception:  # noqa: BLE001 - a screenshot is a nicety
                st.screenshot = None
            st.chars, st.excerpt = len(text), text[:600]
            status = response.status if response else 0
            low = text.lower()
            if status in (403, 429) or any(k in page.url for k in BLOCK_URL) or (len(text) < 2000 and any(k in low for k in BLOCK_TEXT)):
                st.status, st.detail = "blocked", f"the site answered with a robot check or an error page (HTTP {status or '?'})"
            elif len(text) < MIN_USEFUL_CHARS:
                st.status, st.detail = "blocked", "almost no readable text (login wall or bot check)"
            else:
                st.status = "ok"
        except Exception as e:  # noqa: BLE001 - a blocked or slow site must not fail the run
            st.status, st.detail = "error", f"{type(e).__name__}: {str(e)[:160]}"
        finally:
            page.close()
        st.elapsed_s = round(time.time() - t0, 1)
        rec.log(f"market scan: {st.platform} {st.status}" + (f" ({st.chars:,} characters)" if st.status == "ok" else f": {st.detail}"))
        if st.status != "ok":
            return None
        return MarketObservation(platform=st.platform, source=st.url, title=st.title, text=text[:MAX_TEXT_PER_SOURCE], captured_at=now_iso(), via="browser")

    # ---- skill: Content Analyze
    def content_analyze(self, ctx: AgentContext, observations: list[MarketObservation], focus: str = "", guide: str = "") -> MarketAnalysis:
        blocks = "\n\n".join(f"<source platform=\"{o.platform}\" name=\"{o.source}\">\n{o.text}\n</source>" for o in observations)
        user = (f"Hướng dẫn nghiên cứu: {guide.strip() or '(không có)'}\nTrọng tâm biên tập: {focus or '(không có)'}\n\nDỮ LIỆU THU THẬP ({len(observations)} nguồn):\n{blocks}\n\n"
                "Hãy trả về MarketAnalysis.")
        return ctx.llm.structured(agent=self.id, skill="content_analyze", system=ANALYZE_SYSTEM, user=user, schema=MarketAnalysis,
                                  context={"observations": [o.model_dump() for o in observations], "focus": focus, "guide": guide})

    # ---- skill: Trend Ranking
    def trend_ranking(self, candidates: list[TrendCandidate], focus: str = "") -> list[TrendCandidate]:
        """Weighted score per candidate. When the editor gave a focus, candidates on that line come first."""
        f = focus.lower().strip()

        def on_focus(c: TrendCandidate) -> bool:
            return bool(f) and (f in c.theme_category.value or f in THEME_LABEL_VI[c.theme_category].lower() or f in c.topic.lower())

        ranked = [c.model_copy(update={"score": round(sum(getattr(c, k) * w for k, w in WEIGHTS.items()), 2)}) for c in candidates]
        return sorted(ranked, key=lambda c: (not on_focus(c), -c.score, c.topic))

    # ---- agent entry point
    def run(self, ctx: AgentContext, params: ResearchParams, *, fmt: FormatSpec | None = None, scan_id: str | None = None) -> TrendBrief:
        use_browser = ctx.settings.research_use_browser if params.use_browser is None else params.use_browser
        rec = ScanRecorder(ctx, params, use_browser, scan_id)
        try:
            brief = self._run(ctx, params, rec, fmt)
        except AgentError as e:
            rec.finish(error=str(e))
            raise
        except Exception as e:  # noqa: BLE001 - the scan document must not stay "running" forever
            rec.finish(error=f"{type(e).__name__}: {str(e)[:300]}")
            raise
        rec.finish(brief_id=brief.brief_id)
        return brief

    def _run(self, ctx: AgentContext, params: ResearchParams, rec: ScanRecorder, fmt: FormatSpec | None) -> TrendBrief:
        observations = self.market_scan(ctx, params, rec)
        if not observations:
            blocked = [s.platform for s in rec.state.steps if s.status in ("blocked", "error")]
            raise AgentError("Market Scan found nothing to analyse: " + (f"every scanned page was blocked or failed ({', '.join(sorted(set(blocked)))}); " if blocked else "")
                             + "add trend notes under data/inputs/trends/, paste notes into the run, or enable the browser scan (EMVOOX_RESEARCH_USE_BROWSER=true).")
        rec.phase("analyze", f"content analyze: {sum(len(o.text) for o in observations):,} characters from {len(observations)} source(s) to {ctx.llm.model}")
        try:
            analysis = self.content_analyze(ctx, observations, params.focus, params.guide)
        except LlmError as e:
            raise AgentError(f"Content Analyze failed: {e}", retryable=True) from e
        rec.phase("rank", f"trend ranking: {len(analysis.candidates)} genre(s) scored")
        ranked = self.trend_ranking(analysis.candidates, params.focus)[:TOP_GENRES]
        top = ranked[0]
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        brief = TrendBrief(
            brief_id=f"{slug(top.theme_category.value.split('_')[0] + '-' + stamp)}", created_at=now_iso(), topic=top.topic,
            target_audience=top.target_audience, format_spec=fmt or FormatSpec(), theme_category=ThemeCategory(top.theme_category),
            hook=top.hook, premise=top.premise, anti_trope_angle=top.anti_trope_angle, reference_titles=top.reference_titles,
            score=top.score, candidates=ranked, insights=analysis.insights, sources=[o.source for o in observations],
            platforms=sorted({o.platform for o in observations}), notes=params.focus, genre=top.genre, guide=params.guide, selected=0,
            scan_id=rec.state.scan_id)
        ctx.repos.research.save_brief(brief)
        rec.log(f"trend ranking: top {len(ranked)} genre(s): " + "; ".join(f"{c.genre or c.topic} ({c.score})" for c in ranked))
        ctx.log(f"brief {brief.brief_id} = {top.topic!r} ({top.theme_category.value}, score {top.score})")
        return brief
