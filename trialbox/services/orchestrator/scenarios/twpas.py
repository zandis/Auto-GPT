"""TWPAS bundles inside NAV (SPEC §8.4, §9.5): inputs from the record + in-box identity, one HL7 validator run for all
bundles of a job (``-ig tw.gov.mohw.nhi.pas``), the NHI pre-check, outputs stored per patient."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from tb_common.ruleset import Ruleset
from tb_contracts import NavRow, Precheck

from orchestrator.core import Ctx
from orchestrator.reports import twpas_bundle
from orchestrator.scenarios.facts import Facts

DEFAULT_IG = "tw.gov.mohw.nhi.pas#1.2.0"  # the only version on the npm mirror (DECISIONS D-63)
_ECOG = re.compile(r"ECOG\s*體能狀態\s*(\d)\s*分|ECOG\s*(?:PS)?\s*[:：]?\s*(\d)", re.I)


@dataclass
class Built:
    row: NavRow
    bundle: dict[str, Any] | None
    issues: list[str]


def ig_spec(ctx: Ctx) -> str:
    env = os.environ.get("TB_TWPAS_IG")
    if env:
        return env
    want = (
        f"tw.gov.mohw.nhi.pas#{ctx.cfg.settings.profiles.twpas_version}"
        if ctx.cfg.settings.profiles and ctx.cfg.settings.profiles.twpas_version
        else DEFAULT_IG
    )
    home = Path(os.environ.get("TB_FHIR_PACKAGE_HOME", "/opt/hl7/home")) / ".fhir" / "packages"
    return want if (home / want).exists() else DEFAULT_IG


def enabled(ctx: Ctx, rs: Ruleset) -> bool:
    site = ctx.cfg.settings.twpas
    return bool(rs.manifest.twpas and rs.manifest.twpas.enabled and site and site.enabled)


def _identity(ctx: Ctx, pid: str) -> dict[str, str]:
    sec = Path(ctx.cfg.env.secrets_dir)
    if not (sec / "pid_map.sqlite").exists():
        return {}
    from adapter.pidmap import PidMap

    pm = PidMap(sec / "pid_map.sqlite", sec / "pid_map.key")
    try:
        out = dict(pm.identity(pid) or {})
        mrn = pm.resolve(pid)
        if mrn:
            out["mrn"] = mrn
        return out
    finally:
        pm.close()


def _latest(ctx: Ctx, pid: str, code: str, run_date: date, value: str = "value_num") -> tuple[Any, str | None]:
    col = {"value_num": "value_num", "value_code": "value_code"}[value]
    rows = ctx.services.lake.query(
        f"SELECT {col} AS v, CAST(effective AS DATE) AS d FROM observation WHERE pid = $1 AND code = $2 "
        f"AND CAST(effective AS DATE) <= CAST($3 AS DATE) AND {col} IS NOT NULL ORDER BY effective DESC, oid DESC "
        "LIMIT 1",
        [pid, code, run_date.isoformat()],
    ).to_pylist()
    return (rows[0]["v"], rows[0]["d"].isoformat()) if rows else (None, None)


def build_one(ctx: Ctx, rs: Ruleset, row: NavRow, f: Facts, run_date: date, renewal: bool) -> Built:
    issues: list[str] = []
    ident = _identity(ctx, row.pid)
    pr = (ctx.cfg.settings.practitioners or {}).get(row.practitioner_id or "")
    site = ctx.cfg.settings.twpas
    weight, _ = _latest(ctx, row.pid, "29463-7", run_date)
    height, _ = _latest(ctx, row.pid, "8302-2", run_date)
    egfr, egfr_date = _latest(ctx, row.pid, "EGFR-MUT", run_date, "value_code")
    ecog = ecog_date = None
    for v in row.criteria:
        q = (v.evidence.quote or "") if v.evidence else ""
        m = _ECOG.search(q)
        if m:
            ecog, ecog_date = int(m.group(1) or m.group(2)), v.evidence.quote_date if v.evidence else None
    sex = {"male": "male", "female": "female", "男": "male", "女": "female"}.get(str(f.get("sex") or ""), "unknown")
    inp = twpas_bundle.TwpasInput(
        pid=row.pid,
        mrn=ident.get("mrn", ""),
        name=ident.get("name", ""),
        national_id=ident.get("national_id", ""),
        gender=sex,
        birth_date=str(f.get("birth_date") or ""),
        practitioner_id=row.practitioner_id or "",
        practitioner_license=(pr.license if pr and pr.license else ""),
        org_id=(site.org_id if site and site.org_id else ""),
        org_name=(site.org_name if site and site.org_name else ctx.cfg.settings.site.name),
        department=(rs.manifest.scopes.nav.departments or ["02"])[0]
        if rs.manifest.scopes and rs.manifest.scopes.nav
        else "02",
        run_date=run_date,
        diagnosis_code=str(f.get("diagnosis_code") or ""),
        diagnosis_date=f.get("diagnosis_date"),
        weight_kg=weight,
        height_cm=height,
        drug_code=(rs.manifest.twpas.drug_codes or [""])[0] if rs.manifest.twpas else "",
        apply_type=(rs.manifest.twpas.apply_type or "1") if rs.manifest.twpas else "1",
        continuation="2" if renewal else "1",
        program_text=rs.manifest.title or rs.id,
        egfr_positive=None if egfr is None else egfr == "LA9633-4",
        egfr_date=egfr_date,
        ecog=ecog,
        ecog_date=ecog_date,
        summary=f"{f.get('diagnosis') or ''} {f.get('diagnosis_code') or ''}".strip(),
    )
    try:
        bundle = twpas_bundle.build(inp)
    except twpas_bundle.BundleDataMissing as exc:
        return Built(row, None, [str(exc)])
    issues += twpas_bundle.structural_errors(bundle)
    return Built(row, bundle, issues)


def validate(ctx: Ctx, built: list[Built]) -> tuple[str, dict[int, list[str]]]:
    """One HL7 validator run for every bundle (the IG load dominates: ~40 s); structural fallback without the JVM.
    Returns the engine (``hl7-validator`` | ``structural``) and the errors per bundle index."""
    from adapter.validate.validator import Hl7Validator

    with_bundle = [b for b in built if b.bundle is not None]
    v = Hl7Validator.from_env()
    if v is None or not with_bundle:
        return "structural", {i: list(b.issues) for i, b in enumerate(with_bundle) if b.issues}
    v.igs = [ig_spec(ctx)]
    res = v.validate([b.bundle for b in with_bundle if b.bundle is not None])
    per_file = dict(res.per_file)
    for i, b in enumerate(with_bundle):  # R4B structural findings count as errors too
        if b.issues:
            per_file[i] = [*per_file.get(i, []), *b.issues]
    return "hl7-validator", per_file


def attach(ctx: Ctx, rs: Ruleset, built: list[Built], list_to: list[str]) -> list[Any]:
    """Validate + pre-check + publish; fills each row's ``twpas_bundle_key`` and ``precheck``."""
    from orchestrator.precheck import PrecheckRunner

    outputs: list[Any] = []
    with_bundle = [b for b in built if b.bundle is not None]
    engine, per_file = validate(ctx, built)
    runner = PrecheckRunner(ctx.services.fhir)
    lib = rs.manifest.twpas.precheck_library if rs.manifest.twpas else None
    report: dict[str, Any] = {"ig": ig_spec(ctx), "validator": engine, "bundles": []}
    for i, b in enumerate(with_bundle):
        assert b.bundle is not None
        errors = per_file.get(i, [])
        pre = runner.run(lib, b.bundle) if lib else None
        issues = [*errors, *(pre.issues if pre else [])]
        passed = (not errors) and (pre.passed if pre and pre.passed is not None else True)
        b.row.precheck = Precheck(
            passed=passed if (pre is None or pre.passed is not None) else None,
            issues=issues,
            validator_errors=len(errors),
        )
        out = ctx.publish(
            f"twpas_{rs.id}_{b.row.pid[:12]}.json",
            (json.dumps(b.bundle, ensure_ascii=False, indent=1) + "\n").encode(),
            "phi",
            list_to,
        )
        b.row.twpas_bundle_key = out.minio_key
        outputs.append(out)
        report["bundles"].append(
            {
                "pid": b.row.pid,
                "file": out.filename,
                "validator_errors": errors,
                "precheck": None if pre is None else {"passed": pre.passed, "issues": pre.issues},
            }
        )
    for b in built:
        if b.bundle is None:
            b.row.precheck = Precheck(passed=False, issues=b.issues, validator_errors=0)
            report["bundles"].append({"pid": b.row.pid, "file": None, "issues": b.issues})
    if report["bundles"]:
        outputs.append(
            ctx.publish(
                f"twpas_validation_{rs.id}.json",
                (json.dumps(report, ensure_ascii=False, indent=1) + "\n").encode(),
                "phi",
                list_to,
            )
        )
    return outputs
