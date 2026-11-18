"""The box run's driver helper (deploy/gcp/box-run.sh): the estimate, the run's metadata, and the results reader.

The box run is lane G's main paid line (R2 and plan v7 §7.1 G-2, G-6, G-9, G-10): the signed bundle built on the
runner VM with the vendor key from Secret Manager, then the shipped box installed from it on the GPU VM by the real
installer, and every test run on that installed box (deploy/gcp/box-install-run.sh does the work on the VM).

    python -m tools.box_run estimate --steps build,start,g6,g9,g10,acc [--mode M] [--only SETS] [--json]
    python -m tools.box_run settings                       # the declared settings, as shell lines
    python -m tools.box_run metadata --steps ... --out DIR [--mode M] [--only SETS] [--set key=value ...]
    python -m tools.box_run acc-tools --out FILE.tgz       # lane G's accuracy tools at HEAD, for the VM
    python -m tools.box_run results RESULTS.tgz|DIR [--out DIR]   # summary.json and report.md: checks per test,
                                                                 # and what every result names (provenance)
    python -m tools.box_run acc-score DIR                  # each accuracy set's answers against its gold, here
    python -m tools.box_run resume-plan DIR [--deadline V] [--redo STEPS]   # free: what a --resume would take up
    python -m tools.box_run acc-ids [--only SETS] [--rs-tag T] [--protocols "set:RS1,RS2 ..."]   # free: the
                                                                 # ruleset ids a filter matches, refused if none
    python -m tools.box_run src-bundle --commit SHA --out FILE   # the release commit's git bundle, proved
    python -m tools.box_run src-bundle --commit SHA --check FILE # a bundle made by hand, proved
    python -m tools.box_run preflight --steps S [--mode M] [--only SETS] [--src-bundle FILE] [--set k=v ...]
                                                                 # free: every check of a launch (box-run.sh
                                                                 # --preflight runs it with the launch's options)
    python -m tools.box_run session-check --env DEV|VALIDATION  # free (D-1132): would a box in that environment
                                                                 # route the session's calls to its own served pair
                                                                 # and nothing else, and let no text out (D-1131)?

Modes (``--mode``): ``production`` (the default) builds with the vendor key from Secret Manager and starts the box
the box's way (box-install.sh and the first-run wizard: a PRODUCTION box). ``validation`` (the owner's ruling of
2026-11-15, a proof of concept) builds the same bundle from the same commit but signs it with a THROWAWAY key made
on the runner VM (never the vendor key: the bundle is not a release, and every result says so), places that key's
public half on the box, and installs with deploy/install.sh and a synthetic site's answers that make the box
``TB_ENV=VALIDATION`` (``env_extra``): newest prompts served, D2 ceiling, champions only (see
``first-accuracy-run`` notes and the defects the runbook lists).

The ``acc`` group (the public accuracy run on the installed box, Run A of public-accuracy-run-plan.md by default;
``--only`` takes some of its sets, ``name`` or ``name:size``) is costed from the plan's own derivation
(:mod:`tools.public_accuracy.plan`), low and high, with its sources.

The estimate says where each figure comes from: ``measured`` (a run named), ``constant`` (a driver constant with its
reason), ``plan`` (a plan's own estimate) or ``unknown`` (nothing measured: the cap bounds it). It never invents a
figure: a step with no source is ``unknown`` and the US$ is given at the cap.

The ``session`` group (D-1123, the owner's live session; D-1130 to D-1133) composes with ``dev`` only: the commit's
images and the direct route, the public sets tcga and jmed and the synthetic hospital loaded as the acc group loads
them, the session's environment, the box's own egress rules, the owner's accounts, then the session itself. Its cap
is the bring-up's high bound plus the session's hours, rounded up (4 h for three hours), the whole launch's cap.
Nothing from a session is evidence: no score is run, its results go in no evidence page (D-515).

Settings (tb_common.config.DECLARED): ``TB_VENDOR_KEY_SM_NAME`` the Secret Manager secret that holds the vendor
signing key, by name (the value is never read here; the VM reads it with its own service account),
``TB_BUNDLE_SIGNER_SA`` the dedicated service account the build VM runs as (the only reader of that secret),
``TB_PROVISIONING`` (SPOT or STANDARD; the box run defaults to SPOT: its steps resume after a pre-emption).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

# Prices and the VM start: the complete run's constants (one source for every lane G estimate)
from tools.complete_run import BOOT_HOURS, HOSPITAL_MEASURED, ON_DEMAND_PRICE_PER_HOUR, PRICE_PER_HOUR  # noqa: E402

CI_RUN = "CI run 43602503189 (train/16, GitHub 4-core runner, 2026-11-14)"
FIT = "docs/plan/measurements/gpu-run-2026-11-08/fit.json"
CANARY = "docs/plan/measurements/gpu-run-2026-11-08 canary-judge-nvfp4pair.json"
_H50K = next(r for r in HOSPITAL_MEASURED if r["patients"] == 50000 and r["n"] == 16)
SCREEN_50K_S = round(_H50K["screen_calls"] / _H50K["screen_cps"], 1)

# The caps (OD-10: settings with a reason). The cloud's max-run-duration of a launch is the sum of its groups' caps.
GROUP_CAP_HOURS = {
    "build": 2,  # r2-bundle-plan.md: the measured 0.66 h plus the unmeasured image export, sign and upload
    "start": 4,  # box-install-run.sh tb-max-minutes default: twice plan 32's 2.0 h box install ("est.")
    "g6": 7,  # plan 32 G-20's 5.0 h "est." x 1.3 rounded up (the complete run's cap rule)
    "g9": 2,  # two 50k screens (measured 725 s each, thin profile) + four interruptions of at most 20 min each
    "g10": 2,  # an update and a canary and a qualification: none measured
    "dev": 3,  # the commit's images built (b01-b03 measured: 0.11 h) + the stack, G-1, canary, qualify (unmeasured)
    "probe": 1,  # the VM's facts only (00-facts): a boot and a few reads; the hour is the cloud's smallest sure cap
    # D-1123 section 4: the bring-up plus the owner's three hours, rounded up; a session launch's cap is this alone
    # (launch_cap_hours: dev's own cap is not added, its bring-up is the session's)
    "session": 4,
}
GROUPS = ("build", "start", "g6", "g9", "g10", "acc", "probe", "dev", "session")
# The session (D-1123, D-1132): the public sets the integrator named (answer 6: both tcga and jmed, and the synthetic
# hospital), at Run A's sizes; the steps a session leaves out (it walks, it measures nothing: qualify and what follows
# from it are not run, each said in its part as tb-skip does); the bring-up's high bound (D-1123 section 5, "Bring-up
# before the owner can click": 0.61 to 0.98 h from the hand-over's measured rows)
SESSION_SETS = "jmed,tcga"
SESSION_SKIP = "08-qualify 09-promote-judge 10-promote-verifier 11-resolve 12-doctor"
SESSION_BRINGUP_HOURS = (0.61, 0.98)
SESSION_HOURS_DEFAULT = 3
MODES = ("production", "validation")
# The acc group's cap: the plan's high bound of the sets chosen x 1.3 (the complete run's cap rule), whole hours
ACC_CAP_FACTOR = 1.3
# and never above what PoC-1's budget leaves for it (the lead's ruling of 2026-11-15: 24 h, US$65.76 spot)
ACC_CAP_MAX_HOURS = 24
# The paths of lane G's accuracy tools the VM needs (acc-tools): the package, the two tools it imports, and the
# committed TrialGPT criterion labels SIGIR's reader joins (eval/criterion_ml, public domain notice)
ACC_TOOL_PATHS = (
    "tools/__init__.py",
    "tools/public_accuracy",
    "tools/public_site.py",
    "tools/fetch_pinned.py",
    "eval/criterion_ml",
)


# D7 (P1b review): a set whose time is its compiles (many protocols, one after another: the run had 1 in flight and
# the card at 22 % on average) runs this many protocols at once unless --acc-streams says otherwise; the
# orchestrator runs 4 jobs side by side (TB_WORKERS) and keeps one for the ingest. A set of a few protocols (jmed,
# tcga) is bound by its SCREENs and is left at one. The VM script holds the same list (acc_streams_default).
COMPILE_BOUND_STREAMS = 3
COMPILE_BOUND_MIN_PROTOCOLS = 50


# the parts of a set's score that acc-score's summary carries; protocols, pathology and unjudged_exclusions come
# from H-3's scorer (#934) and are taken only when the score has them; ``ladder`` (card 10A-3) the same way
SCORE_SUMMARY_KEYS = ("pairs", "criteria", "compile_pairs", "chia", "compiled", "written_lines", "protocols",
                      "pathology", "unjudged_exclusions", "answer_key", "ladder")  # fmt: skip


def compile_bound(name: str) -> bool:
    """Whether a Run A set is compile-bound (:data:`COMPILE_BOUND_STREAMS` in flight by default)."""
    from tools.public_accuracy import plan

    return plan.acc_set(name).protocols >= COMPILE_BOUND_MIN_PROTOCOLS


def acc_sets(only: str = "") -> list[tuple[str, int]]:
    """The accuracy sets of a run: Run A in its order, or ``only`` (``name`` or ``name:size``, comma-separated) in
    the order given. Sizes default to Run A's."""
    from tools.public_accuracy import plan

    if not only.strip():
        return [(a.name, a.size) for a in plan.RUN_A]
    want: dict[str, int] = {}
    for item in only.replace(" ", ",").split(","):
        if not item:
            continue
        name, _, size = item.partition(":")
        a = plan.acc_set(name)
        try:
            want[name] = int(size) if size else a.size
        except ValueError as exc:
            raise ValueError(f"--only {item}: the size is a number of pairs, trials or items") from exc
        if want[name] < 1:
            raise ValueError(f"--only {item}: a size of at least 1")
    return list(want.items())  # in the order given: a run goes cheapest first (a stop then loses the least)


def acc_cap_hours(sets: list[tuple[str, int]]) -> int:
    """The acc group's cap: the high bound of its sets (scaled to the chosen sizes) x ACC_CAP_FACTOR, whole hours."""
    import math

    from tools.public_accuracy import plan

    high = 0.0
    for name, size in sets:
        a = plan.acc_set(name)
        high += plan.acc_hours(a)["hours_high"] * size / a.size
    return max(1, min(ACC_CAP_MAX_HOURS, math.ceil(high * ACC_CAP_FACTOR)))


def group_cap(group: str, sets: list[tuple[str, int]] | None = None) -> int:
    return acc_cap_hours(sets if sets is not None else acc_sets()) if group == "acc" else GROUP_CAP_HOURS[group]


def launch_cap_hours(
    groups: list[str], sets: list[tuple[str, int]] | None = None, session_hours: int = SESSION_HOURS_DEFAULT
) -> int:
    """The cloud's cap of one launch: the sum of its groups' caps; a session launch's is the bring-up's high bound
    plus the session's hours, rounded up (D-1123 section 4: 4 h for the owner's three), dev's cap not added."""
    import math

    if "session" in groups:
        return math.ceil(SESSION_BRINGUP_HOURS[1] + session_hours)
    return sum(group_cap(g, sets) for g in groups)


def row(
    group: str, what: str, seconds: float | None, kind: str, source: str, high: float | None = None
) -> dict[str, Any]:
    """One estimate row; ``seconds`` is the low bound and ``seconds_high`` the high one (the same when one figure)."""
    return {
        "group": group,
        "step": what,
        "seconds": seconds,
        "seconds_high": seconds if high is None else high,
        "kind": kind,
        "source": source,
    }


def acc_rows(sets: list[tuple[str, int]]) -> list[dict[str, Any]]:
    """The acc group's rows: one per set, low and high from the plan's derivation, scaled to the chosen size."""
    from tools.complete_run import SINGLE_CALL_CPS
    from tools.public_accuracy import plan

    rates = (
        f"rates: compile one call at a time {SINGLE_CALL_CPS}/s, screen {plan.SCREEN_CPS_16}/s at 16 in flight (lane "
        "G's serving of 2026-11-13, superseded: an order of magnitude); box "
        f"{plan.BOX_S_PER_PROTOCOL_DRYRUN} s a protocol (in-process dry run)"
    )
    out = [
        row("acc", "tools, site settings, routes probe, fetch, build, one ingest", None, "unknown", "-"),
    ]
    for name, size in sets:
        a = plan.acc_set(name)
        h = plan.acc_hours(a)
        k = size / a.size
        out.append(
            row(
                "acc",
                f"{name}: {a.title}" + ("" if size == a.size else f", at {size} of {a.size}"),
                round(h["hours_low"] * 3600 * k, 1),
                "plan",
                f"{plan.RUN_A_SOURCE}; {rates}",
                high=round(h["hours_high"] * 3600 * k, 1),
            )
        )
    return out


def session_rows(hours: int = SESSION_HOURS_DEFAULT) -> list[dict[str, Any]]:
    """The session's own rows (D-1123 section 5), after dev's bring-up rows: each from the hand-over's measurements,
    and the owner's hours at the driver's constant."""
    g, ho = "session", "docs/handover/gpu-vm-handover-2026-11-16.md"
    return [
        row(g, "07g the canary through the box's own gate", 0.07 * 3600, "measured", f"{ho} 4.6: 3 to 4 min"),
        row(
            g,
            "53-54 tcga and jmed built and ingested",
            0.03 * 3600,
            "measured",
            f"{ho} 4.8: 0.03 h for jmed; 0.40 h for every set (the high bound)",
            0.40 * 3600,
        ),
        row(
            g,
            "the synthetic hospital, the environment, the egress rules, the accounts",
            None,
            "unknown",
            "not measured: bounded by the cap",
        ),
        row(
            g,
            f"the owner's session ({hours} h)",
            hours * 3600.0,
            "constant",
            "D-1123 section 1: at most three hours of the owner's time (--session-hours)",
        ),
    ]


def rows_for(
    group: str,
    with_g6: bool,
    mode: str = "production",
    sets: list[tuple[str, int]] | None = None,
    session_hours: int = SESSION_HOURS_DEFAULT,
) -> list[dict[str, Any]]:
    """The estimate's rows of one group of steps, each with its source."""
    boot = row(
        group,
        "VM start",
        BOOT_HOURS * 3600,
        "constant",
        "tools/complete_run.py BOOT_HOURS (VM start, both models resident; an upper bound for the build)",
    )
    if group == "build":
        return [
            boot,
            row(group, "b01 source (git bundle from the bucket, clone)", None, "unknown", "-"),
            row(group, "b02+b03 make venv scanners, make images", 334.0, "measured", CI_RUN + ": 5 min 34 s"),
            row(
                group,
                "b04 make trivy-db, make release-gates",
                53.0 + 1070.0,
                "measured",
                CI_RUN + ": 53 s + 17 min 50 s (it failed at the end on the vLLM CVE: the waiver, P1)",
            ),
            row(group, "b05 make_bundle.sh (docker save of ~12 GB, sign, release check)", None, "unknown", "-"),
            row(group, "b06 verify_update.py, release record", None, "unknown", "-"),
            row(group, "b07 upload ~12 GB to the bucket", None, "unknown", "-"),
        ]
    if group == "acc":
        return acc_rows(sets if sets is not None else acc_sets())
    if group == "dev":
        return [
            boot,
            row(
                group,
                "b01-b03 clone, venv, images (this VM, 2026-11-15)",
                17.0 + 21.0 + 160.0,
                "measured",
                "box-20261115T091037Z-ac36aa21f parts b01-b03",
            ),
            row(
                group,
                "02 the stack up by the direct route (this VM, 2026-11-15)",
                281.0,
                "measured",
                "box-20261115T094747Z-4c7c47017 part 02-install (direct)",
            ),
            row(group, "03-07 env, pins, serving record, G-1, canary", 260.0, "measured", "the same run, parts 03-07"),
            row(group, "08 trialbox eval qualify --box (full)", None, "unknown", "never finished on real weights"),
        ]
    if group == "session":
        return session_rows(session_hours)
    if group == "probe":
        return [boot, row(group, "00-facts: disk, image store, python3, TPM, GPU, model folders, a read rate", None,
                          "unknown", "-")]  # fmt: skip
    if group == "start":
        install = (
            "02 installer (install.sh --answers: a VALIDATION box, images loaded, stack up)"
            if mode == "validation"
            else "02 installer (prepare: images loaded, stack up)"
        )
        wizard = (
            "03 the box says VALIDATION (deploy/.env)"
            if mode == "validation"
            else "03 first run (wizard, apply, restart)"
        )
        return [
            boot,
            row(group, "01 fetch the bundle, sha256, manifest", None, "unknown", "-"),
            row(group, install, None, "unknown", "-"),
            row(
                group,
                "  of which the model servers ready",
                117.0 + 82.0,
                "measured",
                FIT + ": judge 117 s + verifier 82 s",
            ),
            row(group, wizard, None, "unknown", "-"),
            row(group, "04-06 pin, serving record, G-1 identity", None, "unknown", "-"),
            row(group, "07 pair canary", 123.8, "measured", CANARY + ": 54 cases, judge 123.8 s"),
            row(group, "08 trialbox eval qualify (full)", None, "unknown", "never run on real weights"),
            row(group, "09-12 promote, resolve, doctor", None, "unknown", "-"),
        ]
    if group == "g6":
        return [
            row(
                group,
                "the 50,000 dense night: feed, ingest, rebuild, screen, backup",
                5.0 * 3600,
                "plan",
                "docs/plan/32-gcp-test-plan.md G-20: 5.0 h est. (screening 2.4 h measured; rebuild 805 s)",
            )
        ]
    if group == "g9":
        out = []
        if not with_g6:
            out.append(
                row(
                    group,
                    "baseline screen, 50,000, 16 in flight",
                    SCREEN_50K_S,
                    "measured",
                    f"tools/complete_run.py HOSPITAL_MEASURED {_H50K['run']}: main SCREEN "
                    f"{_H50K['screen_calls']} calls / {_H50K['screen_cps']} per s (thin profile; dense unknown)",
                )
            )
        out += [
            row(
                group, "the disturbed screen", SCREEN_50K_S, "measured", "as the baseline (thin profile; dense unknown)"
            ),
            row(group, "two restarts back to healthy", None, "unknown", "bounded: tb-healthy-minutes 20 each"),
            row(
                group,
                "the judge's outage (tb-outage-seconds) and its reload",
                120.0 + 117.0,
                "measured",
                "the setting 120 s + the judge's load " + FIT,
            ),
            row(group, "the power cycle (stop, start, models resident)", BOOT_HOURS * 3600, "constant", "BOOT_HOURS"),
        ]
        return out
    return [
        row(group, "g10 update bundle through apply_update.sh", None, "unknown", "-"),
        row(group, "g10 canary", 123.8, "measured", CANARY),
        row(group, "g10 qualify", None, "unknown", "-"),
    ]


def estimate(
    groups: list[str], mode: str = "production", only: str = "", session_hours: int = SESSION_HOURS_DEFAULT
) -> dict[str, Any]:
    """Per launch: the known seconds (with sources; low and high where a row has both), the cap, US$ spot and on
    demand at the known part and at the cap. ``build`` is its own launch (another service account, or the throwaway
    key in validation mode); start, g6, g9, g10 and acc are one launch."""
    bad = [g for g in groups if g not in GROUPS]
    if bad:
        raise ValueError(f"unknown step groups {bad}: one or more of {', '.join(GROUPS)}")
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}: one of {', '.join(MODES)}")
    sets = acc_sets(only or (SESSION_SETS if "session" in groups else ""))
    launches = [["build"]] if "build" in groups else []
    box = [g for g in GROUPS[1:] if g in groups]
    if box:
        launches.append(box)
    out: list[dict[str, Any]] = []
    for gs in launches:
        rows = [r for g in gs for r in rows_for(g, "g6" in gs, mode, sets, session_hours)]
        if gs != ["build"]:  # one VM start for the launch
            rows = [r for i, r in enumerate(rows) if r["step"] != "VM start" or i == 0]
        if "session" in gs:  # a session runs no qualification (SESSION_SKIP)
            rows = [r for r in rows if not r["step"].startswith("08 ")]
        known = sum(r["seconds"] or 0 for r in rows) / 3600
        known_high = sum(r["seconds_high"] or 0 for r in rows) / 3600
        cap = launch_cap_hours(gs, sets, session_hours)
        out.append(
            {
                "groups": gs,
                "rows": rows,
                "known_hours": round(known, 2),
                "known_hours_high": round(known_high, 2),
                "unknown_steps": [r["step"] for r in rows if r["seconds"] is None],
                "cap_hours": cap,
                "usd_known_spot": round(known * PRICE_PER_HOUR, 2),
                "usd_known_high_spot": round(known_high * PRICE_PER_HOUR, 2),
                "usd_cap_spot": round(cap * PRICE_PER_HOUR, 2),
                "usd_cap_on_demand": round(cap * ON_DEMAND_PRICE_PER_HOUR, 2),
            }
        )
    total = {
        "cap_hours": sum(x["cap_hours"] for x in out),
        "usd_cap_spot": round(sum(x["usd_cap_spot"] for x in out), 2),
        "usd_cap_on_demand": round(sum(x["usd_cap_on_demand"] for x in out), 2),
    }
    return {
        "mode": mode,
        "acc_sets": [{"set": n, "size": z} for n, z in sets] if ("acc" in groups or "session" in groups) else [],
        "price_per_hour_spot": PRICE_PER_HOUR,
        "price_per_hour_on_demand": ON_DEMAND_PRICE_PER_HOUR,
        "launches": out,
        "total": total,
    }


def render_estimate(e: dict[str, Any]) -> str:
    lines = [
        f"Prices: g4-standard-48 + RTX PRO 6000, spot US${e['price_per_hour_spot']}/h, on demand "
        f"US${e['price_per_hour_on_demand']}/h (tools/complete_run.py). Mode: {e.get('mode', 'production')}."
    ]
    for x in e["launches"]:
        lines += ["", f"Launch: {' + '.join(x['groups'])}", f"  {'step':58} {'seconds':>15}  source"]
        for r in x["rows"]:
            if r["seconds"] is None:
                s = "unknown"
            elif r["seconds_high"] != r["seconds"]:
                s = f"{r['seconds']:.0f}-{r['seconds_high']:.0f}"
            else:
                s = f"{r['seconds']:.0f}"
            lines.append(f"  {r['step'][:58]:58} {s:>15}  {r['kind']}: {r['source']}")
        span = (
            f"{x['known_hours']} h"
            if x["known_hours_high"] == x["known_hours"]
            else f"{x['known_hours']} to {x['known_hours_high']} h"
        )
        usd = (
            f"US${x['usd_known_spot']}"
            if x["known_hours_high"] == x["known_hours"]
            else f"US${x['usd_known_spot']} to US${x['usd_known_high_spot']}"
        )
        lines.append(
            f"  known part {span} ({usd} spot); {len(x['unknown_steps'])} step(s) "
            f"unmeasured, bounded by the cap: {x['cap_hours']} h = US${x['usd_cap_spot']} spot / "
            f"US${x['usd_cap_on_demand']} on demand"
        )
    for x in e["launches"]:
        if "session" in x["groups"]:
            lo, hi = SESSION_BRINGUP_HOURS
            lines += [
                "",
                f"Session (D-1123 section 5): bring-up {lo} to {hi} h before the owner can click, then the session; "
                f"worst case the cap {x['cap_hours']} h = US${x['usd_cap_spot']} spot (on demand "
                f"US${x['usd_cap_on_demand']}); spot can be pre-empted (GPU hand-over T13). Nothing from it is "
                "evidence.",
            ]
    t = e["total"]
    lines += [
        "",
        f"In all at the caps: {t['cap_hours']} h = US${t['usd_cap_spot']} spot / US${t['usd_cap_on_demand']} on demand",
    ]
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------------------------------------ settings, metadata
def settings() -> dict[str, str]:
    prov = (os.environ.get("TB_PROVISIONING") or "SPOT").strip().upper()
    if prov not in ("SPOT", "STANDARD"):
        raise ValueError(f"TB_PROVISIONING must be SPOT or STANDARD, not {prov!r}")
    return {
        "KEY_SECRET": (os.environ.get("TB_VENDOR_KEY_SM_NAME") or "tb-vendor-signing-key").strip(),
        "SIGNER_SA": (os.environ.get("TB_BUNDLE_SIGNER_SA") or "tb-bundle-signer").strip(),
        "PROVISIONING": prov,
    }


def metadata(
    groups: list[str], values: dict[str, str], out: Path, mode: str = "production", only: str = ""
) -> list[str]:
    """One file per metadata key (gcloud --metadata-from-file: a value may hold commas and spaces). Refuses a value
    that looks like a key: the metadata holds names and versions, never a secret. In validation mode the build needs
    no vendor key (a throwaway one is made on the VM) and the start takes that key's public half."""
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}: one of {', '.join(MODES)}")
    must = {
        "build": (
            "tb-src",
            "tb-commit",
            "tb-release-id",
            "tb-release-seq",
            "tb-vendor-key-version",
            "tb-vendor-pub",
            "tb-out",
        ),
        "start": ("tb-bundle", "tb-bundle-sha256", "tb-vendor-pub", "tb-answers-secret", "tb-answers-version"),
        "g6": ("tb-study",),
        "g9": ("tb-study",),
        "g10": ("tb-g10-vllm-image",),
        "acc": ("tb-acc-tools",),
        "probe": (),
        "dev": ("tb-src", "tb-commit"),
        "session": ("tb-acc-tools", "tb-session-handoff", "tb-session-env", "tb-session-people", "tb-session-minutes"),
    }
    if mode == "validation":  # no vendor key; the synthetic site's answers ride as tb-site-answers (box-run.sh)
        must["build"] = ("tb-src", "tb-commit", "tb-release-id", "tb-release-seq", "tb-out")
        must["start"] = ("tb-bundle", "tb-bundle-sha256", "tb-vendor-pub")
    missing = sorted({k for g in groups for k in must[g] if not values.get(k)})
    if missing:
        raise ValueError(f"missing for {','.join(groups)}: {', '.join(missing)}")
    for k, v in values.items():
        if "PRIVATE KEY" in v or "BEGIN " in v:
            raise ValueError(f"{k}: a key in the metadata is refused (Secret Manager, by name)")
    out.mkdir(parents=True, exist_ok=True)
    sets = acc_sets(only or (SESSION_SETS if "session" in groups else ""))
    session_hours = SESSION_HOURS_DEFAULT
    if "session" in groups:
        refused = session_values(groups, values, mode, only)
        if refused:
            raise ValueError("; ".join(refused))
        session_hours = max(1, int(values["tb-session-minutes"]) // 60)
    vals = {
        **values,
        "tb-mode": mode,
        "tb-steps": " ".join(g for g in GROUPS if g in groups),
        "tb-max-minutes": str(launch_cap_hours(groups, sets, session_hours) * 60 - 5),
    }
    if "session" in groups:
        # D-1130: the project's SSH keys kept off the VM for the session (sshd is also stopped at its boots);
        # D-1132: the public sets loaded as the acc group loads them, and the steps a session does not run
        vals["block-project-ssh-keys"] = "TRUE"
        vals["serial-port-enable"] = "FALSE"  # no interactive serial console either (its output is still read)
        vals["tb-acc-sets"] = " ".join(f"{n}:{z}" for n, z in sets)
        vals["tb-skip"] = SESSION_SKIP  # session_values refused any other (the review's finding 1)
    if "acc" in groups:
        if values.get("tb-acc-protocols"):  # D1: a filter that matches no protocol stops the launch here, not on the VM
            chk = acc_ids(only, values.get("tb-acc-rs-tag", ""), values["tb-acc-protocols"])
            if chk["refused"]:
                raise ValueError("--acc-protocols: " + "; ".join(chk["refused"]))
        vals["tb-acc-sets"] = " ".join(f"{n}:{z}" for n, z in sets)
        # each set's plan high bound in seconds at its size: the VM's time budget per set (box-install-run.sh)
        highs = [r for r in acc_rows(sets) if r["seconds"] is not None]
        vals["tb-acc-plan"] = " ".join(
            f"{n}:{z}:{round(r['seconds_high'])}" for (n, z), r in zip(sets, highs, strict=False)
        )
    if "build" in groups and mode == "production":
        vals.setdefault("tb-vendor-key-secret", settings()["KEY_SECRET"])
    names = []
    for k, v in sorted(vals.items()):
        (out / k).write_text(v, encoding="utf-8")
        names.append(k)
    return names


def _module(name: str, path: Path) -> Any:
    """A module of the tree that is no package's (deploy/egress.py, deploy/gcp/session_vm.py), loaded by its path."""
    import importlib.util

    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # a dataclass in it looks its module up while it is made
    spec.loader.exec_module(mod)
    return mod


def _session_vm() -> Any:
    """deploy/gcp/session_vm.py (standard library; the driver's own checks of the session's options)."""
    return _module("tb_session_vm", ROOT / "deploy" / "gcp" / "session_vm.py")


def session_values(groups: list[str], values: dict[str, str], mode: str = "validation", only: str = "") -> list[str]:
    """Free: a session launch's own options (D-1132): dev and session alone, the validation route (the box the
    first start left is VALIDATION; the session then sets its own environment), DEV or VALIDATION and never
    PRODUCTION, the people as that environment takes them, whole minutes up to the hours allowed, no accuracy filter
    (a session runs no accuracy set)."""
    sv = _session_vm()
    bad: list[str] = []
    if sorted(groups) != ["dev", "session"]:
        bad.append(f"a session launch is --steps dev,session (got {','.join(groups)}): the commit's images, the "
                   "direct route, then the session; nothing else in the same launch")  # fmt: skip
    if mode != "validation":
        bad.append("a session launch is --mode validation (the direct route on the box the first start left)")
    env = values.get("tb-session-env", "")
    if env not in sv.ENVS.values():
        bad.append(f"tb-session-env {env!r}: DEV or VALIDATION (never PRODUCTION, D-1132)")
    else:
        try:
            if sv.parse_people(values.get("tb-session-people", ""), env) != values.get("tb-session-people"):
                bad.append("tb-session-people: not in the checked form (session_vm.py shell writes it)")
        except sv.Refused as exc:
            bad.append(str(exc))
    m = values.get("tb-session-minutes", "")
    if not m.isdigit() or not 1 <= int(m) <= sv.MAX_HOURS * 60:
        bad.append(f"tb-session-minutes {m!r}: whole minutes from 1 to {sv.MAX_HOURS * 60}")
    for k in ("tb-acc-protocols", "tb-acc-streams", "tb-acc-deadline", "tb-acc-rs-tag"):
        if values.get(k):
            bad.append(f"{k}: a session runs no accuracy set, so it takes no accuracy option")
    if only.strip():
        bad.append("--only: a session's public sets are fixed (jmed and tcga, the integrator's answer 6)")
    # a step left out or run again would leave out a proof (55's egress read-back) or the close (58): a session's
    # skip is its own default, never the operator's (the security review's finding 1)
    skip = (values.get("tb-skip") or "").split()
    if skip and skip != SESSION_SKIP.split():
        bad.append(f"--skip {' '.join(skip)}: a session leaves out only {SESSION_SKIP}; none of its own steps")
    if (values.get("tb-redo") or "").strip():
        bad.append("--redo: a session is never run again in part; more time is a new launch (D-1123 4.4)")
    return bad


# The session's calls, as the product labels them (tb_llm v1_labels: a phi prompt is D3, the others D1; the
# embedder's query of a note is D3): each must route to the box's own served builds and nowhere else
SESSION_CALLS = (
    ("compile ir_extract", "extract_criteria", "D1"),
    ("compile concept_map", "concept_select", "D1"),
    ("screen judge", "judge", "D3"),
    ("screen embedder", "embed", "D3"),
)
SERVED = {"j-workhorse", "v-verifier", "e-embed", "f-frontdesk", "g-guard"}  # the box's own builds (no stub)


def session_check(env: str, root: Path = ROOT, answers: Path | None = None) -> dict[str, Any]:
    """Free and local (D-1132, D-1131): would a box in ``env`` (DEV or VALIDATION) route each of the session's calls
    to its own served pair (the gateway's own routing policy and this tree's routing table: perimeter endpoints only,
    no stub), and would the product's egress table (deploy/egress.py, the box's own rules) open any destination
    outside the box, given the synthetic site's answers? Each blocker names the file and the rule; ``can_run`` only
    when none."""
    import yaml

    for sub in ("libs", "services"):
        if str(root / sub) not in sys.path:
            sys.path.insert(0, str(root / sub))
    from gateway.policy import RoutingPolicy, parse_label
    from tb_common.policy.classes import Environment, Topology

    e = Environment(env)
    pol = RoutingPolicy.load(root / "models" / "routing.yaml")
    calls: dict[str, Any] = {}
    blockers: list[str] = []
    asks = list(SESSION_CALLS)
    if e == Environment.DEV:  # DEV's ceiling is D0: what a call relabelled D0 (TB_DATA_CLASS=D0) would be routed to
        asks += [(f"{what} relabelled D0", role, "D0") for what, role, _dc in SESSION_CALLS]
    for what, role, dc in asks:
        try:
            r, cands = pol.candidates(role, parse_label(dc), Topology.A, e, "P-PRO6000")
            got = [{"alias": c.alias, "zone": c.endpoint.zone} for c in cands]
            calls[what] = {"role": role, "class": dc, "route": r.id, "candidates": got}
            off = [c for c in got if c["zone"] != "perimeter" or c["alias"] not in SERVED]
            if off:
                blockers.append(f"{what} ({role}, {dc}) in {env} goes to route {r.id} with {off}: not the box's own "
                                "served build alone (models/routing.yaml)")  # fmt: skip
        except Exception as exc:  # the policy's refusal, as the gateway would give it
            calls[what] = {"role": role, "class": dc, "refused": str(exc)}
            blockers.append(f"{what} ({role}, {dc}) is refused in {env}: {exc} (models/routing.yaml, "
                            "services/gateway/policy.py RoutingPolicy.candidates)")  # fmt: skip
    # D-1131: the product's own egress table for this environment and the synthetic site (no mail relay)
    egress = _module("tb_egress", root / "deploy" / "egress.py")
    site = yaml.safe_load((answers or root / "deploy" / "gcp" / "validation-site-answers.yaml").read_text()) or {}
    site_env = {"TB_ENV": env, "SMTP_HOST": str(site.get("smtp_host") or ""), "IMAP_HOST": str(site.get("imap_host")
                or ""), "TB_CTGOV_MODE": str(site.get("ctgov_mode") or "offline")}  # fmt: skip
    allows = [{"service": a.service, "host": a.host, "port": a.port, "why": a.why}
              for a in egress.allowlist(site_env, root / "models" / "routing.yaml")]  # fmt: skip
    if allows:
        blockers.append(f"the box's egress table in {env} opens {allows} (deploy/egress.py allowlist): a way out of "
                        "the box for the pasted text (D-1131)")  # fmt: skip
    return {"environment": env, "calls": calls, "egress_allows": allows, "can_run": not blockers,
            "blockers": blockers}  # fmt: skip


# ------------------------------------------------------------------------------------------------ the results reader
def _load(d: Path, rel: str) -> Any:
    try:
        return json.loads((d / rel).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def results(d: Path, scored: Path | None = None) -> dict[str, Any]:
    """What a box run's results say: per test its checks (from the parts), and what every result names. ``scored``:
    the folder whose ``acc/<set>/score.json`` the accuracy sets were scored into (acc-score, outside the box)."""
    state = _load(d, "state.json") or {}
    parts = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((d / "parts").glob("*.json"))}
    rec = (
        {p.name: _load(d, f"records/{p.name}") for p in sorted((d / "records").glob("*.json"))}
        if (d / "records").exists()
        else {}
    )

    def part(prefix: str) -> list[dict[str, Any]]:
        return [v for k, v in parts.items() if k.split("-", 1)[-1].startswith(prefix)]

    def check(name: str, cond: bool | None, detail: Any = None) -> dict[str, Any]:
        return {"check": name, "pass": cond, "detail": detail}

    stops = [{"step": k, "reason": v["stop"]["reason"]} for k, v in parts.items() if v.get("status") == "stop"]
    b01 = (parts.get("01-bundle") or {}).get("detail") or {}
    b06 = (parts.get("b06-verify") or {}).get("detail") or {}
    bundle = b01 or b06
    identity = rec.get("identity.json") or {}
    mode = str(b01.get("mode") or b06.get("mode") or (rec.get("bundle.json") or {}).get("mode") or "production")
    routes = rec.get("acc-routes.json") or {}
    acc_settings = (parts.get("51-acc-settings") or {}).get("detail") or {}
    provenance = {
        "mode": mode,
        # validation mode: the bundle is signed with a throwaway key made on the runner VM: it is NOT a release
        "not_a_release": bool((rec.get("bundle.json") or {}).get("not_a_release") or b01.get("not_a_release")),
        "commit": (bundle.get("release") or {}).get("commit"),
        "bundle_id": bundle.get("bundle_id"),
        "release_seq": bundle.get("release_seq"),
        "signature_sha256": bundle.get("signature_sha256"),
        "signing_key_id": bundle.get("key_id"),
        "bundle_sha256": ((rec.get("bundle.json") or {}).get("sha256")),
        "image_digests": {k: v.get("digests") for k, v in (identity.get("images") or {}).items()},
        "weight_manifests": (identity.get("weights") or {}).get("expected"),
        "chat_template_sha256": (identity.get("chat_template") or {}).get("served_sha256"),
        "served_prompts": identity.get("served_prompts"),
        "environment": routes.get("environment"),
        "served_prompts_in_environment": routes.get("served_prompts"),
        "embedder_in_screen": routes.get("embedder"),
        "tripwire": acc_settings.get("tripwire"),
        "limits": acc_settings.get("limits"),
    }
    tests: dict[str, list[dict[str, Any]]] = {}
    if any(k.startswith("b0") for k in parts):
        tests["R2 build"] = [
            check(
                "every build step done",
                all(
                    parts.get(s, {}).get("status") == "done"
                    for s in (
                        "b01-source",
                        "b02-venv",
                        "b03-images",
                        "b04-gates",
                        "b05-sign",
                        "b06-verify",
                        "b07-upload",
                    )
                ),
            ),
            check(
                "signature verified and the release record is one PRODUCTION takes",
                b06.get("refused") == [],
                b06.get("refused"),
            ),
            check(
                "the key file was gone after signing",
                ((parts.get("b05-sign") or {}).get("detail") or {}).get("key_left_on_tmpfs") is False,
            ),
        ]
    if "01-bundle" in parts:
        doc = (parts.get("12-doctor") or {}).get("detail") or {}
        tests[f"G-2 {mode} start"] = [
            check(
                "no stop in steps 01 to 12 (no shell beyond the installer)",
                not [s for s in stops if s["step"][:2] < "13"],
                stops,
            ),
            check("the bundle as PRODUCTION reads it", b01.get("refused") == [], b01.get("refused")),
            check(
                "the box says VALIDATION (deploy/.env, after install.sh --answers)"
                if mode == "validation"
                else "the wizard answered through the console's page",
                ((parts.get("03-wizard") or {}).get("detail") or {}).get("environment") == "VALIDATION"
                if mode == "validation"
                else ((parts.get("03-wizard") or {}).get("detail") or {}).get("wizard") == "done",
            ),
            check(
                "G-1 identity: template, image digests, weights, prompts as pinned",
                identity.get("pass"),
                identity.get("checks"),
            ),
            check("pair canary", (parts.get("07-canary") or {}).get("pass")),
            check("qualification record passed", ((rec.get("qualification.json") or {}).get("passed")) is True),
            check(
                f"{'VALIDATION' if mode == 'validation' else 'PRODUCTION'} resolves to the promoted builds",
                ((parts.get("11-resolve") or {}).get("detail") or {}).get("production_resolves_promoted") is True,
            ),
            check(
                "doctor: no unexpected FAIL, no rehearsal mark",
                (parts.get("12-doctor") or {}).get("pass"),
                {k: doc.get(k) for k in ("fails", "expected_fails", "unexpected_fails", "rehearsal_marks")},
            ),
        ]
    if part("g6-"):
        res = (parts.get("26-g6-result") or {}).get("detail") or {}
        stages = {
            k: {
                "seconds": v.get("seconds"),
                "pass": v.get("pass"),
                "oom_kills": (v.get("detail") or {}).get("oom_kills"),
                "memory": ((v.get("detail") or {}).get("memory") or {}).get("containers"),
            }
            for k, v in parts.items()
            if k[3:] in ("g6-ingest", "g6-rebuild", "g6-screen", "g6-backup")
        }
        tests["G-6 50k dense night"] = [
            check(
                "every stage ended under the caps, no OOM kill", (parts.get("26-g6-result") or {}).get("pass"), stages
            ),
            check("the three largest costs", None, res.get("top_costs")),
        ]
    if part("g9-"):
        r9 = parts.get("39-g9-result") or {}
        tests["G-9 restarts and outage mid-screen"] = [
            check(
                "the job resumed and ended done, its list equals the undisturbed one",
                r9.get("pass"),
                (r9.get("detail") or {}).get("compare"),
            ),
        ]
    if part("g10-"):
        tests["G-10 new model-server image"] = [
            check("both servers on the declared image", (parts.get("41-g10-image") or {}).get("status") == "done"),
            check("canary", (parts.get("42-g10-canary") or {}).get("pass")),
            check("qualify", (parts.get("43-g10-qualify") or {}).get("pass")),
        ]
    if part("acc-"):
        tests["Public accuracy on the installed box (scores: acc-score, outside the box)"] = acc_checks(
            scored, parts, routes
        )
    return {
        "ended": state.get("ended"),
        "steps": len(parts),
        "stops": stops,
        "provenance": provenance,
        "tests": tests,
        "minutes": {k: v.get("minutes") for k, v in parts.items()},
    }


def acc_checks(d: Path | None, parts: dict[str, Any], routes: dict[str, Any]) -> list[dict[str, Any]]:
    """Per accuracy set: what the box did with its protocols. A protocol the gateway's PHI tripwire refused is counted
    as such (a product defect count), never dropped; the score itself is acc-score's (outside the box)."""
    out = [
        {
            "check": "the box routes the compile and the screen in its environment (judge, verifier, compiler)",
            "pass": routes.get("routes_ok"),
            "detail": routes.get("routes"),
        }
    ]
    for k, v in sorted(parts.items()):
        if not k[3:].startswith("acc-") or k[3:] in ("acc-tools", "acc-settings", "acc-routes", "acc-data",
                                                         "acc-ingest", "acc-result"):  # fmt: skip
            continue
        det = v.get("detail") or {}
        counts = det.get("counts") or {}
        score = (_load(d, f"acc/{k[7:]}/score.json") if d is not None else None) or {}
        # D7: said in the check's own line (the detail is cut at 400 characters in report.md)
        flight = f"{det.get('in_flight_max') if det.get('in_flight_max') is not None else '?'} at most of " + str(
            det.get("streams") or 1
        )
        out.append(
            {
                "check": f"{k[7:]}: every protocol compiled, approved and screened (compiled only: a compile-only "
                f"set); protocols in flight: {flight}",
                "pass": v.get("pass"),
                "detail": {
                    "counts": counts,
                    # D7: how many protocols were in flight at once (asked, and the most there were)
                    "streams": det.get("streams") or 1,
                    "in_flight_max": det.get("in_flight_max"),
                    "refused_by_tripwire": counts.get("refused_by_tripwire"),
                    "uploaded": det.get("uploaded"),
                    # D-1129: a set taken up again after its budget: its attempts as one record
                    "attempts": det.get("attempts_line") or None,
                    "score": score.get("summary") if isinstance(score, dict) else None,
                },
            }
        )
    return out


def render_results(r: dict[str, Any]) -> str:
    lines = [f"# Box run: {r.get('ended') or 'not ended'}", "", "## What it ran", ""]
    lines += [f"- {k}: `{json.dumps(v, ensure_ascii=False)[:300]}`" for k, v in r["provenance"].items()]
    for t, cs in r["tests"].items():
        lines += ["", f"## {t}", ""]
        for c in cs:
            mark = {True: "PASS", False: "FAIL", None: "INFO"}[c["pass"]]
            lines.append(
                f"- {mark} {c['check']}" + (f": `{json.dumps(c['detail'], default=str)[:400]}`" if c["detail"] else "")
            )
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------------------------------------ accuracy tools, score
def acc_tools(out: Path, root: Path = ROOT) -> dict[str, Any]:
    """Lane G's accuracy tools as committed at HEAD (``git archive``, never the working tree), for the VM: the paths
    of :data:`ACC_TOOL_PATHS`. Returns the commit and whether those paths differ from it in the working tree."""
    import subprocess

    top = Path(subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"], capture_output=True,
                              text=True, check=True).stdout.strip())  # fmt: skip
    sub = root.resolve().relative_to(top.resolve()).as_posix()
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
    commit = head.stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--", *ACC_TOOL_PATHS],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    out.parent.mkdir(parents=True, exist_ok=True)
    tree = f"{commit}:{sub}" if sub not in ("", ".") else commit
    subprocess.run(
        ["git", "-C", str(top), "archive", "--format=tar.gz", "-o", str(out.resolve()), tree, *ACC_TOOL_PATHS],
        check=True,
    )
    return {"commit": commit, "paths": list(ACC_TOOL_PATHS), "working_tree_differs": bool(dirty), "file": str(out)}


def acc_score(d: Path) -> dict[str, Any]:
    """Score every collected accuracy set under ``d/acc/<set>/`` (``built/gold`` and ``work/answers.json``, as the
    VM uploaded them) with :func:`tools.public_accuracy.score.score`: outside the box, by ids only. Writes
    ``acc/<set>/score.json`` and returns {set: summary}."""
    from tools.public_accuracy import score as sc

    out: dict[str, Any] = {}
    for sd in sorted(p for p in (d / "acc").glob("*") if p.is_dir()):
        built, work = sd / "built", sd / "work"
        if not (built / "gold" / "ids.json").exists() or not (work / "answers.json").exists():
            out[sd.name] = {"scored": False, "why": "no gold or no answers (the set did not finish)"}
            continue
        pm_p = work / "pidmap.json"
        if pm_p.exists():  # the box's pseudonyms (its own site key) -> the scorer's (the demo key), by chart number
            back = {v: k for k, v in json.loads(pm_p.read_text(encoding="utf-8")).items()}
            answers = json.loads((work / "answers.json").read_text(encoding="utf-8"))
            for a in answers.values():
                a["patients"] = {
                    sc.pid_of(back[pid]) if pid in back else f"unmapped:{pid}": v
                    for pid, v in (a.get("patients") or {}).items()
                }
            work = sd / "work-scored"
            work.mkdir(exist_ok=True)
            (work / "answers.json").write_text(json.dumps(answers, ensure_ascii=False), encoding="utf-8")
            if (sd / "work" / "set-clock.json").exists():  # D-1129: the set's attempts, read beside its answers
                (work / "set-clock.json").write_bytes((sd / "work" / "set-clock.json").read_bytes())
        res = sc.score(built, work)
        res["summary"] = {
            k: (v.get("summary") if isinstance(v, dict) and "summary" in v else v)
            for k, v in res.items()
            if k in SCORE_SUMMARY_KEYS
        }
        if "conflicted" in (res.get("pairs") or {}):  # D-1064: the pairs set aside, by id, and the findings to trace
            res["summary"]["conflicted"] = [
                {k: c.get(k) for k in ("patient", "trial", "excluding", "box", "blocked_on", "on_another_line")}
                for c in res["pairs"]["conflicted"]["pairs"]
            ]
            res["summary"]["conflicted_excluded_on_another_line"] = [
                f"{c['patient']} x {c['trial']}" for c in res["pairs"]["conflicted_excluded_on_another_line"]
            ]
        (sd / "score.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        if res.get("not_scored_because"):
            out[sd.name] = {"scored": False, "why": res["not_scored_because"], "summary": res.get("summary")}
            continue
        out[sd.name] = {"scored": True, "summary": res.get("summary") if isinstance(res, dict) else None}
    return out


# ------------------------------------------------------------------------------------------------ resume plan (D-1129)
ACC_NOT_SETS = ("tools", "settings", "routes", "data", "ingest", "result")


def _cut_of(detail: dict[str, Any]) -> int:
    """The protocols a set's budget cut (or never started), as its part says (a part written before D-1129 has only
    its counts)."""
    if "budget_cut" in detail:
        return int(detail.get("budget_cut") or 0)
    return int((detail.get("counts") or {}).get("not_run_time_budget") or 0)


def resume_plan(d: Path, deadline: str = "", redo: str = "") -> dict[str, Any]:
    """Free and local (D-1129, card H-14): what ``box-run.sh --resume`` would take up of the accuracy sets, read from
    the run's last collected results in ``d`` (``results.tgz`` of ``--collect``; its parts) and, where a set was
    fetched, its ``acc/<set>/work/progress.json`` for the protocols' ids. A set that ended on its own budget with
    protocols cut runs those protocols only, in a new attempt, when ``deadline`` (the resume's ``--acc-deadline``: one
    number, or "set:seconds") gives it a budget; without one it stays done. ``redo`` names steps run again from no
    work. ``state`` is "not here" when the run's state is only in the bucket: nothing is read from the cloud here (the
    VM says the same first thing on its boot, ``TB-RESUME-PLAN`` lines). ``refused`` names a budget entry that is not
    seconds or names a set the run does not have."""
    out: dict[str, Any] = {"run_folder": str(d), "state": "not here", "sets": [], "refused": [], "lines": []}
    tgz = d / "results.tgz"
    if not tgz.is_file():
        out["lines"].append(
            f"resume-plan: the run's state is not here ({tgz} missing): it is only in the bucket; `box-run.sh "
            "--collect <run id>` reads it (a bucket read), or the VM says what it takes up first thing on its boot "
            "(TB-RESUME-PLAN lines in its log)"
        )
        return out
    parts: dict[str, dict[str, Any]] = {}
    with tarfile.open(tgz) as tar:
        for m in tar.getmembers():
            name = m.name.removeprefix("./")
            if not (m.isfile() and name.startswith("parts/") and name.endswith(".json") and "-acc-" in name):
                continue
            f = tar.extractfile(m)
            if f is None:
                continue
            try:
                parts[Path(name).stem] = json.loads(f.read().decode("utf-8"))
            except ValueError:
                continue
    from datetime import UTC, datetime

    out["state"] = "the last collect"
    out["as_of"] = datetime.fromtimestamp(tgz.stat().st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    sets = {k.split("-acc-", 1)[1]: k for k in parts if k.split("-acc-", 1)[1] not in ACC_NOT_SETS}
    budgets: dict[str, str] = {}
    for e in deadline.split():
        n, _, v = e.rpartition(":")
        if not v.isdigit():
            out["refused"].append(f'--acc-deadline {e}: seconds (one number, or "set:seconds")')
        elif n and n not in sets:
            out["refused"].append(f"--acc-deadline {e}: set {n} is not a set of this run ({', '.join(sorted(sets))})")
        else:
            budgets[n] = v
    redone = set(redo.replace(",", " ").split())
    for setname, step in sorted(sets.items(), key=lambda kv: kv[1]):
        part = parts[step]
        det = part.get("detail") or {}
        cut = _cut_of(det)
        prog: dict[str, Any] = _load(d, f"acc/{setname}/work/progress.json") or {}
        ids = sorted(rs for rs, a in prog.items() if isinstance(a, dict)
                     and (not a.get("finished") or a.get("outcome") == "not_run_time_budget"))  # fmt: skip
        b = budgets.get(setname) or budgets.get("") or ""
        if step in redone:
            what = "run again from no work (--redo)"
        elif part.get("status") == "stop":
            what = "stopped: runs again" + (
                f" (its {cut} cut protocols in a new attempt with {b} s)" if cut and b else ""
            )
        elif cut <= 0:
            what = "nothing cut: stays done, not run again"
        elif b:
            what = f"runs only its {cut} cut protocols, in a new attempt with {b} s; the finished ones are kept"
        else:
            what = f"{cut} protocols cut by its budget: stays done unless --acc-deadline gives {setname} a budget"
        row = {"set": setname, "step": step, "status": part.get("status"), "budget_cut": cut,
               "cut_protocols": ids or None, "budget_s": int(b) if b else None, "what": what,
               "attempts": det.get("attempts_line")}  # fmt: skip
        out["sets"].append(row)
        listed = f" [{', '.join(ids[:12])}{' ...' if len(ids) > 12 else ''}]" if ids and cut else ""
        out["lines"].append(f"resume-plan: {step} ({part.get('status')}): {what}{listed}")
    out["needs_deadline"] = [r["set"] for r in out["sets"] if r["budget_cut"] and r["budget_s"] is None
                             and r["step"] not in redone]  # fmt: skip
    if out["needs_deadline"]:
        out["lines"].append("resume-plan: --acc-deadline is needed to take up " + ", ".join(out["needs_deadline"])
                            + ' (the old budget is spent): e.g. --acc-deadline "'
                            + " ".join(f"{n}:SECONDS" for n in out["needs_deadline"]) + '"')  # fmt: skip
    if not sets:
        out["lines"].append("resume-plan: no accuracy set in this run's results yet")
    out["lines"] += [f"resume-plan: refused: {r}" for r in out["refused"]]
    return out


# ------------------------------------------------------------------------------------------------ protocol ids (D1)
def acc_ids(only: str = "", rs_tag: str = "", protocols: str = "", cache: Path | None = None) -> dict[str, Any]:
    """Free and local: per set of the launch, the ruleset prefix its ids carry on the box (the set's letter and the
    ``--acc-rs-tag``: tag ``m2`` makes TCGA-BRCA ``Gm2TCGA-BRCA``), the ids where they can be known here (a set of
    fixed protocols: tcga, jmed; else a sampled set whose source files are in the local cache), and what a
    ``--acc-protocols`` filter ("set:RS1,RS2 set2:RS3") matches. ``refused`` names every entry that cannot match: a
    set not in the launch, an id without the set's prefix, an id the set does not have, a set left with none, and a
    filter on a set whose ids are not known here (D-1125: it cannot be checked, so it is not accepted)."""
    from tools.public_accuracy import sets as st
    from tools.public_accuracy import site
    from tools.public_accuracy import sources as src

    if rs_tag and not site.RULESET_ID.match(rs_tag):
        raise ValueError(f"--acc-rs-tag {rs_tag!r}: letters, digits, - and _ only")
    chosen = acc_sets(only)
    fixed = {"tcga": sorted(st.TCGA_CRITERIA), "jmed": sorted(st.JMED_CRITERIA)}
    out: dict[str, Any] = {"rs_tag": rs_tag, "sets": {}, "refused": []}
    for name, size in chosen:
        prefix = site.SET_OFFSETS[name][2] + rs_tag if name in site.SET_OFFSETS else rs_tag
        ids: list[str] | None = None
        how = "not known here: the sample is drawn from the set's source files, not in the local cache"
        if name in fixed:
            ids = sorted(site.ruleset_ids({k: None for k in fixed[name]}, prefix).values())  # type: ignore[misc]
            how = "fixed protocols of the set"
        elif (cache or src.CACHE).joinpath(plan_fetch(name)).is_dir():
            try:
                b = st.read(name, cache or src.CACHE, size, live=False)
                ids = sorted(site.ruleset_ids(b.trials, prefix).values())
                how = "built here from the local cache (the box builds the same sample)"
            except (SystemExit, OSError, ValueError) as exc:
                how = f"not known here: the local cache could not build it ({exc})"
        out["sets"][name] = {"prefix": prefix, "ids": ids, "how": how}
    for entry in protocols.split():
        name, _, rest = entry.partition(":")
        want = [x for x in rest.split(",") if x]
        if name not in out["sets"]:
            out["refused"].append(f"{entry}: set {name} is not in this launch ({', '.join(out['sets']) or 'none'})")
            continue
        info = out["sets"][name]
        if info["ids"] is None:
            # D-1125: a filter that cannot be checked for free is not accepted for free. An id with the right prefix
            # passed here before, and the VM stopped on it after the install was paid for.
            info["filter"], info["matches"] = want, []
            out["refused"].append(
                f"{name}: a filter on this set cannot be checked here ({info['how']}): leave {name} out of "
                "--acc-protocols, or put the set's source files in the local cache first"
            )
            continue
        bad = [x for x in want if not x.startswith(info["prefix"])]
        bad += [x for x in want if x not in bad and info["ids"] is not None and x not in info["ids"]]
        info["filter"] = want
        info["matches"] = [x for x in want if x not in bad]
        if bad:
            known = info["ids"] or []
            listed = f"; ids {', '.join(known[:12])}{' ...' if len(known) > 12 else ''}" if known else ""
            out["refused"].append(f"{name}: {', '.join(bad)} not among its ids (prefix {info['prefix']!r}{listed})")
        if not info["matches"]:
            out["refused"].append(f"{name}: the filter matches no protocol")
    return out


def plan_fetch(name: str) -> str:
    """The cache folder a set's files are fetched into (plan.RUN_A's ``fetch``)."""
    from tools.public_accuracy import plan

    return plan.acc_set(name).fetch


# ------------------------------------------------------------------------------------------------ source bundle (D8)
def src_bundle(commit: str, out: Path | None = None, check: Path | None = None, root: Path = ROOT) -> dict[str, Any]:
    """The release commit's git bundle, proved before it is uploaded (D8, P1b review: a bundle made from a shallow
    checkout could not be cloned on the VM, and the build was paid for nothing). With ``out`` it is made here
    (``git bundle create`` of the commit's whole history); with ``check`` a bundle made by hand is taken. Either way
    it is cloned into a temporary folder and the commit checked out exactly as the VM's b01-source does it (``git
    clone`` of the bundle, ``git checkout --detach`` of the commit, nothing fetched besides); ``ok`` only when HEAD
    there is the commit, all 40 characters (the VM compares them)."""
    import subprocess

    def git(*a: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=False)

    res: dict[str, Any] = {"commit": commit, "ok": False}
    if out is not None:
        full = git("rev-parse", "--verify", f"{commit}^{{commit}}", cwd=root)
        if full.returncode != 0:
            res["why"] = f"{commit} is not a commit of this repository"
            return res
        commit = res["commit"] = full.stdout.strip()
        if git("rev-parse", "--is-shallow-repository", cwd=root).stdout.strip() == "true":
            res["why"] = "this checkout is shallow: its bundle would lack the history (git fetch --unshallow first)"
            return res
        out.parent.mkdir(parents=True, exist_ok=True)
        # git bundles refs, not a bare commit id: a short-lived ref names it, removed again whatever happens. A
        # branch (refs/heads/): a plain `git clone` of the bundle, as on the VM, takes only branches and tags, and a
        # bundle of any other ref clones as an empty repository (H-1: the proof below now clones as the VM does)
        ref = f"refs/heads/tb-release-{commit}"
        git("update-ref", ref, commit, cwd=root)
        try:
            made = git("bundle", "create", str(out.resolve()), ref, cwd=root)
        finally:
            git("update-ref", "-d", ref, cwd=root)
        if made.returncode != 0:
            res["why"] = f"git bundle create: {made.stderr.strip()[:300]}"
            return res
        check = out
    if check is None or not check.is_file():
        res["why"] = f"no bundle at {check}"
        return res
    res["bundle"] = str(check)
    with tempfile.TemporaryDirectory() as t:
        dst = Path(t) / "src"
        steps = [
            ("verify", git("bundle", "verify", str(check.resolve()), cwd=root)),
            ("clone", git("clone", "-q", str(check.resolve()), str(dst))),  # as b01-source: no other fetch
        ]
        if steps[-1][1].returncode == 0:
            steps.append(("checkout", git("checkout", "-q", "--detach", commit, cwd=dst)))
        for what, r in steps:
            if r.returncode != 0:
                res["why"] = f"git {what} of the bundle failed: {(r.stderr or r.stdout).strip()[:300]}"
                return res
        head = git("rev-parse", "HEAD", cwd=dst).stdout.strip()
    if not head or head != commit:
        whole = " (give the full 40-character commit: the VM compares HEAD with it exactly)"
        res["why"] = f"the clone's HEAD is {head or 'nothing'}, not {commit}" + (
            whole if head.startswith(commit) else ""
        )
        return res
    res.update(ok=True, head=head)
    return res


# ------------------------------------------------------------------------------------------------ preflight (H-1)
def _site_workers(site_env: str) -> int:
    """TB_WORKERS as the launch's --site-env sets it, else the box's default (4)."""
    for kv in site_env.split():
        k, _, v = kv.partition("=")
        if k == "TB_WORKERS" and v.isdigit():
            return int(v)
    return 4


def launch_checks(groups: list[str], values: dict[str, str], only: str = "") -> list[str]:
    """Free and local: every option of a launch that would only fail on the VM, after the paid install. Returns
    each refusal (empty: none). The accuracy options (D1, D4, D7 of the P1b review): the protocol filter matches
    protocols of the launch's sets (:func:`acc_ids`); ``--acc-streams`` names sets of the launch with a whole number
    from 1 to the orchestrator's job workers less the one kept for the ingest (TB_WORKERS 4: 3; ``--site-env`` may
    set it); ``--acc-deadline`` and ``--acc-min-start`` are seconds. A build or dev launch (D8): a full commit (the VM
    compares HEAD with it exactly)."""
    bad: list[str] = []
    if "session" in groups:
        bad += session_values(groups, values, values.get("tb-mode", "validation"), only)
    if any(g in groups for g in ("build", "dev")):
        c = values.get("tb-commit", "")
        if not (len(c) == 40 and all(ch in "0123456789abcdef" for ch in c)):
            bad.append(f"--commit {c!r}: the full 40-character commit (b01-source compares HEAD with it exactly)")
    if "acc" not in groups:
        return bad
    from tools.public_accuracy import site

    names = [n for n, _ in acc_sets(only)]
    tag = values.get("tb-acc-rs-tag", "")
    if tag and not site.RULESET_ID.match(tag):
        bad.append(f"--acc-rs-tag {tag!r}: letters, digits, - and _ only")
    elif values.get("tb-acc-protocols") is not None and not values["tb-acc-protocols"].strip():
        bad.append('--acc-protocols is empty: name protocols ("set:RS1,RS2") or leave the option out')
    elif values.get("tb-acc-protocols"):
        bad += [f"--acc-protocols: {r}" for r in acc_ids(only, tag, values["tb-acc-protocols"])["refused"]]
    most = _site_workers(values.get("tb-site-env", "")) - 1
    for entry in (values.get("tb-acc-streams") or "").split():
        name, _, n = entry.partition(":")
        if name not in names:
            bad.append(f"--acc-streams {entry}: set {name} is not in this launch ({', '.join(names)})")
        elif not n.isdigit() or not 1 <= int(n) <= max(1, most):
            bad.append(f"--acc-streams {entry}: a whole number from 1 to {max(1, most)} (TB_WORKERS {most + 1}, "
                       "one kept for the ingest)")  # fmt: skip
    for key, opt in (("tb-acc-deadline", "--acc-deadline"), ("tb-acc-min-start", "--acc-min-start")):
        for entry in (values.get(key) or "").split():
            name, _, n = entry.rpartition(":")
            if (name and name not in names) or not n.isdigit():
                bad.append(f'{opt} {entry}: seconds (one number, or "set:seconds" for a set of this launch)')
    return bad


def streams_of(only: str = "", acc_streams: str = "") -> dict[str, int]:
    """Per set of the launch, the protocols it will have in flight: ``--acc-streams``, else
    :data:`COMPILE_BOUND_STREAMS` for a compile-bound set, else 1 (the VM script's acc_streams_default, D7)."""
    asked = dict(e.split(":", 1) for e in acc_streams.split() if ":" in e)
    return {
        n: int(asked[n]) if asked.get(n, "").isdigit() else (COMPILE_BOUND_STREAMS if compile_bound(n) else 1)
        for n, _ in acc_sets(only)
    }


def preflight(
    groups: list[str],
    values: dict[str, str],
    mode: str = "production",
    only: str = "",
    src: Path | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Every free check of a launch, before anything is uploaded or started (H-1 of the P1b fixes): the options
    (:func:`launch_checks`), the source bundle of a build or dev launch proved as the VM will clone it
    (:func:`src_bundle`; the bucket's own is never taken unproved), and the metadata built into a temporary folder
    (the keys each step needs, no key-like value). ``ok`` only when every check passed; the driver's
    ``--preflight`` runs this alone, a launch runs it first. The validation-check stays the driver's own step."""
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"check": name, "pass": ok, "detail": detail})

    unknown = [g for g in groups if g not in GROUPS]
    add("the steps are known", not unknown and bool(groups), unknown or None)
    refused = launch_checks(groups, values, only)
    add("the launch's options would hold on the VM (filter, tag, streams, budgets, commit)", not refused,
        refused or None)  # fmt: skip
    if "acc" in groups:
        add("protocols in flight per set (D7: 3 for a compile-bound set unless --acc-streams)", True,
            streams_of(only, values.get("tb-acc-streams", "")))  # fmt: skip
    if any(g in groups for g in ("build", "dev")):
        if src is None:
            add("the source bundle is proved (D8)", False,
                "--src-bundle FILE is needed: the bucket's src.bundle is never taken unproved (make one with "
                "tools/box_run.py src-bundle --commit <sha> --out FILE)")  # fmt: skip
        else:
            sb = src_bundle(values.get("tb-commit", ""), check=src, root=root)
            add("the source bundle is proved (D8): cloned as the VM clones it, the commit checked out", sb["ok"], sb)
    try:
        with tempfile.TemporaryDirectory() as t:
            vals = dict(values)
            if "acc" in groups or "session" in groups:
                vals.setdefault("tb-acc-tools", "<uploaded by the launch>")
            keys = metadata(groups, vals, Path(t), mode, only)
        add("the metadata builds (every key the steps need, no key-like value)", True, len(keys))
    except ValueError as exc:
        add("the metadata builds (every key the steps need, no key-like value)", False, str(exc))
    if "session" in groups and values.get("tb-session-env") in ("DEV", "VALIDATION"):
        sc = session_check(values["tb-session-env"], root)
        add(f"the box in {sc['environment']} routes the session's calls to its own served pair only and lets no "
            "text out (session-check, D-1131, D-1132)", sc["can_run"], sc["blockers"] or None)  # fmt: skip
    return {"ok": all(c["pass"] for c in checks), "checks": checks}


# ------------------------------------------------------------------------------------------------ the VALIDATION check
def validation_check(root: Path = ROOT) -> dict[str, Any]:
    """Can a VALIDATION box with the real pair run the accuracy set on THIS tree? Free and local: the routing policy,
    the registry, the compose file and the declared settings the box would load, asked the questions the run's calls
    ask. Each blocker names the file and the rule; ``can_run`` is True only when none is left. (The installed box's
    step 52-acc-routes asks its own gateway the same, on the bundle's tree.)"""
    import yaml

    for sub in ("libs", "services"):
        if str(root / sub) not in sys.path:
            sys.path.insert(0, str(root / sub))
    from gateway.policy import RoutingPolicy, parse_label
    from registry import registry as rg
    from tb_common.config import DECLARED
    from tb_common.policy.classes import Environment, Topology

    env = Environment.VALIDATION
    pol = RoutingPolicy.load(root / "models" / "routing.yaml")

    def route(role: str, dc: str) -> dict[str, Any]:
        try:
            r, c = pol.candidates(role, parse_label(dc), Topology.A, env, "P-PRO6000")
            return {"role": role, "class": dc, "route": r.id, "aliases": [x.alias for x in c]}
        except Exception as exc:  # the policy's refusal, as the gateway would give it
            return {"role": role, "class": dc, "refused": str(exc)}

    calls = {
        "screen judge (a phi prompt: D3 unless TB_DATA_CLASS)": route("judge", "D3"),
        "screen judge at D2-L": route("judge", "D2-L"),
        "compile ir_extract (D1 unless TB_DATA_CLASS)": route("extract_criteria", "D1"),
        "compile ir_extract at D2-L": route("extract_criteria", "D2-L"),
        "compile concept_map (D1)": route("concept_select", "D1"),
        "qualify's calls (class D0, tools/qualify.py)": route("judge", "D0"),
    }
    reg = yaml.safe_load((root / "models" / "registry.yaml").read_text(encoding="utf-8")) or {}
    pair = {
        str(b.get("build_id")): str(b.get("status"))
        for b in reg.get("builds") or []
        if str(b.get("build_id", "")).endswith("-rtxpro6000") and b.get("alias") in ("j-workhorse", "v-verifier")
    }
    status_ok = {b: rg._status_ok(rg.Status(st), "judge", env) for b, st in pair.items()}
    compose = (root / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")
    shared_class = compose.count('TB_DATA_CLASS: "${TB_DATA_CLASS:-}"')
    tripwire = sorted(k for k in DECLARED if "TRIPWIRE" in k)
    blockers = []
    if "refused" in calls["screen judge (a phi prompt: D3 unless TB_DATA_CLASS)"]:
        if "refused" in calls["compile ir_extract at D2-L"] and shared_class >= 2:
            blockers.append(
                "the screen's judge call is D3 and VALIDATION's ceiling is D2 (models/routing.yaml, the patient route "
                "is PRODUCTION only); the only D2 route for it is D2-L, but TB_DATA_CLASS is one value for the "
                "compiler and the orchestrator (deploy/docker-compose.yml), and at D2-L the compile has no route: no "
                "setting lets one VALIDATION box both compile and screen"
            )
        else:
            blockers.append("the screen's judge call does not route in VALIDATION")
    if not all(status_ok.values()):
        how = (
            "and qualify's own calls (D0) have no route in VALIDATION, so the record cannot be made on the box"
            if "refused" in calls["qualify's calls (class D0, tools/qualify.py)"]
            else "qualify must pass first"
        )
        blockers.append(
            f"VALIDATION routes a judge or verifier only as champion (services/registry/registry.py _status_ok); the "
            f"pair is {sorted(set(pair.values()))} and becomes champion only by pin_model --promote from a passing "
            f"qualification record, {how}"
        )
    return {
        "environment": env.value,
        "calls": calls,
        "pair_status": pair,
        "pair_routes_in_validation": status_ok,
        "tb_data_class_shared_by_services": shared_class,
        "tripwire_settings_declared": tripwire,
        "can_run": not blockers,
        "blockers": blockers,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("estimate")
    e.add_argument("--steps", required=True)
    e.add_argument("--json", action="store_true")
    e.add_argument("--session-hours", type=int, default=SESSION_HOURS_DEFAULT, choices=(1, 2, 3))
    sub.add_parser("settings")
    m = sub.add_parser("metadata")
    m.add_argument("--steps", required=True)
    m.add_argument("--out", type=Path, required=True)
    m.add_argument("--set", action="append", default=[], help="key=value")
    for x in (e, m):
        x.add_argument("--mode", default="production", choices=MODES)
        x.add_argument("--only", default="", help="accuracy sets: name or name:size, comma-separated (default Run A)")
    at = sub.add_parser("acc-tools")
    at.add_argument("--out", type=Path, required=True)
    c = sub.add_parser("acc-score")
    c.add_argument("dir", type=Path)
    rp = sub.add_parser("resume-plan", help="free: what a --resume would take up of the accuracy sets (D-1129)")
    rp.add_argument("dir", type=Path)
    rp.add_argument("--deadline", default="", help="the resume's --acc-deadline")
    rp.add_argument("--redo", default="", help="the resume's --redo")
    ai = sub.add_parser("acc-ids", help="free: the ruleset ids an --acc-protocols filter matches (D1)")
    ai.add_argument("--only", default="")
    ai.add_argument("--rs-tag", default="")
    ai.add_argument("--protocols", default="")
    sb = sub.add_parser("src-bundle", help="the release commit's git bundle, proved by a clone and a checkout (D8)")
    sb.add_argument("--commit", required=True)
    sbx = sb.add_mutually_exclusive_group(required=True)
    sbx.add_argument("--out", type=Path)
    sbx.add_argument("--check", type=Path)
    pf = sub.add_parser("preflight", help="free: every check of a launch before anything is uploaded or started")
    pf.add_argument("--steps", required=True)
    pf.add_argument("--mode", default="production", choices=MODES)
    pf.add_argument("--only", default="")
    pf.add_argument("--src-bundle", type=Path)
    pf.add_argument("--set", action="append", default=[], help="key=value")
    sub.add_parser("validation-check", help="can a VALIDATION box with the real pair run the accuracy set here?")
    sc = sub.add_parser("session-check", help="free (D-1132): would a box in ENV route the session's calls here?")
    sc.add_argument("--env", required=True, choices=("DEV", "VALIDATION"))
    r = sub.add_parser("results")
    r.add_argument("results", type=Path)
    r.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "estimate":
            est = estimate([g for g in a.steps.replace(",", " ").split() if g], a.mode, a.only, a.session_hours)
            sys.stdout.write(json.dumps(est, indent=1) + "\n" if a.json else render_estimate(est))
            return 0
        if a.cmd == "settings":
            for k, v in settings().items():
                print(f"{k}={v}")
            return 0
        if a.cmd == "metadata":
            vals = dict(x.split("=", 1) for x in a.set)
            steps = [g for g in a.steps.replace(",", " ").split() if g]
            print(" ".join(metadata(steps, vals, a.out, a.mode, a.only)))
            return 0
        if a.cmd == "acc-tools":
            print(json.dumps(acc_tools(a.out)))
            return 0
        if a.cmd == "acc-score":
            print(json.dumps(acc_score(a.dir), ensure_ascii=False, indent=1))
            return 0
        if a.cmd == "resume-plan":
            plan = resume_plan(a.dir, a.deadline, a.redo)
            print(json.dumps(plan, ensure_ascii=False, indent=1))
            for line in plan["lines"]:
                print(line, file=sys.stderr)
            return 6 if plan["refused"] else 0
        if a.cmd == "acc-ids":
            ids = acc_ids(a.only, a.rs_tag, a.protocols)
            print(json.dumps(ids, ensure_ascii=False, indent=1))
            for r in ids["refused"]:
                print(f"box_run: --acc-protocols refused: {r}", file=sys.stderr)
            return 4 if ids["refused"] else 0
        if a.cmd == "src-bundle":
            sbr = src_bundle(a.commit, out=a.out, check=a.check)
            print(json.dumps(sbr, indent=1))
            if not sbr["ok"]:
                print(f"box_run: the source bundle is not usable: {sbr.get('why')}", file=sys.stderr)
            return 0 if sbr["ok"] else 5
        if a.cmd == "preflight":
            pfr = preflight([g for g in a.steps.replace(",", " ").split() if g],
                            dict(x.split("=", 1) for x in a.set), a.mode, a.only, a.src_bundle)  # fmt: skip
            print(json.dumps(pfr, ensure_ascii=False, indent=1))
            for c in pfr["checks"]:
                said = not c["pass"] or c["check"].startswith("protocols in flight")
                print(f"preflight: {'ok    ' if c['pass'] else 'FAILED'} {c['check']}"
                      + (f": {c['detail']}" if said else ""), file=sys.stderr)  # fmt: skip
            return 0 if pfr["ok"] else 6
        if a.cmd == "session-check":
            scr = session_check(a.env)
            print(json.dumps(scr, ensure_ascii=False, indent=1))
            for b in scr["blockers"]:
                print(f"session-check: refused: {b}", file=sys.stderr)
            return 0 if scr["can_run"] else 3
        if a.cmd == "validation-check":
            vc = validation_check()
            print(json.dumps(vc, ensure_ascii=False, indent=1))
            return 0 if vc["can_run"] else 3
    except ValueError as exc:
        print(f"box_run: {exc}", file=sys.stderr)
        return 2
    src: Path = a.results
    with tempfile.TemporaryDirectory() as t:
        if src.is_file():
            with tarfile.open(src) as tar:
                tar.extractall(t, filter="data")
            src = Path(t)
        res = results(src, a.out)
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / "summary.json").write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        (a.out / "report.md").write_text(render_results(res), encoding="utf-8")
    sys.stdout.write(render_results(res))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
