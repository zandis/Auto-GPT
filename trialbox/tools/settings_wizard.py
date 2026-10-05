"""Site onboarding wizard (SPEC §12 phase 9): writes a validated ``settings.yaml`` and a matching ``deploy/.env``.

Interactive by default (every question shows its default; Enter keeps it). ``--answers answers.yaml`` runs without
questions (automation, tests, re-runs); the answers file uses the same keys as the questions below. The result is
validated against ``schemas/settings.schema.json`` plus the cross-checks that the schema cannot express (practitioner
departments exist, mail recipients are inside the internal domains, the MRN regex compiles, the mapping file exists).
Secrets in ``.env`` (MinIO, Postgres, mailbox) are generated randomly unless given; the file is written with mode 0600.

    python -m tools.settings_wizard                                   # interactive
    python -m tools.settings_wizard --answers site_c.yaml --out deploy/settings.yaml --env-out deploy/.env
"""

from __future__ import annotations

import argparse
import re
import secrets
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
for _p in ("libs", "services"):
    sys.path.insert(0, str(ROOT / _p))

EXAMPLE = ROOT / "deploy" / "settings.example.yaml"
MAPPING_ROOT = ROOT / "services" / "adapter"

# key, question, default (None = from the example settings), kind
QUESTIONS: list[tuple[str, str, Any, str]] = [
    ("site_id", "Site id (short, upper case)", None, "str"),
    ("site_name", "Site name", None, "str"),
    ("tz", "Time zone (IANA)", "Asia/Taipei", "str"),
    ("locale", "Report language (zh-TW | ja)", "zh-TW", "str"),
    ("contact", "Box contact e-mail (operations)", None, "str"),
    ("internal_domains", "Internal mail domains (comma separated)", None, "list"),
    ("intake_address", "Intake mailbox address of the box", None, "str"),
    ("senders", "Allowed senders (comma separated)", None, "list"),
    ("physicians", "Physicians allowed to SUBMIT (comma separated)", None, "list"),
    ("reviewers", "Ruleset reviewers / approvers (comma separated)", None, "list"),
    ("alliance_sites", "Alliance member boxes (comma separated, may be empty)", [], "list"),
    ("data_source_type", "HIS source type (csv | cgrd_sql | fhir_bulk)", "csv", "str"),
    ("data_source_path", "Source directory (csv / fhir_bulk) or empty", "/data/source/site", "str"),
    ("data_source_dsn_env", "Env var holding the SQL DSN (cgrd_sql) or empty", "", "str"),
    ("mapping", "Mapping YAML (relative to services/adapter)", "mapping/tw_core/demo_his.yaml", "str"),
    ("mrn_regex", "MRN pattern (regular expression)", r"^\d{8}$", "str"),
    ("registry_type", "Consent registry (csv | sql | none)", "none", "str"),
    ("registry_path", "Registry CSV path (csv) or empty", "", "str"),
    ("departments", "Departments CODE=name (comma separated)", None, "map"),
    ("practitioners", "Practitioners id=name|dept|email|capacity|license (comma separated)", None, "practitioners"),
    ("llm_mode", "LLM (gpu | stub)", "gpu", "str"),
    ("cloud_enabled", "Allow the cloud LLM for protocol extraction (yes/no)", "no", "bool"),
    ("attachment_encryption", "PHI attachments (zip | smime)", "zip", "str"),
    ("twpas_enabled", "TWPAS bundles in NAV (yes/no)", "no", "bool"),
    ("twpas_org_id", "NHI hospital code (TWPAS)", "", "str"),
    ("alliance_root", "This box is the alliance root (yes/no)", "no", "bool"),
    ("alliance_root_address", "Alliance root box address (members only)", "", "str"),
    ("cohort_rulesets", "Cohort rulesets run quarterly (comma separated)", [], "list"),
    ("smtp_host", "Hospital SMTP relay host", "smtp.example.org", "str"),
    ("smtp_port", "SMTP port", "587", "str"),
    ("imap_host", "Intake IMAP host", "imap.example.org", "str"),
    ("imap_port", "IMAP port", "993", "str"),
    ("imap_user", "Intake mailbox user", "trialbox", "str"),
    ("mta_authserv_id", "authserv-id your MTA writes first in Authentication-Results (e.g. mx.hospital.tw)", "", "str"),
]


class WizardError(ValueError):
    pass


def _split(v: Any) -> list[str]:
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [x.strip() for x in str(v or "").split(",") if x.strip()]


def _bool(v: Any) -> bool:
    return v is True or str(v).strip().lower() in ("y", "yes", "true", "1")


def _map(v: Any) -> dict[str, str]:
    if isinstance(v, dict):
        return {str(k): str(x) for k, x in v.items()}
    out = {}
    for item in _split(v):
        k, _, name = item.partition("=")
        out[k.strip()] = name.strip()
    return out


def _practitioners(v: Any) -> dict[str, dict[str, Any]]:
    if isinstance(v, dict):
        return {str(k): dict(x) for k, x in v.items()}
    out: dict[str, dict[str, Any]] = {}
    for item in _split(v):
        pid, _, rest = item.partition("=")
        name, dept, email, cap, lic = ([*rest.split("|"), "", "", "", ""])[:5]
        p: dict[str, Any] = {"name": name.strip(), "department": dept.strip()}
        if email.strip():
            p["email"] = email.strip()
        if cap.strip():
            p["capacity_per_month"] = float(cap)
        if lic.strip():
            p["license"] = lic.strip()
        out[pid.strip()] = p
    return out


def defaults() -> dict[str, Any]:
    ex = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    return {
        "site_id": ex["site"]["id"],
        "site_name": ex["site"]["name"],
        "contact": ex["site"].get("contact", ""),
        "internal_domains": ex["internal_domains"],
        "intake_address": f"trialbox@{ex['internal_domains'][0]}",
        "senders": ex["allowlist"]["senders"],
        "physicians": ex["allowlist"].get("physicians", []),
        "reviewers": ex.get("reviewers", []),
        "departments": ex.get("departments", {}),
        "practitioners": ex.get("practitioners", {}),
    }


def ask(answers: dict[str, Any], prompt: Callable[[str], str] = input) -> dict[str, Any]:
    base = defaults()
    out: dict[str, Any] = {}
    for key, question, default, _kind in QUESTIONS:
        d = default if default is not None else base.get(key, "")
        shown = ", ".join(d) if isinstance(d, list) else d
        if isinstance(d, dict):
            shown = ", ".join(f"{k}=…" for k in d)
        reply = prompt(f"{question} [{shown}]: ").strip()
        out[key] = reply if reply else d
    out.update(answers)
    return out


def build(a: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    """Answers -> (settings dict, env dict, warnings). Raises WizardError on inconsistent answers."""
    base = defaults()

    def get(k: str) -> Any:
        return a.get(k, base.get(k))

    domains = _split(get("internal_domains"))
    senders, physicians, reviewers = _split(get("senders")), _split(get("physicians")), _split(get("reviewers"))
    errors: list[str] = []
    warnings: list[str] = []
    if not domains:
        errors.append("at least one internal mail domain is required")
    for who in senders + physicians + reviewers:
        if "@" not in who:
            errors.append(f"{who!r} is not an e-mail address")
        elif not any(who.lower().endswith("@" + d.lower()) or who.lower().endswith("." + d.lower()) for d in domains):
            warnings.append(f"{who} is outside the internal domains: it will never receive patient lists")
    try:
        re.compile(str(get("mrn_regex")))
    except re.error as exc:
        errors.append(f"mrn_regex does not compile: {exc}")
    depts = _map(get("departments"))
    prac = _practitioners(get("practitioners"))
    for pid, p in prac.items():
        if p.get("department") and p["department"] not in depts:
            errors.append(f"practitioner {pid}: department {p['department']!r} is not in departments")
    mapping = str(get("mapping"))
    if not (MAPPING_ROOT / mapping).exists() and not Path(mapping).exists():
        errors.append(f"mapping file {mapping} not found (copy a template from services/adapter/mapping/templates)")
    ds_type = str(get("data_source_type"))
    data_source: dict[str, Any] = {"type": ds_type, "mapping": mapping, "nightly_at": "02:00"}
    if ds_type == "cgrd_sql":
        if not get("data_source_dsn_env"):
            errors.append("cgrd_sql needs data_source_dsn_env (the env var holding the DSN)")
        data_source["dsn_env"] = str(get("data_source_dsn_env"))
    else:
        data_source["path"] = str(get("data_source_path"))
    reg_type = str(a.get("registry_type", "none"))
    registry: dict[str, Any] = {"type": reg_type}
    if reg_type == "csv":
        registry["path"] = str(a.get("registry_path", ""))
    alliance_root = _bool(a.get("alliance_root", "no"))
    root_addr = str(a.get("alliance_root_address", "") or "")
    if not alliance_root and _split(a.get("cohort_rulesets")) and not root_addr:
        warnings.append("cohort rulesets without an alliance root address: tables stay on this box")
    if not str(a.get("mta_authserv_id") or "").strip():
        warnings.append(
            "mta_authserv_id is empty: the top-most Authentication-Results header is trusted whoever wrote it; set it "
            "unless the MTA always adds its own header in front of the intake mailbox"
        )
    twpas = _bool(a.get("twpas_enabled", "no"))
    if twpas and not a.get("twpas_org_id"):
        errors.append("TWPAS needs the NHI hospital code (twpas_org_id)")
    if errors:
        raise WizardError("; ".join(errors))
    site_id = str(get("site_id")).upper()
    settings: dict[str, Any] = {
        "site": {
            "id": site_id,
            "name": str(get("site_name")),
            "tz": str(a.get("tz", "Asia/Taipei")),
            "locale": str(a.get("locale", "zh-TW")),
            "contact": str(get("contact")),
        },
        "internal_domains": domains,
        "allowlist": {
            "senders": senders,
            "physicians": physicians,
            "alliance_sites": _split(a.get("alliance_sites")),
        },
        "permissions": {
            "FEAS": ["senders"],
            "SCREEN": ["senders"],
            "NAV": ["senders"],
            "COHORT": ["senders", "alliance_sites"],
            "APPROVE": ["reviewers"],
            "STATUS": ["senders", "reviewers"],
            "CANCEL": ["senders"],
            "FEEDBACK": ["senders"],
            "SUBMIT": ["physicians"],
        },
        "reviewers": reviewers,
        "require_spf_dkim": True,
        "rate_limit_per_sender_per_day": 20,
        "data_source": data_source,
        "mrn_regex": str(get("mrn_regex")),
        "profiles": {"tw_core": "1.0.0", "twpas_version": "1.2.0"},
        "models": {
            "judge": "qwen3.5-35b-a3b-q4",
            "extract_local": "gpt-oss-120b-mxfp4",
            "embed": "bge-m3",
            "cloud_enabled": _bool(a.get("cloud_enabled", "no")),
        },
        "thresholds": {
            "tier_high_confidence": 0.75,
            "small_cell": 5,
            "equivalence_min_pct": 98,
            "validation_error_max_pct": 0.5,
        },
        "schedule": {
            "ingest": "02:00",
            "microbatch": "MON 03:00",
            "nav": "MON 03:30",
            "cohort": "1st 04:00",
            "retention": "05:00",
            "calibration": "1st 05:30",
        },
        "registry_source": registry,
        "attachment_encryption": str(a.get("attachment_encryption", "zip")),
        "departments": depts,
        "practitioners": prac,
        "retention": {
            "attachments_days": 90,
            "outputs_days": 365,
            "logs_days": 180,
            "nightly_snapshots": 3,
            "month_end_snapshots_months": 36,
            "pool_months_after_ruleset": 24,
            "audit_years": 10,
        },
        "calibration_defaults": {"reach_rate": 0.6, "accept_rate": 0.35},
        "twpas": {"enabled": twpas, "dry_run": True, **({"org_id": str(a["twpas_org_id"])} if twpas else {})},
        "cohort": {
            "alliance_root": alliance_root,
            **({"root_address": root_addr} if root_addr else {}),
            "rulesets": _split(a.get("cohort_rulesets")),
            "ctgov_cache_days": 30,
        },
    }
    intake = str(get("intake_address"))
    env = {
        "TB_SITE_ID": site_id,
        "TB_TZ": settings["site"]["tz"],
        "COMPOSE_PROFILES": "gpu" if str(a.get("llm_mode", "gpu")) == "gpu" else "stub",
        "TB_LLM_MODE": "vllm" if str(a.get("llm_mode", "gpu")) == "gpu" else "stub",
        "TB_EMBED_MODE": "model" if str(a.get("llm_mode", "gpu")) == "gpu" else "hash",
        "IMAP_HOST": str(a.get("imap_host", "")),
        "IMAP_PORT": str(a.get("imap_port", "993")),
        "IMAP_SSL": "true",
        "IMAP_USER": str(a.get("imap_user", "trialbox")),
        "IMAP_PASS": str(a.get("imap_pass") or secrets.token_urlsafe(18)),
        "SMTP_HOST": str(a.get("smtp_host", "")),
        "SMTP_PORT": str(a.get("smtp_port", "587")),
        "SMTP_STARTTLS": "true",
        "SMTP_USER": str(a.get("smtp_user", "")),
        "SMTP_PASS": str(a.get("smtp_pass", "")),
        "MAIL_INTAKE_ADDR": intake,
        "MAIL_FROM_ADDR": intake,
        "TB_MAIL_AUTHSERV_ID": str(a.get("mta_authserv_id") or "").strip(),
        "FHIR_BASE_URL": "http://fhir-store:8080/fhir",
        "LAKE_URL": "http://lake:8013",
        "EMBED_URL": "http://embed-service:8014",
        "LLM_BASE_URL": "http://llm-service:8000/v1",
        "LLM_MODEL": "qwen3.5-35b-a3b-q4",
        "CLOUD_LLM_BASE_URL": str(a.get("cloud_llm_base_url", "")),
        "CLOUD_LLM_API_KEY": str(a.get("cloud_llm_api_key", "")),
        "TB_OBJECT_STORE": "minio",
        "MINIO_ENDPOINT": "minio:9000",
        "MINIO_ACCESS_KEY": "trialbox",
        "MINIO_SECRET_KEY": secrets.token_urlsafe(24),
        "NHI_TWPAS_BASE_URL": "",
        "ATTACH_PASSWORD_MODE": settings["attachment_encryption"],
        "LOG_LEVEL": "INFO",
        "POSTGRES_PASSWORD": secrets.token_urlsafe(24),
        "TB_SETTINGS": "/etc/trialbox/settings.yaml",
        "TB_CTGOV_MODE": "live",
    }
    if ds_type == "cgrd_sql" and a.get("data_source_dsn"):
        env[str(get("data_source_dsn_env"))] = str(a["data_source_dsn"])
    return settings, env, warnings


def write(settings: dict[str, Any], env: dict[str, str], out: Path, env_out: Path | None) -> None:
    from tb_common.config import load_settings

    out.parent.mkdir(parents=True, exist_ok=True)
    header = (
        f"# TrialBox settings.yaml for {settings['site']['id']} — written by tools/settings_wizard.py.\n"
        "# Validated against schemas/settings.schema.json; services refuse to start on error. Re-run the wizard\n"
        "# with --answers to regenerate, or edit and check with: python -m tools.settings_wizard --check <file>\n"
    )
    out.write_text(header + yaml.safe_dump(settings, allow_unicode=True, sort_keys=False), encoding="utf-8")
    load_settings(out)  # the same validation the services run at start-up
    if env_out is not None:
        env_out.parent.mkdir(parents=True, exist_ok=True)
        env_out.write_text(
            "# TrialBox environment — written by tools/settings_wizard.py (secrets generated); root only.\n"
            + "".join(f"{k}={v}\n" for k, v in env.items()),
            encoding="utf-8",
        )
        env_out.chmod(0o600)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--answers", type=Path, help="YAML answers file (no questions)")
    ap.add_argument("--out", type=Path, default=ROOT / "deploy" / "settings.yaml")
    ap.add_argument("--env-out", type=Path, help="also write the .env (mode 0600)")
    ap.add_argument("--check", type=Path, help="only validate an existing settings.yaml")
    args = ap.parse_args(argv)
    from tb_common.config import ConfigError, load_settings

    if args.check:
        try:
            s = load_settings(args.check)
        except ConfigError as exc:
            print(f"INVALID: {exc}", file=sys.stderr)
            return 1
        print(f"OK: {args.check} — site {s.site.id}, {len(s.allowlist.senders)} senders")
        return 0
    answers = yaml.safe_load(args.answers.read_text(encoding="utf-8")) if args.answers else {}
    a = answers if args.answers else ask({})
    try:
        settings, env, warnings = build(a)
        write(settings, env, args.out, args.env_out)
    except (WizardError, ConfigError) as exc:
        print(f"not written: {exc}", file=sys.stderr)
        return 1
    for w in warnings:
        print(f"warning: {w}")
    print(f"wrote {args.out}" + (f" and {args.env_out} (0600)" if args.env_out else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
