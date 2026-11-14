"""The box run's driver helper (deploy/gcp/box-run.sh): the estimate, the run's metadata, and the results reader.

The box run is lane G's main paid line (R2 and plan v7 §7.1 G-2, G-6, G-9, G-10): the signed bundle built on the
runner VM with the vendor key from Secret Manager, then the shipped box installed from it on the GPU VM by the real
installer, and every test run on that installed box (deploy/gcp/box-install-run.sh does the work on the VM).

    python -m tools.box_run estimate --steps build,start,g6,g9,g10 [--json]
    python -m tools.box_run settings                       # the declared settings, as shell lines
    python -m tools.box_run metadata --steps ... --out DIR [--set key=value ...]   # one file per metadata key
    python -m tools.box_run results RESULTS.tgz|DIR [--out DIR]   # summary.json and report.md: checks per test,
                                                                 # and what every result names (provenance)

The estimate says where each figure comes from: ``measured`` (a run named), ``constant`` (a driver constant with its
reason), ``plan`` (a plan's own estimate) or ``unknown`` (nothing measured: the cap bounds it). It never invents a
figure: a step with no source is ``unknown`` and the US$ is given at the cap.

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
}
GROUPS = ("build", "start", "g6", "g9", "g10")


def row(group: str, what: str, seconds: float | None, kind: str, source: str) -> dict[str, Any]:
    return {"group": group, "step": what, "seconds": seconds, "kind": kind, "source": source}


def rows_for(group: str, with_g6: bool) -> list[dict[str, Any]]:
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
    if group == "start":
        return [
            boot,
            row(group, "01 fetch the bundle, sha256, manifest", None, "unknown", "-"),
            row(group, "02 installer (prepare: images loaded, stack up)", None, "unknown", "-"),
            row(
                group,
                "  of which the model servers ready",
                117.0 + 82.0,
                "measured",
                FIT + ": judge 117 s + verifier 82 s",
            ),
            row(group, "03 first run (wizard, apply, restart)", None, "unknown", "-"),
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


def estimate(groups: list[str]) -> dict[str, Any]:
    """Per launch: the known seconds (with sources), the cap, US$ spot and on demand at the known part and at the cap.
    ``build`` is its own launch (another service account); start, g6, g9, g10 are one launch."""
    bad = [g for g in groups if g not in GROUPS]
    if bad:
        raise ValueError(f"unknown step groups {bad}: one or more of {', '.join(GROUPS)}")
    launches = [["build"]] if "build" in groups else []
    box = [g for g in GROUPS[1:] if g in groups]
    if box:
        launches.append(box)
    out: list[dict[str, Any]] = []
    for gs in launches:
        rows = [r for g in gs for r in rows_for(g, "g6" in gs)]
        if gs != ["build"]:  # one VM start for the launch
            rows = [r for i, r in enumerate(rows) if r["step"] != "VM start" or i == 0]
        known = sum(r["seconds"] or 0 for r in rows) / 3600
        cap = sum(GROUP_CAP_HOURS[g] for g in gs)
        out.append(
            {
                "groups": gs,
                "rows": rows,
                "known_hours": round(known, 2),
                "unknown_steps": [r["step"] for r in rows if r["seconds"] is None],
                "cap_hours": cap,
                "usd_known_spot": round(known * PRICE_PER_HOUR, 2),
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
        "price_per_hour_spot": PRICE_PER_HOUR,
        "price_per_hour_on_demand": ON_DEMAND_PRICE_PER_HOUR,
        "launches": out,
        "total": total,
    }


def render_estimate(e: dict[str, Any]) -> str:
    lines = [
        f"Prices: g4-standard-48 + RTX PRO 6000, spot US${e['price_per_hour_spot']}/h, on demand "
        f"US${e['price_per_hour_on_demand']}/h (tools/complete_run.py)."
    ]
    for x in e["launches"]:
        lines += ["", f"Launch: {' + '.join(x['groups'])}", f"  {'step':58} {'seconds':>9}  source"]
        for r in x["rows"]:
            s = "unknown" if r["seconds"] is None else f"{r['seconds']:.0f}"
            lines.append(f"  {r['step'][:58]:58} {s:>9}  {r['kind']}: {r['source']}")
        lines.append(
            f"  known part {x['known_hours']} h (US${x['usd_known_spot']} spot); {len(x['unknown_steps'])} step(s) "
            f"unmeasured, bounded by the cap: {x['cap_hours']} h = US${x['usd_cap_spot']} spot / "
            f"US${x['usd_cap_on_demand']} on demand"
        )
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


def metadata(groups: list[str], values: dict[str, str], out: Path) -> list[str]:
    """One file per metadata key (gcloud --metadata-from-file: a value may hold commas and spaces). Refuses a value
    that looks like a key: the metadata holds names and versions, never a secret."""
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
    }
    missing = sorted({k for g in groups for k in must[g] if not values.get(k)})
    if missing:
        raise ValueError(f"missing for {','.join(groups)}: {', '.join(missing)}")
    for k, v in values.items():
        if "PRIVATE KEY" in v or "BEGIN " in v:
            raise ValueError(f"{k}: a key in the metadata is refused (Secret Manager, by name)")
    out.mkdir(parents=True, exist_ok=True)
    vals = {
        **values,
        "tb-steps": " ".join(g for g in GROUPS if g in groups),
        "tb-max-minutes": str(sum(GROUP_CAP_HOURS[g] for g in groups) * 60 - 5),
    }
    if "build" in groups:
        vals.setdefault("tb-vendor-key-secret", settings()["KEY_SECRET"])
    names = []
    for k, v in sorted(vals.items()):
        (out / k).write_text(v, encoding="utf-8")
        names.append(k)
    return names


# ------------------------------------------------------------------------------------------------ the results reader
def _load(d: Path, rel: str) -> Any:
    try:
        return json.loads((d / rel).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def results(d: Path) -> dict[str, Any]:
    """What a box run's results say: per test its checks (from the parts), and what every result names."""
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
    provenance = {
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
        tests["G-2 production start"] = [
            check(
                "no stop in steps 01 to 12 (no shell beyond the installer)",
                not [s for s in stops if s["step"][:2] < "13"],
                stops,
            ),
            check("the bundle as PRODUCTION reads it", b01.get("refused") == [], b01.get("refused")),
            check(
                "the wizard answered through the console's page",
                ((parts.get("03-wizard") or {}).get("detail") or {}).get("wizard") == "done",
            ),
            check(
                "G-1 identity: template, image digests, weights, prompts as pinned",
                identity.get("pass"),
                identity.get("checks"),
            ),
            check("pair canary", (parts.get("07-canary") or {}).get("pass")),
            check("qualification record passed", ((rec.get("qualification.json") or {}).get("passed")) is True),
            check(
                "PRODUCTION resolves to the promoted builds",
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
    return {
        "ended": state.get("ended"),
        "steps": len(parts),
        "stops": stops,
        "provenance": provenance,
        "tests": tests,
        "minutes": {k: v.get("minutes") for k, v in parts.items()},
    }


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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("estimate")
    e.add_argument("--steps", required=True)
    e.add_argument("--json", action="store_true")
    sub.add_parser("settings")
    m = sub.add_parser("metadata")
    m.add_argument("--steps", required=True)
    m.add_argument("--out", type=Path, required=True)
    m.add_argument("--set", action="append", default=[], help="key=value")
    r = sub.add_parser("results")
    r.add_argument("results", type=Path)
    r.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "estimate":
            est = estimate([g for g in a.steps.replace(",", " ").split() if g])
            sys.stdout.write(json.dumps(est, indent=1) + "\n" if a.json else render_estimate(est))
            return 0
        if a.cmd == "settings":
            for k, v in settings().items():
                print(f"{k}={v}")
            return 0
        if a.cmd == "metadata":
            vals = dict(x.split("=", 1) for x in a.set)
            print(" ".join(metadata([g for g in a.steps.replace(",", " ").split() if g], vals, a.out)))
            return 0
    except ValueError as exc:
        print(f"box_run: {exc}", file=sys.stderr)
        return 2
    src: Path = a.results
    with tempfile.TemporaryDirectory() as t:
        if src.is_file():
            with tarfile.open(src) as tar:
                tar.extractall(t, filter="data")
            src = Path(t)
        res = results(src)
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / "summary.json").write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        (a.out / "report.md").write_text(render_results(res), encoding="utf-8")
    sys.stdout.write(render_results(res))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
