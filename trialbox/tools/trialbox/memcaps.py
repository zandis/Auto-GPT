"""Memory caps of the adapter, the lake and the orchestrator sized from the patient count (T-692, D-473; scale review
F-05, OD-10; H23b-01, D-1005).

The night's ingest and the lake rebuild stream (D-473), so what they need grows only slowly with the hospital: a fixed
part (the interpreter, the libraries, the batches, the held samples) and a small part per patient (the patient rows
and ids that are held). Both parts come from a measured record, ``deploy/measured/ingest_memory.json``, written by
``--measure``; nothing here is a guessed constant. The caps add what the services already reserve by their own
settings: the adapter's FHIR validator heap (``TB_VALIDATOR_XMX``) and the share of the cap the merge's sort runs may
take (``adapter.ndjson.sort_run_bytes``, a sixteenth); the lake's DuckDB takes 40 % of the lake's cap
(``lake.store.memory_limit``), so the Python part must fit in the rest. A cap is never below the compose default.

The orchestrator's SCREEN and FEAS hold the whole hospital's rows (the size test H-23b, D-1137): its need is a line
over the peaks of the size ladder (``tools/size_ladder.py``), recorded in ``deploy/measured/orchestrator_memory.json``
by ``--from-ladder``. The line's slope is the least-squares slope of the peaks, and its fixed part is raised until the
line lies on or above every measured peak; a run killed at its cap is left out (its peak is the cap, not the need).
``TB_MEM_ORCH`` is written only when the need is above the compose default (4 GiB; the 96 GB class's overlays give
6 GiB, read with ``--overlay``), so a small hospital keeps the shipped shape (the two-device workstation's 3 GiB
included); one this tool wrote and no longer needs is removed.

The patient count is the lake's ``CURRENT`` snapshot (its ``Patient.ndjson``) when there is one, else
``TB_SITE_PATIENTS`` (the hospital's size, set before the first night). ``deploy/install.sh`` calls ``--write``: it
writes ``TB_MEM_ADAPTER``, ``TB_MEM_LAKE`` and (above the default) ``TB_MEM_ORCH`` into ``deploy/.env`` unless the
operator set one by hand (a value that is not the one this tool wrote, recorded in its marker line). ``trialbox
doctor`` (``check_memory_caps``) fails when a cap is below what the patient count needs.

    python -m tools.trialbox.memcaps --env-file deploy/.env [--lake DIR] [--overlay COMPOSE_FILE] [--write]
    python -m tools.trialbox.memcaps --measure [--sizes 500 2000]
    python -m tools.trialbox.memcaps --from-ladder docs/plan/measurements/size-test-2026-11-17.json
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import IO, Any

from tools.trialbox.private_file import replace_private

ROOT = Path(__file__).resolve().parents[2]
RECORD = ROOT / "deploy" / "measured" / "ingest_memory.json"
COMPOSE = ROOT / "deploy" / "docker-compose.yml"
FORMAT = "tb-ingest-memory/1"
#: the services sized here and the cap variable of each
CAPS = {"adapter": "TB_MEM_ADAPTER", "lake": "TB_MEM_LAKE"}
#: the orchestrator's cap, sized from the size ladder's peaks (H23b-01, D-1005)
ORCH, ORCH_VAR = "orchestrator", "TB_MEM_ORCH"
ORCH_RECORD = ROOT / "deploy" / "measured" / "orchestrator_memory.json"
ORCH_FORMAT = "tb-orchestrator-memory/1"
MARKER = "# memcaps:"
SORT_SHARE = 16  # adapter.ndjson.sort_run_bytes: a sixteenth of the cap
LAKE_DUCKDB_SHARE = 0.4  # lake.store.memory_limit: 40 % of the cap
MEASURE_SORT_MB = "4"
#: E2E P-02: the services' measured peaks by the hospital's size (``deploy/measured/site_peaks.json``), which the box
#: plan reads too; optional: a box without it is sized as before
PEAKS_NAME, PEAKS_FORMAT = "site_peaks.json", "tb-site-peaks/1"
HEADROOM = 1.5  # a cap from a measured peak keeps 1.5 times it (tests/unit/test_pin_consistency.py)
MEASURE_DUCKDB = "256MB"
_SIZE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([kmgt]?)b?\s*$", re.I)


def size_mb(value: str) -> int:
    """``6g``, ``512m``, ``4096`` (bytes when bare, as compose reads it) as whole megabytes."""
    m = _SIZE.match(value or "")
    if not m:
        raise ValueError(f"not a memory size: {value!r}")
    n, unit = float(m.group(1)), m.group(2).lower()
    scale = {"": 1 / 2**20, "k": 1 / 1024, "m": 1, "g": 1024, "t": 1024**2}[unit]
    return math.ceil(n * scale)


def compose_default(var: str, compose: Path = COMPOSE) -> str:
    """The default compose gives ``var`` (``${TB_MEM_X:-6g}``)."""
    m = re.search(r"\$\{" + re.escape(var) + r":-([^}]+)\}", compose.read_text(encoding="utf-8"))
    if not m:
        raise ValueError(f"{compose} gives {var} no default")
    return m.group(1)


def orch_default(compose: Path = COMPOSE, overlay: Path | None = None) -> str:
    """The orchestrator's default cap: the machine profile's overlay's (``--overlay``, the 96 GB class gives 6g) when
    it names one, else the base file's."""
    if overlay is not None and overlay.is_file() and f"${{{ORCH_VAR}:-" in overlay.read_text(encoding="utf-8"):
        return compose_default(ORCH_VAR, overlay)
    return compose_default(ORCH_VAR, compose)


def profile_overlay(files: Sequence[Path]) -> Path | None:
    """The box's compose file (of ``COMPOSE_FILE``, in order) whose orchestrator default compose uses: the last one
    that names one, as a later file overrides an earlier one; None when none does."""
    named = [f for f in files if f.is_file() and f"${{{ORCH_VAR}:-" in f.read_text(encoding="utf-8")]
    return named[-1] if named else None


def load_record(path: Path = RECORD) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("format") != FORMAT or not all(s in doc.get("services", {}) for s in CAPS):
        raise ValueError(f"{path}: not a {FORMAT} record of {', '.join(CAPS)}")
    return dict(doc)


def load_peaks(path: Path) -> list[tuple[int, dict[str, float]]]:
    """The measured-peak table (``site_peaks.json``): ``(patients, {cap variable: MiB})`` per size class, smallest
    first; none when the file is not there."""
    if not path.is_file():
        return []
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("format") != PEAKS_FORMAT:
        raise ValueError(f"{path}: not a {PEAKS_FORMAT} record")
    rows = [(int(c["patients"]), {k: float(v) for k, v in c["peak_mib"].items()}) for c in doc["classes"]]
    return sorted(rows, key=lambda r: r[0])


def peak_mib(peaks: Sequence[tuple[int, Mapping[str, float]]], var: str, n: int) -> float:
    """E2E P-02: the measured peak of the service capped by ``var`` (MiB) for a hospital of ``n`` patients: that of the
    nearest size class of at least ``n`` patients that measured it, never below a smaller class's. Above the largest
    such class, the line through the two largest (one: its peak), never below the largest measured peak; 0 when none
    measured it."""
    have = [(p, row[var]) for p, row in peaks if var in row]
    if not have:
        return 0.0
    upto = next((i for i, (p, _) in enumerate(have) if p >= n), None)
    if upto is not None:
        return max(mib for _, mib in have[: upto + 1])
    if len(have) == 1:
        return have[0][1]
    (a, pa), (b, pb) = have[-2:]
    return max(*(mib for _, mib in have), pb + (pb - pa) / (b - a) * (n - b))


def load_orch_record(path: Path = ORCH_RECORD) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    part = doc.get("services", {}).get(ORCH, {}) if doc.get("format") == ORCH_FORMAT else {}
    if not {"fixed_mb", "per_patient_kb"} <= set(part):
        raise ValueError(f"{path}: not a {ORCH_FORMAT} record of {ORCH}")
    return dict(doc)


def patients(env: Mapping[str, str], lake: Path | None) -> tuple[int | None, str]:
    """The patient count and where it came from: the lake's CURRENT snapshot, else ``TB_SITE_PATIENTS``."""
    if lake is not None and (lake / "CURRENT").is_file():
        snap = (lake / "CURRENT").read_text(encoding="utf-8").strip()
        f = lake / "ndjson" / snap / "Patient.ndjson"
        if snap and f.is_file():
            with f.open("rb") as fh:
                return sum(1 for line in fh if line.strip()), f"lake snapshot {snap}"
    raw = (env.get("TB_SITE_PATIENTS") or "").strip()
    if raw:
        if not raw.isdigit():
            raise ValueError(f"TB_SITE_PATIENTS={raw!r}: a whole number of patients")
        return int(raw), "TB_SITE_PATIENTS"
    return None, "no CURRENT snapshot and no TB_SITE_PATIENTS"


def need_mb(
    n: int,
    record: Mapping[str, Any],
    env: Mapping[str, str],
    compose: Path = COMPOSE,
    orch: Mapping[str, Any] | None = None,
    overlay: Path | None = None,
    peaks: Sequence[tuple[int, Mapping[str, float]]] = (),
) -> dict[str, int]:
    """The cap each service needs for ``n`` patients, in MB, never below its compose default (the orchestrator's
    too, when its record ``orch`` is given; its default the profile ``overlay``'s when that names one); each measured
    service's at least HEADROOM times its peak for ``n`` in ``peaks`` (the adapter's whole night, validator and FHIR
    load included, where the ingest record measured the streamed write alone)."""
    out: dict[str, int] = {}
    orch_mb: int | None = None
    if orch is not None:
        part = orch["services"][ORCH]
        mb = float(part["fixed_mb"]) + float(part["per_patient_kb"]) * n / 1024
        orch_mb = max(math.ceil(mb), size_mb(orch_default(compose, overlay)))
    for svc, var in CAPS.items():
        part = record["services"][svc]
        python = float(part["fixed_mb"]) + float(part["per_patient_kb"]) * n / 1024
        if svc == "adapter":
            heap = size_mb(env.get("TB_VALIDATOR_XMX") or _validator_default(compose))
            mb = (python + heap) * SORT_SHARE / (SORT_SHARE - 1)
        else:
            mb = python / (1 - LAKE_DUCKDB_SHARE)
        mb = max(mb, HEADROOM * peak_mib(peaks, var, n))  # E2E P-02: the 50k night was killed at 3,520 MiB
        out[svc] = max(math.ceil(mb), size_mb(compose_default(var, compose)))
    if orch_mb is not None:
        out[ORCH] = max(orch_mb, math.ceil(HEADROOM * peak_mib(peaks, ORCH_VAR, n)))  # 100k's SCREEN: 11.77 GiB
    return out


def _validator_default(compose: Path) -> str:
    m = re.search(r"TB_VALIDATOR_XMX:\s*([0-9]+[kmgKMG]?)", compose.read_text(encoding="utf-8"))
    return m.group(1) if m else "3g"


def _marker(env_text: str) -> dict[str, str]:
    for line in env_text.splitlines():
        if line.startswith(MARKER):
            return dict(p.split("=", 1) for p in line[len(MARKER) :].split() if "=" in p)
    return {}


def plan(
    env_text: str,
    n: int,
    record: Mapping[str, Any],
    compose: Path = COMPOSE,
    orch: Mapping[str, Any] | None = None,
    overlay: Path | None = None,
    peaks: Sequence[tuple[int, Mapping[str, float]]] = (),
) -> dict[str, str | None]:
    """The caps ``--write`` sets: each service's need, except a cap the operator set by hand (kept). The orchestrator's
    only above its default (the profile ``overlay``'s when it names one: a value under it would lower the cap);
    ``None``: a value this tool wrote that is no longer needed, removed."""
    env = _parse_env(env_text)
    ours = _marker(env_text)
    need = need_mb(n, record, env, compose, orch, overlay, peaks)
    out: dict[str, str | None] = {}
    if ORCH in need:
        have = env.get(ORCH_VAR)
        mine = have is not None and ours.get(ORCH_VAR) == have
        if need[ORCH] > size_mb(orch_default(compose, overlay)):
            if have is None or mine:
                out[ORCH_VAR] = f"{need[ORCH]}m"
        elif mine:
            out[ORCH_VAR] = None
    for svc, var in CAPS.items():
        have = env.get(var)
        if have is not None and ours.get(var) != have:
            continue  # set by hand: kept; doctor says when it is too small
        out[var] = f"{need[svc]}m"
    return out


def _parse_env(text: str) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def write(env_file: Path, caps: Mapping[str, str | None], n: int, source: str) -> None:
    """Set each cap of ``caps`` in ``env_file`` (``None``: remove it) and record what this tool wrote."""
    lines = [ln for ln in env_file.read_text(encoding="utf-8").splitlines() if not ln.startswith(MARKER)]
    lines = [ln for ln in lines if ln.split("=", 1)[0].strip() not in caps]
    lines += [f"{k}={v}" for k, v in caps.items() if v is not None]
    recorded = {**_marker(env_file.read_text(encoding="utf-8")), **caps}
    recorded = {k: v for k, v in recorded.items() if v is not None}
    lines.append(f"{MARKER} " + " ".join(f"{k}={v}" for k, v in sorted(recorded.items())) + f" n={n} ({source})")
    replace_private(env_file, "\n".join(lines) + "\n")  # H-110: whole, 0600, never in place


def check(
    env: Mapping[str, str],
    lake: Path | None,
    record_path: Path = RECORD,
    compose: Path = COMPOSE,
    orch_path: Path | None = None,
    overlay: Path | None = None,
) -> tuple[str, str]:
    """``(status, detail)`` for ``trialbox doctor``: FAIL when a cap is below what the patient count needs (the
    orchestrator's too when ``orch_path``, its record, is given; its default the profile ``overlay``'s, as compose
    runs it)."""
    n, source = patients(env, lake)
    if n is None:
        return "WARN", f"{source}: the memory caps were not compared with the hospital's size"
    record = load_record(record_path)
    orch = load_orch_record(orch_path) if orch_path is not None else None
    need = need_mb(n, record, env, compose, orch, overlay, load_peaks(record_path.parent / PEAKS_NAME))
    names = {**CAPS, **({ORCH: ORCH_VAR} if orch is not None else {})}
    have = {svc: size_mb(env.get(var) or compose_default(var, compose)) for svc, var in CAPS.items()}
    if orch is not None:
        have[ORCH] = size_mb(env.get(ORCH_VAR) or orch_default(compose, overlay))
    low = [f"{names[s]} {have[s]} MB < {need[s]} MB" for s in names if have[s] < need[s]]
    facts = f"{n} patients ({source}); measured record {record_path.name} ({record.get('measured_at', '?')})"
    if low:
        fix = "re-run deploy/install.sh (it sizes them) or set them in deploy/.env"
        what = "the night's ingest, the rebuild or a SCREEN of the whole hospital may be killed"
        return "FAIL", f"{'; '.join(low)} for {facts}: {what}; {fix}"
    return "PASS", f"{', '.join(f'{names[s]} {have[s]} MB (needs {need[s]})' for s in names)} for {facts}"


# ------------------------------------------------------------------------------------------------ the measurement
def _canon(r: Mapping[str, Any]) -> str:
    return json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def observation(i: int, j: int, value: float) -> dict[str, Any]:
    """One synthetic creatinine result of synthetic patient ``i``."""
    return {
        "resourceType": "Observation",
        "id": f"obs-{i:06d}-{j:02d}",
        "status": "final",
        "subject": {"reference": f"Patient/syn-{i:06d}"},
        "code": {"coding": [{"system": "http://loinc.org", "code": "2160-0"}], "text": "creatinine"},
        "effectiveDateTime": "2026-09-01T08:00:00+08:00",
        "valueQuantity": {"value": value, "unit": "mg/dL", "code": "mg/dL", "system": "http://unitsofmeasure.org"},
    }


def synthetic(n: int, per: int = 10) -> Iterator[dict[str, Any]]:
    """``n`` synthetic patients, each with ``per`` results and one note (the measured mix; synthetic data only)."""
    for i in range(n):
        yield {"resourceType": "Patient", "id": f"syn-{i:06d}", "gender": "female", "birthDate": "1960-01-01"}
        for j in range(per):
            yield observation(i, j, 1.0 + j / 10)
        text = base64.b64encode(f"note {i}: creatinine stable, no dialysis.".encode()).decode()
        yield {
            "resourceType": "DocumentReference",
            "id": f"doc-{i:06d}",
            "status": "current",
            "subject": {"reference": f"Patient/syn-{i:06d}"},
            "date": "2026-09-01T09:00:00+08:00",
            "type": {"text": "progress"},
            "content": [{"attachment": {"contentType": "text/plain", "data": text}}],
        }


def write_ndjson(folder: Path, n: int) -> None:
    """:func:`synthetic` as a snapshot folder, one NDJSON file per type."""
    folder.mkdir(parents=True, exist_ok=True)
    files: dict[str, IO[str]] = {}
    try:
        for r in synthetic(n):
            fh = files.get(r["resourceType"])
            if fh is None:
                fh = files[r["resourceType"]] = (folder / f"{r['resourceType']}.ndjson").open("w", encoding="utf-8")
            fh.write(_canon(r) + "\n")
    finally:
        for fh in files.values():
            fh.close()


_WORK = r"""
import json, resource, sys, tempfile
from pathlib import Path
from tools.trialbox import memcaps as t
from adapter import ndjson
svc, n = sys.argv[1], int(sys.argv[2])
d = Path(tempfile.mkdtemp())
if svc == "adapter":
    sp = ndjson.Spool(d / "spool")
    for r in t.synthetic(n):
        sp.add(r)
    ndjson.write_snapshot(d / "out", sp, None)
    sp.close()
else:
    from embed_service.embedder import HashEmbedder
    from lake.store import Lake
    t.write_ndjson(d / "lake" / "ndjson" / "2026-10-04", n)
    Lake(d / "lake").rebuild("2026-10-04", HashEmbedder())
print(json.dumps({"maxrss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}))
"""


def _rss_mb(svc: str, n: int) -> float:
    env = {**os.environ, "PYTHONPATH": "libs:services:.", "TB_LAKE_SOURCE": "legacy"}
    env.setdefault("TB_TZ", "UTC")  # the zone moves no byte counted here (D-315: never a site's zone in code)
    env.pop("TB_DB_URL", None)
    # a sort run and a DuckDB limit both sizes pass, so the slope is what grows with the patients, not a buffer
    # filling up to its bound (the bounds are the services' own shares of the cap, added in need_mb)
    env["TB_INGEST_SORT_MB"] = MEASURE_SORT_MB
    env["TB_LAKE_MEMORY_LIMIT"] = MEASURE_DUCKDB
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "work.py"
        script.write_text(_WORK, encoding="utf-8")
        out = subprocess.run(
            [sys.executable, str(script), svc, str(n)], cwd=ROOT, env=env, capture_output=True, text=True, check=True
        )
    return float(json.loads(out.stdout.strip().splitlines()[-1])["maxrss_kb"]) / 1024


def measure(sizes: tuple[int, int]) -> dict[str, Any]:
    """Peak resident memory of the streamed ingest write and of the rebuild at two synthetic sizes (10 results and
    one note per patient): the fixed part and the slope per patient of each."""
    from datetime import UTC, datetime

    a, b = sizes
    services: dict[str, Any] = {}
    for svc in CAPS:
        ra, rb = _rss_mb(svc, a), _rss_mb(svc, b)
        slope = max(0.0, (rb - ra) / (b - a))
        services[svc] = {
            "fixed_mb": round(ra - slope * a, 1),
            "per_patient_kb": round(slope * 1024, 3),
            "peak_mb": {str(a): round(ra, 1), str(b): round(rb, 1)},
        }
    return {
        "format": FORMAT,
        "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "how": "python -m tools.trialbox.memcaps --measure: peak RSS of one process, synthetic patients (10 results "
        "and one note each), the streamed spool and merge (adapter) and the legacy rebuild (lake), sort run "
        f"{MEASURE_SORT_MB} MB, DuckDB limit {MEASURE_DUCKDB}",
        "sizes": [a, b],
        "services": services,
    }


# ------------------------------------------------------------------------------------------------ the orchestrator
def _tables(doc: Mapping[str, Any]) -> list[tuple[list[Mapping[str, Any]], Mapping[str, Any]]]:
    """Each size ladder table of a results file (its ``table``) or of a combined record (the ``table`` of each part),
    with the part that holds it (its ``commit`` and ``written``)."""
    out = [(doc["table"], doc)] if isinstance(doc.get("table"), list) else []
    return out + [(v["table"], v) for v in doc.values() if isinstance(v, dict) and isinstance(v.get("table"), list)]


def ladder_peaks(docs: list[Mapping[str, Any]]) -> tuple[dict[int, float], list[str]]:
    """The orchestrator's peak per patient count, in MB, over the size ladder's tables, and what was left out. A
    patient count where any of the orchestrator's stages did not finish is left out of that table: the stage was
    killed at its cap, so its peak is the cap and the count's need is not known from that table."""
    peaks: dict[int, float] = {}
    left: list[str] = []
    for table, _part in (t for d in docs for t in _tables(d)):
        rows = [r for r in table if r.get("service") == ORCH]
        killed = {int(r["patients"]) for r in rows if not r.get("ok")}
        for n in sorted(killed):
            stages = ", ".join(sorted(str(r["stage"]) for r in rows if int(r["patients"]) == n and not r.get("ok")))
            left.append(f"{n} patients: {stages} killed at the cap")
        for r in rows:
            n = int(r["patients"])
            if n not in killed:
                peaks[n] = max(peaks.get(n, 0.0), int(r["peak"]) / 2**20)
    return peaks, left


def from_ladder(paths: list[Path]) -> dict[str, Any]:
    """The orchestrator's record from size ladder results: a line on or above every peak (see the module text)."""
    docs = [json.loads(p.read_text(encoding="utf-8")) for p in paths]
    peaks, left = ladder_peaks(docs)
    if len(peaks) < 2:
        raise ValueError(f"{', '.join(map(str, paths))}: the orchestrator's peaks at two patient counts are needed")
    xs, ys = list(peaks), list(peaks.values())
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    slope = max(0.0, sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sum((x - mx) ** 2 for x in xs))
    fixed = max(y - slope * x for x, y in peaks.items())
    parts = [part for d in docs for _t, part in _tables(d)]
    return {
        "format": ORCH_FORMAT,
        "how": "python -m tools.trialbox.memcaps --from-ladder: the orchestrator's peak resident memory per patient "
        "count over every stage of the size ladder (tools/size_ladder.py; SCREEN and FEAS of the whole hospital), "
        "a count with a stage killed at its cap left out, the least-squares slope, the fixed part raised until the "
        "line lies on or above every peak",
        "measured_at": max((str(p.get("written") or "") for p in parts), default="") or None,
        "sources": [p.name for p in paths],
        "commits": sorted({str(p.get("commit") or "?") for p in parts}),
        "left_out": sorted(set(left)),
        "services": {
            ORCH: {
                "fixed_mb": math.ceil(fixed * 10) / 10,
                "per_patient_kb": math.ceil(slope * 1024 * 1000) / 1000,
                "peak_mb": {str(n): round(peaks[n], 1) for n in sorted(peaks)},
            }
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="memcaps", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--env-file", type=Path, default=ROOT / "deploy" / ".env")
    ap.add_argument("--lake", type=Path, default=None)
    ap.add_argument("--overlay", type=Path, default=None, help="the machine profile's compose file (its TB_MEM_ORCH)")
    ap.add_argument("--write", action="store_true", help="write the caps into --env-file")
    ap.add_argument("--measure", action="store_true", help="measure and write deploy/measured/ingest_memory.json")
    ap.add_argument("--sizes", type=int, nargs=2, default=(5000, 10000), help="patients (above INSERT_BATCH notes)")
    ap.add_argument("--out", type=Path, default=None, help="where --measure or --from-ladder writes its record")
    ap.add_argument("--from-ladder", type=Path, nargs="+", default=None, metavar="RESULTS",
                    help="write deploy/measured/orchestrator_memory.json from size ladder results")  # fmt: skip
    a = ap.parse_args(argv)
    if a.from_ladder:
        doc = from_ladder(a.from_ladder)
        (a.out or ORCH_RECORD).write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(doc["services"], sort_keys=True))
        return 0
    if a.measure:
        doc = measure((a.sizes[0], a.sizes[1]))
        (a.out or RECORD).write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(doc["services"], sort_keys=True))
        return 0
    text = a.env_file.read_text(encoding="utf-8") if a.env_file.is_file() else ""
    env = {**_parse_env(text), **{k: v for k, v in os.environ.items() if k == "TB_SITE_PATIENTS"}}
    n, source = patients(env, a.lake or (Path(env["TB_LAKE_DIR"]) if env.get("TB_LAKE_DIR") else None))
    if n is None:
        print(f"memcaps: {source}: the compose defaults stay (set TB_SITE_PATIENTS to size them)")
        return 0
    orch = load_orch_record(ORCH_RECORD) if ORCH_RECORD.is_file() else None
    caps = plan(text, n, load_record(), orch=orch, overlay=a.overlay, peaks=load_peaks(RECORD.parent / PEAKS_NAME))
    gone = "removed (the compose default fits)"
    said = ", ".join(f"{k}={v}" if v is not None else f"{k} {gone}" for k, v in caps.items())
    print(f"memcaps: {n} patients ({source}): " + (said or "set by hand"))
    if a.write and caps:
        write(a.env_file, caps, n, source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
