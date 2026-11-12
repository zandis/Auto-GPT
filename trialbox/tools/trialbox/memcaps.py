"""Memory caps of the adapter and the lake sized from the patient count (T-692, D-473; scale review F-05, OD-10).

The night's ingest and the lake rebuild stream (D-473), so what they need grows only slowly with the hospital: a fixed
part (the interpreter, the libraries, the batches, the held samples) and a small part per patient (the patient rows
and ids that are held). Both parts come from a measured record, ``deploy/measured/ingest_memory.json``, written by
``--measure``; nothing here is a guessed constant. The caps add what the services already reserve by their own
settings: the adapter's FHIR validator heap (``TB_VALIDATOR_XMX``) and the share of the cap the merge's sort runs may
take (``adapter.ndjson.sort_run_bytes``, a sixteenth); the lake's DuckDB takes 40 % of the lake's cap
(``lake.store.memory_limit``), so the Python part must fit in the rest. A cap is never below the compose default.

The patient count is the lake's ``CURRENT`` snapshot (its ``Patient.ndjson``) when there is one, else
``TB_SITE_PATIENTS`` (the hospital's size, set before the first night). ``deploy/install.sh`` calls ``--write``: it
writes ``TB_MEM_ADAPTER`` and ``TB_MEM_LAKE`` into ``deploy/.env`` unless the operator set one by hand (a value that
is not the one this tool wrote, recorded in its marker line). ``trialbox doctor`` (``check_memory_caps``) fails when
a cap is below what the patient count needs.

    python -m tools.trialbox.memcaps --env-file deploy/.env [--lake DIR] [--write]
    python -m tools.trialbox.memcaps --measure [--sizes 500 2000]
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
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import IO, Any

ROOT = Path(__file__).resolve().parents[2]
RECORD = ROOT / "deploy" / "measured" / "ingest_memory.json"
COMPOSE = ROOT / "deploy" / "docker-compose.yml"
FORMAT = "tb-ingest-memory/1"
#: the services sized here and the cap variable of each
CAPS = {"adapter": "TB_MEM_ADAPTER", "lake": "TB_MEM_LAKE"}
MARKER = "# memcaps:"
SORT_SHARE = 16  # adapter.ndjson.sort_run_bytes: a sixteenth of the cap
LAKE_DUCKDB_SHARE = 0.4  # lake.store.memory_limit: 40 % of the cap
MEASURE_SORT_MB = "4"
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


def load_record(path: Path = RECORD) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("format") != FORMAT or not all(s in doc.get("services", {}) for s in CAPS):
        raise ValueError(f"{path}: not a {FORMAT} record of {', '.join(CAPS)}")
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


def need_mb(n: int, record: Mapping[str, Any], env: Mapping[str, str], compose: Path = COMPOSE) -> dict[str, int]:
    """The cap each service needs for ``n`` patients, in MB, never below its compose default."""
    out: dict[str, int] = {}
    for svc, var in CAPS.items():
        part = record["services"][svc]
        python = float(part["fixed_mb"]) + float(part["per_patient_kb"]) * n / 1024
        if svc == "adapter":
            heap = size_mb(env.get("TB_VALIDATOR_XMX") or _validator_default(compose))
            mb = (python + heap) * SORT_SHARE / (SORT_SHARE - 1)
        else:
            mb = python / (1 - LAKE_DUCKDB_SHARE)
        out[svc] = max(math.ceil(mb), size_mb(compose_default(var, compose)))
    return out


def _validator_default(compose: Path) -> str:
    m = re.search(r"TB_VALIDATOR_XMX:\s*([0-9]+[kmgKMG]?)", compose.read_text(encoding="utf-8"))
    return m.group(1) if m else "3g"


def _marker(env_text: str) -> dict[str, str]:
    for line in env_text.splitlines():
        if line.startswith(MARKER):
            return dict(p.split("=", 1) for p in line[len(MARKER) :].split() if "=" in p)
    return {}


def plan(env_text: str, n: int, record: Mapping[str, Any], compose: Path = COMPOSE) -> dict[str, str]:
    """The caps ``--write`` sets: each service's need, except a cap the operator set by hand (kept)."""
    env = _parse_env(env_text)
    ours = _marker(env_text)
    need = need_mb(n, record, env, compose)
    out: dict[str, str] = {}
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


def write(env_file: Path, caps: Mapping[str, str], n: int, source: str) -> None:
    lines = [ln for ln in env_file.read_text(encoding="utf-8").splitlines() if not ln.startswith(MARKER)]
    lines = [ln for ln in lines if ln.split("=", 1)[0].strip() not in caps]
    lines += [f"{k}={v}" for k, v in caps.items()]
    recorded = {**_marker(env_file.read_text(encoding="utf-8")), **caps}
    lines.append(f"{MARKER} " + " ".join(f"{k}={v}" for k, v in sorted(recorded.items())) + f" n={n} ({source})")
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def check(
    env: Mapping[str, str], lake: Path | None, record_path: Path = RECORD, compose: Path = COMPOSE
) -> tuple[str, str]:
    """``(status, detail)`` for ``trialbox doctor``: FAIL when a cap is below what the patient count needs."""
    n, source = patients(env, lake)
    if n is None:
        return "WARN", f"{source}: the memory caps were not compared with the hospital's size"
    record = load_record(record_path)
    need = need_mb(n, record, env, compose)
    have = {svc: size_mb(env.get(var) or compose_default(var, compose)) for svc, var in CAPS.items()}
    low = [f"{CAPS[s]} {have[s]} MB < {need[s]} MB" for s in CAPS if have[s] < need[s]]
    facts = f"{n} patients ({source}); measured record {record_path.name} ({record.get('measured_at', '?')})"
    if low:
        fix = "re-run deploy/install.sh (it sizes them) or set them in deploy/.env"
        return "FAIL", f"{'; '.join(low)} for {facts}: the night's ingest or rebuild may be killed; {fix}"
    return "PASS", f"{', '.join(f'{CAPS[s]} {have[s]} MB (needs {need[s]})' for s in CAPS)} for {facts}"


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
    Lake(d / "lake", "Asia/Taipei").rebuild("2026-10-04", HashEmbedder())
print(json.dumps({"maxrss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}))
"""


def _rss_mb(svc: str, n: int) -> float:
    env = {**os.environ, "PYTHONPATH": "libs:services:.", "TB_LAKE_SOURCE": "legacy", "TB_TZ": "Asia/Taipei"}
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="memcaps", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--env-file", type=Path, default=ROOT / "deploy" / ".env")
    ap.add_argument("--lake", type=Path, default=None)
    ap.add_argument("--write", action="store_true", help="write the caps into --env-file")
    ap.add_argument("--measure", action="store_true", help=f"measure and write {RECORD.relative_to(ROOT)}")
    ap.add_argument("--sizes", type=int, nargs=2, default=(500, 2000))
    a = ap.parse_args(argv)
    if a.measure:
        doc = measure((a.sizes[0], a.sizes[1]))
        RECORD.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(doc["services"], sort_keys=True))
        return 0
    text = a.env_file.read_text(encoding="utf-8") if a.env_file.is_file() else ""
    env = {**_parse_env(text), **{k: v for k, v in os.environ.items() if k == "TB_SITE_PATIENTS"}}
    n, source = patients(env, a.lake or (Path(env["TB_LAKE_DIR"]) if env.get("TB_LAKE_DIR") else None))
    if n is None:
        print(f"memcaps: {source}: the compose defaults stay (set TB_SITE_PATIENTS to size them)")
        return 0
    caps = plan(text, n, load_record())
    print(f"memcaps: {n} patients ({source}): " + (", ".join(f"{k}={v}" for k, v in caps.items()) or "set by hand"))
    if a.write and caps:
        write(a.env_file, caps, n, source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
