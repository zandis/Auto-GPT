"""v4 cascade pilot runs (MS1 slice: data platform → cascade S0–S5 → DL-1 pack + recall certificate).

The orchestrator has no cascade scenario yet (the v4 orchestrator steps are later work), so the pilot workspace runs
``tools.cascade_e2e.run_end_to_end`` on the synthetic site drop, with every judge call through ``tb-gateway``.
Refused outside DEV/TEST and on anything but D0 data (the tool checks both). Only the D1 outputs are offered to the
browser: the DL-1 pack (PDF, XLSX, JSON) and the recall certificate. The D3 cascade folder (traces, review queue,
final list) stays on the console volume and is never listed or served.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tb_common.ulid import new_ulid

SERVED = {
    "dl1_pdf": "dl1/DL1_{trial}.pdf",
    "dl1_xlsx": "dl1/DL1_{trial}.xlsx",
    "dl1_json": "dl1/DL1_{trial}.json",
    "recall_certificate": "recall/recall_certificate.json",
}


def _flat(v: Any) -> str:
    if isinstance(v, dict):
        return ", ".join(f"{k} {_flat(x)}" for k, x in v.items())
    if isinstance(v, list):
        return ", ".join(_flat(x) for x in v)
    return str(v)


Runner = Callable[[Path, str, Path], dict[str, Any]]  # (source dir, trial, out dir) -> summary


@dataclass
class CascadeRun:
    run_id: str
    trial: str
    started_by: str
    state: str  # running | done | failed
    started: float
    seconds: float = 0.0
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def default_runner(source: Path, trial: str, out: Path) -> dict[str, Any]:
    from tools.cascade_e2e import run_end_to_end

    res = run_end_to_end(source, trial, out, recipient_class="external_sponsor", repro=False)
    return {"passed": res.passed, "certificate_status": res.certificate_status}


class CascadeRuns:
    def __init__(self, root: Path, source_dir: Path | None, runner: Runner = default_runner) -> None:
        self.root = root
        self.source_dir = source_dir
        self.runner = runner
        self._lock = threading.Lock()
        root.mkdir(parents=True, exist_ok=True)

    @property
    def available(self) -> bool:
        return self.source_dir is not None and (self.source_dir / "patient.csv").is_file()

    def _meta(self, run_id: str) -> Path:
        return self.root / run_id / "run.json"

    def _save(self, run: CascadeRun) -> None:
        path = self._meta(run.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(run.as_dict()), encoding="utf-8")
        tmp.replace(path)

    def get(self, run_id: str) -> CascadeRun | None:
        if not run_id.isalnum():
            return None
        path = self._meta(run_id)
        if not path.is_file():
            return None
        return CascadeRun(**json.loads(path.read_text(encoding="utf-8")))

    def list(self) -> list[CascadeRun]:
        runs = [self.get(p.parent.name) for p in self.root.glob("*/run.json")]
        return sorted((r for r in runs if r is not None), key=lambda r: r.started, reverse=True)

    def start(self, trial: str, user: str, on_done: Callable[[CascadeRun], None] | None = None) -> CascadeRun:
        if not self.available or self.source_dir is None:
            raise RuntimeError("no synthetic site drop is mounted (TB_CONSOLE_SOURCE_DIR)")
        with self._lock:
            if any(r.state == "running" for r in self.list()):
                raise RuntimeError("a cascade run is already running; wait for it to finish")
            run = CascadeRun(new_ulid(), trial, user, "running", time.time())
            self._save(run)
        source = self.source_dir

        def work() -> None:
            t0 = time.monotonic()
            try:
                summary = self.runner(source, trial, self.root / run.run_id / "out")
                run.state = "done" if summary.get("passed", True) else "failed"
                if run.state == "failed":
                    run.error = "the end-to-end checks did not all pass (see the DL-1 pack and certificate)"
            except Exception as exc:  # report, never crash the console
                run.state, run.error = "failed", f"{type(exc).__name__}: {exc}"[:500]
            run.seconds = round(time.monotonic() - t0, 1)
            self._save(run)
            if on_done is not None:
                on_done(run)

        threading.Thread(target=work, name=f"cascade-{run.run_id}", daemon=True).start()
        return run

    def file(self, run: CascadeRun, name: str) -> Path | None:
        rel = SERVED.get(name)
        if rel is None:
            return None
        path = self.root / run.run_id / "out" / rel.format(trial=run.trial)
        return path if path.is_file() else None

    def summary(self, run: CascadeRun) -> dict[str, Any]:
        """Released (D1) numbers only: the DL-1 cascade block and headline, the certificate status and statement."""
        out: dict[str, Any] = {}
        dl1 = self.file(run, "dl1_json")
        if dl1 is not None:
            obj = json.loads(dl1.read_text(encoding="utf-8")).get("object", {})
            casc = obj.get("cascade") or {}
            out["funnel"] = list((casc.get("n_after") or {}).items())
            out["n_scope"] = casc.get("n_scope")
            out["data_class"] = casc.get("data_class")
            out["headline"] = {k: _flat(v) for k, v in (obj.get("headline") or {}).items() if k != "recall_sentence"}
        summ = self.root / run.run_id / "out" / "e2e_summary.json"
        if summ.is_file():
            s = json.loads(summ.read_text(encoding="utf-8"))
            out["certificate_status"] = s.get("certificate_status")
            out["certificate_statement"] = s.get("certificate_statement")
            checks = s.get("checks") or {}
            out["checks"] = sorted((str(k), bool(v)) for k, v in checks.items()) if isinstance(checks, dict) else []
        return out
