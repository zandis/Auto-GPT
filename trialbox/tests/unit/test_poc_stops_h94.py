"""H-94 (the owner's ruling, relayed as 7092087958; D-1091): on a PoC box the install, start and update paths stop for
five things only: (1) the bundle's or update's signature or hashes do not hold; (2) the machine physically cannot run
it; (3) a PoC box would load real patient data or become PRODUCTION; (4) the step needs root and does not have it;
(5) a secret would be read from, or written to, a place others can read (7095256773). The review of #1396 and its
ruling (7096812411, 7096812799): ``test_poc_stops_review_h94.py``.
Every other stop, on a PoC box, warns, is written to one list that ``doctor`` shows, and the install goes on; on a
PRODUCTION box nothing changes.

THE ONE TEST: :func:`test_a_poc_install_goes_through_every_converted_point`. The REAL ``deploy/install.sh`` (the
bench of ``test_poc_stops_bench_h94.py``), through the bundle load and the run from the signed tree, on PoC boxes
with every converted point of the file forced, each run ending installed, the list holding every point. The rule of
7092045961 items 1-2 (a guard rides only with a test on the real path it sits on) binds each point.

The PRODUCTION twins: :func:`test_on_production_the_same_forced_points_stop_with_master_s_words` (a sample of the
points, the stop's words and exit code as master's, with every variable a caller could plant set to a PoC value)
and :func:`test_every_converted_message_is_master_s` (every converted point's words, byte for byte, against the
fixture of master's stops).

THE RATCHET: :func:`test_no_bare_stop_on_the_install_path` (a new ``die`` / ``exit N`` without the numbered comment
or the helper fails it; the files not yet converted are held to their count).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_poc_stops_bench_h94 import Box, Run
from tools.trialbox import doctor, stops

pytestmark = [pytest.mark.nodb, pytest.mark.skipif(sys.platform != "linux", reason="bash and GNU tools")]

ROOT = Path(__file__).resolve().parents[2]
INSTALL = ROOT / "deploy" / "install.sh"
PAGE = ROOT / "docs" / "handover" / "poc-stops-h94-2026-11-23.md"
MASTER = json.loads((ROOT / "tests" / "fixtures" / "h94" / "install_sh_master_stops.json").read_text(encoding="utf-8"))
SIGNED = "continuing from the signed release"
RUNNING = "TrialBox is running."

# ---------------------------------------------------------------------------------------------------- the points
STOP = re.compile(r"""(?<![\w-])die\s+["'$]|\bexit\s+(?:[1-9]|"?\$)""")
#: the five of D-1091 (the fifth, a secret read or written where others can read, added by the integrator,
#: 7095256773), "depends (N)" (kept: it protects stop N on the input that reaches it, H94-03), or not a stop at all
MARK = re.compile(r"H-94 (?:\(([1-5])\)|depends \(([1-5])\)|not a stop)")
CALL = re.compile(
    r"""(?:stop_or_warn(?:\s+--rc\s+(?:\d+|"\$\w+")|\s+--silent)*|rrs_drop|rehearsal_only|finish_check)\s+"?([A-Za-z0-9:._-]+)"""
)
#: the files of the install, start and update paths, and how many bare stops each may still have. A converted
#: file is 0. The count of a file not yet converted can only go down (H-94: stop at a file boundary)
RATCHET = {
    "deploy/install.sh": 0,
    "deploy/box-install.sh": 0,
    "tools/apply_update.sh": 0,
    "deploy/bootstrap.sh": 0,
    "deploy/launcher.sh": 0,
    "deploy/check_host.sh": 0,
    "deploy/settings_guard.sh": 0,
}
PY_RATCHET = {"tools/rehearsal_real.py": 0, "tools/trialbox/launch.py": 0}  # sys.exit, SystemExit, raise


#: a named block whose header names one of the five (H-96's KEK-INPUT: "# KEK-INPUT (H-96, F-45, H-94 (5); ..."):
#: every stop inside it, to its "# ---- end of <NAME>", is that refusal (its lines are H-96's, held together by its
#: own test across three files, so no line inside it carries a mark of its own)
BLOCK = re.compile(r"#\s*(?:---- )?([A-Z][A-Z0-9-]*) \([^)]*?H-94 \(([1-5])\)")


def marked_blocks(lines: list[str]) -> dict[int, str]:
    """Line index -> the number the enclosing marked block names."""
    out: dict[int, str] = {}
    name, n = "", ""
    for i, line in enumerate(lines):
        s = line.strip()
        if not name and (m := BLOCK.match(s)) and f"# ---- end of {m.group(1)}" in (x.strip() for x in lines[i:]):
            name, n = m.group(1), m.group(2)  # a block only where it is closed
        elif name and s == f"# ---- end of {name}":
            name = ""
        elif name:
            out[i] = n
    return out


def bare_stops(text: str) -> list[tuple[int, str]]:
    """Each line that stops (die, exit N) with neither the helper nor ``H-94 (N)``/``H-94 depends`` on it or on the two
    lines above it. The helper's own block is not counted."""
    lines = text.splitlines()
    out: list[tuple[int, str]] = []
    block = False
    marked = marked_blocks(lines)
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("# ---- STOP-OR-WARN"):
            block = True
        if s.startswith("# ---- end of STOP-OR-WARN"):
            block = False
            continue
        code = line.split("  # ")[0]
        if block or i in marked or s.startswith("#") or re.match(r"\s*\w+\(\) *\{", line) or "stop_or_warn" in code:
            continue
        if STOP.search(code) and not MARK.search(" ".join(lines[max(0, i - 2) : i + 1])):
            out.append((i + 1, s))
    return out


def converted_keys(text: str) -> set[str]:
    """The keys of the converted points (the list's ``install.sh/<key>``)."""
    keys: set[str] = set()
    for line in text.splitlines():
        if line.strip().startswith("#") or re.match(r"\s*\w+\(\) *\{", line):
            continue
        for m in CALL.finditer(line):
            k = m.group(1)
            if k.startswith(("$", "fail:")):
                continue
            keys.add(k)
            if re.search(r"(^|\s)finish_check\s", line):
                keys.add(f"{k}-did-not-run")
    return keys | ({"fail"} if '"fail: ' in text else set())  # install.sh's FAIL lines: one point, a key per line


def mark_of(lines: list[str], i: int) -> re.Match[str] | None:
    """The marker of the stop on line ``i``: its own line's first, then the nearest of the two lines above."""
    for j in (i, i - 1, i - 2):
        if j >= 0 and (m := MARK.search(lines[j])):
            return m
    return None


def kept_counts(text: str) -> dict[str, int]:
    counts = {n: 0 for n in ("1", "2", "3", "4", "5", "depends")}
    lines = text.splitlines()
    marked = marked_blocks(lines)
    for i, line in enumerate(lines):
        code = line.split("  # ")[0]
        if line.strip().startswith("#") or not STOP.search(code) or "stop_or_warn" in code:
            continue
        if re.match(r"\s*\w+\(\) *\{", line) or code.strip() == 'exit "$_rc"':  # a definition, the helper's own
            continue
        if i in marked:
            counts[marked[i]] += 1
            continue
        m = mark_of(lines, i)
        if m and "not a stop" not in m.group(0):
            counts[m.group(1) or "depends"] += 1  # a "depends (N)" counts as depends
    return counts


#: converted points a PoC run cannot reach, and why (each is still converted: it calls the helper, which stops on
#: PRODUCTION; the PRODUCTION twins cover them)
NOT_DRIVEN = {
    "early-env": "an environment that is none of the four is a box that cannot be told: the helper always stops",
    "wizard-env": "an environment that is none of the four is a box that cannot be told: the helper always stops",
    "environment-value": "an environment that is none of the four is a box that cannot be told: the helper always stops",
    "feed-folder-production": "its condition is TB_ENV=PRODUCTION",
    "tls-production": "its condition is TB_ENV=PRODUCTION",
    "sae-mailbox-production": "its condition is TB_ENV=PRODUCTION",
    "pin-embedder-production": "its condition is TB_ENV=PRODUCTION",
    "cron-production": "its condition is TB_ENV=PRODUCTION",
    "finish-early-no-python3": "its condition is a PRODUCTION environment",
    "finish-gate-no-python3": "its condition is TB_ENV=PRODUCTION",
    "rrs-record-other-card": "the real servers run on a rehearsal box only: the box is one by then",
    "rehearsal-answers-validation": "--rehearsal writes the mark before the settings step: the mark is there",
    "host-baseline-ssh": "root only (deploy/site/hardening.conf as root): the tests run as a user, as CI does",
    "host-baseline": "root only: the tests run as a user, as CI does",
    "systemd-units": "root only (systemd): the tests run as a user, as CI does",
    "install-lock-open": "the deploy folder cannot be made unreadable to root, and the bench may run as root",
    "override-owner": "a file owned by another user cannot be made without root",
    "docker-missing": "the next step that runs Docker is kept refusal 1: test_with_no_docker_a_poc_box_warns_then_stops_at_the_load",
}

# --------------------------------------------------------------------------------------------------- the PoC runs
STANDINS_LINE = "x-trialbox-rehearsal-standins: true"
BAD_SITE = (
    "TB_ENV=TEST\nTB_TLS_HOSTNAME=tb.example.test\nTB_TLS_OLD_CLIENTS=bogus\nTB_SAE_OFFICE_MAILBOX=notamail\n"
    "TB_SOURCE_DIR=/nonexistent/h94-feed\nTB_HOST_PROFILE=bogus\n"
)  # fmt: skip
POC_VALIDATION = "TB_HOST_PROFILE=poc\n"  # a rehearsal's settings: the rehearsal step writes TB_ENV=VALIDATION
REHEARSAL = ("--rehearsal", "--yes")


def _probe(tmp: Path) -> str:
    p = tmp / "tb-engine-probe.json"
    p.write_text("{}\n", encoding="utf-8")
    return str(p)


def _override(tmp: Path, *, standins: bool = False, mode: int = 0o644) -> str:
    tmp.mkdir(parents=True, exist_ok=True)
    f = tmp / "override.yml"
    f.write_text((STANDINS_LINE + "\n" if standins else "") + "services: {}\n", encoding="utf-8")
    f.chmod(mode)
    return str(f)


def _scenarios(tmp: Path) -> list[tuple[str, Box, tuple[str, ...], tuple[str, ...], dict[str, str], set[str]]]:
    """(name, box, arguments, forced, environment, the keys the run lists). Each forces what it can in one run:
    some points exclude each other (the five GPU profiles, the first check of the bench-only options)."""
    rrs = ("--rehearsal", "--rehearsal-real-servers", "--yes")
    t = tmp
    out = []

    def add(name: str, box_kw: dict[str, Any], args: list[str], force: Sequence[str] = (),
            env: dict[str, str] | None = None, keys: Sequence[str] = ()) -> None:  # fmt: skip
        out.append((name, Box(t / name, **box_kw), tuple(args), tuple(force), dict(env or {}), set(keys)))

    add(
        "site-inputs",
        {"env": BAD_SITE},
        [
            "--environment",
            "TEST",
            "--mode",
            "stub",
            "--yes",
            "--ctgov",
            "bogus",
            "--rehearsal-real-servers",
            "--gpu-index",
            "1",
            "--engine-probe",
            "x",
        ],
        [
            "anchor-read",
            "memcaps",
            "pgsize",
            "tls-check",
            "pre-start",
            "project-cleanup-failed",
            "site-keys",
            "db-up",
            "backup-schedule",
            "host-check",
        ],
        {"TB_INSTALL_PULL": "bogus", "TB_COMPOSE_OVERRIDE": _override(t, standins=True)},
        [
            "ctgov-value",
            "rrs-without-rehearsal",
            "gpu-index-without-rehearsal",
            "engine-probe-without-rehearsal",
            "host-profile-value",
            "feed-folder-missing",
            "tls-old-clients-value",
            "sae-mailbox-form",
            "memcaps",
            "pgsize",
            "tls-check",
            "anchor-read",
            "standins",
            "install-pull",
            "pre-start",
            "project-cleanup-failed",
            "site-keys",
            "db-up",
            "backup-schedule",
            "fail",
        ],
    )
    add(
        "no-python-no-flock",
        {"no": ("python3", "flock")},
        ["--environment", "TEST", "--mode", "stub", "--tier", "small", "--yes"],
        ["db-roles", "db-schemas"],
        {"COMPOSE_PROJECT_NAME": "another"},
        ["install-lock-flock", "tier-mode", "tier-python3", "compose-project-name", "db-roles", "db-schemas"],
    )
    add(
        "gpu-unmeasured",
        {},
        ["--environment", "TEST", "--mode", "gpu", "--gpu", "rtxpro6000", "--tier", "large", "--yes"],
        ["tier-record", "serving"],
        {"TB_ACCEPT_UNMEASURED_GPU": "1", "TB_COMPOSE_OVERRIDE": _override(t / "gw", mode=0o664)},
        ["tier-and-gpu", "tier-record", "unmeasured-card", "override-mode", "serving"],
    )
    add(
        "gpu-record-not-this-card",
        {"record": True},
        ["--environment", "DEV", "--mode", "gpu", "--gpu", "rtxpro6000", "--yes"],
        ["serving-record", "anchors-compose"],
        {"TB_COMPOSE_OVERRIDE": str(t / "nowhere.yml")},
        ["serving-record", "anchors-compose", "override-missing"],
    )
    add(
        "gpu-no-record",
        {},
        ["--environment", "DEV", "--mode", "gpu", "--gpu", "rtx5090", "--yes"],
        ["project-cleanup-refused"],
        {},
        ["serving-record-missing", "project-cleanup-refused"],
    )
    for gpu in ("shared-quota", "b200-no-mig", "arm64-dgpu"):
        add(f"gpu-{gpu}", {}, ["--environment", "DEV", "--mode", "gpu", "--gpu", gpu, "--yes"], keys=[f"gpu-{gpu}"])
    add(
        "rehearsal-box-without-the-argument",
        {
            "env": POC_VALIDATION,
            "standins": False,
            "prewritten_env": "TB_ENV=VALIDATION\nTB_REHEARSAL=1\n",
            "mark": True,
            "rrs_record": True,
        },
        ["--environment", "TEST", "--gpu-index", "1", "--mode", "stub", "--yes"],
        [],
        {},
        ["rehearsal-without-argument", "rehearsal-standins", "rrs-box-without-options", "rehearsal-environment"],
    )
    add(
        "rehearsal-real-servers",
        {"env": POC_VALIDATION, "record": True},
        [*rrs, "--gpu", "rtxpro6000", "--gpu-index", "1", "--engine-probe", _probe(t), "--environment", "TEST"],
        ["rrs-caps"],
        {},
        ["rrs-environment", "rrs-caps"],
    )
    probe = _probe(t)
    for key, args in (
        ("rrs-profile-missing", ["--gpu-index", "1", "--engine-probe", probe]),
        ("rrs-profile-unknown", ["--gpu", "rtx4090", "--gpu-index", "1", "--engine-probe", probe]),
        ("rrs-tier", ["--gpu", "rtxpro6000", "--tier", "large", "--gpu-index", "1", "--engine-probe", probe]),
        ("rrs-mode", ["--gpu", "rtxpro6000", "--mode", "stub", "--gpu-index", "1", "--engine-probe", probe]),
        ("rrs-gpu-index", ["--gpu", "rtxpro6000", "--gpu-index", "x", "--engine-probe", probe]),
        ("rrs-engine-probe", ["--gpu", "rtxpro6000", "--gpu-index", "1", "--engine-probe", str(t / "none.json")]),
    ):
        add(key, {"env": POC_VALIDATION, "record": True}, [*rrs, *args], keys=[key])
    add(
        "rrs-python3",
        {"env": POC_VALIDATION, "no": ("python3",)},
        [*rrs, "--gpu", "rtxpro6000", "--gpu-index", "1", "--engine-probe", probe],
        keys=["rrs-python3"],
    )
    add(
        "rehearsal-options",
        {"env": POC_VALIDATION},
        ["--rehearsal", "--gpu-index", "1", "--mode", "stub", "--yes"],
        keys=["rrs-options-without-rrs"],
    )
    # D-1091 (H94-03): the stops that were "depends" and protect none of the five
    add(
        "command-line-and-host",
        {},
        ["--environment", "TEST", "--mode", "bogus", "--tier-check", "--bogus-flag", "--yes"],
        [
            "docker-not-running",
            "compose-missing",
            "host-python-modules",
            "db-start",
            "stack-health",
            "finish-gate",
            "anchor-gate",
        ],
        {},
        [
            "unknown-option",
            "tier-check-without-tier",
            "mode-value",
            "docker-not-running",
            "compose-missing",
            "host-python-modules",
            "db-start",
            "stack-health",
            "finish-gate",
            "anchor-gate",
        ],
    )
    add("gpu-value", {}, ["--environment", "DEV", "--mode", "gpu", "--gpu", "bogus", "--yes"],
        ["finish-gate-did-not-run", "anchor-gate-did-not-run"], {},
        ["gpu-value", "finish-gate-did-not-run", "anchor-gate-did-not-run"])  # fmt: skip
    return out


def _check(name: str, r: Run, keys: set[str]) -> set[str]:
    assert r.rc == 0, f"{name}: rc {r.rc}\n{r.text[-6000:]}"
    assert SIGNED in r.out and RUNNING in r.out, f"{name}\n{r.text[-4000:]}"
    got = {k.removeprefix("install.sh/").split(": ", 1)[0].split(":", 1)[0] for k in r.listed_keys()}
    assert keys <= got, f"{name}: not listed: {sorted(keys - got)}\n{r.err[-4000:]}"
    assert "install: warning (PoC box, H-94): " in r.err
    return got


def test_a_poc_install_goes_through_every_converted_point(tmp_path: Path) -> None:
    """THE ONE TEST (H-94; 7092045961 items 1-2): every converted point of install.sh, forced on a PoC box, warns,
    is listed, and the install goes on through the load and the signed re-run to the end."""
    want = converted_keys(INSTALL.read_text(encoding="utf-8")) - set(NOT_DRIVEN)
    assert set(NOT_DRIVEN) <= converted_keys(INSTALL.read_text(encoding="utf-8"))  # none stale
    seen: set[str] = set()
    first: Box | None = None
    for name, box, args, force, env, keys in _scenarios(tmp_path):
        r = box.install(*args, force=force, env=env)
        seen |= _check(name, r, keys)
        first = first or box
    # a second and a third install on the first box: each list is its own install's, kept through its signed re-run
    # (review L-3 of #1396, ruled 7096812799: a point fixed before the next install is not shown again)
    assert first is not None
    r = first.install("--environment", "DEV", "--mode", "stub", "--yes",
                      force=("project-cleanup-refused", "finish-early"))  # fmt: skip
    seen |= _check("second install", r, {"environment-change", "project-cleanup-refused", "finish-early"})
    r = first.install("--mode", "stub", "--yes", force=("finish-early-did-not-run",))
    seen |= _check("third install", r, {"finish-early-did-not-run"})
    assert not {"install.sh/project-cleanup-refused", "install.sh/finish-early"} & r.listed_keys()
    # the questions on a terminal: no answers file, a ClinicalTrials.gov answer that is neither
    tty = Box(tmp_path / "tty", env="TB_ENV=TEST\n")
    r = tty.install("--environment", "TEST", "--mode", "stub", "--answers", str(tmp_path / "none.yaml"),
                    answers=False, tty="bogus\n\n\ny\n")  # fmt: skip
    seen |= _check("questions", r, {"answers-file", "ctgov-answer"})
    # no answers and no terminal: no settings are written (the services cannot start), the install goes on
    r = Box(tmp_path / "no-settings").install("--environment", "TEST", "--mode", "stub", "--yes", answers=False)
    seen |= _check("no settings", r, {"no-settings"})
    # another installer holds the folder's lock: this run takes nothing of the other's down
    held = Box(tmp_path / "second-installer")
    r = held.install("--environment", "TEST", "--mode", "stub", "--yes", force=("project-cleanup-failed",),
                     hold_lock=True)  # fmt: skip
    seen |= _check("second installer", r, {"second-installer"})
    assert " down " not in (held.tmp / "calls.log").read_text(encoding="utf-8")  # no cleanup was run
    assert want <= seen, f"converted points no PoC run reached: {sorted(want - seen)}"
    # doctor shows each point of the first box's list as one WARN line with its action
    lines = doctor.poc_stops(doctor.DoctorInputs(deploy=first.deploy), [])
    assert lines and all(c.status == "WARN" and c.name == "poc_stop" and "Action: " in c.detail for c in lines)
    keys = Run(0, "", "", first.tmp).listed_keys()
    assert len(lines) == len(keys) and all(any(c.detail.startswith(f"{k} (") for c in lines) for k in keys)


# ------------------------------------------------------------------------------------------ PRODUCTION: unchanged
PLANTED = {  # what a caller could set: none of it makes a PRODUCTION box a PoC box
    "TB_ENV": "VALIDATION", "TB_STOP_ARG_ENV": "VALIDATION", "TB_STOP_REHEARSAL": "1", "TB_REHEARSAL": "1",
    "TB_STOP_DEPLOY": "/nonexistent", "TB_STOP_WHO": "x", "ENVIRONMENT": "DEV", "REHEARSAL": "1",
    "ANCHOR_OK": "0", "ANCHOR_UNSAFE": "1",  # review H-2 of #1396: the script's own
    "TB_STOP_KEEP_LIST": "1",  # the lane H lead: box-install.sh hands it on as an option, never a variable
}  # fmt: skip
PROD_SITE = "TB_ENV=PRODUCTION\nTB_TLS_HOSTNAME=tb.example.test\nTB_SAE_OFFICE_MAILBOX=office@hospa.test\n"


VAR = re.compile(r"\$\{[^}]*\}|\$\([^)]*\)|\$[A-Za-z_][A-Za-z0-9_]*|\$[0-9*@]")


def _as_pattern(raw: str) -> str:
    """Master's words as written (unexpanded) as a pattern of what they print: each variable stands for any text."""
    raw = raw.replace('\\"', '"')
    return ".*?".join(re.escape(part) for part in VAR.split(raw))


def _master(message_start: str, rc: int = 1) -> str:
    hits = [s["message"] for s in MASTER["stops"] if s["message"].startswith(message_start) and s["rc"] == rc]
    assert len(hits) == 1, (message_start, hits)
    return str(hits[0])


PROD_CASES = [
    # (name, the env file the wizard writes, args, forced, extra env, master's message (unexpanded), rc)
    ("ctgov", PROD_SITE, ["--ctgov", "bogus"], (), {}, "--ctgov must be live or offline", 2),
    ("rrs option", PROD_SITE, ["--rehearsal-real-servers"], (), {},
     "--rehearsal-real-servers is for a rehearsal box only", 2),
    ("tls old clients", PROD_SITE + "TB_TLS_OLD_CLIENTS=bogus\n", [], (), {}, "TB_TLS_OLD_CLIENTS must be off or cbc", 1),
    ("memcaps", PROD_SITE, [], ("memcaps",), {}, "the memory caps could not be sized", 1),
    ("tls check", PROD_SITE, [], ("tls-check",), {}, "the TLS settings do not pass", 1),
    ("finish gate (depends)", PROD_SITE, [], ("finish-gate",), {}, "$said (above: the setting", 1),
    ("pre-start", PROD_SITE, [], ("pre-start",), {}, "a start-up step of this release failed", 1),
    ("cleanup", PROD_SITE, [], ("project-cleanup-failed",), {}, "project cleanup failed", 1),
    ("site keys", PROD_SITE, [], ("site-keys",), {}, "the site keys could not be made or read", 1),
    ("gpu profile", PROD_SITE, ["--mode", "gpu", "--gpu", "shared-quota"], (), {}, "this card has MIG on", 1),
    ("unmeasured", PROD_SITE, ["--mode", "gpu", "--gpu", "rtxpro6000"], (), {"TB_ACCEPT_UNMEASURED_GPU": "1"},
     "$1: only on a rehearsal box", 1),
]  # fmt: skip


@pytest.mark.parametrize(("name", "site", "args", "force", "extra", "said", "rc"), PROD_CASES,
                         ids=[c[0] for c in PROD_CASES])  # fmt: skip
def test_on_production_the_same_forced_points_stop_with_master_s_words(
    tmp_path: Path,
    name: str,
    site: str,
    args: list[str],
    force: tuple[str, ...],
    extra: dict[str, str],
    said: str,
    rc: int,
) -> None:
    """A fresh box with no environment given (D-127: PRODUCTION) whose settings say PRODUCTION: each forced point
    stops as on master, the variables a caller could plant changing nothing, and nothing is listed."""
    box = Box(tmp_path / "prod", env=site)
    (tmp_path / "feed").mkdir()
    if "TB_SOURCE_DIR" not in site:
        (tmp_path / "wizard.env").write_text(site + f"TB_SOURCE_DIR={tmp_path / 'feed'}\n", encoding="utf-8")
        box_env = tmp_path / "prod" / "wizard.env"
        box_env.write_text(site + f"TB_SOURCE_DIR={tmp_path / 'feed'}\n", encoding="utf-8")
    master = _master(said, rc)
    args = [*args, *([] if "--mode" in args else ["--mode", "stub"])]
    clean = box.install(*args, "--yes", force=force, env=extra)
    planted_box = Box(tmp_path / "planted", env=(tmp_path / "prod" / "wizard.env").read_text(encoding="utf-8"))
    planted = planted_box.install(*args, "--yes", force=force, env={**extra, **PLANTED})
    last = clean.err.splitlines()[-1]
    assert clean.rc == rc, clean.text[-4000:]
    assert re.fullmatch("install: " + _as_pattern(master), last), (last, master)
    norm = [(r.rc, r.out.replace(str(b), "<box>"), r.err.replace(str(b), "<box>"))
            for r, b in ((clean, tmp_path / "prod"), (planted, tmp_path / "planted"))]  # fmt: skip
    assert norm[0] == norm[1]
    assert "PoC box, H-94" not in clean.err and not (tmp_path / "prod" / "deploy" / "site" / "poc-stops.jsonl").exists()


def test_on_production_every_fail_line_and_exit_1_stay(tmp_path: Path) -> None:
    """To the end on PRODUCTION as a user: the site keys' sealing (root's, kept refusal 4) is left to a box's apply
    step (TB_BOX_DEFER_SEAL=1, master's own knob)."""
    site = PROD_SITE + f"TB_SOURCE_DIR={tmp_path}\n"
    r = Box(tmp_path / "prod", env=site).install("--mode", "stub", "--yes", force=("host-check",),
                                                  env={"TB_BOX_DEFER_SEAL": "1", **PLANTED})  # fmt: skip
    fails = [ln for ln in r.err.splitlines() if ln.startswith("install: FAIL: ")]
    assert r.rc == 1 and RUNNING in r.out, r.text[-4000:]
    assert "install: FAIL: the host check reported FAIL lines (above; docs/SECURITY.md)" in fails
    assert r.err.splitlines()[-len(fails) :] == fails and "PoC box" not in r.err


@pytest.mark.parametrize(("rel", "fixture", "least"), [("deploy/install.sh", "install_sh", 60),
                                                    ("deploy/box-install.sh", "box_install_sh", 8),
                                                    ("tools/apply_update.sh", "apply_update_sh", 5)])  # fmt: skip
def test_every_converted_message_is_master_s(rel: str, fixture: str, least: int) -> None:
    """The words of every converted point, as written in the script, are master's (the fixture of master's stops):
    on PRODUCTION the helper prints exactly them, with master's exit code."""
    text = (ROOT / rel).read_text(encoding="utf-8")
    doc = json.loads((ROOT / "tests" / "fixtures" / "h94" / f"{fixture}_master_stops.json").read_text(encoding="utf-8"))
    master = {(s["message"], s["rc"]) for s in doc["stops"]}
    q = r'"((?:[^"\\]|\\.)*)"'
    found = 0
    for line in text.splitlines():
        if "stop_or_warn" not in line or line.strip().startswith("#") or re.match(r"\s*\w+\(\) *\{", line):
            continue
        if "_rc=" in line or "--silent" in line:
            continue  # the helper's own line; --silent prints nothing on PRODUCTION (the reason is above, as on master)
        if re.search(r'stop_or_warn "\$1"|stop_or_warn "\$key', line):
            continue  # the two helpers' own calls: rrs_drop and rehearsal_only (their words below)
        call = re.search(r"stop_or_warn((?:\s+--rc \d|\s+--silent)*)\s+\S+\s+" + q + r"\s+" + q, line)
        assert call, line
        rc = int(m.group(1)) if (m := re.search(r"--rc (\d)", call.group(1))) else 1
        msg = call.group(3)
        assert (msg, rc) in master, f"not master's words: {msg!r} (rc {rc})"
        found += 1
    for m in re.finditer(r"(?:rrs_drop)\s+[\w-]+\s+" + q, text):  # its words are master's die words
        assert (m.group(1), 1) in master, m.group(1)
        found += 1
    assert found >= least


# ------------------------------------------------------------------------------------------------- what a box is
def _shell_poc(deploy: Path, arg: str, rehearsal: str, env: dict[str, str]) -> bool:
    text = INSTALL.read_text(encoding="utf-8")
    block = text[text.index("# ---- STOP-OR-WARN") : text.index("# ---- end of STOP-OR-WARN")]
    script = (
        f"{block}\nTB_STOP_DEPLOY={str(deploy)!r}; TB_STOP_ARG_ENV={arg!r}; TB_STOP_REHEARSAL={rehearsal!r}\ntb_poc_box"
    )
    r = subprocess.run(["bash", "-c", script], env={"PATH": os.environ["PATH"], **env}, capture_output=True,
                       text=True, check=False)  # fmt: skip
    assert r.returncode in (0, 1), r.stderr
    return r.returncode == 0


STATES = [  # (deploy/.env or None, files, --environment, --rehearsal, PoC?)
    (None, (), "", "0", False),  # a fresh box, nothing given: PRODUCTION (D-127)
    (None, (), "VALIDATION", "0", True),
    (None, (), "test", "0", True),
    (None, (), "", "1", True),  # --rehearsal: VALIDATION
    (None, (), "PRODUCTION", "1", False),
    (None, (), "BOGUS", "0", False),
    (None, ("settings.yaml",), "", "0", False),  # installed, no TB_ENV: PRODUCTION
    (None, ("settings.yaml",), "VALIDATION", "0", False),
    (None, ("updates/installed.json",), "DEV", "0", False),
    (None, ("site/rehearsal.json",), "", "0", True),  # the mark alone, nothing recorded yet: VALIDATION
    (None, ("site/rehearsal.json", "settings.yaml"), "", "0", False),  # the mark on an installed box with no TB_ENV
    ("TB_ENV=PRODUCTION\n", (), "VALIDATION", "1", False),  # the record wins when it is stricter
    ("TB_ENV=PRODUCTION\n", ("site/rehearsal.json",), "", "0", False),
    ("TB_ENV=VALIDATION\n", (), "", "0", True),
    ("TB_ENV='dev'\n", ("settings.yaml",), "", "0", True),
    ("TB_ENV=VALIDATION\n", (), "PRODUCTION", "0", False),
    ("TB_ENV=TEST\nTB_ENV=PRODUCTION\n", (), "", "0", False),  # the last line counts, as everywhere
    ("TB_ENV=SOMETHING\n", (), "TEST", "0", False),  # a value none of the four: cannot be told
    ("TB_ENV=\n", ("settings.yaml",), "TEST", "0", False),
    ("TB_HOST_PROFILE=poc\n", (), "", "0", False),  # a .env that names no environment, nothing given
    ("TB_HOST_PROFILE=poc\n", (), "TEST", "0", True),
]


@pytest.mark.parametrize(("dotenv", "files", "arg", "rehearsal", "poc"), STATES)
def test_the_shell_and_python_rules_agree_and_no_variable_changes_them(
    tmp_path: Path, dotenv: str | None, files: tuple[str, ...], arg: str, rehearsal: str, poc: bool
) -> None:
    d = tmp_path / "deploy"
    d.mkdir()
    if dotenv is not None:
        (d / ".env").write_text(dotenv, encoding="utf-8")
    for f in files:
        (d / f).parent.mkdir(parents=True, exist_ok=True)
        (d / f).write_text("{}\n", encoding="utf-8")
    assert stops.poc_box(d, environment=arg, rehearsal=rehearsal == "1") is poc
    assert _shell_poc(d, arg, rehearsal, {}) is poc
    assert _shell_poc(d, arg, rehearsal, {k: v for k, v in PLANTED.items() if not k.startswith("TB_STOP")}) is poc


def test_a_box_file_that_cannot_be_read_is_production(tmp_path: Path) -> None:
    d = tmp_path / "deploy"
    d.mkdir()
    (d / ".env").symlink_to(tmp_path / "nowhere")  # a dangling link
    assert not stops.poc_box(d, environment="VALIDATION") and not _shell_poc(d, "VALIDATION", "0", {})
    (d / ".env").unlink()
    (d / ".env").mkdir()  # not a file
    assert not stops.poc_box(d, environment="VALIDATION") and not _shell_poc(d, "VALIDATION", "0", {})


def test_install_sets_its_own_rule_inputs_before_any_call() -> None:
    """The helper's inputs are the script's own (from its command line), set once after the arguments are read:
    a caller's TB_STOP_* is overwritten, never read."""
    text = INSTALL.read_text(encoding="utf-8")
    first_call = min(text.index(f"{w} early-env") for w in ("stop_or_warn",))
    setting = text.index('TB_STOP_ARG_ENV="$ENVIRONMENT"; TB_STOP_REHEARSAL="$REHEARSAL"')
    assert setting < first_call
    assert text.index('ENVIRONMENT=""') < text.index("while [ $# -gt 0 ]")


# --------------------------------------------------------------------------------------------------- the one list


def test_the_shell_list_writes_the_same_entries(tmp_path: Path) -> None:
    text = INSTALL.read_text(encoding="utf-8")
    block = text[text.index("# ---- STOP-OR-WARN") : text.index("# ---- end of STOP-OR-WARN")]
    d = tmp_path / "deploy"
    (d / "site").mkdir(parents=True)
    script = (block + f"\nTB_STOP_WHO=install; TB_STOP_FILE=install.sh; TB_STOP_DEPLOY={str(d)!r}; "
              "TB_STOP_ARG_ENV=TEST; TB_STOP_REHEARSAL=0\n"
              'stop_or_warn k1 "a step" "a \\"quoted\\" TB_SERVICE_TOKEN=s3cret at /data/uploads/x.pdf"\n'
              'echo after\n')  # fmt: skip
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
    assert r.returncode == 0 and r.stdout == "after\n", r.stderr
    entries, problems = stops.read(d)
    assert not problems and len(entries) == 1
    e = entries[0]
    assert (e.key, e.skipped, e.by) == ("install.sh/k1", "a step", "install.sh")
    assert e.what == 'a "quoted" TB_SERVICE_TOKEN=<hidden> at <a path under uploads/>'
    (d / stops.LIST).unlink()
    (d / stops.LIST).symlink_to(tmp_path / "elsewhere")
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
    assert r.returncode == 0 and "cannot be written" in r.stderr and not (tmp_path / "elsewhere").exists()


@pytest.mark.parametrize("rel", sorted(RATCHET))
def test_no_bare_stop_on_the_install_path(rel: str) -> None:
    """A new ``die`` / ``exit N`` on the install, start or update path names one of the four (``H-94 (N)``), is
    marked ``H-94 depends`` (ruled on by the integrator), or calls ``stop_or_warn``. A file not yet converted keeps
    its count: it can only go down (when a stop is converted, lower the number here)."""
    path = ROOT / rel
    if not path.exists():
        pytest.fail(f"{rel} is gone: take it out of RATCHET")
    bare = bare_stops(path.read_text(encoding="utf-8"))
    assert len(bare) <= RATCHET[rel], f"{rel}: {len(bare)} bare stops, at most {RATCHET[rel]}: {bare}"


@pytest.mark.parametrize("rel", sorted(PY_RATCHET))
def test_no_bare_exit_in_the_python_guards(rel: str) -> None:
    text = (ROOT / rel).read_text(encoding="utf-8")
    bare = [ln for ln in text.splitlines()
            if re.search(r"\bsys\.exit\(|raise SystemExit|\braise ", ln) and "H-94" not in ln]  # fmt: skip
    assert len(bare) <= PY_RATCHET[rel], bare


def test_the_ratchet_sees_a_new_bare_stop() -> None:
    text = INSTALL.read_text(encoding="utf-8")
    assert bare_stops(text) == []
    assert len(bare_stops(text + '\n[ -f x ] || die "a new guard"\n')) == 1
    assert len(bare_stops(text + "\n[ -f x ] || { echo no >&2; exit 4; }\n")) == 1
    assert bare_stops(text + '\n[ -f x ] || stop_or_warn k "" "a new guard"\n') == []


def test_the_helper_is_the_same_bytes_wherever_it_is() -> None:
    blocks = set()
    for rel in RATCHET:
        text = (ROOT / rel).read_text(encoding="utf-8")
        if "# ---- STOP-OR-WARN" in text:
            blocks.add(text[text.index("# ---- STOP-OR-WARN") : text.index("# ---- end of STOP-OR-WARN")])
    assert len(blocks) == 1


# ------------------------------------------------------------------------------------------ the card's inventory
@pytest.mark.parametrize("rel", ["deploy/install.sh", "deploy/box-install.sh", "tools/apply_update.sh"])
def test_the_page_lists_every_point_of_install_sh(rel: str) -> None:
    """The inventory (the card's page): every converted key of the script is a row, and the kept stops per number
    are as many as the rows that say so."""
    page = PAGE.read_text(encoding="utf-8")
    section = page[page.index(f"### {rel}\n") :]
    section = section[: section.index("\n### ", 4)] if "\n### " in section[4:] else section
    text = (ROOT / rel).read_text(encoding="utf-8")
    for key in converted_keys(text):
        assert f"`{key}`" in section, f"{key} is not in the page's install.sh table"
    for n, count in kept_counts(text).items():
        label = f"| kept ({n}) |" if n != "depends" else "| depends"
        assert section.count(label) == count, (n, section.count(label), count)


def test_the_findings_file_is_in_the_register_s_form() -> None:
    data = json.loads((PAGE.with_suffix("") / "findings.json").read_text(encoding="utf-8"))
    assert data["card"] == "H94" and data["source"] == f"docs/handover/{PAGE.name}"
    rows = data["findings"]
    assert rows and all(r["id"].startswith("H94-") and r["lane"] == "H" for r in rows)
    assert all(r["basis"] in ("shown", "hypothesis", "not_run", "not stated") for r in rows)


def test_with_no_docker_a_poc_box_warns_then_stops_at_the_load(tmp_path: Path) -> None:
    """D-1091: Docker missing protects none of the five, so it warns; the first step that needs the release's image
    is kept refusal 1 (it cannot be shown loaded), so the install stops there, with the warning listed."""
    box = Box(tmp_path / "b", no=("docker",))
    (box.tmp / "bin" / "docker").unlink()
    r = box.install("--environment", "TEST", "--mode", "stub", "--yes")
    assert r.rc == 1 and "install: warning (PoC box, H-94): Docker is not installed" in r.err, r.text[-3000:]
    assert r.err.splitlines()[-1] == "install: the bundle carried no trialbox-py:1.0.0 image"
    assert "install.sh/docker-missing" in r.listed_keys()


# ---------------------------------------------------------------------------------------- deploy/box-install.sh
BOX_INSTALL = ROOT / "deploy" / "box-install.sh"
BOX_NOT_DRIVEN = {
    "python3-missing": "every step of the script runs python3 (the plan, the code, the finish check)",
    "docker-missing": "the bench's image stand-in (TB_BOX_PY) is the script's own way past the Docker check",
}
BOX_PY = r"""#!/bin/sh
F=" ${TB_H94_FORCE:-} "
case "$F" in *" apply "*) [ "$3" = apply ] && { echo "apply: refused (stand-in)"; exit 1; } ;; esac
exit 0
"""
BOX_PYTHON3 = r"""#!/bin/sh
F=" ${TB_H94_FORCE:-} "
has() { case "$F" in *" $1 "*) return 0 ;; esac; return 1; }
if [ "$1 $2 $3" = "-m tools.trialbox finish-check" ]; then
  case " $* " in
    *" --print-anchors "*)
      has finish-did-not-run && exit 2
      has finish-gate && { echo "  - the anchor is a system folder (stand-in)" >&2; exit 1; }
      has anchor-read && echo "$TB_H94_TMP/anchor"
      exit 0 ;;
    *" --mount-anchors "*) has anchor-mount && exit 1; exit 0 ;;
  esac
fi
exec "$TB_H94_REAL_PY" "$@"
"""


def _firstrun(tmp: Path, *args: str, force: tuple[str, ...] = (), environment: str = "VALIDATION",
              env: dict[str, str] | None = None) -> Run:  # fmt: skip
    """box-install.sh --firstrun, the real script, on a box its install made (a rehearsal box, a PoC box, unless
    ``environment`` says PRODUCTION), the owner's answers given: stand-ins for the image (TB_BOX_PY), compose, the
    host check, the read probe and the finish check's verdict; every other python3 call is the real one."""
    box = tmp / "box"
    d = box / "deploy"
    (d / "site" / "box").mkdir(parents=True)
    shutil.copy(BOX_INSTALL, d / "box-install.sh")
    for name in ("libs", "services", "tools"):
        (box / name).symlink_to(ROOT / name)
    (d / "site" / "box" / "answers.json").write_text('{"tls_hostname": "trialbox.local", "tz": "Asia/Tokyo"}\n')
    (d / "site" / "box" / "hardware.json").write_text('{"tpm": true}\n')
    if environment != "PRODUCTION":
        (d / "site" / "rehearsal.json").write_text('{"rehearsal": true}\n')
    (d / ".env").write_text(f"TB_ENV={environment}\n" + ("TB_REHEARSAL=1\n" if environment != "PRODUCTION" else ""))
    fr = tmp / "fr"
    fr.mkdir()
    (fr / "answers.json").write_text('{"tz": "Asia/Tokyo"}\n')
    cron = tmp / "cron"
    cron.mkdir()
    (cron / "trialbox-retention").write_text(
        "20 0 * * * root cd x && { python3 -m tools.trialbox logs daily; python3 -m tools.trialbox audit-sign; }\n"
    )
    (tmp / "anchor").mkdir()
    b = tmp / "bin"
    b.mkdir()
    stubs = {"python3": BOX_PYTHON3, "boxpy": BOX_PY,
             "compose": '#!/bin/sh\ncase " $TB_H94_FORCE " in *" stack-restart "*) exit 1 ;; esac\nexit 0\n',
             "hostcheck": '#!/bin/sh\ncase " $TB_H94_FORCE " in *" host-check "*) echo "FAIL  x"; exit 1 ;; esac\n',
             "probe": '#!/bin/sh\ncase " $TB_H94_FORCE " in *" anchor-read "*) exit 1 ;; esac\nexit 0\n'}  # fmt: skip
    for name, text in stubs.items():
        (b / name).write_text(text, encoding="utf-8")
        (b / name).chmod(0o755)
    full = {k: v for k, v in os.environ.items() if not k.startswith(("TB_", "PYTHON"))}
    full.update(
        PATH=f"{b}:{os.environ['PATH']}", HOME=str(tmp), TB_H94_FORCE=" ".join(force), TB_H94_TMP=str(tmp),
        TB_H94_REAL_PY=sys.executable, TB_BOX_NO_ROOT="1", TB_BOX_PY=str(b / "boxpy"), TB_BOX_COMPOSE=str(b / "compose"),
        TB_BOX_HOST_CHECK=str(b / "hostcheck"), TB_BOX_DOCKER=str(b / "probe"), TB_ISSUE_DIR=str(tmp / "issue.d"),
        TB_FIRSTRUN_HOST_DIR=str(fr), TB_SYSTEMD="0", TB_BOX_WSL2="0", TB_CRON_DIR=str(cron),
    )  # fmt: skip
    full.update(env or {})
    r = subprocess.run(["bash", str(d / "box-install.sh"), "--firstrun", *args], cwd=tmp, env=full,
                       stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=180)  # fmt: skip
    return Run(r.returncode, r.stdout, r.stderr, box)


def test_a_poc_box_s_first_run_goes_through_every_converted_point_of_box_install(tmp_path: Path) -> None:
    """THE ONE TEST for deploy/box-install.sh (H-94, D-1091): its real first run on a rehearsal box, every converted
    point forced, each warned and listed, the run ending "ready" with exit 0; a warned finish check takes the signed
    head out of the nightly cron (the folder is never written into)."""
    want = converted_keys(BOX_INSTALL.read_text(encoding="utf-8")) - set(BOX_NOT_DRIVEN)
    assert set(BOX_NOT_DRIVEN) <= converted_keys(BOX_INSTALL.read_text(encoding="utf-8"))
    seen: set[str] = set()
    runs = [
        (("--bogus", "--answers"), ("apply", "finish-gate", "stack-restart", "host-check"), {"TB_BOX_WSL2": "x"},
         {"unknown-option", "answers-value", "wsl2-value", "apply", "finish-gate", "stack-restart", "host-check"}),
        ((), ("finish-did-not-run",), {}, {"finish-did-not-run"}),
        ((), ("anchor-read",), {}, {"anchor-read"}),
        ((), ("anchor-mount",), {}, {"anchor-mount"}),
    ]  # fmt: skip
    for i, (args, force, env, keys) in enumerate(runs):
        r = _firstrun(tmp_path / str(i), *args, force=force, env=env)
        assert r.rc == 0 and "TrialBox is ready" in r.out, r.text[-4000:]
        got = {k.removeprefix("box-install.sh/") for k in r.listed_keys()}
        assert keys <= got, (keys - got, r.err[-3000:])
        assert "box-install: warning (PoC box, H-94): " in r.err
        cron = (tmp_path / str(i) / "cron" / "trialbox-retention").read_text(encoding="utf-8")
        assert ("audit-sign" in cron) is not bool({"finish-gate", "finish-did-not-run"} & set(force))
        seen |= got
    assert want <= seen, sorted(want - seen)


@pytest.mark.parametrize(
    ("force", "env", "said", "rc"),
    [
        ((), {"TB_BOX_WSL2": "x"}, "box-install: TB_BOX_WSL2 is 0 or 1, not 'x'", 1),
        (("apply",), {}, "box-install: the owner's answers could not be applied (above)", 1),
        (("stack-restart",), {}, "box-install: the stack did not restart on the new settings", 1),
        (("finish-gate",), {}, "box-install: the set-up is not finished (above).", 1),
    ],
)  # fmt: skip
def test_on_production_box_install_stops_as_before(
    tmp_path: Path, force: tuple[str, ...], env: dict[str, str], said: str, rc: int
) -> None:
    r = _firstrun(tmp_path, force=force, environment="PRODUCTION", env={**env, **PLANTED})
    assert r.rc == rc and r.err.splitlines()[-1].startswith(said), r.text[-3000:]
    assert "PoC box" not in r.err and not r.listed_keys()


def test_on_production_the_host_check_s_code_stays_the_exit_code(tmp_path: Path) -> None:
    r = _firstrun(tmp_path, force=("host-check",), environment="PRODUCTION")
    assert r.rc == 1 and "TrialBox is ready" in r.out and "PoC box" not in r.err


# ---------------------------------------------------------------------------------------- tools/apply_update.sh
APPLY_UPDATE = ROOT / "tools" / "apply_update.sh"
APPLY_NOT_DRIVEN = {"no-backup-production": "its condition is a box that is not DEV, TEST or VALIDATION"}
AU_DOCKER = '#!/bin/sh\necho \'{"bundle_id": "b1", "stand_in": true}\'\n'
AU_PYTHON3 = r"""#!/bin/sh
case "$1 $2 $3" in "-m tools.trialbox update") echo "update: applied (stand-in)"; exit 0 ;; esac
case "$1 $2" in "-c import") exit 1 ;; esac
exec "$TB_H94_REAL_PY" "$@"
"""


def _apply_update(tmp: Path, *args: str, environment: str = "TEST", guard_rc: int = 0) -> Run:
    """tools/apply_update.sh, the real script, on a box that records ``environment``: the verifier in its container
    (a stand-in that passes: the signature is not what is tested here), the settings guard and the update path
    stand-ins."""
    box = tmp / "box"
    (box / "tools").mkdir(parents=True)
    (box / "deploy" / "keys").mkdir(parents=True)
    shutil.copy(APPLY_UPDATE, box / "tools" / "apply_update.sh")
    (box / "deploy" / "keys" / "vendor_ed25519.pub").write_text("stand-in key\n")
    (box / "deploy" / ".env").write_text(f"TB_ENV={environment}\n")
    (box / "deploy" / "settings_guard.sh").write_text(f"#!/bin/sh\nexit {guard_rc}\n")
    (tmp / "b.tar").write_bytes(b"stand-in bundle\n")
    b = tmp / "bin"
    b.mkdir()
    for name, text in (("docker", AU_DOCKER), ("python3", AU_PYTHON3)):
        (b / name).write_text(text, encoding="utf-8")
        (b / name).chmod(0o755)
    full = {k: v for k, v in os.environ.items() if not k.startswith(("TB_", "PYTHON"))}
    full.update(PATH=f"{b}:{os.environ['PATH']}", TB_VERIFY_IN_DOCKER="1", TB_H94_REAL_PY=sys.executable,
                TB_SECRETS_HOST_DIR=str(tmp / "no-secrets"), TMPDIR=str(tmp))  # fmt: skip
    r = subprocess.run(["sh", str(box / "tools" / "apply_update.sh"), str(tmp / "b.tar"), *args], cwd=tmp, env=full,
                       capture_output=True, text=True, check=False, timeout=120)  # fmt: skip
    return Run(r.returncode, r.stdout, r.stderr, box)


def test_a_poc_box_s_update_goes_through_every_converted_point_of_apply_update(tmp_path: Path) -> None:
    """THE ONE TEST for tools/apply_update.sh (H-94, D-1091): on a TEST box every converted point, forced, warns, is
    listed, and the update goes on to the update path."""
    r = _apply_update(tmp_path, "--conf", "x.conf", "--bogus", "--no-backup-reason", "why", guard_rc=1)
    assert r.rc == 0 and "update: applied (stand-in)" in r.out, r.text[-3000:]
    got = {k.removeprefix("apply_update.sh/") for k in r.listed_keys()}
    want = converted_keys(APPLY_UPDATE.read_text(encoding="utf-8")) - set(APPLY_NOT_DRIVEN)
    assert want <= got, (want - got, r.err)
    assert set(APPLY_NOT_DRIVEN) <= converted_keys(APPLY_UPDATE.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("args", "guard_rc", "said", "rc"),
    [
        (("--conf", "x.conf"), 0, "apply_update: --conf is for ospatch", 2),
        (("--bogus",), 0, "apply_update: unknown option --bogus", 2),
        (("--no-backup-reason", "why"), 0, "apply_update: --no-backup-reason goes with --no-backup", 2),
        (("--no-backup",), 0, "update REFUSED: --no-backup on a PRODUCTION box needs --no-backup-reason REASON", 2),
        ((), 1, "update REFUSED: nothing was changed", 1),
    ],
)  # fmt: skip
def test_on_production_apply_update_stops_as_before(
    tmp_path: Path, args: tuple[str, ...], guard_rc: int, said: str, rc: int
) -> None:
    r = _apply_update(tmp_path, *args, environment="PRODUCTION", guard_rc=guard_rc)
    assert r.rc == rc and r.err.splitlines()[-1].startswith(said), r.text[-2000:]
    assert "PoC box" not in r.err and not r.listed_keys()
