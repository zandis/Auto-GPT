"""``trialbox support-bundle``: one PHI-free file for a support ticket (T-209b, D-405; WS-17.4, R-61, D-23, OPS-047).

    sudo python3 -m tools.trialbox support-bundle --out /media/usb [--days 3] [--add ingest_report.json]
    python -m tools.support_bundle --out DIR [--deploy deploy] [--no-commands]

Writes ``trialbox-support-<UTC time>.tar.gz`` (0600) with a ``MANIFEST.json`` that lists every file inside, its
sha256, what was left out and why, and every line the scrubber changed or removed (counts and pattern ids, never a
value). What goes in:

==========================  ======================================================================================
``ops-snapshot.json``       what the Operations page shows (``trialbox ops``): version, updates, rollback points,
                            backups by name and age, secrets by name, presence and age (never a value), log days
``health.json``             the host half of the box's health (T-209a, ``tb_common.metrics``)
``release.json``            the release identity: the version, ``deploy/updates/installed.json``,
                            ``deploy/release.json`` when there is one
``history.jsonl``           the last 400 lines of the update history
``env.redacted``            ``deploy/.env`` with every secret-like value replaced by ``[redacted]``
``audit-verify.json``       the audit chain's verification (counts and errors; no event)
``cmd/*.txt``               ``doctor --json``, ``check_host.sh``, ``docker compose config`` (redacted), ``compose
                            ps``, container restart counts, ``df -h``, ``nvidia-smi``
``logs/<day>/<svc>.log``    the last ``--days`` collected days (``trialbox logs collect``) of TrialBox's own services
``added/<name>``            each ``--add`` file (text only)
==========================  ======================================================================================

What never goes in: ``/data`` or any Docker volume, the secrets folder, a key, a backup, a rollback dump, the audit
chain, the pid map, the lake, any database table (the judged-pair store ``orch.judged_pairs``, D-908, and the
answer store ``orch.answers``, D-1360, among them), ``settings.yaml``, and the logs of the third-party services
(PostgreSQL, HAPI FHIR, vLLM: they log statement values and prompts unscrubbed, OPS-035). An ``--add`` path in one
of those places is refused and nothing is written.

How it is kept free of patient data: the logs and added files go through the log scrubber
(``tb_common.logging.redact``: Taiwan IDs, マイナンバー, insurer numbers, postcodes, phone numbers) and the site's
chart-number pattern (``settings.yaml`` ``mrn_regex``); a credential of a well-known shape that no setting names (a
private key block, a cloud or chat token, a web token: :data:`CREDENTIALS`) is replaced, as detect-secrets would
find it; then every file is read by the data-handling scan
(``tools.data_scan``) and each line it flags is removed, and the run says so. The finished archive is scanned once
more; a hit there, or a file the scan cannot read, means no bundle is written.
"""

from __future__ import annotations

import argparse
import errno
import gzip
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "libs") not in sys.path:  # the host's python3 from the install folder
    sys.path.insert(0, str(ROOT / "libs"))

# TrialBox's own services: their logs are written through the scrubber (tb_common.logging). Only these are collected.
OWN_SERVICES = frozenset({"lake", "embed-service", "doc-parser", "criteria-compiler", "adapter", "orchestrator",
                          "mail-gateway", "gateway", "console", "llm-stub", "model-guard"})  # fmt: skip
NEVER_LOGS = {"db": "PostgreSQL logs a failed statement with its values (OPS-035)",
              "fhir-store": "HAPI FHIR logs resources unscrubbed (OPS-035)",
              "llm-service": "vLLM may log prompts, which hold note text"}  # fmt: skip
REFUSED_SUFFIXES = (".key", ".tbbak", ".dump", ".sql", ".sql.gz", ".parquet", ".duckdb", ".db", ".sqlite", ".age")
REFUSED_NAMES = re.compile(r"^(?:\.env|secrets\.env|pidmap.*|.*\.token|id_[a-z0-9]+)$", re.I)
SECRET_KEY = re.compile(r"PASS|_PW|SECRET|TOKEN|KEY|CREDENTIAL|PRIVATE|DSN|AUTH|SALT|PEPPER|COOKIE|PIN", re.I)
SAFE_KEY = re.compile(r"_(?:FILE|PATH|DIR|DAYS|HOURS|MODE|TARGETS)$", re.I)  # a path or a number, not a secret
ASSIGN = re.compile(r"^(?P<lead>\s*-?\s*)(?P<key>[A-Za-z_][A-Za-z0-9_.\-]*)(?P<sep>\s*[:=]\s*)(?P<val>.*)$")
USERINFO = re.compile(r"(?P<scheme>[A-Za-z][A-Za-z0-9+.\-]*://)[^/@\s:]+:[^/@\s]+@")
MAX_MEMBER = 16 * 2**20  # below the scan's 32 MB limit: a longer file keeps its last 16 MB
HISTORY_LINES = 400
DEFAULT_DAYS = 3
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")

Runner = Callable[[Sequence[str], int], tuple[int, str]]  # (argv, timeout seconds) -> (exit code, output)


class BundleRefused(RuntimeError):
    """Nothing was written: the bundle would hold something it must never hold."""


def run_cmd(argv: Sequence[str], timeout: int) -> tuple[int, str]:
    try:
        r = subprocess.run(list(argv), capture_output=True, check=False, timeout=timeout, cwd=ROOT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, f"not run: {type(exc).__name__}: {exc}"
    return r.returncode, (r.stdout + r.stderr).decode("utf-8", errors="replace")


# ------------------------------------------------------------------------------------------------ redaction
def redact_secrets(text: str) -> tuple[str, int]:
    """Values of secret-like names (``KEY=v``, ``key: v``) and the user:password of URLs become ``[redacted]``.
    A name ending ``_FILE``, ``_PATH`` or ``_DIR`` keeps its value: it is where a secret is, not the secret."""
    n = 0
    out = []
    for line in text.splitlines():
        line, k = USERINFO.subn(r"\g<scheme>[redacted]@", line)
        n += k
        m = ASSIGN.match(line)
        if m and SECRET_KEY.search(m["key"]) and not SAFE_KEY.search(m["key"]):
            val = m["val"].strip()
            if val and val not in ("[redacted]", "''", '""', "{}", "[]", "null") and not val.endswith(":"):
                line = f"{m['lead']}{m['key']}{m['sep']}[redacted]"
                n += 1
        out.append(line)
    return "\n".join(out) + ("\n" if text.endswith("\n") else ""), n


#: D-723: a secret's value shorter than this is not looked for by value (a two-letter value would be replaced in every
#: word); it is still redacted by its name. Every secret the box makes is far longer.
MIN_VALUE = 4
#: every setting of the tree that holds a secret's VALUE (not a path to one). A test
#: (tests/unit/test_support_bundle_no_secret.py) fails on a secret-like setting in neither this list nor NOT_SECRETS.
SECRET_SETTINGS = (
    "IMAP_PASS", "SMTP_PASS", "CLOUD_LLM_API_KEY", "TB_LLM_API_KEY", "TB_SERVICE_TOKEN", "POSTGRES_PASSWORD",
    "POSTGRES_WF_PASSWORD", "TB_DB_PW_ADAPTER", "TB_DB_PW_AUDIT_WRITER", "TB_DB_PW_CONSOLE",
    "TB_DB_PW_CRITERIA_COMPILER", "TB_DB_PW_FHIR_STORE", "TB_DB_PW_GATEWAY", "TB_DB_PW_LAKE", "TB_DB_PW_MAIL_GATEWAY",
    "TB_DB_PW_ORCHESTRATOR", "TB_ACCEPTANCE_MAIL_KEYSTORE_PASSWORD", "TB_ACCEPTANCE_MAIL_PASSWORD",
    "TB_DEMO_PASSWORD", "TB_EDC_EVENT_SECRET", "TB_EDC_INTERNAL_TOKEN", "TB_EDC_OIDC_CLIENT_SECRET",
    "TB_EDC_TOOL_TOKEN", "TB_KEK_PASSPHRASE", "TB_KEK_NEW_PASSPHRASE", "TB_KMS_TOKEN", "TB_RC_CASSETTE_TOKEN",
    "TB_REDCAP_API_TOKEN", "TB_REDCAP_PROJECT_TOKENS", "TB_REDCAP_TOKEN_", "OPENROUTER_API_KEY",
    "SPRING_DATASOURCE_PASSWORD", "TB_BAKEOFF_API_KEY", "VLLM_API_KEY",
    "TB_SOURCE_DSN", "TB_PG_DSN", "RESTIC_PASSWORD",
)  # fmt: skip
#: secret-LOOKING names whose value is not a secret, with why: their line is still redacted by the name rule, but
#: their value is not replaced in every file (that wrecked JSON, memory limits and host names)
NOT_SECRETS = {
    "TB_GPU_KEY": "the name of a GPU profile (rtxpro6000, gb10, ...)",
    "TB_OIDC_CLIENT_SECRET": "the path of the client secret's file (its value is read from deploy/secrets/authelia)",
    "TB_VENDOR_KEY_SM_NAME": "the name of a Secret Manager secret (box run, R2), not key material",
}
#: a setting not in the list whose name says it holds a secret's value: looked for too (a site's own setting)
_SECRET_VALUE_NAME = re.compile(r"PASS|_PW_|SECRET|TOKEN|PHRASE|API_KEY|_DSN$|CREDENTIAL|PRIVATE_KEY", re.I)
_NOT_A_SECRET = frozenset({"true", "false", "yes", "no", "on", "off", "0", "1", "none", "null", "[redacted]"})
#: D-723: files of the secrets folders larger than this are not read for their values (a secret file is a token, a
#: key or a short .env; a large file there is something else)
MAX_SECRET_FILE = 64 * 1024


def env_value(raw: str) -> list[str]:
    """The value of one ``.env`` line's right side as compose reads it, and as it is written: a quoted value is what
    is between its quotes (``\\"`` and ``\\\\`` unescaped in double quotes); an unquoted one ends before `` #``."""
    raw = raw.strip()
    forms = [raw.strip("\"'")]
    if raw[:1] == '"':
        end, out, k = raw.find('"', 1), [], 1
        while k < len(raw):
            ch = raw[k]
            if ch == "\\" and k + 1 < len(raw):
                out.append(raw[k + 1])
                k += 2
                continue
            if ch == '"':
                break
            out.append(ch)
            k += 1
        forms.append("".join(out))
        if end > 0:
            forms.append(raw[1:end])
    elif raw[:1] == "'":
        end = raw.find("'", 1)
        forms.append(raw[1:end] if end > 0 else raw[1:])
    else:
        forms.append(re.split(r"\s+#", raw, maxsplit=1)[0].strip())
    return [f for f in dict.fromkeys(forms) if f]


def _wanted(name: str, value: str) -> bool:
    if name in NOT_SECRETS or SAFE_KEY.search(name) or value.lower() in _NOT_A_SECRET or len(value) < MIN_VALUE:
        return False
    return name in SECRET_SETTINGS or bool(_SECRET_VALUE_NAME.search(name))


def _secret_files(roots: Iterable[Path]) -> dict[str, str]:
    """The values of the box's secret FILES, by a name that says only where: every line of a small text file of the
    secrets folders (a token, a key's hex, a ``.env`` line's value). Public files (``*.pub``, certificates) are not
    read. The files themselves never go in a bundle (:func:`refusal`)."""
    out: dict[str, str] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for f in sorted(root.rglob("*")):
            if not f.is_file() or f.suffix in (".pub", ".crt", ".pem") or f.stat().st_size > MAX_SECRET_FILE:
                continue
            try:
                text = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for i, line in enumerate(text.splitlines()):
                line = line.strip()
                if not line or line.startswith(("#", "-----")):
                    continue
                key, sep, rest = line.partition("=")
                values = env_value(rest) if sep and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) else [line]
                for k, v in enumerate(values):
                    if len(v) >= MIN_VALUE and v.lower() not in _NOT_A_SECRET:
                        out[f"a secret file ({f.name}, line {i + 1}.{k})"] = v
    return out


def secret_values(raw_env: Mapping[str, str], environ: Mapping[str, str], files: Iterable[Path] = ()) -> dict[str, str]:
    """D-723: the box's own secret values, by a name that never shows a value: the secret settings of
    ``deploy/.env`` and of the process environment (a passphrase typed in front of the command), each in every form
    compose could read it, and the values of the secrets folders' files. A name list is never complete and a value
    can turn up where no name stands next to it, so the values themselves are what is looked for."""
    out: dict[str, str] = {}
    for source in (raw_env, environ):
        for name, raw in source.items():
            for k, v in enumerate(env_value(str(raw))):
                if _wanted(name, v):
                    out.setdefault(name if k == 0 else f"{name} ({k})", v)
    out.update(_secret_files(files))
    return out


def _forms(value: str) -> list[str]:
    """The value as text, as a URL carries it (both percent-encodings) and as JSON writes it."""
    forms = {
        value,
        urllib.parse.quote(value, safe=""),
        urllib.parse.quote(value),
        urllib.parse.quote_plus(value),
        json.dumps(value)[1:-1],
        json.dumps(value, ensure_ascii=False)[1:-1],
    }
    return sorted(forms, key=len, reverse=True)


def hide_values(text: str, values: Mapping[str, str]) -> tuple[str, int]:
    """Every form of every value in ``values`` becomes ``[redacted]``; the text and how many were replaced."""
    n = 0
    for value in sorted(set(values.values()), key=len, reverse=True):
        for form in _forms(value):
            k = text.count(form)
            if k:
                text = text.replace(form, "[redacted]")
                n += k
    return text, n


#: credentials of a well-known shape that no setting of the box names (a service that printed its config, a stack trace
#: with a key in it): the bundle's own form of detect-secrets' core plugins, standard library only (the bundle is made
#: by the host's python3). A private key is a whole block, so it is replaced as one, never line by line.
CREDENTIALS: dict[str, re.Pattern[str]] = {
    "private key": re.compile(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY"
        r"(?: BLOCK)?-----|\Z)",
        re.S,
    ),
    "AWS access key": re.compile(r"(?<![A-Z0-9])(?:A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[A-Z0-9]{16}(?![A-Z0-9])"),
    "GitHub token": re.compile(r"(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})"),
    "Slack token": re.compile(r"(?<![A-Za-z0-9])xox[abposr]-[A-Za-z0-9-]{10,}"),
    "JSON web token": re.compile(r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
}


def hide_credentials(text: str) -> tuple[str, Counter[str]]:
    """Every credential of :data:`CREDENTIALS` becomes ``[credential removed: <kind>]``; the text and the counts."""
    found: Counter[str] = Counter()
    for kind, rx in CREDENTIALS.items():
        text, k = rx.subn(f"[credential removed: {kind}]", text)
        if k:
            found[kind] += k
    return text, found


def still_held(text: str, values: Mapping[str, str]) -> list[str]:
    """The NAMES of the settings whose value is still in ``text`` in some form (never the values)."""
    return sorted(name for name, value in values.items() if any(f in text for f in _forms(value)))


def mrn_pattern(deploy: Path) -> re.Pattern[str] | None:
    """The site's chart-number pattern (``settings.yaml`` ``mrn_regex``) as the log scrubber uses it."""
    f = deploy / "settings.yaml"
    if not f.is_file():
        return None
    m = re.search(r"(?m)^mrn_regex:\s*(['\"]?)(.+?)\1\s*(?:#.*)?$", f.read_text(encoding="utf-8"))
    if not m:
        return None
    body = m.group(2).replace("\\\\", "\\").strip("^$")
    try:
        return re.compile(rf"(?<![0-9A-Za-z]){body}(?![0-9A-Za-z])")
    except re.error:
        return None


def scrub(text: str, mrn: re.Pattern[str] | None) -> tuple[str, int]:
    """The log scrubber's patterns, then the site's chart number; returns the text and the number replaced."""
    from tb_common.logging import _PHI_PATTERNS  # the same patterns the services log through

    n = 0
    for pat, repl in _PHI_PATTERNS:
        text, k = pat.subn(repl, text)
        n += k
    if mrn is not None:
        text, k = mrn.subn("[MRN]", text)
        n += k
    return text, n


# ------------------------------------------------------------------------------------------------ what is refused
def refused_roots(deploy: Path, env: Mapping[str, str]) -> list[Path]:
    """Folders nothing is ever copied from: patient data, volumes, secrets, keys, backups, the audit chain."""
    docker = Path(env.get("TB_DOCKER_ROOT") or "/var/lib/docker")
    roots = [Path("/data"), docker / "volumes", Path("/var/lib/docker/volumes"), deploy / "secrets",
             deploy / "pre-restore", deploy / "refdata", deploy / "updates" / "incoming"]  # fmt: skip
    for key in ("TB_SECRETS_HOST_DIR", "TB_AUDIT_HOST_DIR", "TB_AUDIT_ARCHIVE_DIR", "TB_RESTORE_KEEP_DIR",
                "TB_LAKE_DIR", "TB_AUDIT_DIR", "TB_BACKUP_DIRS"):  # fmt: skip
        roots += [Path(v.partition("=")[2] or v) for v in str(env.get(key) or "").replace(",", " ").split() if v]
    roots += [Path(t) for t in str(env.get("TB_BACKUP_TARGETS") or "").replace(",", " ").split() if t]
    roots.append(Path(env.get("TB_LOG_DIR") or deploy / "logs") / "third-party")  # D-406: class D3, never in a bundle
    return roots


def refusal(path: Path, deploy: Path, env: Mapping[str, str]) -> str | None:
    """Why ``path`` may not go into a bundle, or None. The path is resolved first (a link to /data is /data)."""
    try:
        real = path.resolve()
    except OSError as exc:
        return f"cannot be resolved ({exc})"
    for root in refused_roots(deploy, env):
        for r in {root, root.resolve()}:
            if real == r or real.is_relative_to(r):
                return f"under {root}: patient data, secrets, keys, backups or the audit chain never leave the box"
    if "rollback" in real.parts:
        return "a rollback point holds database dumps"
    name = real.name
    if REFUSED_NAMES.match(name) or name.lower().endswith(REFUSED_SUFFIXES):
        return f"{name}: a key, token, backup, dump, database or the raw .env never goes in a bundle"
    return None


# ------------------------------------------------------------------------------------------------ the bundle
@dataclass
class Bundle:
    members: dict[str, str] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    left_out: list[dict[str, str]] = field(default_factory=list)
    changed: dict[str, dict[str, Any]] = field(default_factory=dict)

    def add(
        self, name: str, text: str, source: str, *, scrubbed: bool = False, mrn: re.Pattern[str] | None = None
    ) -> None:
        if len(text.encode("utf-8")) > MAX_MEMBER:
            text = text.encode("utf-8")[-MAX_MEMBER:].decode("utf-8", errors="ignore").partition("\n")[2]
            self.note(name, "truncated", 1)
        if scrubbed:
            text, n = scrub(text, mrn)
            self.note(name, "redacted", n)
        self.members[name] = text
        self.sources[name] = source

    def note(self, name: str, what: str, n: int) -> None:
        if n:
            row = self.changed.setdefault(name, {})
            row[what] = row.get(what, 0) + n

    def leave_out(self, what: str, why: str) -> None:
        self.left_out.append({"what": what, "why": why})


# ------------------------------------------------------------------------------------------------ 10K-5 (D-1381)
#: the keys of an update history line (``tools/trialbox/update.py`` ``_history``) filled from fixed words, ids, times
#: and a yes/no; every other key (``detail``: a step's note or an error, a failed command's last 600 characters of
#: stderr among them) is free text
HISTORY_FIELDS = ("at", "bundle", "box", "step", "ok")
#: the keys of the ops snapshot (``tools/trialbox/ops.py`` ``snapshot``, its health facts and this builder's fallback)
#: whose value can be an error text or a person's words, wherever they stand in it
TEXT_KEYS = frozenset({"error", "detail", "drill_error", "why", "reason", "message"})
_ERROR_TYPE = re.compile(r"([A-Za-z_][A-Za-z0-9_]{0,48}(?:Error|Exception|Failed|Refused|Interrupt|Expired|Timeout|"
                         r"Violation|Exit))(?::|$)")  # fmt: skip
#: the one backup problem that quotes an error (``backup_schedule.drill_failure``): its words stay, the error does not
_DRILL = re.compile(r"^(the restore drill of \S+ failed: )(.*)( \(trialbox restore-drill, RUNBOOK §5\))$", re.S)
#: what ``texts_marked`` changes, as MANIFEST.json's ``left_out`` names it
MARKED = (
    "the free text of history.jsonl and ops-snapshot.json: each history line's detail (and any key its writer does "
    "not write, and a line that is not JSON), the snapshot's error, detail, drill_error, why, reason and message "
    "values, and the restore drill's error in the backup problems; health.json is evaluated from the marked snapshot"
)
#: the members ``left_out`` may name
LEAVABLE = ("env.redacted", "cmd/doctor.json", "cmd/check_host.txt", "cmd/compose-config.yaml", "cmd/compose-ps.txt",
            "cmd/df.txt", "cmd/nvidia-smi.txt")  # fmt: skip


def mark(text: str) -> str:
    """A text left out: a fixed mark with its length and, when it starts with one, the error's type name."""
    m = _ERROR_TYPE.match(text)
    return f"[text left out: {m.group(1) + ', ' if m else ''}{len(text)} characters]"


def mark_history(text: str) -> tuple[str, int]:
    """The update history with every free-text value marked (:func:`mark`); the text and how many were marked."""
    out, n = [], 0
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            row = None
        if not isinstance(row, dict):
            out.append(mark(line) if line else line)
            n += bool(line)
            continue
        for k, v in row.items():
            plain = isinstance(v, (bool, type(None))) or (isinstance(v, str) and k in HISTORY_FIELDS and k != "ok")
            if (k in HISTORY_FIELDS and plain) or v in ("", None):
                continue
            row[k] = mark(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str))
            n += 1
        out.append(json.dumps(row, ensure_ascii=False))
    return "\n".join(out) + ("\n" if text.endswith("\n") else ""), n


def mark_texts(obj: Any) -> tuple[Any, int]:
    """The ops snapshot with every value of :data:`TEXT_KEYS` marked, and the error in the restore drill's problem."""
    if isinstance(obj, list):
        pairs = [mark_texts(v) for v in obj]
        return [v for v, _ in pairs], sum(k for _, k in pairs)
    if not isinstance(obj, dict):
        return obj, 0
    out: dict[str, Any] = {}
    n = 0
    for key, v in obj.items():
        if key in TEXT_KEYS and v not in ("", None):
            out[key] = mark(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str))
            n += 1
        elif key == "problems" and isinstance(v, list):
            out[key] = []
            for p in v:
                m = _DRILL.match(p) if isinstance(p, str) else None
                out[key].append(f"{m[1]}{mark(m[2])}{m[3]}" if m else p)
                n += bool(m)
        else:
            out[key], k = mark_texts(v)
            n += k
    return out, n


def _json(d: Any) -> str:
    return json.dumps(d, indent=1, ensure_ascii=False, sort_keys=True, default=str) + "\n"


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _raw_env(deploy: Path) -> dict[str, str]:
    """``deploy/.env`` as written: the right side of each line whole (quotes and comments in it), the last line of a
    name winning, as compose reads it."""
    out: dict[str, str] = {}
    text = _read(deploy / ".env") or ""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, sep, rest = line.partition("=")
        if sep and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key.strip()):
            out[key.strip()] = rest
    return out


def _env_file(deploy: Path) -> dict[str, str]:
    from tools.trialbox import logs as tb_logs

    return {k: v.strip("\"'") for k, v in tb_logs.env_file(deploy).items()}


def _box_part(b: Bundle, deploy: Path, env: Mapping[str, str], now: datetime,
              left_out: Mapping[str, str] | None = None, texts_marked: str | None = None) -> None:  # fmt: skip
    from tb_common import metrics

    from tools.trialbox import ops as tb_ops

    box = tb_ops.Box.compose(deploy)
    try:
        snap = tb_ops.snapshot(box)
    except Exception as exc:  # the bundle reports, it does not stop
        snap = {"error": f"{type(exc).__name__}: {exc}"[:300]}
    if texts_marked is not None:  # 10K-5 (D-1381): before health.json is evaluated from it
        snap, marked = mark_texts(snap)
        b.note("ops-snapshot.json", "texts_marked", marked)
    b.add("ops-snapshot.json", _json(snap), "trialbox ops snapshot")
    facts = snap.get("health") if isinstance(snap.get("health"), dict) else None
    health = metrics.evaluate(facts, None, now, metrics.Thresholds.from_env(env)).as_dict()
    health["checks"] = [c for c in health["checks"] if c["name"] != "canary"]
    health["note"] = "the model self-test (canary) is read by the console from the orchestrator, not on the host"
    b.add("health.json", _json(health), "tb_common.metrics.evaluate (host facts)")
    updates = deploy / "updates"
    rel: dict[str, Any] = {"trialbox": tb_ops._version()}
    for key, f in (("installed", updates / "installed.json"), ("release", deploy / "release.json")):
        text = _read(f)
        if text is not None:
            try:
                rel[key] = json.loads(text)
            except ValueError:
                rel[key] = {"error": f"{f.name} is not JSON"}
    b.add("release.json", _json(rel), "pyproject version, deploy/updates/installed.json, deploy/release.json")
    hist = _read(updates / "history.jsonl")
    if hist is not None and texts_marked is not None:  # 10K-5 (D-1381)
        text, marked = mark_history("\n".join(hist.splitlines()[-HISTORY_LINES:]) + "\n")
        b.add("history.jsonl", text, "deploy/updates/history.jsonl")
        b.note("history.jsonl", "texts_marked", marked)
    elif hist is not None:
        b.add("history.jsonl", "\n".join(hist.splitlines()[-HISTORY_LINES:]) + "\n", "deploy/updates/history.jsonl")
    else:
        b.leave_out("history.jsonl", "no update has run on this box yet")
    if texts_marked is not None:
        b.leave_out(MARKED, texts_marked)
    raw_env = _read(deploy / ".env")
    if left_out and "env.redacted" in left_out:  # 10K-5 (D-1381)
        b.leave_out("env.redacted", left_out["env.redacted"])
    elif raw_env is not None:
        text, n = redact_secrets(raw_env)
        b.add("env.redacted", text, "deploy/.env, secret values redacted")
        b.note("env.redacted", "secrets_redacted", n)
    b.leave_out("deploy/.env (raw), deploy/secrets/", "secrets: only names and ages, in ops-snapshot.json")
    b.leave_out("deploy/settings.yaml", "holds the site's contacts; the doctor output says what is wrong in it")


def _audit_part(b: Bundle, env: Mapping[str, str]) -> None:
    from tb_common import audit

    from tools.trialbox import logs as tb_logs

    d = Path(env.get("TB_AUDIT_HOST_DIR") or tb_logs.DEFAULT_AUDIT)
    try:
        here = d.is_dir()
    except OSError as exc:  # the volume's folder under /var/lib/docker, for an operator who is not root
        why = errno.errorcode.get(exc.errno or 0, type(exc).__name__)
        b.add("audit-verify.json", _json({"dir": str(d), "ok": None, "error": f"the audit folder could not be read "
                                          f"({why}): run the bundle as root to verify the chain"}),
              "tb_common.audit.verify")  # fmt: skip
        here = None
    if here is False:
        b.add("audit-verify.json", _json({"dir": str(d), "ok": None, "error": "the audit folder is not here"}),
              "tb_common.audit.verify")  # fmt: skip
    elif here:
        try:
            r = audit.verify(d)
            res: dict[str, Any] = {"dir": str(d), "ok": r.ok, "files": r.files, "lines": r.lines,
                                   "errors": r.errors[:20], "notes": r.notes[:20]}  # fmt: skip
        except Exception as exc:
            res = {"dir": str(d), "ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
        b.add("audit-verify.json", _json(res), "tb_common.audit.verify")
    b.leave_out("the audit chain", "its events name pseudonyms and jobs; only the verification is included")


def _cmd_part(b: Bundle, deploy: Path, runner: Runner, left_out: Mapping[str, str] | None = None) -> None:
    from tools.trialbox import logs as tb_logs

    comp = tb_logs.compose(deploy)
    env_file = str(deploy / ".env")
    cmds: list[tuple[str, list[str], int, bool]] = [
        (
            "doctor.json",
            [sys.executable, "-m", "tools.trialbox", "doctor", "--json", "--env-file", env_file],
            300,
            False,
        ),
        ("check_host.txt", ["sh", str(deploy / "check_host.sh"), "--env", env_file], 300, False),
        ("compose-config.yaml", [*comp, "config"], 120, True),
        ("compose-ps.txt", [*comp, "ps", "--all"], 60, False),
        ("df.txt", ["df", "-h"], 30, False),
        ("nvidia-smi.txt", ["nvidia-smi"], 60, False),
    ]
    for name, argv, timeout, secret in cmds:
        if left_out and f"cmd/{name}" in left_out:  # 10K-5 (D-1381): not run at all
            b.leave_out(f"cmd/{name}", left_out[f"cmd/{name}"])
            continue
        rc, out = runner(argv, timeout)
        if secret:
            out, n = redact_secrets(out)
            b.note(f"cmd/{name}", "secrets_redacted", n)
        b.add(f"cmd/{name}", out if rc == 0 else f"# exit {rc}\n{out}", " ".join(argv[-4:]))
    rc, ids = runner([*comp, "ps", "--all", "-q"], 60)
    fmt = ("{{.Name}} restarts={{.RestartCount}} status={{.State.Status}} "
           "health={{if .State.Health}}{{.State.Health.Status}}{{end}} started={{.State.StartedAt}}")  # fmt: skip
    if rc == 0 and ids.split():
        rc, out = runner(["docker", "inspect", "--format", fmt, *ids.split()], 60)
    else:
        out = f"no containers listed (exit {rc}): {ids.strip()[:200]}"
    b.add("cmd/restarts.txt", out, "docker inspect (restart counts)")


def _logs_part(b: Bundle, deploy: Path, env: Mapping[str, str], days: int, mrn: re.Pattern[str] | None) -> list[str]:
    base = Path(env.get("TB_LOG_DIR") or deploy / "logs") / "services"
    got = sorted((d for d in base.iterdir() if d.is_dir() and DAY.match(d.name)), reverse=True) if base.is_dir() else []
    chosen = got[:days]
    third: set[str] = set()
    for d in chosen:
        for f in sorted(d.glob("*.log.gz")):
            svc = f.name[: -len(".log.gz")]
            if svc not in OWN_SERVICES:
                third.add(svc)
                continue
            try:
                with gzip.open(f, "rb") as fh:
                    data = fh.read(MAX_MEMBER * 4)
            except (OSError, EOFError) as exc:
                b.leave_out(f"logs/{d.name}/{svc}.log", f"unreadable ({type(exc).__name__})")
                continue
            b.add(f"logs/{d.name}/{svc}.log", data.decode("utf-8", errors="replace"), str(f), scrubbed=True, mrn=mrn)
    for svc in sorted(third):
        b.leave_out(f"logs of {svc}", NEVER_LOGS.get(svc, "not a TrialBox service: its log is not scrubbed"))
    if not chosen:
        b.leave_out("logs", f"no collected days in {base} (trialbox logs collect)")
    return [d.name for d in chosen]


def last_look(archive: Path) -> list[Any]:
    """The scan of the finished archive before it leaves (D-723), with the exits' patterns (D-747)."""
    from tools import data_scan as ds

    return ds.run([archive], patterns=ds.load_patterns(exits=True), in_repo=False)


def clean_lines(b: Bundle, say: Callable[[str], None]) -> None:
    """Remove every line the data-handling scan flags, in every member, and say so (counts and pattern ids only)."""
    from tools import data_scan as ds

    patterns, allow = ds.load_patterns(exits=True), ds.load_allow()  # D-747: the bundle leaves the box
    for name in sorted(b.members):
        lines = ds._lines(b.members[name])
        removed: Counter[str] = Counter()
        while True:
            hits = [h for h in ds.scan_lines(lines, name, patterns, allow) if h.line > 0]
            if not hits:
                break
            # a name flags the dated lines just after it too (the scan's name-date window): drop the first flagged
            # line and every flagged line outside its window, then scan again, so a timestamp is not taken for a
            # birth date once the name is gone
            hits.sort(key=lambda h: h.line)
            first = hits[0].line
            kept = [h for h in hits if h.line == first or h.line > first + ds.NEAR_LINES]
            drop = {h.line for h in kept}
            removed.update(h.pattern for h in kept)
            lines = [x if i not in drop else "[line removed by the data-handling scan]" for i, x in enumerate(lines, 1)]
        if removed:
            b.members[name] = "\n".join(lines)
            b.note(name, "lines_removed", sum(removed.values()))
            b.changed[name]["patterns"] = dict(sorted(removed.items()))
            say(f"removed {sum(removed.values())} line(s) from {name}: {', '.join(sorted(removed))}")


def _write_tar(target: Path, members: Mapping[str, str], at: datetime) -> None:
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as raw, tarfile.open(fileobj=raw, mode="w:gz") as tar:
        for name in sorted(members):
            data = members[name].encode("utf-8")
            info = tarfile.TarInfo(f"support/{name}")
            info.size, info.mode, info.mtime = len(data), 0o600, int(at.timestamp())
            tar.addfile(info, io.BytesIO(data))


def build(deploy: Path, out_dir: Path, *, days: int = DEFAULT_DAYS, add: Iterable[Path] = (),
          runner: Runner = run_cmd, commands: bool = True, now: datetime | None = None,
          say: Callable[[str], None] = print, logs_left_out: str | None = None,
          left_out: Mapping[str, str] | None = None, texts_marked: str | None = None,
          scanned: Callable[[str, int], None] | None = None) -> Path:  # fmt: skip
    """Make the bundle in ``out_dir``; return its path. :class:`BundleRefused` when it would hold something it must
    not (an ``--add`` path under /data, a key, a file the scan cannot read); then nothing is written.

    ``logs_left_out`` (10K-5, D-1381; the command never passes it): a reason; when given, no service log is read
    and ``MANIFEST.json`` lists ``logs/`` as left out with that reason (``log_days`` empty). Left as None, the
    bundle is made exactly as before.

    The console's button (10K-5, D-1381) passes three more, each a constant of ``tools/trialbox/ops_support.py``; the
    command passes none, and left as None each changes nothing:

    ``left_out``: members of :data:`LEAVABLE` mapped to a reason; such a member is not made (its command is not run)
    and ``MANIFEST.json`` lists it under ``left_out`` with the reason. ``texts_marked``: a reason; every free-text
    value of ``history.jsonl`` and ``ops-snapshot.json`` (:data:`MARKED`) becomes :func:`mark` (a fixed mark, its
    length, the error's type name), and ``left_out`` lists :data:`MARKED` with the reason. ``scanned``: called, once
    the bundle has its final name, with the sha256 and the size of the copy the last look scanned."""

    now = now or datetime.now(UTC)
    deploy = deploy.resolve()
    env = {**_env_file(deploy), **{k: v for k, v in os.environ.items() if k in ("TB_LOG_DIR", "TB_AUDIT_HOST_DIR")}}
    raw = {k: v for k, v in _raw_env(deploy).items()}
    sec = [deploy / "secrets", *(Path(p) for p in (raw.get("TB_SECRETS_HOST_DIR") or "").split(os.pathsep) if p)]
    values = secret_values(raw, os.environ, sec)
    unknown = sorted(set(left_out or {}) - set(LEAVABLE))
    if unknown:
        raise ValueError(f"left_out names no member the builder can leave out: {unknown}")
    extra = list(add)
    for p in extra:  # before any work: a refused path stops the whole bundle
        why = refusal(p, deploy, env)
        if why:
            raise BundleRefused(f"{p}: {why}")
    for p in extra:
        if not p.is_file():
            raise BundleRefused(f"{p}: not a file")
        if p.stat().st_size > MAX_MEMBER:
            raise BundleRefused(f"{p}: larger than {MAX_MEMBER // 2**20} MB")
    b = Bundle()
    mrn = mrn_pattern(deploy)
    _box_part(b, deploy, env, now, left_out, texts_marked)
    _audit_part(b, env)
    if commands:
        _cmd_part(b, deploy, runner, left_out)
    else:
        b.leave_out("cmd/", "--no-commands")
    if logs_left_out is None:
        log_days = _logs_part(b, deploy, env, days, mrn)
    else:
        log_days = []
        b.leave_out("logs/", logs_left_out)
    used: set[str] = set()
    for p in extra:
        text = _read(p)
        if text is None:
            raise BundleRefused(f"{p}: not a UTF-8 text file; the scan could not read it")
        name = p.name if p.name not in used else f"{len(used)}-{p.name}"
        used.add(name)
        b.add(f"added/{name}", text, str(p), scrubbed=True, mrn=mrn)
    clean_lines(b, say)
    # §3.4 (wave 1): a credential no setting names, of a well-known shape (what detect-secrets would find)
    for name in list(b.members):
        b.members[name], found = hide_credentials(b.members[name])
        if found:
            b.note(name, "credentials_removed", sum(found.values()))
            b.changed[name]["credentials"] = dict(sorted(found.items()))
            say(f"removed {sum(found.values())} credential(s) from {name}: {', '.join(sorted(found))}")
    # D-723: the box's own secret values, in every file and every form, whatever name (or none) stood next to them;
    # before the manifest, so its checksums are of the files as they leave
    hidden = 0
    for name in list(b.members):
        b.members[name], k = hide_values(b.members[name], values)
        b.note(name, "secrets_hidden", k)
        hidden += k
    manifest = {
        "made": now.isoformat(timespec="seconds"),
        "tool": "tools/support_bundle.py (T-209b, D-405)",
        "log_days": log_days,
        "files": [
            {
                "name": n,
                "bytes": len(t.encode("utf-8")),
                "sha256": hashlib.sha256(t.encode("utf-8")).hexdigest(),
                "from": b.sources.get(n, ""),
            }
            for n, t in sorted(b.members.items())
        ],
        "changed": b.changed,
        "left_out": b.left_out,
        "never": [
            "/data and every Docker volume",
            "secrets, keys, tokens",
            "backups and rollback dumps",
            "the audit chain",
            "the pid map and the lake",
            "settings.yaml",
            *(f"logs of {s}: {why}" for s, why in sorted(NEVER_LOGS.items())),
        ],
    }
    b.members["MANIFEST.json"], k = hide_values(_json(manifest), values)
    hidden += k
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"trialbox-support-{now:%Y%m%dT%H%M%SZ}.tar.gz"
    part = out_dir / f".{target.name}.part"
    part.unlink(missing_ok=True)
    looked = ("", 0)
    try:
        _write_tar(part, b.members, now)
        with tempfile.TemporaryDirectory(prefix="tb-support-scan-") as tmp:  # the scan names a member by path
            scan_copy = Path(tmp) / target.name
            scan_copy.write_bytes(part.read_bytes())
            hits = last_look(scan_copy)
            if scanned is not None:  # 10K-5 (D-1381): the copy as the last look read it
                seen = scan_copy.read_bytes()
                looked = (hashlib.sha256(seen).hexdigest(), len(seen))
        if hits:
            raise BundleRefused("the finished bundle still holds what the scan flags: " + "; ".join(
                f"{Path(h.where).name}:{h.line}: {h.pattern}" for h in hits[:5]))  # fmt: skip
        with tarfile.open(part, "r:gz") as tar:  # D-723: the last look is on the archive as it will leave
            text = "\n".join(
                (fh.read().decode("utf-8", errors="replace") if (fh := tar.extractfile(m)) else "")
                for m in tar.getmembers()
            )
        left = sorted(kind for kind, rx in CREDENTIALS.items() if rx.search(text))
        if left:
            raise BundleRefused(f"the finished bundle still holds a credential ({', '.join(left)}): not written")
        held = still_held(text, values)
        if held:
            raise BundleRefused(f"the finished bundle still holds the secret value of {', '.join(held)}: not written")
        part.replace(target)
    finally:
        part.unlink(missing_ok=True)
    if scanned is not None:
        scanned(*looked)
    total = sum(int(v.get("lines_removed", 0)) for v in b.changed.values())
    red = sum(int(v.get("redacted", 0)) for v in b.changed.values())
    say(f"wrote {target}: {len(b.members)} files; scrubber replaced {red} value(s); {hidden} secret value(s) of the "
        f"box replaced; scan removed {total} line(s); the finished bundle scans clean")  # fmt: skip
    return target


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trialbox support-bundle", description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, required=True, help="the folder the bundle goes to (a USB stick)")
    ap.add_argument("--deploy", type=Path, default=ROOT / "deploy")
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS, help="collected log days to include (default 3)")
    ap.add_argument("--add", type=Path, action="append", default=[], help="one more text file support asked for")
    ap.add_argument("--no-commands", action="store_true", help="run no command (doctor, docker, df, nvidia-smi)")
    a = ap.parse_args(argv)
    try:
        build(a.deploy, a.out, days=max(0, a.days), add=a.add, commands=not a.no_commands)
    except BundleRefused as exc:
        print(f"support-bundle: refused, nothing written: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
