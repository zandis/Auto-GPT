"""The 48 GB measuring run, unattended (lane H, card H-53; the run of H-47's sheet without SSH): the decisions and the
records of tools/measure48-vm.sh, and the driver's free arithmetic (deploy/gcp/measure48-run.sh). Standard
library only: the VM runs it with its own python3 before any venv exists (as box_vm.py is run).

    python3 measure48_vm.py estimate [--no-o] [--json]          # the stages, low / estimate / high, US$, the lines
    python3 measure48_vm.py gate --stage 6 --used-s N --line-s N # may a stage START (its high before the stop line)?
    python3 measure48_vm.py ladder-next [--tried OPTION:RC ...]  # the next option of the ladder, or none (and why)
    python3 measure48_vm.py disk --path / --need-gb N            # is there room for the next big step?
    python3 measure48_vm.py pack --run DIR --out DIR [--mask-file F ...]   # the allow-listed records, redacted
    python3 measure48_vm.py summary DIR                          # --collect: what the run measured
    python3 measure48_vm.py quota DIR --zone Z --disk-gb N [--hdb-free-gb N]  # the driver's preflight: GPU, CPU, disk
    python3 measure48_vm.py host-need [--pull]                   # on an existing host (H-67): GB in each place

Every figure of ``STAGES`` is H-47's (docs/plan/measurements/48gb-measuring-run-2026-11-19.md, section 5), unchanged:
the unattended form does the same steps in the same order; only the disk is smaller (100 GB, the region's
HDB_TOTAL_GB of 500 GB with tb-gpu-sim holding 400), which changes the worst case by the disk's own price.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import math
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

PRICE_PER_HOUR = 2.74  # g4-standard-48 SPOT, RTX PRO 6000: tools/complete_run.py PRICE_PER_HOUR (a test pins it)
ON_DEMAND_PRICE_PER_HOUR = round(3 * PRICE_PER_HOUR, 2)  # tools/complete_run.py ON_DEMAND_PRICE_PER_HOUR
DISK_GB = 100  # the boot disk: HDB_TOTAL_GB 500 GB, tb-gpu-sim 400 (a refused create, 11-19; not listed: H-59)
DISK_USD_PER_GIB_MONTH = 0.093  # hyperdisk-balanced, Taiwan list price (H-47 section 5, the hand-over's figure)
CAP_HOURS = 4  # --max-run-duration 4h, as H-47
HOURS_PER_MONTH = 730

# (key, what, low, estimate, high): H-47 section 5's table, hours. "O" is optional (stage O, H-49's flag).
STAGES: list[tuple[str, str, float, float, float]] = [
    ("1", "VM created, booted", 0.05, 0.10, 0.25),
    ("2", "driver (one reboot), Docker, toolkit", 0.20, 0.35, 0.75),
    ("3", "checkout, weights 27.9 GB", 0.08, 0.20, 0.47),
    ("4", "stub start once (builds the box's images, the database image too), down", 0.11, 0.43, 1.05),
    ("5", "engine image (9.2 GB compressed), ballast on", 0.04, 0.10, 0.25),
    ("6", "the ladder: pair-32k --keep (else pair-16k, else judge-alone)", 0.13, 0.25, 0.80),
    ("7", "the screen's tools", 0.15, 0.25, 0.40),
    ("8", "the screen, 1,000 patients, ja, 16 in flight", 0.12, 0.20, 0.50),
    ("O", "OPTIONAL: the verifier flag (H-49), canary, diff", 0.06, 0.12, 0.25),
    ("9", "one more option: pair-32k-host53", 0.13, 0.25, 0.80),
    ("10", "down, ballast released, records up, power off", 0.03, 0.05, 0.10),
]
STAGE = {s[0]: s for s in STAGES}
STOP_LINE_FACTOR = 1.5  # H-47: the stop line is 50 % over the estimate

LADDER = ["pair-32k", "pair-16k", "judge-alone"]  # lane J's order (runbook 29 step 7): the first that starts is kept

# The run's records that may leave the VM (the sheet's step 10 list, plus this card's step log and decisions). A file
# is uploaded only when its path (relative to the run folder) matches one of these AND none of DENY. Text is redacted
# line by line (REDACT, box_vm.py's own pattern, and every value of --mask-file) before it is written to the stage.
ALLOW = [
    "steps.json", "decisions.json", "disk.jsonl", "clock.txt", "vm.log",
    "host.log", "preflight.txt", "records/docker-objects.json",  # the host form (H-67, tools/measure48-host.sh)
    "records/o0-card.csv", "records/plan.txt", "records/ballast.log", "records/head.json",
    "records/tb-dgpu48-*/measure.*.json", "records/tb-dgpu48-*/serving_config.dgpu48.*.json",
    "records/tb-dgpu48-*/canary.*.json",
    "records/screen-during.json", "records/screen/parts/prepare.json", "records/screen/parts/hospital-ja.json",
    "records/canary-verifier-flag.json", "records/canary-verifier-flag-diff.json",
    "logs/*.log",
]  # fmt: skip
DENY = [
    "raw/*", "*/raw/*", "*.env", "*/.env", "*secrets*", "*down.json", "*verifier-flag.yml", "*poc-up*", "*.key",
    "*.pem", "*key*.json", "*/.serving_config.*", "*gpu-pin.yml", "kv/*",
]  # fmt: skip
REDACT = re.compile(r"(password|passwort|enrol|enroll|secret|token|api[_-]?key|authorization|bearer)", re.I)
MAX_LOG_LINES = 400  # a step's log goes up as its last lines (the end of a log says what failed)

# The disk (GB, decimal, as df -B1 / 1e9): what each big step needs free before it starts. From the repository's own
# figures where they exist (docs/handover/installer-first-contact-2026-11-15 .../facts-vm.txt: the engine image 23.4 GB,
# the box's images 3.7 GB, the build cache 4.0 GB; tools/fetch_weights.py --dry-run: 27.9 GB) and a margin; the
# rest is not measured and said so on the page.
NEED_GB = {
    "weights": 30.0,  # 27.9 GB staged on the same disk and renamed into place (no second copy) + 2 GB
    "stub": 14.0,  # the box's images 3.7 GB + build cache 4.0 GB + base images and layers in flight (not measured) 5 GB
    "engine": 30.0,  # 23.4 GB unpacked + layers in flight (not measured; 9.2 GB compressed in all, three at a time)
    "tools": 6.0,  # apt (postgresql, tesseract), the venv (0.65 GB here), uv's cache, node, Chromium (not measured)
    "screen": 3.0,  # PostgreSQL for 1,000 synthetic patients, the part's folder, screenshots (not measured; small)
    "host53": 1.0,  # one more measure: records only
}


# An existing host (H-67, tools/measure48-host.sh): steps s05 to s14 only. The weights are there already (checked, not
# fetched); the images go to Docker's data root (the stub's, and the engine's only with --pull); the screen's tools
# (the venv, node and Chromium, uv's cache) and the screen itself go to the run folder.
HOST_DOCKER_STEPS = ("stub",)  # + "engine" with --pull
HOST_RUN_DIR_STEPS = ("tools", "screen", "host53")
RENTED_DRIVER_BRANCH = "580"  # the rented run's driver (D-966: nvidia-driver-580-server-open); a host's is recorded


def host_need(pull: bool = False) -> dict[str, float]:
    """GB free each place needs before the host form starts, from NEED_GB (the run sheet's figures and margins)."""
    docker = [*HOST_DOCKER_STEPS, *(("engine",) if pull else ())]
    return {"docker_root_gb": round(sum(NEED_GB[k] for k in docker), 1),
            "run_dir_gb": round(sum(NEED_GB[k] for k in HOST_RUN_DIR_STEPS), 1)}  # fmt: skip


def hours(with_o: bool) -> tuple[float, float, float]:
    rows = [s for s in STAGES if with_o or s[0] != "O"]
    return (round(sum(r[2] for r in rows), 2), round(sum(r[3] for r in rows), 2), round(sum(r[4] for r in rows), 2))


def estimate(with_o: bool = True, disk_gb: int = DISK_GB) -> dict[str, Any]:
    low, est, high = hours(with_o)
    line_h = stop_line_h(with_o)
    disk_usd = round(disk_gb * DISK_USD_PER_GIB_MONTH * CAP_HOURS / HOURS_PER_MONTH, 2)
    cap_usd = round(CAP_HOURS * PRICE_PER_HOUR, 2)
    return {
        "schema": "tb-measure48-estimate/1", "with_o": with_o, "price_per_hour": PRICE_PER_HOUR,
        "stages": [{"stage": k, "what": w, "low_h": lo, "estimate_h": e, "high_h": h} for k, w, lo, e, h in STAGES
                   if with_o or k != "O"],
        "low_h": low, "estimate_h": est, "high_h": high,
        "low_usd": round(low * PRICE_PER_HOUR, 2), "estimate_usd": round(est * PRICE_PER_HOUR, 2),
        "high_usd": round(high * PRICE_PER_HOUR, 2),
        "stop_line_h": line_h, "stop_line_usd": round(est * PRICE_PER_HOUR * STOP_LINE_FACTOR, 2),
        "cap_h": CAP_HOURS, "cap_usd": cap_usd, "disk_gb": disk_gb, "disk_usd_at_cap": disk_usd,
        "worst_case_usd": round(cap_usd + disk_usd, 2),
        "worst_case_on_demand_usd": round(CAP_HOURS * ON_DEMAND_PRICE_PER_HOUR, 2),
        "vm_stop_line_min": vm_stop_line_min(with_o),
    }  # fmt: skip


def stop_line_h(with_o: bool = True) -> float:
    """50 % over the estimate, rounded UP to a tenth of an hour (H-47: 2.30 h -> 3.5 h; 2.18 h -> 3.3 h)."""
    return math.ceil(round(hours(with_o)[1] * STOP_LINE_FACTOR * 10, 6)) / 10


def vm_stop_line_min(with_o: bool = True) -> int:
    """The stop line on the VM's own clock (its seconds up, over every boot): the run's line less stage 1's estimate,
    which is spent before the start-up script's first line."""
    return round((stop_line_h(with_o) - STAGE["1"][3]) * 60)


def gate(stage: str, used_s: float, line_s: float, also: list[str] | None = None) -> tuple[bool, str]:
    """A stage starts only when its high estimate ends before the stop line (H-47: O's rule, applied to every stage).
    ``also``: stages that must follow it to be worth starting (the screen's tools are worth nothing without the
    screen), their highs added."""
    keys = [stage, *(also or [])]
    high_s = sum(STAGE[k][4] for k in keys) * 3600
    name = "stage " + " + ".join(keys)
    left = line_s - used_s
    if used_s + high_s <= line_s:
        return True, f"{name} starts: {left / 3600:.2f} h left before the stop line, its high is {high_s / 3600:.2f} h"
    return False, (f"{name} not started: {max(left, 0) / 3600:.2f} h left before the stop line, its high is "
                   f"{high_s / 3600:.2f} h")  # fmt: skip


def ladder_next(tried: list[tuple[str, int]]) -> tuple[str, str]:
    """The next option to try, or "" with the reason. ``tried``: (option, ballast48 measure's exit code) in order:
    0 started (kept: the ladder ends), 1 did not start (the next one), anything else (2: refused before any server,
    the ballast or the card not as asked; 3: the tool broke, exit 1 with a traceback or no record, as the VM script
    tells them apart; 130: stopped at the stop line) ends the ladder: the next option would meet the same."""
    for opt, rc in tried:
        if rc == 0:
            return "", f"{opt} started and is kept"
        if rc != 1:
            return "", f"{opt} ended with exit {rc} (refused, broke or stopped, not 'did not start'): the ladder ends"
    done = [o for o, _ in tried]
    for opt in LADDER:
        if opt not in done:
            why = "the first option" if not done else f"{done[-1]} did not start"
            return opt, why
    return "", "no option of the ladder started"


def disk_ok(path: str, need_gb: float, free_bytes: int | None = None) -> tuple[bool, str]:
    free = shutil.disk_usage(path).free if free_bytes is None else free_bytes
    gb = free / 1e9
    if gb >= need_gb:
        return True, f"{gb:.1f} GB free on {path}, {need_gb:g} GB needed"
    return False, f"{gb:.1f} GB free on {path}, {need_gb:g} GB needed: the step would not fit (DISK-SHORT)"


def allowed(rel: str) -> bool:
    rel = rel.replace(os.sep, "/")
    if any(part.startswith(".") for part in rel.split("/")) or any(fnmatch.fnmatch(rel, d) for d in DENY):
        return False
    return any(fnmatch.fnmatch(rel, a) for a in ALLOW)


def mask_text(text: str, masks: list[str]) -> str:
    """Every value of the mask files replaced (a JSON record keeps its form: a value inside a string)."""
    for m in sorted({m for m in masks if len(m) >= 8}, key=len, reverse=True):
        text = text.replace(m, "[masked]")
    return text


def redact_text(text: str, masks: list[str]) -> str:
    """A log's text: masked, and each line naming a password, a token, a key or a secret replaced whole."""
    text = mask_text(text, masks)
    out = []
    for line in text.splitlines(keepends=True):
        out.append("[redacted line]\n" if REDACT.search(line) else line)  # the whole line: no prefix is trusted
    return "".join(out)


def read_masks(files: list[Path]) -> list[str]:
    """The values never to upload: each VALUE of a KEY=VALUE line (quotes removed), or the whole file's text."""
    out: list[str] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            v = line.split("=", 1)[1] if "=" in line else line
            v = v.strip().strip("\"'")
            if v:
                out.append(v)
    return out


def mask_files(files: list[Path], dirs: list[Path]) -> list[Path]:
    """--mask-file and every file under each --mask-dir (deploy/secrets/: the site's keys, the servers' key file)."""
    out = [f for f in files if f.is_file()]
    for d in dirs:
        if d.is_dir():
            out += [f for f in sorted(d.rglob("*")) if f.is_file() and not f.is_symlink() and f.stat().st_size < 65536]
    return out


def records(run: Path, used_s: float, ended: str = "") -> None:
    """steps.json and decisions.json from the script's tab-separated lines (steps.tsv, decisions.tsv, kv/)."""
    steps = []
    for line in _lines(run / "steps.tsv"):
        f = (line.split("\t") + [""] * 5)[:5]
        rc: int | str = int(f[3]) if f[3].lstrip("-").isdigit() else f[3]
        steps.append({"step": f[0], "started": f[1], "ended": f[2], "rc": rc, "note": f[4]})
    prev = _load(run / "steps.json") or {}
    doc = {"schema": "tb-measure48-steps/1", "used_s": int(used_s), "ended": ended or prev.get("ended") or "",
           "steps": steps}  # fmt: skip
    _write(run / "steps.json", doc)
    dec = []
    for line in _lines(run / "decisions.tsv"):
        f = (line.split("\t") + [""] * 5)[:5]
        used: int | str = int(f[1]) if f[1].isdigit() else f[1]
        dec.append({"at": f[0], "used_s": used, "what": f[2], "choice": f[3], "why": f[4]})
    kept = (run / "kv" / "kept").read_text(encoding="utf-8").strip() if (run / "kv" / "kept").is_file() else None
    tried = (run / "kv" / "tried").read_text(encoding="utf-8").split() if (run / "kv" / "tried").is_file() else []
    _write(run / "decisions.json", {"schema": "tb-measure48-decisions/1", "kept": kept, "ladder_tried": tried,
                                    "decisions": dec})  # fmt: skip


def _lines(p: Path) -> list[str]:
    try:
        return [x for x in p.read_text(encoding="utf-8", errors="replace").splitlines() if x.strip()]
    except OSError:
        return []


def _write(p: Path, doc: Any) -> None:
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def pack(run: Path, out: Path, masks: list[str]) -> list[str]:
    """The allow-listed files of ``run`` copied, redacted, to ``out`` (emptied first). Returns their paths."""
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    took: list[str] = []
    for p in sorted(run.rglob("*")):
        if not p.is_file() or p.is_symlink():
            continue
        rel = p.relative_to(run).as_posix()
        if not allowed(rel):
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if rel.startswith("logs/"):
            text = "".join(text.splitlines(keepends=True)[-MAX_LOG_LINES:])
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        # a JSON record is masked only (its own tool scrubbed it, and "kv_cache_tokens" is no token); text is redacted
        dest.write_text(mask_text(text, masks) if rel.endswith(".json") else redact_text(text, masks), encoding="utf-8")
        took.append(rel)
    return took


def _load(p: Path) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _max_len(root: Path | None, option: str, role: str) -> int | None:
    """The option's max context for a role, from deploy/dgpu48-profile.yaml (the driver's checkout; PyYAML there)."""
    if root is None:
        return None
    try:
        import yaml  # the driver's venv; never on the VM

        doc = yaml.safe_load((root / "deploy" / "dgpu48-profile.yaml").read_text(encoding="utf-8"))
    except Exception:  # a summary without this figure
        return None
    for o in doc.get("options") or []:
        if o.get("id") == option:
            v = (o.get("env") or {}).get(f"{role.upper()}_MAX_LEN")
            return int(v) if v else None
    return None


def summary(d: Path, root: Path | None = None) -> dict[str, Any]:
    """What --collect prints: the option kept, free at peak, sequences that fit, seconds per judged call, the
    screen's wall time, O's verdict counts, and every decision the script made."""
    dec = _load(d / "decisions.json") or {}
    steps = _load(d / "steps.json") or {}
    out: dict[str, Any] = {"schema": "tb-measure48-summary/1", "ended": steps.get("ended"),
                           "used_s": steps.get("used_s"), "steps": [],
                           "decisions": dec.get("decisions", [])}  # fmt: skip
    for s in steps.get("steps", []):
        out["steps"].append({k: s.get(k) for k in ("step", "rc", "started", "ended", "note")})
    out["kept"] = dec.get("kept")
    options = {}
    for m in sorted(d.glob("records/tb-dgpu48-*/measure.*.json")):
        rec = _load(m) or {}
        opt = str(rec.get("option") or m.name.split(".")[1])
        b = rec.get("ballast") or {}
        seqs = {}
        for role, e in (rec.get("engine_log") or {}).items():
            n, ml = (e or {}).get("kv_cache_tokens"), _max_len(root, opt, role)
            seqs[role] = {"kv_cache_tokens": n, "max_len": ml,
                          "full_context_sequences": (n // ml) if (n and ml) else None}  # fmt: skip
        canary = _load(m.parent / f"canary.{opt}.json") or {}
        judge = next((x for x in canary.get("models") or [] if isinstance(x, dict) and x.get("role") == "judge"), {})
        spc = None
        if judge.get("seconds") and judge.get("cases"):
            spc = round(float(judge["seconds"]) / float(judge["cases"]), 2)
        options[opt] = {"started": rec.get("started"), "outcome": rec.get("outcome"),
                        "free_at_peak_mib": b.get("free_at_peak_mib"), "card_peak_mib": rec.get("card_peak_mib"),
                        "host_peak_mib": rec.get("host_peak_mib"), "sequences": seqs,
                        "seconds_per_judged_call": spc}  # fmt: skip
    out["options"] = options
    sd = _load(d / "records/screen-during.json") or {}
    part = _load(d / "records/screen/parts/hospital-ja.json") or {}
    out["screen"] = {"wall_seconds": sd.get("wall_seconds"), "exit_code": sd.get("exit_code"),
                     "free_at_peak_mib": sd.get("free_at_peak_mib"), "part_wall_seconds": part.get("wall_seconds"),
                     "ballast_held_at_end": sd.get("ballast_held_at_end")} if sd else None  # fmt: skip
    diff = _load(d / "records/canary-verifier-flag-diff.json")
    if diff:
        out["o"] = {"verdicts_differ": diff.get("verdicts_differ"), "exact": diff.get("exact"),
                    "runs": {k: {x: v.get(x) for x in ("cases", "answered", "correct", "seconds_per_call")}
                             for k, v in (diff.get("runs") or {}).items()}}  # fmt: skip
    else:
        out["o"] = next((x for x in out["decisions"] if x.get("what") == "O"), None)
    return out


def _hdb_free_gb(text: str) -> float:
    """``--hdb-free-gb``: the region's free HDB_TOTAL_GB by hand (a number of GB, 0 or more); anything else refused."""
    try:
        v = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number of GB: {text!r}") from None
    if not math.isfinite(v) or v < 0:
        raise argparse.ArgumentTypeError(f"not a number of GB (0 or more): {text!r}")
    return v


def _read_json(path: Path, what: str) -> tuple[Any, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, ValueError) as exc:
        return None, f"{what} not readable ({path.name}: {type(exc).__name__}); the quota cannot be judged"


def quota_check(folder: Path, zone: str, disk_gb: int, hdb_free_gb: float | None = None) -> tuple[list[str], list[str]]:
    """The driver's preflight: one Spot RTX PRO 6000 VM in ``zone`` (tools/complete_run.py quota_problems, the same
    reading the complete run's launch makes) and room for its boot disk in the region's HDB_TOTAL_GB. Returns
    (problems, notes): any problem refuses the launch; a note is said and the preflight goes on.

    H-59: ``regions describe`` may not list HDB_TOTAL_GB at all (asia-east1, 11-19: 113 rows, none of it). A
    well-formed list without the row is a note, not a problem: the disk cannot be checked beforehand and the create
    call itself refuses when the quota is short. A row that is there and short still refuses. ``hdb_free_gb`` (the
    free figure by hand, e.g. from a refused create's message) is checked against the need exactly like a listed
    row. Output that is not JSON, or not a quota list, is a problem: an error is never taken for "go on"."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.complete_run import quota_problems  # the driver's checkout

    region = zone.rsplit("-", 1)[0]
    project, e1 = _read_json(folder / "project.json", "project-info describe")
    reg, e2 = _read_json(folder / f"region-{region}.json", f"regions describe {region}")
    bad = [e for e in (e1, e2) if e]
    if bad:
        return bad, []
    rows = reg.get("quotas") if isinstance(reg, dict) else None
    if not isinstance(project, dict) or not isinstance(rows, list) or not all(isinstance(q, dict) for q in rows):
        return [f"regions describe {region} / project-info describe: not a quota list; the quota cannot be judged"], []
    bad = list(quota_problems(project, {region: reg}, [zone]))
    notes: list[str] = []
    hdb = next((q for q in rows if q.get("metric") == "HDB_TOTAL_GB"), None)
    if hdb is not None:
        try:
            lim, use = float(hdb.get("limit", 0)), float(hdb.get("usage", 0))
        except (TypeError, ValueError):
            bad.append(f"{region}: HDB_TOTAL_GB row not readable: {hdb!r}")
        else:
            if lim - use < disk_gb:
                bad.append(f"{region}: HDB_TOTAL_GB: limit {lim:g}, in use {use:g}, free {lim - use:g} GB; the boot "
                           f"disk needs {disk_gb} GB")  # fmt: skip
    elif hdb_free_gb is None:
        notes.append(f"{region}: HDB_TOTAL_GB is not in the region's quota list ({len(rows)} rows), so the "
                     f"{disk_gb} GB disk quota cannot be checked beforehand; the create call itself refuses if it "
                     f"is short (--hdb-free-gb N gives the free figure by hand)")  # fmt: skip
    if hdb_free_gb is not None:
        if hdb_free_gb < disk_gb:
            bad.append(f"{region}: HDB_TOTAL_GB: free {hdb_free_gb:g} GB (given by hand, --hdb-free-gb); the boot "
                       f"disk needs {disk_gb} GB")  # fmt: skip
        else:
            notes.append(f"{region}: HDB_TOTAL_GB: free {hdb_free_gb:g} GB (given by hand, --hdb-free-gb); the boot "
                         f"disk needs {disk_gb} GB")  # fmt: skip
    return bad, notes


def quota(folder: Path, zone: str, disk_gb: int, hdb_free_gb: float | None = None) -> list[str]:
    """The problems of ``quota_check`` (empty: the launch may go on)."""
    return quota_check(folder, zone, disk_gb, hdb_free_gb)[0]


def _print_estimate(e: dict[str, Any]) -> None:
    print(f"{'stage':<6}{'what':<74}{'low':>6}{'est':>6}{'high':>6}")
    for s in e["stages"]:
        print(f"{s['stage']:<6}{s['what']:<74}{s['low_h']:>6.2f}{s['estimate_h']:>6.2f}{s['high_h']:>6.2f}")
    print(
        f"in all ({'with' if e['with_o'] else 'without'} O): low {e['low_h']} h US${e['low_usd']:.2f}, estimate "
        f"{e['estimate_h']} h US${e['estimate_usd']:.2f}, high {e['high_h']} h US${e['high_usd']:.2f} "
        f"(US${e['price_per_hour']} a VM hour, SPOT)"
    )
    print(
        f"stop line: {e['stop_line_h']} h, US${e['stop_line_usd']:.2f} (50 % over the estimate); on the VM's own "
        f"clock {e['vm_stop_line_min']} min (less stage 1's estimate)"
    )
    print(
        f"cap: --max-run-duration {e['cap_h']}h, US${e['cap_usd']:.2f}; worst case US${e['worst_case_usd']:.2f} "
        f"(the cap + the {e['disk_gb']} GB disk for {e['cap_h']} h, US${e['disk_usd_at_cap']:.2f}); on demand "
        f"US${e['worst_case_on_demand_usd']:.2f}"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="measure48_vm.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("estimate")
    e.add_argument("--no-o", action="store_true")
    e.add_argument("--json", action="store_true")
    e.add_argument("--disk-gb", type=int, default=DISK_GB)
    g = sub.add_parser("gate")
    g.add_argument("--stage", required=True, choices=sorted(STAGE))
    g.add_argument("--used-s", type=float, required=True)
    g.add_argument("--line-s", type=float, required=True)
    g.add_argument("--also", action="append", default=[], choices=sorted(STAGE))
    ln = sub.add_parser("ladder-next")
    ln.add_argument("--tried", nargs="*", default=[])
    dk = sub.add_parser("disk")
    dk.add_argument("--path", default="/")
    dk.add_argument("--need-gb", type=float)
    dk.add_argument("--for", dest="what", choices=sorted(NEED_GB))
    dk.add_argument("--free-bytes", type=int, default=None)  # the rehearsal's stand-in disk
    p = sub.add_parser("pack")
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--mask-file", type=Path, action="append", default=[])
    p.add_argument("--mask-dir", type=Path, action="append", default=[])
    rd = sub.add_parser("redact")  # stdin to stdout, as pack writes a text
    rd.add_argument("--mask-file", type=Path, action="append", default=[])
    rd.add_argument("--mask-dir", type=Path, action="append", default=[])
    rc = sub.add_parser("records")
    rc.add_argument("--run", type=Path, required=True)
    rc.add_argument("--used-s", type=float, required=True)
    rc.add_argument("--ended", default="")
    s = sub.add_parser("summary")
    s.add_argument("dir", type=Path)
    s.add_argument("--json", action="store_true")
    q = sub.add_parser("quota")
    q.add_argument("dir", type=Path)
    q.add_argument("--zone", required=True)
    q.add_argument("--disk-gb", type=int, default=DISK_GB)
    q.add_argument("--hdb-free-gb", type=_hdb_free_gb, default=None)  # H-59: the free figure by hand
    sub.add_parser("stop-line-min").add_argument("--no-o", action="store_true")
    hn = sub.add_parser("host-need")
    hn.add_argument("--pull", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "estimate":
        est = estimate(not a.no_o, a.disk_gb)
        print(json.dumps(est, indent=1)) if a.json else _print_estimate(est)
        return 0
    if a.cmd == "host-need":
        gb = host_need(a.pull)
        print(f"{gb['docker_root_gb']:g} {gb['run_dir_gb']:g}")
        return 0
    if a.cmd == "stop-line-min":
        print(vm_stop_line_min(not a.no_o))
        return 0
    if a.cmd == "gate":
        ok, why = gate(a.stage, a.used_s, a.line_s, a.also)
        print(why)
        return 0 if ok else 1
    if a.cmd == "ladder-next":
        tried = []
        for t in a.tried:
            opt, _, rc = t.rpartition(":")
            tried.append((opt, int(rc)))
        opt, why = ladder_next(tried)
        print(f"{opt}\t{why}")
        return 0
    if a.cmd == "disk":
        need = a.need_gb if a.need_gb is not None else NEED_GB.get(a.what or "", 0.0)
        ok, why = disk_ok(a.path, need, a.free_bytes)
        print(why)
        return 0 if ok else 1
    if a.cmd == "records":
        records(a.run, a.used_s, a.ended)
        return 0
    if a.cmd == "redact":
        sys.stdout.write(redact_text(sys.stdin.read(), read_masks(mask_files(a.mask_file, a.mask_dir))))
        return 0
    if a.cmd == "pack":
        for rel in pack(a.run, a.out, read_masks(mask_files(a.mask_file, a.mask_dir))):
            print(rel)
        return 0
    if a.cmd == "summary":
        res = summary(a.dir, Path(__file__).resolve().parents[1])
        print(json.dumps(res, indent=1, sort_keys=True))
        return 0
    bad, notes = quota_check(a.dir, a.zone, a.disk_gb, a.hdb_free_gb)
    for n in notes:
        print(f"quota: {n}")
    for b in bad:
        print(f"quota: {b}", file=sys.stderr)
    if bad:
        print("quota: the run's VM cannot be made now; nothing was made or started", file=sys.stderr)
        return 4
    checked = not any("cannot be checked beforehand" in n for n in notes)
    disk = f"its {a.disk_gb} GB disk fit" if checked else f"its {a.disk_gb} GB disk: not checked (above)"
    print(f"quota: one Spot RTX PRO 6000 VM in {a.zone} and {disk}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
