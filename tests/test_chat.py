"""The AI-first chat: one message to the Producer agent leads to a mastered episode, stopping only where a person
decides; the thread, its open questions and its runs' decisions survive a restart; everything is on the record."""

from __future__ import annotations

import time

import pytest
from conftest import needs_ffmpeg, restart_workers, seed_registry
from fastapi.testclient import TestClient

from emvoox.api import app as webapp
from emvoox.config import reset_settings
from emvoox.repositories import get_repositories

pytestmark = needs_ffmpeg
IDEA = "Làm một series 10 tập thể loại trọng sinh cho khán giả nữ 25-34"


@pytest.fixture
def client(sandbox, monkeypatch):
    monkeypatch.setenv("EMVOOX_LLM_PROVIDER", "mock")  # the studio's default model drives the chat
    monkeypatch.setenv("EMVOOX_TTS_PROVIDER", "mock")
    reset_settings()
    repos = get_repositories()
    seed_registry(sandbox)
    repos.blobs.write_text("inputs/trends/week41.md", "Top DramaBox tuần này: trọng sinh báo thù, tổng tài hợp đồng, vả mặt mẹ chồng. Khán giả khen phản diện thông minh.")
    return TestClient(webapp.app)


def settle(client, thread_id: str, timeout: float = 60.0) -> dict:
    """Wait for the Producer's turn to end."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = client.get(f"/api/chat/threads/{thread_id}").json()
        if v["thread"]["status"] != "running":
            return v
        time.sleep(0.1)
    raise AssertionError("the turn did not end")


def wait_run(client, run_id: str, until: tuple[str, ...], timeout: float = 120.0) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = client.get(f"/api/runs/{run_id}").json()
        if r["status"] in until:
            return r
        time.sleep(0.2)
    raise AssertionError(f"run is {r['status']}, expected one of {until}")


def kinds(view: dict) -> list[str]:
    return [i["tool"] if i["kind"] == "tool" else i["kind"] for i in view["items"]]


def test_one_message_reaches_a_mastered_episode_stopping_only_for_decisions(client):
    repos = get_repositories()
    # 1. the idea: the Producer hands the research to the Market Research agent, reads the brief, and asks which genre
    v = client.post("/api/chat/threads", json={"text": IDEA, "user": "an"}).json()
    tid = v["thread"]["id"]
    assert v["thread"]["status"] == "running" and v["thread"]["title"] == IDEA[:60] + "…" and kinds(v) == ["user"]
    v = settle(client, tid)
    assert v["thread"]["status"] == "waiting" and kinds(v) == ["user", "spawn_subagent", "library_list_briefs", "ask_user"]
    spawn, _, ask = v["items"][1:]
    assert spawn["status"] == "done" and spawn["result"]["agent"] == "market_research" and spawn["result"]["brief_id"]
    q = ask["pending"]
    assert ask["status"] == "waiting" and q["kind"] == "question" and len(q["options"]) == 3 and q["message"] == "Bạn muốn sản xuất thể loại nào?"
    brief = repos.research.load_brief(spawn["result"]["brief_id"])
    assert [c.genre for c in brief.candidates] == q["options"] and brief.selected == 0

    # 2. the person picks the second genre: the Producer wants to start production, which needs their approval
    v = client.post(f"/api/chat/threads/{tid}/answers", json={"answers": [{"id": q["id"], "answer": q["options"][1]}]}).json()
    v = settle(client, tid)
    start = v["items"][-1]
    assert v["thread"]["status"] == "waiting" and start["tool"] == "production_start" and start["pending"]["kind"] == "tool_approval"
    assert start["args"]["brief_id"] == brief.brief_id and start["args"]["genre_index"] == 1 and start["args"]["produce"] == 1
    assert v["runs"] == [] and repos.series.list_ids() == []  # nothing has been spent yet

    # 3. approved: the run starts in the background and the Producer says so
    v = client.post(f"/api/chat/threads/{tid}/answers", json={"answers": [{"id": start["pending"]["id"], "approved": True, "reviewer": "an"}]}).json()
    v = settle(client, tid)
    assert v["thread"]["status"] == "idle" and v["items"][-1]["kind"] == "assistant" and "Đã bắt đầu sản xuất" in v["items"][-1]["text"]
    assert len(v["runs"]) == 1 and repos.research.load_brief(brief.brief_id).selected == 1
    run_id, sid = v["runs"][0]["run_id"], v["runs"][0]["series_id"]
    assert wait_run(client, run_id, ("awaiting_approval", "failed"))["status"] == "awaiting_approval"

    # 4. the episode is mastered and waits at the gate; it is shown in the conversation and approved from there
    v = client.get(f"/api/chat/threads/{tid}").json()
    run = v["runs"][0]
    assert run["status"] == "awaiting_approval" and run["progress"]["done"] == run["progress"]["total"] and run["decisions"] == []
    assert [(e["episode_number"], e["state"], bool(e["master_url"])) for e in run["episodes"]] == [(1, "awaiting_approval", True)]
    assert client.get(run["episodes"][0]["master_url"]).status_code == 200
    assert client.post(f"/api/series/{sid}/episodes/1/approve", json={"reviewer": "an"}).json()["state"] == "approved"
    assert client.get(f"/api/chat/threads/{tid}").json()["runs"][0]["episodes"][0]["state"] == "approved"

    # 5. later: a follow-up question is a new turn in the same thread
    client.post(f"/api/chat/threads/{tid}/messages", json={"text": "Tiến độ thế nào rồi?"})
    v = settle(client, tid)
    assert kinds(v)[-3:] == ["user", "library_run_status", "assistant"] and "awaiting_approval" in v["items"][-1]["text"]

    # everything that happened is on the record: the thread's events, and every model and tool call in the ledger
    events = client.get(f"/api/chat/threads/{tid}/events").json()["events"]
    types = [e["type"] for e in events]
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1)) and types[0] == "user.message" and types.count("user.message") == 2
    assert {"agent.spawned", "tool.called", "tool.result", "agent.asked", "agent.waiting", "agent.answered", "agent.finished", "agent.text"} <= set(types)
    assert [e["data"]["tool"] for e in events if e["type"] == "agent.asked"] == ["ask_user", "production_start"]
    ledger = repos.docs.read_log("telemetry/run_log.jsonl")
    tools = [r["skill"] for r in ledger if r["kind"] == "agent" and r["skill"].startswith("tool:")]
    assert "tool:production_start" in tools and "tool:research_write_brief" in tools and "tool:spawn_subagent" in tools
    assert sum(1 for r in ledger if r["kind"] == "llm" and r["agent"] == "producer") >= 6
    assert next(r for r in ledger if r["skill"] == "tool:production_start")["note"] == "an"  # who it ran for
    stream = client.get(f"/api/chat/threads/{tid}/stream?after={len(events) - 1}").text
    assert f"id: {len(events)}" in stream and "event: turn.end" in stream


def test_the_thread_and_what_it_waits_for_survive_a_restart_and_scene_decisions_show_in_the_chat(client):
    v = client.post("/api/chat/threads", json={"text": IDEA + ", duyệt từng cảnh"}).json()
    tid = v["thread"]["id"]
    v = settle(client, tid)
    question = v["items"][-1]["pending"]

    restart_workers()  # the server restarted, the browser was closed
    client = TestClient(webapp.app)
    assert [t["id"] for t in client.get("/api/chat/threads").json()["threads"]] == [tid]
    again = client.get(f"/api/chat/threads/{tid}").json()
    assert again["thread"]["status"] == "waiting" and again["items"] == v["items"] and again["items"][-1]["pending"] == question

    client.post(f"/api/chat/threads/{tid}/answers", json={"answers": [{"id": question["id"], "answer": question["options"][0]}]})
    v = settle(client, tid)
    client.post(f"/api/chat/threads/{tid}/answers", json={"answers": [{"id": v["items"][-1]["pending"]["id"], "approved": True, "reviewer": "an"}]})
    v = settle(client, tid)
    run_id = v["runs"][0]["run_id"]
    wait_run(client, run_id, ("waiting", "failed"))
    run = client.get(f"/api/chat/threads/{tid}").json()["runs"][0]
    assert run["status"] == "waiting" and [(d["kind"], d["scene_id"]) for d in run["decisions"]] == [("scene_approval", "sc01"), ("scene_approval", "sc02")]
    assert run["decisions"][0]["scene"]["stems"] and run["decisions"][0]["run_id"] == run_id  # the same cards as the Approvals page
    answers = [{"id": d["id"], "approved": True, "reviewer": "an"} for d in run["decisions"]]
    assert client.post(f"/api/runs/{run_id}/decisions", json={"decisions": answers}).status_code == 200
    assert wait_run(client, run_id, ("awaiting_approval", "failed"))["status"] == "awaiting_approval"
    assert client.get(f"/api/chat/threads/{tid}").json()["runs"][0]["decisions"] == []


def test_declining_the_start_spends_nothing_and_a_reply_counts_as_the_answer(client):
    repos = get_repositories()
    v = client.post("/api/chat/threads", json={"text": IDEA}).json()
    tid = v["thread"]["id"]
    v = settle(client, tid)
    genres = v["items"][-1]["pending"]["options"]
    # typing a reply instead of pressing an option answers the open question
    client.post(f"/api/chat/threads/{tid}/messages", json={"text": genres[2]})
    v = settle(client, tid)
    assert v["items"][-2]["result"] == {"answer": genres[2]} and v["items"][-1]["args"]["genre_index"] == 2 and v["thread"]["status"] == "waiting"
    assert kinds(v).count("user") == 1  # it was recorded as the answer, not as a second request
    # ... and typing a reply instead of approving declines the tool call
    client.post(f"/api/chat/threads/{tid}/messages", json={"text": "khoan, để mai"})
    v = settle(client, tid)
    assert v["thread"]["status"] == "idle" and v["items"][-2]["status"] == "failed" and "did not approve this call: khoan, để mai" in v["items"][-2]["result"]["error"]
    assert v["items"][-1]["text"].startswith("Mình chưa bắt đầu sản xuất") and v["runs"] == [] and repos.series.list_ids() == []


def test_own_story_skips_research_and_api_guards(client):
    repos = get_repositories()
    story = "Tựa: Bản hợp đồng\nTruyện: Linh bị đổ lỗi cho một khoản thâm hụt và mất việc. Cô giữ lại một bản sao lưu, lần theo dòng tiền và phát hiện sự thật."
    v = client.post("/api/chat/threads", json={"text": story}).json()
    tid = v["thread"]["id"]
    v = settle(client, tid)
    start = v["items"][-1]
    thread = repos.chat.load(tid)
    repos.chat.save(thread.model_copy(update={"status": "running"}))  # while the Producer is working, the thread takes no new message
    assert client.post(f"/api/chat/threads/{tid}/messages", json={"text": "nhanh lên"}).status_code == 409
    assert client.delete(f"/api/chat/threads/{tid}").status_code == 409
    assert client.post(f"/api/chat/threads/{tid}/answers", json={"answers": [{"id": start["pending"]["id"], "approved": True}]}).status_code == 409
    repos.chat.save(thread)
    assert kinds(v) == ["user", "production_start"] and start["args"]["source"] == "story" and start["args"]["title"] == "Bản hợp đồng"
    assert client.post(f"/api/chat/threads/{tid}/answers", json={"answers": [{"id": "nope", "approved": True}]}).status_code == 422
    client.post(f"/api/chat/threads/{tid}/answers", json={"answers": [{"id": start["pending"]["id"], "approved": True}]})
    v = settle(client, tid)
    run = v["runs"][0]
    assert wait_run(client, run["run_id"], ("awaiting_approval", "failed"))["status"] == "awaiting_approval"
    assert repos.series.load_bible(run["series_id"]).title and repos.research.list_briefs() == []
    assert client.post("/api/chat/threads", json={"text": "  "}).status_code == 422 and client.get("/api/chat/threads/th-nope").status_code == 404
    assert client.delete(f"/api/chat/threads/{tid}").json() == {"ok": True} and client.get("/api/chat/threads").json()["threads"] == []
    assert repos.sessions.load(tid) is None and client.get(f"/api/runs/{run['run_id']}").status_code == 200  # the production outlives the conversation
