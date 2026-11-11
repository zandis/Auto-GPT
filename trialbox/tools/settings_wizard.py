"""Site onboarding wizard (SPEC §12 phase 9): writes a validated ``settings.yaml`` and a matching ``deploy/.env``.

Interactive by default (every question shows its default; Enter keeps it). ``--answers answers.yaml`` runs without
questions (automation, tests, re-runs); the answers file uses the same keys as the questions below. The result is
validated against ``schemas/settings.schema.json`` plus the cross-checks that the schema cannot express (practitioner
departments exist, mail recipients are inside the internal domains, the MRN regex compiles, the mapping file exists).
Secrets in ``.env`` (MinIO, Postgres, mailbox) are generated randomly unless given; the file is written with mode 0600.

Site inputs (T-632, D-382): the mapping is looked up in the site's mapping folder first (``--mapping-dir``,
``TB_MAPPING_DIR``, the ``mapping/`` folder beside the answers file, ``deploy/site/mapping``), then in the image, as
the adapter does (``adapter.mapping.site``). The feed folder on the host becomes ``TB_SOURCE_DIR`` and the settings'
``data_source.path`` the folder it is mounted at (``TB_SOURCE_MOUNT``). The console's DNS name and certificate mode
become ``TB_TLS_HOSTNAME`` and ``TB_TLS_MODE``: ``deploy/install.sh`` turns TLS on from them.

    python -m tools.settings_wizard                                   # interactive
    python -m tools.settings_wizard --answers site_c.yaml --out deploy/settings.yaml --env-out deploy/.env
"""

from __future__ import annotations

import argparse
import os
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
SITE_MAPPING = ROOT / "deploy" / "site" / "mapping"  # the site's own mappings (kept by every update, D-367)
TLS_MODES = ("internal", "hospital")

# key, question, default (None = from the example settings), kind
QUESTIONS: list[tuple[str, str, Any, str]] = [
    ("site_id", "Site id (short, upper case)", None, "str"),
    ("site_name", "Site name", None, "str"),
    ("tz", "Time zone (IANA, e.g. Asia/Tokyo; the mapping's tz)", "", "str"),  # no default zone (D-315)
    ("locale", "Report language (zh-TW | ja)", "zh-TW", "str"),
    ("contact", "Box contact e-mail (operations)", None, "str"),
    ("internal_domains", "Internal mail domains (comma separated)", None, "list"),
    ("intake_address", "Intake mailbox address of the box", None, "str"),
    ("senders", "Allowed senders (comma separated)", None, "list"),
    ("physicians", "Physicians allowed to SUBMIT (comma separated)", None, "list"),
    ("reviewers", "Ruleset reviewers / approvers (comma separated)", None, "list"),
    ("alliance_sites", "Alliance member boxes (comma separated, may be empty)", [], "list"),
    ("data_source_type", "HIS source type (csv | cgrd_sql | fhir_bulk)", "csv", "str"),
    ("data_source_path", "Source directory as the adapter sees it (csv / fhir_bulk)", "/data/source/site", "str"),
    # T-632 (OPS-011): the host folder the nightly export lands in; compose mounts it at data_source_path
    ("data_source_host_dir", "Feed folder on this host (relative = under deploy/)", "./site/feed", "str"),
    ("data_source_dsn_env", "Env var holding the SQL DSN (cgrd_sql) or empty", "", "str"),
    ("mapping", "Mapping YAML (in deploy/site/mapping, else the shipped ones)", "mapping/tw_core/demo_his.yaml", "str"),
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
    # T-632 (OPS-013): the console is reached at https://<tls_hostname> through Caddy (RUNBOOK §12)
    ("tls_hostname", "Console DNS name for https (from hospital IT)", "", "str"),
    ("tls_mode", "Certificate (internal = Caddy's own CA | hospital = the hospital's)", "internal", "str"),
    ("tls_cert_file", "Hospital certificate and chain, PEM (hospital mode)", "", "str"),
    ("tls_key_file", "Its key, PEM (hospital mode)", "", "str"),
    # D-138: log retention per country (tb_common.retention.DEFAULTS); "" = from the report language (ja -> jp)
    ("retention_rules", "Retention defaults (jp | tw; empty = from the report language)", "", "str"),
    ("logs_days", "Days to keep service logs (empty = the default of those rules)", "", "str"),
    ("mail_log_days", "Days to keep the mail logs (empty = the default of those rules)", "", "str"),
    # D-140 (owner, 2026-11-09): ClinicalTrials.gov offline (the data pack of each update) unless the hospital says live
    ("ctgov_mode", "ClinicalTrials.gov (offline | live)", "offline", "ctgov"),
]

# D-140: the ClinicalTrials.gov choice in plain words, in the three languages of the box (install.sh asks the same)
CTGOV_QUESTION = {
    "en": "ClinicalTrials.gov: may this box reach clinicaltrials.gov on the internet?\n"
    "  offline = no (default). TrialBox uses the copy that comes with each update: no outbound access; the data are "
    "as of the update.\n"
    "  live    = yes. TrialBox asks ClinicalTrials.gov directly: always current; one outbound address; no patient data "
    "is sent.",
    "ja": "ClinicalTrials.gov：この機器からインターネット上の clinicaltrials.gov に接続してよいですか？\n"
    "  offline = いいえ（既定）。更新のたびに届く写しを使います。外部へは接続しません。データは更新の時点のものです。\n"
    "  live    = はい。TrialBox が ClinicalTrials.gov に直接問い合わせます。常に最新。外部への接続先は1か所で、"
    "患者データは送りません。",
    "zh-TW": "ClinicalTrials.gov：本機可以連上網際網路的 clinicaltrials.gov 嗎？\n"
    "  offline = 不可以（預設）。使用每次更新附帶的資料副本：不對外連線；資料為該次更新當時的版本。\n"
    "  live    = 可以。TrialBox 直接查詢 ClinicalTrials.gov：資料隨時最新；只對外連一個位址；不傳送病人資料。",
}
CTGOV_MODES = ("offline", "live")


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
    preset = os.environ.get("TB_CTGOV_MODE", "").strip().lower()  # install.sh --ctgov: already answered
    for key, question, default, kind in QUESTIONS:
        if kind == "ctgov":
            if preset in CTGOV_MODES:
                out[key] = preset
                continue
            print("\n".join(CTGOV_QUESTION[lang] for lang in ("en", "ja", "zh-TW")))
        d = default if default is not None else base.get(key, "")
        shown = ", ".join(d) if isinstance(d, list) else d
        if isinstance(d, dict):
            shown = ", ".join(f"{k}=…" for k in d)
        reply = prompt(f"{question} [{shown}]: ").strip()
        out[key] = reply if reply else d
    out.update(answers)
    return out


def _zone_errors(tz: str, mapping: Path) -> list[str]:
    """site.tz must be a real zone and the one the data source mapping states (D-315, doctor check site_tz)."""
    from zoneinfo import ZoneInfo

    if not tz:
        return ["tz is required: the site's IANA time zone (for example Asia/Tokyo)"]
    try:
        ZoneInfo(tz)
    except Exception:
        return [f"tz {tz!r} is not a valid IANA time zone"]
    try:
        stated = (yaml.safe_load(mapping.read_text(encoding="utf-8")) or {}).get("tz")
    except (OSError, yaml.YAMLError, AttributeError):
        return []  # a missing mapping is reported above
    if stated and str(stated) != tz:
        return [f"tz {tz} differs from the mapping's tz {stated} ({mapping.name}): the source's days would move"]
    return []


def find_mapping(mapping: str, mapping_dirs: list[Path] | None = None) -> Path:
    """The mapping file, as the adapter finds it: the site's folders first, then the image (T-632)."""
    from adapter.mapping.site import resolve

    path = Path(mapping)
    if path.is_absolute() or path.exists():  # an absolute path, or one relative to where the wizard runs
        return path
    return resolve(mapping, [*(mapping_dirs or []), SITE_MAPPING])


def build(
    a: dict[str, Any], mapping_dirs: list[Path] | None = None
) -> tuple[dict[str, Any], dict[str, str], list[str]]:
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
    mapping = str(get("mapping") or "mapping/tw_core/demo_his.yaml")
    mapping_file = find_mapping(mapping, mapping_dirs)
    if not mapping_file.is_file():
        errors.append(
            f"mapping file {mapping} not found in the site mapping folder (deploy/site/mapping) or the image "
            "(copy a template from services/adapter/mapping/templates into deploy/site/mapping)"
        )
    tz = str(a.get("tz") or "").strip()  # the site's zone: one answer, no default (D-315)
    errors += _zone_errors(tz, mapping_file)
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
    ctgov = str(a.get("ctgov_mode") or os.environ.get("TB_CTGOV_MODE") or "offline").strip().lower()
    if ctgov not in CTGOV_MODES:
        errors.append(f"ctgov_mode must be offline or live, not {ctgov!r}")
    elif ctgov == "live":
        warnings.append(
            "ClinicalTrials.gov live: the box will reach clinicaltrials.gov:443 (the network sheet lists it)"
        )
    tls_host = str(a.get("tls_hostname") or "").strip()
    tls_mode = str(a.get("tls_mode") or "internal").strip().lower()
    tls_env: dict[str, str] = {}
    if tls_mode not in TLS_MODES:
        errors.append(f"tls_mode must be internal or hospital, not {tls_mode!r}")
    elif tls_host:
        if not re.fullmatch(r"[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?", tls_host) or "." not in tls_host:
            errors.append(f"tls_hostname {tls_host!r} is not a DNS name (for example trialbox.hospital.tw)")
        tls_env = {"TB_TLS_HOSTNAME": tls_host, "TB_TLS_MODE": tls_mode}
        if tls_mode == "hospital":
            for k, var in (("tls_cert_file", "TB_TLS_CERT_FILE"), ("tls_key_file", "TB_TLS_KEY_FILE")):
                if not str(a.get(k) or "").strip():
                    errors.append(f"tls_mode hospital needs {k}")
                tls_env[var] = str(a.get(k) or "").strip()
    else:
        warnings.append("tls_hostname is empty: install.sh asks for it (a PRODUCTION box runs only behind https)")
    twpas = _bool(a.get("twpas_enabled", "no"))
    if twpas and not a.get("twpas_org_id"):
        errors.append("TWPAS needs the NHI hospital code (twpas_org_id)")
    from tb_common.retention import defaults_for

    rules = str(a.get("retention_rules") or "").strip().lower() or (
        "jp" if str(a.get("locale", "zh-TW")).startswith("ja") else "tw"
    )
    retention: dict[str, int] = {}
    try:
        retention = defaults_for(rules, {k: a.get(k) for k in ("logs_days", "mail_log_days", "outputs_days",
                                                               "attachments_days")})  # fmt: skip
    except ValueError as exc:
        errors.append(str(exc))
    if errors:
        raise WizardError("; ".join(errors))
    site_id = str(get("site_id")).upper()
    settings: dict[str, Any] = {
        "site": {
            "id": site_id,
            "name": str(get("site_name")),
            "tz": tz,
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
        "profiles": {"tw_core": "1.0.0", "twpas_version": "1.2.5"},
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
        "retention": retention,
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
        "TB_OBJECT_STORE": "fs:/data/objects",
        "TB_SERVICE_TOKEN": secrets.token_urlsafe(24),
        "NHI_TWPAS_BASE_URL": "",
        "ATTACH_PASSWORD_MODE": settings["attachment_encryption"],
        "LOG_LEVEL": "INFO",
        "POSTGRES_PASSWORD": secrets.token_urlsafe(24),
        "TB_SETTINGS": "/etc/trialbox/settings.yaml",
        "TB_CTGOV_MODE": ctgov,
    }
    if ds_type == "cgrd_sql" and a.get("data_source_dsn"):
        env[str(get("data_source_dsn_env"))] = str(a["data_source_dsn"])
    # T-632 (OPS-011): the feed folder on the host and where the adapter sees it (deploy/docker-compose.yml)
    env["TB_SOURCE_DIR"] = str(a.get("data_source_host_dir") or "./site/feed")
    env["TB_SOURCE_MOUNT"] = str(data_source.get("path") or "/data/source/site")
    env.update(tls_env)
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
    ap.add_argument(
        "--mapping-dir",
        type=Path,
        action="append",
        default=[],
        help="a site mapping folder to look in first (default: mapping/ beside --answers, deploy/site/mapping)",
    )
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
        dirs = list(args.mapping_dir) + ([args.answers.parent / "mapping"] if args.answers else [])
        settings, env, warnings = build(a, dirs)
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
