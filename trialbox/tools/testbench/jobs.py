"""Background jobs with a live log (Server-Sent Events) for the slow bench actions (pipeline, e2e, simulation)."""

from __future__ import annotations

import threading
import time
import traceback
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tb_common.ulid import new_ulid

Log = Callable[[str], None]
JobFn = Callable[[Log, Path], Any]


@dataclass
class Job:
    id: str
    kind: str
    title: str
    workdir: Path
    status: str = "running"  # running | done | error
    lines: list[str] = field(default_factory=list)
    result: Any = None
    error: str = ""
    started: float = field(default_factory=time.time)
    finished: float | None = None

    @property
    def done(self) -> bool:
        return self.status != "running"

    @property
    def seconds(self) -> float:
        return round((self.finished or time.time()) - self.started, 1)


class JobStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, kind: str, title: str, fn: JobFn, *, wait: bool = False) -> Job:
        jid = new_ulid().lower()
        workdir = self.root / f"{kind}-{jid}"
        workdir.mkdir(parents=True, exist_ok=True)
        job = Job(jid, kind, title, workdir)
        with self._lock:
            self.jobs[jid] = job

        def log(msg: str) -> None:
            job.lines.append(f"[{time.strftime('%H:%M:%S')}] {msg}")

        def body() -> None:
            log(f"started: {title}")
            try:
                job.result = fn(log, workdir)
                job.status = "done"
                log("finished")
            except Exception as exc:  # the page shows the failure; the server keeps running
                job.error = f"{type(exc).__name__}: {exc}"
                job.status = "error"
                log(job.error)
                for line in traceback.format_exc().splitlines()[-8:]:
                    log(line)
            finally:
                job.finished = time.time()

        if wait:
            body()
        else:
            threading.Thread(target=body, name=f"testbench-{kind}-{jid}", daemon=True).start()
        return job

    def get(self, jid: str) -> Job | None:
        return self.jobs.get(jid)

    def latest(self, kind: str) -> Job | None:
        js = [j for j in self.jobs.values() if j.kind == kind]
        return max(js, key=lambda j: j.started) if js else None


def sse(job: Job, poll: float = 0.25, limit_s: float = 3600.0) -> Iterator[str]:
    """``text/event-stream`` frames: one ``log`` event per line, then ``done`` with the final status."""
    sent = 0
    t0 = time.time()
    while True:
        lines = job.lines[sent:]
        for line in lines:
            yield "event: log\ndata: " + line.replace("\n", " ") + "\n\n"
        sent += len(lines)
        if job.done and sent >= len(job.lines):
            yield f"event: done\ndata: {job.status}\n\n"
            return
        if time.time() - t0 > limit_s:
            yield "event: done\ndata: timeout\n\n"
            return
        time.sleep(poll)


__all__ = ["Job", "JobStore", "Log", "sse"]
