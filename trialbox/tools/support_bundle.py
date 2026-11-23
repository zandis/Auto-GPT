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

H-71 (D-1354): every member's name and text, every source and left-out line and the manifest go through the bundle's
scrub (``tools.bundle_scrub``): pseudonyms and screening numbers masked, secrets replaced by their form (query
strings, URL userinfo, headers, bearer tokens, PEM blocks, JSON, multi-line values, every setting the declarations
mark secret). It runs as a member comes in, once more after the passes above, and ``_write_tar``, the one writer,
refuses a member the scrub would still change. The update history keeps each step's own fields; a step's detail
(and the builder's own caught errors) is its type and length. A log or a command's output that is not UTF-8 text
is left out and listed.
"""

from __future__ import annotations

import argparse
import base64
import errno
import gzip
import hashlib
import html
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

from tools import bundle_scrub as bs  # standard library only at import: libs/ is read when it scrubs

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
#: H-76: a member larger than this is announced before its scrub, with the time it may take: the scrub, its second
#: pass and the writer's check measured about 6 s a MB on a log of encoded URLs (the slowest kind; a plain log is
#: faster); a 64 MiB log is about 6 to 7 minutes
SAY_LARGE = 4 * 2**20
SCRUB_SECONDS_PER_MB = 6.0
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
    """The value as text, as a URL carries it (both percent-encodings, up to three layers: H76-08, a value encoded
    twice with no name next to it), as JSON and HTML write it, and in base64 (either alphabet, padded or not)."""
    forms = {value, json.dumps(value)[1:-1], json.dumps(value, ensure_ascii=False)[1:-1], html.escape(value)}
    for enc in (lambda v: urllib.parse.quote(v, safe=""), urllib.parse.quote, urllib.parse.quote_plus):
        v = value
        for _ in range(3):
            v = enc(v)
            forms |= {v}
    raw = value.encode("utf-8")
    for b in (base64.b64encode(raw).decode(), base64.urlsafe_b64encode(raw).decode()):
        forms |= {b, b.rstrip("=")}
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
#: with a key in it): the bundle's own form of detect-secrets' core plugins, kept with the scrub (H-71, D-1354).
CREDENTIALS = bs.CREDENTIALS


def hide_credentials(text: str) -> tuple[str, Counter[str]]:
    """Every credential of :data:`CREDENTIALS` becomes ``[credential removed: <kind>]``; the text and the counts."""
    found: Counter[str] = Counter()
    for kind, rx in CREDENTIALS.items():
        text, k = rx.subn(f"[credential removed: {kind}]", text)
        if k:
            found[kind] += k
    return text, found


def _bundle_credentials(text: str) -> tuple[str, Counter[str]]:
    """The bundle's credential pass as the scrub calls it: :func:`hide_credentials` looked up at each call, so the
    last look of :func:`build` stays a separate check of the same shapes."""
    return hide_credentials(text)


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
    """The members on their way into the archive. H-71 (D-1354): every name, text, source and left-out line goes
    through the bundle's scrubber as it comes in (:meth:`add`, :meth:`leave_out`), once more after the last secret
    pass (:meth:`seal`), and the archive writer (:func:`_write_tar`) refuses a member the scrub would still change."""

    scrubber: bs.Scrubber = field(default_factory=bs.Scrubber)
    say: Callable[[str], None] = lambda _: None
    members: dict[str, str] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    left_out: list[dict[str, str]] = field(default_factory=list)
    changed: dict[str, dict[str, Any]] = field(default_factory=dict)

    def add(
        self, name: str, text: str, source: str, *, scrubbed: bool = False, mrn: re.Pattern[str] | None = None
    ) -> None:
        name = self._unique(self.scrubber.name(name), self.members)
        size = len(text.encode("utf-8"))
        if size > SAY_LARGE:  # H-76: the operator is told before a long scrub, not left at a silent prompt
            mb = size / 2**20
            self.say(f"scrubbing {name} ({mb:.0f} MB): about {max(1, round(mb * SCRUB_SECONDS_PER_MB / 60))} minute(s)")
        if scrubbed:  # H76: counted only; the scrub below applies the same patterns after it decodes each line
            _, n = scrub(text, mrn)
            self.note(name, "redacted", n)
        # review H2: the scrub runs on the whole text, THEN the member is cut to its last MAX_MEMBER bytes: a cut made
        # first can open a PEM block, a quoted value or a YAML block in the middle, where no rule sees its start
        text = self._scrub(name, text)
        if len(text.encode("utf-8")) > MAX_MEMBER:
            text = text.encode("utf-8")[-MAX_MEMBER:].decode("utf-8", errors="ignore").partition("\n")[2]
            self.note(name, "truncated", 1)
        self.members[name] = text
        self.sources[name] = self.scrubber.text(source)

    @staticmethod
    def _unique(name: str, taken: Mapping[str, str]) -> str:
        """Review L2: two names the scrub makes one (``pw=a.txt``, ``pw=b.txt``) both stay: ``~2`` before the
        extension of the second."""
        if name not in taken:
            return name
        stem, dot, ext = name.rpartition(".")
        if not dot or "/" in ext:
            stem, dot, ext = name, "", ""
        k = 2
        while f"{stem}~{k}{dot}{ext}" in taken:
            k += 1
        return f"{stem}~{k}{dot}{ext}"

    def _scrub(self, name: str, text: str) -> str:
        before = Counter(self.scrubber.found)
        text = self.scrubber.content(name, text)
        kinds = {k: v for k, v in (self.scrubber.found - before).items() if v}
        creds = {k[len("credential (") : -1]: v for k, v in kinds.items() if k.startswith("credential (")}
        if creds:  # said as the credential pass says it: the kind and the count, never the value
            self.note(name, "credentials_removed", sum(creds.values()))
            row = self.changed[name].setdefault("credentials", {})
            for k, v in creds.items():
                row[k] = row.get(k, 0) + v
            self.say(f"removed {sum(creds.values())} credential(s) from {name}: {', '.join(sorted(creds))}")
        if kinds:
            self.note(name, "scrubbed", sum(kinds.values()))
            row = self.changed[name].setdefault("scrub", {})
            for k, v in kinds.items():
                row[k] = row.get(k, 0) + v
        return text

    def seal(self) -> None:
        """The scrub once more over every member, after the passes that change members in place."""
        old, self.members = self.members, {}
        sources, self.sources = self.sources, {}
        for name, text in old.items():
            clean = self._unique(self.scrubber.name(name), self.members)
            self.members[clean] = self._scrub(clean, text)
            self.sources[clean] = sources.get(name, "")

    def note(self, name: str, what: str, n: int) -> None:
        if n:
            row = self.changed.setdefault(name, {})
            row[what] = row.get(what, 0) + n

    def leave_out(self, what: str, why: str) -> None:
        self.left_out.append({"what": self.scrubber.text(what), "why": self.scrubber.text(why)})


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


def _box_part(b: Bundle, deploy: Path, env: Mapping[str, str], now: datetime) -> None:
    from tb_common import metrics

    from tools.trialbox import ops as tb_ops

    box = tb_ops.Box.compose(deploy)
    try:
        snap = tb_ops.snapshot(box)
    except Exception as exc:  # the bundle reports, it does not stop
        snap = {"error": bs.error_shape(f"{type(exc).__name__}: {exc}")}
    # H-71: the update rows' step details (often an error's text) as their type and length
    b.add("ops-snapshot.json", _json(bs.free_text_out(snap)), "trialbox ops snapshot")
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
    if hist is not None:
        # H-71: each line's own fields; an error's text as its type and length (the order of 2026-11-20 09:41)
        last = "\n".join(hist.splitlines()[-HISTORY_LINES:]) + "\n"
        b.add("history.jsonl", bs.history_text(last), "deploy/updates/history.jsonl (details as type and length)")
    else:
        b.leave_out("history.jsonl", "no update has run on this box yet")
    raw_env = _read(deploy / ".env")
    if raw_env is not None:
        # H-71: the scrub first, on the raw text: the name pass below sees one line at a time, so it would leave the
        # second line of a quoted value and a YAML block value
        text, n = redact_secrets(b.scrubber.text(raw_env))
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
            res = {"dir": str(d), "ok": False, "error": bs.error_shape(f"{type(exc).__name__}: {exc}")}
        b.add("audit-verify.json", _json(res), "tb_common.audit.verify")
    b.leave_out("the audit chain", "its events name pseudonyms and jobs; only the verification is included")


def _cmd_part(b: Bundle, deploy: Path, runner: Runner) -> None:
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
        rc, out = runner(argv, timeout)
        if bs.as_text(out) is None:  # H-71: not text the scrub can read: left out and listed, never copied
            b.leave_out(f"cmd/{name}", f"its output is not text the scrub can read (exit {rc})")
            continue
        if secret:
            out, n = redact_secrets(b.scrubber.text(out))  # H-71: the scrub first, as for env.redacted
            b.note(f"cmd/{name}", "secrets_redacted", n)
        b.add(f"cmd/{name}", out if rc == 0 else f"# exit {rc}\n{out}", " ".join(argv[-4:]))
    rc, ids = runner([*comp, "ps", "--all", "-q"], 60)
    fmt = ("{{.Name}} restarts={{.RestartCount}} status={{.State.Status}} "
           "health={{if .State.Health}}{{.State.Health.Status}}{{end}} started={{.State.StartedAt}}")  # fmt: skip
    if rc == 0 and ids.split():
        rc, out = runner(["docker", "inspect", "--format", fmt, *ids.split()], 60)
    else:
        # review H2: the scrub before the cut, so the cut cannot halve a token the scrub would then not know
        out = f"no containers listed (exit {rc}): {b.scrubber.text(ids.strip())[:200]}"
    if bs.as_text(out) is None:
        b.leave_out("cmd/restarts.txt", "its output is not text the scrub can read")
    else:
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
            cut = len(data) == MAX_MEMBER * 4
            text = bs.as_text(data, cut=cut)  # review L3: a dropped last byte only if cut
            if text is None:  # H-71: not UTF-8 text (UTF-16, binary): left out and listed, never copied unscrubbed
                b.leave_out(f"logs/{d.name}/{svc}.log", "not UTF-8 text the scrub can read")
                continue
            if cut:  # H76-10: the read limit cut the log; its last, partial line (a token cut in two) is dropped
                text = text.rpartition("\n")[0] + "\n" if "\n" in text else ""
            b.add(f"logs/{d.name}/{svc}.log", text, str(f), scrubbed=True, mrn=mrn)
            if cut:
                b.note(f"logs/{d.name}/{svc}.log", "cut_at_read_limit", 1)
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


def _write_tar(target: Path, members: Mapping[str, str], at: datetime, scrubber: bs.Scrubber) -> None:
    """The one function that writes into the archive (H-71, D-1354; a test finds every writer). A member the scrub
    would still change is refused before anything is written."""
    for i, name in enumerate(sorted(members), 1):
        if not scrubber.is_clean(name, members[name]):
            raise BundleRefused(f"member {i} of {len(members)} did not go through the scrub: not written")
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as raw, tarfile.open(fileobj=raw, mode="w:gz") as tar:
        for name in sorted(members):
            data = members[name].encode("utf-8")
            info = tarfile.TarInfo(f"support/{name}")
            info.size, info.mode, info.mtime = len(data), 0o600, int(at.timestamp())
            tar.addfile(info, io.BytesIO(data))


def build(deploy: Path, out_dir: Path, *, days: int = DEFAULT_DAYS, add: Iterable[Path] = (),
          runner: Runner = run_cmd, commands: bool = True, now: datetime | None = None,
          say: Callable[[str], None] = print) -> Path:  # fmt: skip
    """Make the bundle in ``out_dir``; return its path. :class:`BundleRefused` when it would hold something it must
    not (an ``--add`` path under /data, a key, a file the scan cannot read); then nothing is written."""
    try:  # R22-34 (D-1072): rc1 makes no support bundle on a PRODUCTION box (the box's deploy/.env; first, always)
        from tb_common import rc1_refusals

        rc1_refusals.check("support_exports", rc1_refusals.host_env(deploy))
    except rc1_refusals.Rc1Refused as exc:
        raise BundleRefused(exc.say()) from None
    try:
        return _build(deploy, out_dir, days=days, add=add, runner=runner, commands=commands, now=now, say=say)
    except bs.ScrubError as exc:
        raise BundleRefused(str(exc)) from None


def _build(deploy: Path, out_dir: Path, *, days: int, add: Iterable[Path], runner: Runner, commands: bool,
           now: datetime | None, say: Callable[[str], None]) -> Path:  # fmt: skip
    now = now or datetime.now(UTC)
    deploy = deploy.resolve()
    env = {**_env_file(deploy), **{k: v for k, v in os.environ.items() if k in ("TB_LOG_DIR", "TB_AUDIT_HOST_DIR")}}
    raw = {k: v for k, v in _raw_env(deploy).items()}
    sec = [deploy / "secrets", *(Path(p) for p in (raw.get("TB_SECRETS_HOST_DIR") or "").split(os.pathsep) if p)]
    values = secret_values(raw, os.environ, sec)
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
    mrn = mrn_pattern(deploy)
    # H-71: one scrubber for the bundle: the site's chart number, a tag key made now and never kept, and the bundle's
    # own credential pass (looked up when called, so the last look below stays a separate check)
    b = Bundle(scrubber=bs.Scrubber.for_bundle(mrn, credentials=_bundle_credentials), say=say)
    _box_part(b, deploy, env, now)
    _audit_part(b, env)
    if commands:
        _cmd_part(b, deploy, runner)
    else:
        b.leave_out("cmd/", "--no-commands")
    log_days = _logs_part(b, deploy, env, days, mrn)
    used: set[str] = set()
    for p in extra:
        text = _read(p)
        if text is None or bs.as_text(text) is None:
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
    b.seal()  # H-71: the scrub once more, after every pass that changed a member in place
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
    text, k = hide_values(_json(manifest), values)
    b.members["MANIFEST.json"] = b.scrubber.content("MANIFEST.json", text)
    hidden += k
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"trialbox-support-{now:%Y%m%dT%H%M%SZ}.tar.gz"
    part = out_dir / f".{target.name}.part"
    part.unlink(missing_ok=True)
    try:
        _write_tar(part, b.members, now, b.scrubber)
        with tempfile.TemporaryDirectory(prefix="tb-support-scan-") as tmp:  # the scan names a member by path
            scan_copy = Path(tmp) / target.name
            scan_copy.write_bytes(part.read_bytes())
            hits = last_look(scan_copy)
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
        print(f"support-bundle: refused, nothing written: {bs.scrub_text(str(exc))}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
