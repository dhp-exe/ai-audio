"""Pipeline orchestrator: runs the skill CLIs as jobs with dependencies and records progress.

Job graph for one run (N episodes planned, K episodes produced):

    outline ──> cast ──> ep01.draft ─> ep01.direct ─> ep01.voice ─> ep01.assemble ─> ep01.qa
                    └──> ep02.draft ─> ep02.direct ─> ep02.voice ─> ...
                    └──> ...

Episodes run in parallel up to `max_parallel_episodes` (LLM stages), but the `voice` stage holds a
lock so only one episode talks to ElevenLabs at a time.

State is written to series/<id>/pipeline_run.json after every change so the web UI (or a CLI
`--watch`) can render it, and per-job stdout/stderr go to series/<id>/logs/<job_id>.log.

CLI:  python -m pipeline.orchestrator --series demo --story story.txt --episodes 30 --produce 5 \
          --min-sec 50 --max-sec 70
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from pipeline import naming
from pipeline import registry as registry_io
from pipeline.casting import guess_gender, placeholder_voice
from pipeline.schema import CharacterProfile, ProviderVoice, SeriesBible, StoryInput

SKILLS = naming.REPO_ROOT / ".claude" / "skills"
STAGES = ("draft", "direct", "voice", "assemble", "qa")
STAGE_LABELS = {"outline": "Outline", "cast": "Cast", "draft": "Draft", "direct": "Direct",
                "voice": "Voice", "assemble": "Assemble", "qa": "QA"}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class Job:
    id: str
    stage: str
    episode: int | None
    cmd: list[str]
    status: str = "pending"  # pending | running | done | warn | failed | skipped
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    log_path: str | None = None
    summary: dict = field(default_factory=dict)
    error: str | None = None

    @property
    def label(self) -> str:
        return STAGE_LABELS.get(self.stage, self.stage)


@dataclass
class RunParams:
    series_id: str
    episodes: int = 30
    produce: int | None = None
    min_sec: int = 50
    max_sec: int = 70
    max_parallel_episodes: int = 2
    force: bool = False


class Run:
    def __init__(self, params: RunParams):
        self.params = params
        self.run_id = f"{params.series_id}-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
        self.created_at = _now()
        self.finished_at: str | None = None
        self.status = "pending"  # pending | running | done | failed | cancelled
        self.error: str | None = None
        self.jobs: dict[str, Job] = {}
        self.notes: list[str] = []
        self.casting: list[dict] = []
        self._lock = threading.Lock()

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id, "series_id": self.params.series_id, "status": self.status, "error": self.error,
            "created_at": self.created_at, "finished_at": self.finished_at, "params": asdict(self.params),
            "stages": ["outline", "cast", *STAGES], "notes": self.notes, "casting": self.casting,
            "jobs": [asdict(j) | {"label": j.label} for j in self.jobs.values()],
        }

    def state_path(self) -> Path:
        return naming.series_root(self.params.series_id) / "pipeline_run.json"

    def save(self) -> None:
        with self._lock:
            p = self.state_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(p)

    @staticmethod
    def load_dict(series_id: str) -> dict | None:
        p = naming.series_root(series_id) / "pipeline_run.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


class Orchestrator:
    def __init__(self, params: RunParams, story: StoryInput | str | None = None, *, python: str = sys.executable,
                 runner: Callable[[Job], tuple[int, str]] | None = None, on_update: Callable[[Run], None] | None = None):
        self.params = params
        self.story = story
        self.python = python
        self.run = Run(params)
        self._runner = runner or self._run_subprocess
        self._on_update = on_update
        self._cancel = threading.Event()
        self._voice_lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> Run:
        self._thread = threading.Thread(target=self._main, name=f"pipeline-{self.run.run_id}", daemon=True)
        self._thread.start()
        return self.run

    def wait(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    def cancel(self) -> None:
        self._cancel.set()

    def _skill(self, name: str, script: str, *args: str) -> list[str]:
        return [self.python, str(SKILLS / name / "scripts" / script), *args]

    def build_jobs(self) -> dict[str, Job]:
        p = self.params
        s = p.series_id
        jobs: dict[str, Job] = {}
        outline_args = ["--series", s, "--outline-only", "--episodes", str(p.episodes), "--min-sec", str(p.min_sec), "--max-sec", str(p.max_sec)]
        if p.force:
            outline_args.append("--redo-outline")
        jobs["outline"] = Job("outline", "outline", None, self._skill("episodize", "episodize.py", *outline_args))
        jobs["cast"] = Job("cast", "cast", None, ["<internal:ensure_voices>"])
        produce = p.produce or p.episodes
        for n in range(1, min(produce, p.episodes) + 1):
            e = f"ep{n:02d}"
            force = ["--force"] if p.force else []
            jobs[f"{e}.draft"] = Job(f"{e}.draft", "draft", n, self._skill("episodize", "episodize.py", "--series", s, "--only", str(n), *force))
            jobs[f"{e}.direct"] = Job(f"{e}.direct", "direct", n, self._skill("parse-script", "parse_script.py", "--series", s, "--episode", str(n), "--force"))
            jobs[f"{e}.voice"] = Job(f"{e}.voice", "voice", n, self._skill("generate-voice", "generate_voice.py", "--series", s, "--episode", str(n), "--concurrency", "2"))
            jobs[f"{e}.assemble"] = Job(f"{e}.assemble", "assemble", n, self._skill("assemble-audio", "assemble_audio.py", "--series", s, "--episode", str(n)))
            jobs[f"{e}.qa"] = Job(f"{e}.qa", "qa", n, self._skill("qa-audio", "qa_audio.py", "--series", s, "--episode", str(n)))
        return jobs

    def _update(self) -> None:
        self.run.save()
        if self._on_update:
            self._on_update(self.run)

    def _write_story(self) -> None:
        sid = self.params.series_id
        if isinstance(self.story, StoryInput):
            sj = naming.story_json_path(sid)
            sj.parent.mkdir(parents=True, exist_ok=True)
            sj.write_text(self.story.model_dump_json(indent=2), encoding="utf-8")
            naming.story_raw_path(sid).write_text(self.story.to_text(), encoding="utf-8")
        elif isinstance(self.story, str):
            sp = naming.story_raw_path(sid)
            sp.parent.mkdir(parents=True, exist_ok=True)
            sp.write_text(self.story.strip() + "\n", encoding="utf-8")
            naming.story_json_path(sid).unlink(missing_ok=True)

    def _main(self) -> None:
        run = self.run
        run.status = "running"
        run.jobs = self.build_jobs()
        try:
            self._write_story()
            self._update()
            if not self._exec(run.jobs["outline"]):
                raise RuntimeError("outline failed")
            self._exec(run.jobs["cast"])
            episodes = sorted({j.episode for j in run.jobs.values() if j.episode})
            with ThreadPoolExecutor(max_workers=max(1, self.params.max_parallel_episodes)) as pool:
                list(pool.map(self._episode_pipeline, episodes))
            failed = [j.id for j in run.jobs.values() if j.status == "failed"]
            run.status = "failed" if failed else ("cancelled" if self._cancel.is_set() else "done")
            if failed:
                run.error = f"{len(failed)} job(s) failed: {', '.join(failed[:5])}"
        except Exception as e:  # noqa: BLE001
            run.status = "failed"
            run.error = str(e)
            for j in run.jobs.values():
                if j.status == "pending":
                    j.status = "skipped"
        finally:
            run.finished_at = _now()
            self._update()

    def _episode_pipeline(self, n: int) -> None:
        e = f"ep{n:02d}"
        for stage in STAGES:
            job = self.run.jobs[f"{e}.{stage}"]
            if self._cancel.is_set():
                job.status = "skipped"
                self._update()
                continue
            if stage == "voice":
                with self._voice_lock:
                    ok = self._exec(job)
            else:
                ok = self._exec(job)
            if job.stage == "voice" and job.summary.get("placeholder_voices"):
                note = (f"{e}: ElevenLabs rejected voice(s) {', '.join(job.summary['placeholder_voices'])} on this plan; "
                        f"rendered with placeholder premade voices. Upgrade the plan and re-run with overwrite to use the real Voice IPs.")
                if note not in self.run.notes:
                    self.run.notes.append(note)
            if not ok:
                for later in STAGES[STAGES.index(stage) + 1:]:
                    self.run.jobs[f"{e}.{later}"].status = "skipped"
                self._update()
                return

    def _exec(self, job: Job) -> bool:
        job.status = "running"
        job.started_at = _now()
        self._update()
        try:
            if job.cmd and job.cmd[0].startswith("<internal:"):
                code, out = self._internal(job)
            else:
                code, out = self._runner(job)
            job.exit_code = code
            job.summary = _last_json_line(out)
            if code == 0:
                job.status = "done"
            elif code == 2 and job.stage == "qa":
                job.status = "warn"
            else:
                job.status = "failed"
                job.error = _last_text_line(out)
        except Exception as e:  # noqa: BLE001
            job.status = "failed"
            job.error = f"{type(e).__name__}: {e}"
        job.finished_at = _now()
        self._update()
        return job.status in ("done", "warn")

    def _log_file(self, job: Job) -> Path:
        p = naming.series_root(self.params.series_id) / "logs" / f"{job.id}.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        job.log_path = str(p)
        return p

    def _run_subprocess(self, job: Job) -> tuple[int, str]:
        log = self._log_file(job)
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "AI_AUDIO_ROOT": str(naming.REPO_ROOT)}
        with log.open("w", encoding="utf-8") as fh:
            fh.write(f"$ {' '.join(job.cmd)}\n\n")
            fh.flush()
            proc = subprocess.Popen(job.cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env, cwd=str(naming.REPO_ROOT))
            lines: list[str] = []
            assert proc.stdout is not None
            for line in proc.stdout:
                if "automatic function calling" in line:
                    continue
                fh.write(line)
                fh.flush()
                lines.append(line)
                if self._cancel.is_set():
                    proc.terminate()
            code = proc.wait()
            fh.write(f"\n[exit {code}]\n")
        return code, "".join(lines)

    def _internal(self, job: Job) -> tuple[int, str]:
        log = self._log_file(job)
        out: list[str] = []
        if job.cmd[0] == "<internal:ensure_voices>":
            out = self.ensure_voices()
        log.write_text("\n".join(out) + "\n", encoding="utf-8")
        return 0, "\n".join(out)

    def ensure_voices(self) -> list[str]:
        """Give every cast member a voice on the default provider. Roles the outline could not cast
        (pending_characters) get one-off registry entries with placeholder premade voices."""
        bible = SeriesBible.model_validate_json(naming.series_bible_path(self.params.series_id).read_text(encoding="utf-8"))
        reg = registry_io.load()
        provider = reg.default_provider
        model_id = os.getenv("AI_AUDIO_TTS_MODEL", "eleven_v3")
        lines: list[str] = []
        added: list[str] = []
        counters = {"female": 0, "male": 0}
        pending = {nc.character_id: nc for nc in bible.pending_characters}
        for cid in bible.cast:
            if cid in reg.ids() and provider in reg.get(cid).providers:
                lines.append(f"{cid}: ok ({provider}:{reg.get(cid).providers[provider].voice_id})")
                continue
            nc = pending.get(cid)
            existing = reg.get(cid) if cid in reg.ids() else None
            gender = (existing.gender if existing and existing.gender else None) or guess_gender(nc.voice_description if nc else "", nc.persona if nc else "")
            voice_id = placeholder_voice(gender, counters[gender])
            counters[gender] += 1
            voice = ProviderVoice(voice_id=voice_id, model_id=model_id)
            if existing:
                registry_io.set_provider_voice(cid, provider, voice)
            else:
                registry_io.upsert(CharacterProfile(
                    character_id=cid, display_name=(nc.display_name if nc else cid), persona=(nc.persona if nc else ""),
                    voice_description=f"PLACEHOLDER ({gender} premade {voice_id}). Target: {nc.voice_description if nc else 'n/a'}",
                    gender=gender, providers={provider: voice}, is_ip_asset=False))
            added.append(cid)
            lines.append(f"{cid}: no voice -> placeholder {gender} {voice_id} (one-off; replace in the Characters page)")
        reg = registry_io.load()
        self.run.casting = [
            {"role": r.role_name, "type": r.role_type, "actor": r.actor_id, "assigned_by": r.assigned_by, "reason": r.reason,
             "actor_name": reg.get(r.actor_id).display_name if r.actor_id in reg.ids() else None}
            for r in bible.roles
        ]
        for c in self.run.casting:
            lines.append(f"casting: {c['role']} -> {c['actor']} ({c['assigned_by']}) {c['reason']}")
        if added:
            self.run.notes.append(f"Placeholder voices assigned to: {', '.join(added)}. Replace them in the Characters page before publishing.")
        lines.append(json.dumps({"ok": True, "cast": bible.cast, "placeholders": added}, ensure_ascii=False))
        return lines


def _last_json_line(out: str) -> dict:
    for line in reversed(out.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return {}


def _last_text_line(out: str) -> str | None:
    lines = [ln.strip() for ln in out.strip().splitlines() if ln.strip() and not ln.strip().startswith("{")]
    return lines[-1][:300] if lines else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--series", required=True)
    ap.add_argument("--story", type=Path, help="story text (.txt) or StoryInput (.json); omitted = existing series/<id>/story.*")
    ap.add_argument("--episodes", type=int, default=30)
    ap.add_argument("--produce", type=int, default=None)
    ap.add_argument("--min-sec", type=int, default=50)
    ap.add_argument("--max-sec", type=int, default=70)
    ap.add_argument("--parallel", type=int, default=2)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    params = RunParams(series_id=a.series, episodes=a.episodes, produce=a.produce, min_sec=a.min_sec, max_sec=a.max_sec,
                       max_parallel_episodes=a.parallel, force=a.force)
    story: StoryInput | str | None = None
    if a.story:
        text = a.story.read_text(encoding="utf-8")
        story = StoryInput.model_validate_json(text) if a.story.suffix == ".json" else text
    orch = Orchestrator(params, story)
    run = orch.start()
    last = ""
    while run.status in ("pending", "running"):
        time.sleep(1)
        snapshot = " ".join(f"{j.id}:{j.status}" for j in run.jobs.values() if j.status != "pending")
        if snapshot != last:
            print(snapshot[-200:], file=sys.stderr)
            last = snapshot
    print(json.dumps({"ok": run.status == "done", "run_id": run.run_id, "status": run.status, "error": run.error, "state": str(run.state_path())}))
    return 0 if run.status == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
