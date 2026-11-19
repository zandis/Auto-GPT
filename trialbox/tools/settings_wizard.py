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

The box (T-729, D-466): ``tools/box/plan.py`` writes the answers from the owner's first-run answers and the detected
hardware; its ``env_extra`` (declared ``TB_*`` settings only: the memory caps, the backup target) goes into ``.env``.

    python -m tools.settings_wizard                                   # interactive
    python -m tools.settings_wizard --answers site_c.yaml --out deploy/settings.yaml --env-out deploy/.env
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import sys
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
for _p in ("libs", "services"):
    sys.path.insert(0, str(ROOT / _p))
from tb_common import site_country, workdays  # noqa: E402 - libs is on the path only from here
from tb_common.dates import PRINTED_STYLES, YEAR_BASES  # noqa: E402

EXAMPLE = ROOT / "deploy" / "settings.example.yaml"
MAPPING_ROOT = ROOT / "services" / "adapter"
SITE_MAPPING = ROOT / "deploy" / "site" / "mapping"  # the site's own mappings (kept by every update, D-367)
# D-736: one plain mail address, as deploy/install.sh checks it too (the same text there): no quote first, no $, `,
# backslash, space or comma that deploy/.env or compose would read otherwise; every domain label non-empty
MAILBOX_RE = (
    r"[A-Za-z0-9._%+-][A-Za-z0-9._%+'-]*"  # the local part: no quote first
    r"@[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+"  # every label non-empty
)
TLS_MODES = ("hospital", "internal")  # OPS-060: the hospital certificate is the first choice
DATA_SOURCES = ("csv", "cgrd_sql", "fhir_bulk", "ssmix2")  # schemas/settings.schema.json data_source.type

# key, question, default (None = from the example settings), kind. 10K-1: the first question is the site's country;
# the defaults of the keys in COUNTRY_KEYS then come from tb_common.site_country.TABLE, and the TWPAS questions are
# asked only where that table lists them (a Taiwan site)
QUESTIONS: list[tuple[str, str, Any, str]] = [
    ("country", "Country or region (jp | tw | us | other)", "", "country"),
    ("site_id", "Site id (short, upper case)", None, "str"),
    ("site_name", "Site name", None, "str"),
    ("tz", "Time zone (IANA, e.g. Asia/Tokyo; the mapping's tz)", "", "str"),  # no default zone (D-315)
    ("locale", "Report language (en | ja | zh-TW)", "zh-TW", "str"),
    # 10C-13, 10C-15 (D-1229): the defaults are the country's (Japan: both, fiscal)
    (
        "printed_dates",
        f"Dates on printed pages ({' | '.join(PRINTED_STYLES)}; era = 令和8年11月18日)",
        "western",
        "str",
    ),
    (
        "year_basis",
        f"The year in yearly reports ({' | '.join(YEAR_BASES)}; fiscal = 年度, 1 April to 31 March)",
        "calendar",
        "str",
    ),
    ("contact", "Box contact e-mail (operations)", None, "str"),
    ("internal_domains", "Internal mail domains (comma separated)", None, "list"),
    ("intake_address", "Intake mailbox address of the box", None, "str"),
    ("senders", "Allowed senders (comma separated)", None, "list"),
    ("physicians", "Physicians allowed to SUBMIT (comma separated)", None, "list"),
    ("reviewers", "Ruleset reviewers / approvers (comma separated)", None, "list"),
    ("alliance_sites", "Alliance member boxes (comma separated, may be empty)", [], "list"),
    ("data_source_type", "HIS source type (csv | cgrd_sql | fhir_bulk | ssmix2)", "csv", "str"),
    (
        "data_source_path",
        "Source directory as the adapter sees it (csv / fhir_bulk / ssmix2)",
        "/data/source/site",
        "str",
    ),
    # T-632 (OPS-011): the host folder the nightly export lands in; compose mounts it at data_source_path, read-only
    (
        "data_source_host_dir",
        "Feed folder on this host (relative = under deploy/; SS-MIX2: the storage's root folder, mounted read-only)",
        "./site/feed",
        "str",
    ),
    # D-594: asked for an SS-MIX2 source only (the reader's TB_SSMIX2_ORDER_NUMBERS)
    (
        "ssmix2_order_numbers",
        "SS-MIX2 order numbers (unique | per_day = the same order number comes back on another day)",
        "unique",
        "str",
    ),
    ("data_source_dsn_env", "Env var holding the SQL DSN (cgrd_sql) or empty", "", "str"),
    ("mapping", "Mapping YAML (in deploy/site/mapping, else the shipped ones)", "mapping/tw_core/demo_his.yaml", "str"),
    ("mrn_regex", "MRN pattern (regular expression)", r"^\d{8}$", "str"),
    # NEW-DIN-3 (D-579): asked once; no answer is asis (leading zeros significant) and a warning
    (
        "chartno_rule",
        "Chart-number format: digits:<width> | hex:<width>[:lower] | asis (empty: asis, as written)",
        "",
        "str",
    ),
    ("registry_type", "Consent registry (csv | sql | none)", "none", "str"),
    ("registry_path", "Registry CSV path (csv) or empty", "", "str"),
    ("departments", "Departments CODE=name (comma separated)", None, "map"),
    ("practitioners", "Practitioners id=name|dept|email|capacity|license (comma separated)", None, "practitioners"),
    ("llm_mode", "LLM (gpu | stub)", "gpu", "str"),
    ("cloud_enabled", "Allow the cloud LLM for protocol extraction (yes/no)", "no", "bool"),
    # D-369 (OD-1): patient files by a sign-in link by default; zip (a password zip) is refused for them on a real box
    ("attachment_encryption", "Patient files by mail (link | smime)", "link", "str"),
    ("console_url", "Address of the console that mail links point to (e.g. https://trialbox.hospital.tw)", "", "str"),
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
    # D-736 (LIFE-007): told at once when a serious adverse event is entered (no AE term); a PRODUCTION install needs it
    ("sae_office_mailbox", "Trial office mailbox, told at once when a serious adverse event is entered", "", "str"),
    # 10C-14 (JP-15): asked only for a country with a holiday list (Japan); the default is the country's 年末年始.
    # More days off or days open: env_extra TB_DAYS_OFF and TB_DAYS_OPEN (tb_common.workdays)
    ("new_year_break", "New Year break: the hospital's first and last day off (MM-DD/MM-DD, or none)", "", "str"),
    # OPS-060: the hospital's certificate is the first choice; Caddy's own CA needs its root on every clinic PC by
    # group policy and never works on a personal device
    (
        "tls_mode",
        "Certificate (hospital = the hospital's, first choice | internal = Caddy's own CA)",
        "hospital",
        "str",
    ),
    ("tls_cert_file", "Hospital certificate and chain, PEM (hospital mode)", "", "str"),
    ("tls_key_file", "Its key, PEM (hospital mode)", "", "str"),
    # D-138: log retention per country (tb_common.retention.DEFAULTS); "" = from the report language (ja -> jp)
    (
        "retention_rules",
        "Retention defaults (jp | tw; empty = the country's, else from the report language)",
        "",
        "str",
    ),
    ("logs_days", "Days to keep service logs (empty = the default of those rules)", "", "str"),
    ("mail_log_days", "Days to keep the mail logs (empty = the default of those rules)", "", "str"),
    # 10K-1: asked only when the site's country has no retention rules in TrialBox (no default then)
    ("outputs_days", "Days to keep job outputs", "", "str"),
    ("attachments_days", "Days to keep inbound attachments", "", "str"),
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
# T-607 (D-429, LLM-013): the embed service's modes (services/embed_service/embedder.py MODES). A GPU box runs the
# pinned local embedder; a stub box the hash stub, which an embed service with TB_ENV PRODUCTION refuses to start.
EMBED_MODE_GPU = "model"
EMBED_MODE_STUB = "hash"


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


# 10K-1: the questions whose default is the country's (tb_common.site_country.TABLE), and the table's field for each
COUNTRY_KEYS = {
    "locale": "locale",
    "tz": "tz",
    "data_source_type": "data_source_type",
    "mapping": "mapping",
    "retention_rules": "retention_rules",
    "printed_dates": "printed_dates",
    "year_basis": "year_basis",
}
NO_DEFAULT = "no default for this country: please answer"
# 10K-21 (D-1365): a PRODUCTION site answers the chart-number question; asis is an answer, Enter is not
CHARTNO_REQUIRED = "required in PRODUCTION: asis, digits:<width> or hex:<width>"
HEALTH_PAGE = "health-page"  # tools.trialbox.backup_schedule.PAGE_ROUTE (D-735)


def production(environment: str) -> bool:
    """10K-21: the guards of a PRODUCTION site apply. The wizard is told (``--environment``, from deploy/install.sh);
    not told, it reads answers as before (a test, a rehearsal, the box's apply step after its first-run page)."""
    return environment.strip().upper() == "PRODUCTION"


NO_RULES_DAYS = ("outputs_days", "attachments_days")  # asked only where the country has no retention rules here
RULE_DAYS = ("logs_days", "mail_log_days", *NO_RULES_DAYS)


def _no_rules(cd: site_country.CountryDefaults, out: dict[str, Any]) -> bool:
    return cd is not site_country.LEGACY and not cd.retention_rules and not out.get("retention_rules")


def _required(key: str, cd: site_country.CountryDefaults, out: dict[str, Any], prod: bool = False) -> bool:
    """10K-1: a question with no default for this site, so an empty answer is asked again: a country value the table
    does not hold, the SS-MIX2 storage's root folder, and the retention days where TrialBox has no rules. 10K-21: the
    chart-number rule on a PRODUCTION site."""
    if prod and key == "chartno_rule":
        return True
    if cd is site_country.LEGACY:
        return False
    if key in COUNTRY_KEYS and key != "retention_rules":
        return not getattr(cd, COUNTRY_KEYS[key])
    if key == "data_source_host_dir":
        return str(out.get("data_source_type")) == "ssmix2"
    return key in RULE_DAYS and _no_rules(cd, out)


def _asked(key: str, cd: site_country.CountryDefaults, out: dict[str, Any]) -> bool:
    """Whether the interactive wizard asks ``key`` for a site of the country ``cd`` with the answers so far."""
    if key in site_country.TWPAS_QUESTIONS:
        return key in cd.insurer_questions
    if key == "ssmix2_order_numbers":
        return str(out.get("data_source_type")) == "ssmix2"
    if key in NO_RULES_DAYS:
        return _no_rules(cd, out)
    if key == "new_year_break":
        return workdays.holidays(cd.country) is not None
    return True


def _reply(prompt: Callable[[str], str], text: str, key: str) -> str:
    """One answer; a closed standard input is a refusal that names the question, not a traceback."""
    try:
        return prompt(text).strip()
    except EOFError:
        raise WizardError(f"{key}: no answer (the input ended)") from None


def ask(answers: dict[str, Any], prompt: Callable[[str], str] = input, *, environment: str = "") -> dict[str, Any]:
    base = defaults()
    prod = production(environment)  # 10K-21
    out: dict[str, Any] = {}
    cd = site_country.LEGACY
    preset = os.environ.get("TB_CTGOV_MODE", "").strip().lower()  # install.sh --ctgov: already answered
    for key, question, default, kind in QUESTIONS:
        if kind == "country":
            print("\n".join(site_country.QUESTION[lang] for lang in ("en", "ja", "zh-TW")))
            for _ in range(5):  # no default: the answer decides every default after it (10K-1)
                reply = _reply(prompt, f"{question}: ", key).lower()
                if reply in site_country.COUNTRIES:
                    break
            else:
                raise WizardError(f"country: one of {', '.join(site_country.COUNTRIES)}")
            out[key], cd = reply, site_country.defaults(reply)
            continue
        if not _asked(key, cd, out):
            continue
        if kind == "ctgov":
            if preset in CTGOV_MODES:
                out[key] = preset
                continue
            print("\n".join(CTGOV_QUESTION[lang] for lang in ("en", "ja", "zh-TW")))
        d = default if default is not None else base.get(key, "")
        if key in COUNTRY_KEYS and cd is not site_country.LEGACY:
            d = getattr(cd, COUNTRY_KEYS[key]) or ""
        if key == "new_year_break":
            d = new_year_default(cd.country)
        required = _required(key, cd, out, prod)
        if required:  # review of #1088, items 3 and 5: no default; Enter is not an answer here
            d = ""
        if key in RULE_DAYS and required:
            question = question.split(" (")[0]  # no rules to take a default from: the question does not name them
        shown = ", ".join(d) if isinstance(d, list) else d
        if isinstance(d, dict):
            shown = ", ".join(f"{k}=…" for k in d)
        if required:
            shown = CHARTNO_REQUIRED if prod and key == "chartno_rule" else NO_DEFAULT
        for _ in range(5):
            reply = _reply(prompt, f"{question} [{shown}]: ", key)
            if reply or not required:
                break
        else:
            raise WizardError(f"{key}: {shown}")
        out[key] = reply if reply else d
    out.update(answers)
    return out


_PROBE_WIDTHS = range(1, 65)  # the widths tb_common.chartno accepts


def _rule_fits(kind: str, case: str, width: int | None, pat: re.Pattern[str]) -> bool:
    """Whether the MRN pattern describes chart numbers the rule can write without making two of them one.

    With a width: the pattern accepts a number of that width with leading zeros and no number of any other width
    (padding and stripping then only join spellings of one number). Without a width the rule strips leading zeros:
    the pattern must accept some number and none that starts with a zero. The services read the pattern with
    ``re.match``, so "accepts no other width" is asked the same way: a pattern without its end anchor fails."""
    last = "1" if kind == "digits" else ("a" if case == "lower" else "A")

    def padded(k: int) -> str:
        return "0" * (k - 1) + last

    if width:
        if not pat.fullmatch(padded(width)):
            return False
        others = [k for k in (*_PROBE_WIDTHS, _PROBE_WIDTHS[-1] + 1) if k != width]
        return not any(pat.match(padded(k)) or pat.match(last * k) for k in others)
    if not any(pat.fullmatch(last * k) for k in _PROBE_WIDTHS):
        return False
    return not any(pat.match("0" + last * k) for k in _PROBE_WIDTHS)


def chartno_rule(answer: Any, mrn_regex: str, errors: list[str], warnings: list[str]) -> str:
    """The site's chart-number rule for ``TB_CHARTNO_RULE`` (NEW-DIN-3, D-579; ``tb_common.chartno``).

    An answer must be a rule the normaliser reads, and the MRN pattern must describe numbers that rule can write
    (:func:`_rule_fits`). No answer is ``asis``, the rule every box ran on, with a warning that names the question.
    A rule is never read from the MRN pattern: the pattern may under-describe the hospital's numbers, and a wrong
    rule makes two patients one."""
    from tb_common import chartno

    text = str(answer or "").strip()
    if not text:
        warnings.append(
            "chartno_rule was not answered: asis, where leading zeros stay significant: a chart number that lost "
            "them in a sheet is another patient. Answer chartno_rule (digits:<width> or hex:<width>) with the "
            "hospital's chart-number format"
        )
        return "asis"
    if any(c in text for c in "\r\n"):
        errors.append("chartno_rule has a line break")
        return "asis"
    try:
        rule = chartno.parse_rule(text)
    except ValueError as exc:  # ChartNoError, and a width that is a digit but not an ASCII number
        errors.append(f"chartno_rule {text!r} is not a rule: {exc}")
        return "asis"
    if rule.kind != "asis" and not mrn_regex.strip():
        warnings.append(
            f"chartno_rule {rule} was taken with no MRN pattern to check it against: answer mrn_regex with the "
            "hospital's chart-number pattern"
        )
    elif rule.kind != "asis":
        try:
            pat = re.compile(mrn_regex)
        except re.error:
            return str(rule)  # the pattern's own error is reported by the caller
        if not _rule_fits(rule.kind, rule.case, rule.width, pat):
            errors.append(
                f"chartno_rule {rule} contradicts mrn_regex {mrn_regex}: the pattern must accept a chart number as "
                "the rule writes it and no number the rule would join with another (one fixed width for a rule "
                "with a width; no leading zero for a rule without; for a lower-case key say hex:<width>:lower)"
            )
    return str(rule)


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
    a: dict[str, Any], mapping_dirs: list[Path] | None = None, *, environment: str = ""
) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    """Answers -> (settings dict, env dict, warnings). Raises WizardError on inconsistent answers. ``environment``:
    the site's TB_ENV when the caller knows it; PRODUCTION refuses what 10K-21 (D-1365) says may not stay silent."""
    base = defaults()
    prod = production(environment)

    def get(k: str) -> Any:
        return a.get(k, base.get(k))

    errors: list[str] = []
    warnings: list[str] = []
    # 10K-1: the site's country decides the defaults below (tb_common.site_country.TABLE); with no country the
    # answers read exactly as before (site_country.LEGACY, and the code paths marked "legacy")
    try:
        cd = site_country.defaults(a.get("country"))
    except ValueError as exc:  # the one message: every default after it would follow a country that is not there
        raise WizardError(str(exc)) from None
    legacy = cd is site_country.LEGACY

    def by_country(k: str) -> Any:
        """The answer, else the country's value; None when neither exists (the caller reports it)."""
        v = a.get(k)
        return v if v not in (None, "") else getattr(cd, k)

    domains = _split(get("internal_domains"))
    senders, physicians, reviewers = _split(get("senders")), _split(get("physicians")), _split(get("reviewers"))
    if not domains:
        errors.append("at least one internal mail domain is required")
    for who in senders + physicians + reviewers:
        if "@" not in who:
            errors.append(f"{who!r} is not an e-mail address")
        elif not any(who.lower().endswith("@" + d.lower()) or who.lower().endswith("." + d.lower()) for d in domains):
            warnings.append(f"{who} is outside the internal domains: it will never receive patient lists")
    # no pattern is the empty string, which every reader takes as "no pattern" (the scrubber, the candidate
    # registry, the adapter's column check); it was the text "None", which they took for a pattern (D-579)
    mrn_regex = "" if get("mrn_regex") is None else str(get("mrn_regex")).strip()
    try:
        re.compile(mrn_regex)
    except re.error as exc:
        errors.append(f"mrn_regex does not compile: {exc}")
    chart_rule = chartno_rule(a.get("chartno_rule"), mrn_regex, errors, warnings)
    chart_answered = bool(str(a.get("chartno_rule") or "").strip())  # 10K-21: asis typed is an answer
    if prod and not chart_answered:
        errors.append(
            "chartno_rule is required in PRODUCTION: the rule cannot be changed once patients are loaded. Answer "
            "digits:<width> or hex:<width> with the hospital's chart-number format, or asis where chart numbers are "
            "taken exactly as written (D-1365)"
        )
    if not mrn_regex:
        warnings.append(
            "mrn_regex was not answered: nothing checks what a chart number looks like, and a chart number written "
            "in a note without its label is not masked. Answer mrn_regex (or a chart-number rule with a width)"
        )
    depts = _map(get("departments"))
    prac = _practitioners(get("practitioners"))
    for pid, p in prac.items():
        if p.get("department") and p["department"] not in depts:
            errors.append(f"practitioner {pid}: department {p['department']!r} is not in departments")
    if legacy:
        mapping = str(get("mapping") or "mapping/tw_core/demo_his.yaml")
    else:
        mapping = str(by_country("mapping") or "")
        if not mapping:
            errors.append(f"mapping is required: TrialBox ships no mapping for country {cd.country}")
    mapping_file = find_mapping(mapping, mapping_dirs)
    if mapping and not mapping_file.is_file():
        errors.append(
            f"mapping file {mapping} not found in the site mapping folder (deploy/site/mapping) or the image "
            "(copy a template from services/adapter/mapping/templates into deploy/site/mapping)"
        )
    # the site's zone: one answer, no code default (D-315); a country with one zone gives it (10K-1)
    tz = str((a.get("tz") if legacy else by_country("tz")) or "").strip()
    errors += _zone_errors(tz, mapping_file)
    if legacy:
        ds_type = str(get("data_source_type"))
    else:
        ds_type = str(by_country("data_source_type") or "")
        if not ds_type:
            errors.append(f"data_source_type is required: no default for country {cd.country}")
    if ds_type and ds_type not in DATA_SOURCES:
        errors.append(f"data_source_type must be one of {' | '.join(DATA_SOURCES)}, not {ds_type!r}")
    data_source: dict[str, Any] = {"type": ds_type, "mapping": mapping, "nightly_at": "02:00"}
    ssmix2_env: dict[str, str] = {}
    if ds_type == "cgrd_sql":
        if not get("data_source_dsn_env"):
            errors.append("cgrd_sql needs data_source_dsn_env (the env var holding the DSN)")
        data_source["dsn_env"] = str(get("data_source_dsn_env"))
    elif ds_type == "ssmix2":
        # the storage's root folder on the host (TB_SOURCE_DIR), mounted read-only at data_source_path (compose)
        data_source["path"] = str(a.get("data_source_path") or "/data/source/site")
        # D-594's key; written only when answered (no answer: the reader's own default, unique, as before 10K-1)
        order = str(a.get("ssmix2_order_numbers") or "").strip()
        if order and order not in site_country.SSMIX2_ORDER_NUMBERS:
            errors.append(f"ssmix2_order_numbers must be unique or per_day, not {order!r} (D-594)")
        elif order:
            ssmix2_env["TB_SSMIX2_ORDER_NUMBERS"] = order
        if not legacy and not str(a.get("data_source_host_dir") or "").strip():
            errors.append(
                "data_source_host_dir is required for ssmix2: the SS-MIX2 storage's root folder on this host (mounted "
                "read-only)"
            )
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
        warnings.append(  # D-369 (SEC-11): sender authentication fails closed without it
            "mta_authserv_id is empty: no sender can be authenticated, so the box refuses every request mail until "
            "TB_MAIL_AUTHSERV_ID is set"
        )
    attach = str(a.get("attachment_encryption") or "link").strip().lower()
    if attach not in ("link", "smime", "zip"):
        errors.append(f"attachment_encryption must be link or smime, not {attach!r}")
    elif attach == "zip":
        warnings.append("attachment_encryption zip: patient files are refused by mail outside TB_ENV DEV, TEST (D-369)")
    elif attach == "link" and not str(a.get("console_url") or "").strip():
        warnings.append("attachment_encryption link without console_url: mails with patient files are refused")
    ctgov = str(a.get("ctgov_mode") or os.environ.get("TB_CTGOV_MODE") or "offline").strip().lower()
    if ctgov not in CTGOV_MODES:
        errors.append(f"ctgov_mode must be offline or live, not {ctgov!r}")
    elif ctgov == "live":
        warnings.append(
            "ClinicalTrials.gov live: the box will reach clinicaltrials.gov:443 (the network sheet lists it)"
        )
    tls_host = str(a.get("tls_hostname") or "").strip()
    tls_mode = str(a.get("tls_mode") or "hospital").strip().lower()
    tls_env: dict[str, str] = {}
    if tls_mode not in TLS_MODES:
        errors.append(f"tls_mode must be hospital or internal, not {tls_mode!r}")
    elif tls_host:
        if not re.fullmatch(r"[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?", tls_host) or "." not in tls_host:
            errors.append(f"tls_hostname {tls_host!r} is not a DNS name (for example trialbox.hospital.tw)")
        tls_env = {"TB_TLS_HOSTNAME": tls_host, "TB_TLS_MODE": tls_mode}
        if tls_mode == "hospital":
            for k, var in (("tls_cert_file", "TB_TLS_CERT_FILE"), ("tls_key_file", "TB_TLS_KEY_FILE")):
                if not str(a.get(k) or "").strip():
                    errors.append(f"tls_mode hospital (the default) needs {k}, or set tls_mode internal")
                tls_env[var] = str(a.get(k) or "").strip()
        else:
            warnings.append(
                "tls_mode internal: hospital IT must install Caddy's root certificate on every clinic PC (group "
                "policy), and personal devices cannot open the console; the hospital's certificate is the first "
                "choice (RUNBOOK §12)"
            )
            tls_env |= root_confirmation(a, warnings)
    else:
        warnings.append("tls_hostname is empty: install.sh asks for it (a PRODUCTION box runs only behind https)")
    sae_to = str(a.get("sae_office_mailbox") or "").strip()
    if sae_to and not re.fullmatch(MAILBOX_RE, sae_to):
        errors.append(f"sae_office_mailbox {sae_to!r} is not one mail address (for example trial-office@hospital.tw)")
    elif not sae_to:
        warnings.append("sae_office_mailbox is empty: nobody is mailed when a serious adverse event is entered; a "
                        "PRODUCTION install stops without it (D-736)")  # fmt: skip
    break_env = new_year_env(cd.country, a.get("new_year_break"), errors)
    twpas = _bool(a.get("twpas_enabled", "no"))
    if twpas and "twpas_enabled" not in cd.insurer_questions:
        errors.append(f"TWPAS is Taiwan's National Health Insurance: not offered for country {cd.country}")
    elif twpas and not a.get("twpas_org_id"):
        errors.append("TWPAS needs the NHI hospital code (twpas_org_id)")
    if legacy:
        locale = str(a.get("locale", "zh-TW"))
    else:
        locale = str(by_country("locale") or "")
        if not locale:
            errors.append(f"locale is required: no report language default for country {cd.country}")
    from tb_common.retention import defaults_for, site_own

    days = {k: a.get(k) for k in ("logs_days", "mail_log_days", "outputs_days", "attachments_days")}
    if legacy:
        rules = str(a.get("retention_rules") or "").strip().lower() or (
            "jp" if str(a.get("locale", "zh-TW")).startswith("ja") else "tw"
        )
    else:
        rules = str(by_country("retention_rules") or "").strip().lower()
    retention: dict[str, int] = {}
    try:
        retention = defaults_for(rules, days) if rules else site_own(days)
    except ValueError as exc:
        errors.append(str(exc))
    # 10C-13, 10C-15 (D-1229): a new site gets its country's defaults written out; an answers file without a country
    # (an installed box, a file from before) writes them only when answered, so its prints and years do not change
    dated: dict[str, str] = {}
    for k, allowed in (("printed_dates", PRINTED_STYLES), ("year_basis", YEAR_BASES)):
        v = str(a.get(k) or "") if legacy else str(by_country(k) or "")
        if v and v not in allowed:
            errors.append(f"{k}: one of {', '.join(allowed)}")
        elif v:
            dated[k] = v
    extra = env_extra(a.get("env_extra"), errors)
    raw_extra = a.get("env_extra")
    given: dict[str, Any] = raw_extra if isinstance(raw_extra, dict) else {}
    refused = frozenset(k for k in NAME_KEYS if k in given and k not in extra)
    watcher_problem(extra, prod, errors, warnings, refused)  # 10K-21
    if errors:
        raise WizardError("; ".join(errors))
    site_id = str(get("site_id")).upper()
    settings: dict[str, Any] = {
        "site": {
            "id": site_id,
            "name": str(get("site_name")),
            "tz": tz,
            "locale": locale,
            "contact": str(get("contact")),
            **dated,  # 10C-13, 10C-15 (D-1229)
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
        "mrn_regex": mrn_regex,
        "profiles": {"tw_core": "1.0.0", "twpas_version": "1.2.5"},
        "models": {
            "judge": "qwen3.5-35b-a3b-q4",
            "extract_local": "gpt-oss-120b-mxfp4",
            "embed": "e-embed",  # the registry alias; the build is e-embed-1 (D-429)
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
        "attachment_encryption": attach,
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
    embed_mode = EMBED_MODE_GPU if str(a.get("llm_mode", "gpu")) == "gpu" else EMBED_MODE_STUB
    env = {
        "TB_SITE_ID": site_id,
        "TB_TZ": settings["site"]["tz"],
        "TB_CHARTNO_RULE": chart_rule,  # NEW-DIN-3 (D-579): every service reads .env (tb_common.chartno)
        **({"TB_CHARTNO_RULE_ANSWERED": "yes"} if chart_answered else {}),  # 10K-21: doctor tells chosen from silent
        "COMPOSE_PROFILES": "gpu" if str(a.get("llm_mode", "gpu")) == "gpu" else "stub",
        "TB_LLM_MODE": "vllm" if str(a.get("llm_mode", "gpu")) == "gpu" else "stub",
        "TB_EMBED_MODE": embed_mode,
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
        "TB_CONSOLE_URL": str(a.get("console_url") or "").strip(),
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
    env.update(ssmix2_env)
    if sae_to:
        env["TB_SAE_OFFICE_MAILBOX"] = sae_to
    env.update(break_env)
    env.update(extra)
    return settings, env, warnings


NAME_KEYS = ("TB_BACKUP_ALERT_WATCHER", "TB_TLS_ROOT_CONFIRMED_BY")  # 10K-21: the people a site names in .env
NAME_RULE = (  # 10K-21: tb_common.box_answers.person_name, said
    "letters and digits of any script, single spaces, and . , - ( ) / ’ ・ · only; at most 100 characters"
)


def root_confirmation(a: dict[str, Any], warnings: list[str]) -> dict[str, str]:
    """10K-21 (D-1365): with Caddy's own CA, IT's confirmation that its root certificate is on every clinic PC.

    Review of #1175, S3: the wizard runs before Caddy's first start, when the root does not exist yet, so nothing it
    is told can be a confirmation: it records none (an answer ``tls_root_confirmed_by`` is not written, and it says
    so) and says the next action. The confirmation is recorded once the root exists: the box's first-run page (served
    through Caddy, so its root is there), or ``TB_TLS_ROOT_CONFIRMED_BY`` and ``_ON`` in ``deploy/.env`` after IT has
    pushed it; until then ``doctor`` (named_choices) WARNs on a PRODUCTION box. Never a refusal."""
    given = str(a.get("tls_root_confirmed_by") or "").strip()
    warnings.append(
        "tls_mode internal: Caddy makes its root certificate at its first start; once hospital IT has pushed it to "
        "every clinic PC, put TB_TLS_ROOT_CONFIRMED_BY (who in IT confirmed it) and TB_TLS_ROOT_CONFIRMED_ON "
        "(YYYY-MM-DD) in deploy/.env; doctor warns until then (RUNBOOK §12)"
        + ("; tls_root_confirmed_by in the answers is not recorded: the root does not exist yet" if given else "")
    )
    return {}


def watcher_problem(
    extra: dict[str, str], prod: bool, errors: list[str], warnings: list[str], bad: frozenset[str] = frozenset()
) -> None:
    """10K-21 (D-1365): the health page as the backup alert route (``TB_BACKUP_ALERT_ROUTE=health-page``, D-735)
    names the person who opens it every working day (``TB_BACKUP_ALERT_WATCHER``). Unnamed: refused in PRODUCTION,
    a warning elsewhere. A box's first-run page asks it (``health_page_person``)."""
    from tb_common.box_answers import person_name

    if extra.get("TB_BACKUP_ALERT_ROUTE", "").strip().lower() != HEALTH_PAGE:
        return
    if "TB_BACKUP_ALERT_WATCHER" in bad:  # env_extra refused the name already
        return
    if not person_name(extra.get("TB_BACKUP_ALERT_WATCHER")):
        why = ("the backup alert route is the health page and nobody is named to open it every working day: give "
               "TB_BACKUP_ALERT_WATCHER (a box: health_page_person) (D-1365)")  # fmt: skip
        (errors if prod else warnings).append(why)


def new_year_default(country: str) -> str:
    """The country's New Year break as the question shows it (``12-29/01-03`` for Japan); "" for none."""
    nb = workdays.NEW_YEAR_BREAK.get((country or "").upper())
    return f"{nb[0][0]:02d}-{nb[0][1]:02d}/{nb[1][0]:02d}-{nb[1][1]:02d}" if nb else ""


def new_year_env(country: str, answer: Any, errors: list[str]) -> dict[str, str]:
    """10C-14: ``TB_NEW_YEAR_BREAK`` when the site's break is not its country's (nothing is written otherwise)."""
    text = str(answer or "").strip()
    if not text or text == new_year_default(country):
        return {}
    if workdays.holidays(country) is None:
        errors.append(f"new_year_break: country {country or '(none)'} has no holiday list, so no working-day calendar")
        return {}
    try:
        workdays.parse_break(text)
    except ValueError as exc:
        errors.append(f"new_year_break: {exc}")
        return {}
    return {"TB_NEW_YEAR_BREAK": text}


def env_extra(raw: Any, errors: list[str]) -> dict[str, str]:
    """``env_extra`` of an answers file (the box's plan, T-729): only declared ``TB_*`` settings, string values."""
    if not raw:
        return {}
    if not isinstance(raw, dict):
        errors.append("env_extra must be a mapping of TB_* settings")
        return {}
    from tb_common.box_answers import confirmed_on, person_name
    from tb_common.config import DECLARED, DECLARED_FAMILIES

    out: dict[str, str] = {}
    for k, v in raw.items():
        name = str(k)
        if not re.fullmatch(r"TB_[A-Z0-9_]+", name) or not (
            name in DECLARED or any(name.startswith(f) for f in DECLARED_FAMILIES)
        ):
            errors.append(f"env_extra: {name} is not a declared TB_* setting")
        elif why := env_value_problem(str(v)):
            errors.append(f"env_extra: {name} {why}")
        elif name in NAME_KEYS:  # 10K-21 (review of #1175): a person's name, by the allow-list, whatever the route
            who = person_name(v)
            if who is None:
                errors.append(f"env_extra: {name} is not one plain name ({NAME_RULE})")
            else:
                out[name] = who
        elif name == "TB_TLS_ROOT_CONFIRMED_ON" and str(v).strip() and confirmed_on(v) is None:
            errors.append(f"env_extra: {name} must be a day (YYYY-MM-DD), today or before")
        else:
            out[name] = str(v)
    # 10C-14: the working-day settings are refused at entry, whatever the route (a box never stops on them)
    errors += [f"env_extra: {p}" for p in workdays.settings_problems(out)]
    return out


# 10K-21 (review of #1175): what may never stand in a deploy/.env value, whoever typed it. Each line of the file is
# one ``KEY=value``, and every reader (compose, tb_common.config._read_dotenv, the tools' own readers) splits the file
# into lines first, with str.splitlines, which also breaks on the C0/C1 controls and U+2028/U+2029. A value holding
# one of them would add or override a variable, so it is refused, not escaped (no reader unescapes)
_ENV_KEY = re.compile(r"[A-Z][A-Z0-9_]*")


def env_value_problem(value: str) -> str:
    """Why ``value`` cannot be one ``deploy/.env`` value ("" when it can): a control character (CR, LF, NUL, tab,
    and the rest of Unicode's Cc), a line or paragraph separator, or a leading or trailing space (every reader strips
    it, so the value read back would not be the one written)."""
    for ch in value:
        if unicodedata.category(ch) in ("Cc", "Zl", "Zp"):
            return f"holds a control character or line break (U+{ord(ch):04X})"
    if value != value.strip():
        return "starts or ends with a space"
    return ""


def env_text(env: dict[str, str]) -> str:
    """The ``deploy/.env`` lines, one ``KEY=value`` per variable; refuses (WizardError) any key or value that would
    not read back as exactly that one variable with exactly that value (:func:`env_value_problem`)."""
    lines = []
    for k, v in env.items():
        if not _ENV_KEY.fullmatch(k):
            raise WizardError(f"deploy/.env: {k!r} is not a setting name")
        if why := env_value_problem(str(v)):
            raise WizardError(f"deploy/.env: {k} {why}; nothing was written")
        lines.append(f"{k}={v}\n")
    return "".join(lines)


def write(settings: dict[str, Any], env: dict[str, str], out: Path, env_out: Path | None) -> None:
    from tb_common.config import load_settings

    body = env_text(env) if env_out is not None else ""  # 10K-21: refused before any file is written

    # D-579: a box that is installed (it has an .env) keeps its chart-number rule. The wizard writes the whole
    # file and cannot ask the database whether patients are loaded; another rule would change their pseudonyms
    if env_out is not None and env_out.exists():
        have = [ln.split("=", 1)[1].strip() for ln in env_out.read_text(encoding="utf-8").splitlines()
                if ln.startswith("TB_CHARTNO_RULE=")]  # fmt: skip
        present, wanted = (have[-1] if have and have[-1] else "asis"), env.get("TB_CHARTNO_RULE") or "asis"
        if present != wanted:
            raise WizardError(
                f"{env_out} already runs on TB_CHARTNO_RULE={present} and the answers say {wanted}: another "
                "rule gives the chart numbers of loaded patients other pseudonyms. Answer chartno_rule: "
                f"{present}, or set the rule on a box that has loaded no patient"
            )
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
            "# TrialBox environment — written by tools/settings_wizard.py (secrets generated); root only.\n" + body,
            encoding="utf-8",
        )
        env_out.chmod(0o600)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--answers", type=Path, help="YAML answers file (no questions)")
    ap.add_argument("--out", type=Path, default=ROOT / "deploy" / "settings.yaml")
    ap.add_argument("--env-out", type=Path, help="also write the .env (mode 0600)")
    ap.add_argument("--check", type=Path, help="only validate an existing settings.yaml")
    ap.add_argument(  # 10K-21 (D-1365): deploy/install.sh says it; PRODUCTION refuses a silent chart-number rule
        "--environment",
        type=str.upper,
        choices=("DEV", "TEST", "VALIDATION", "PRODUCTION"),
        default="",
        help="the site's TB_ENV (deploy/install.sh gives it); PRODUCTION asks what may not stay silent",
    )
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
    try:
        a = answers if args.answers else ask({}, environment=args.environment)
    except WizardError as exc:  # 10K-1: a refused or missing answer, said as every other refusal
        print(f"not written: {exc}", file=sys.stderr)
        return 1
    try:
        dirs = list(args.mapping_dir) + ([args.answers.parent / "mapping"] if args.answers else [])
        settings, env, warnings = build(a, dirs, environment=args.environment)
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
