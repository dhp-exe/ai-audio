"""Starting production runs: what the API, the CLI and the production tools share."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime

from emvoox.contracts.jobs import Job
from emvoox.contracts.market import TrendBrief
from emvoox.contracts.production import StoryInput
from emvoox.contracts.run import LIVE_RUN, RunParams, RunState
from emvoox.engine.orchestrator import Engine
from emvoox.repositories import Repositories


def slug(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn").replace("đ", "d").replace("Đ", "D")
    text = re.sub(r"[^a-z0-9-]+", "-", text.lower()).strip("-")
    return text[:24].rstrip("-") or "series"


def new_series_id(base: str) -> str:
    return slug(base) + "-" + datetime.now(UTC).strftime("%m%d%H%M")


def busy(repos: Repositories, series_id: str) -> dict | None:
    """The series' latest run when it is queued, in progress or waiting for a decision."""
    raw = repos.runs.load_raw(series_id)
    return raw if raw and raw.get("status") in (*LIVE_RUN, "waiting") and "steps" in raw else None


def start_run(repos: Repositories, params: RunParams, submit: Callable[[Job], object], *, story: StoryInput | None = None,
              brief: TrendBrief | None = None) -> RunState:
    """Save the run as pending and queue it for a worker."""
    engine = Engine.create(params, story=story, brief=brief, repos=repos)
    submit(Job(kind="run", action="start", tenant=repos.tenant, series_id=params.series_id, run_id=engine.run_id))
    return engine.state
