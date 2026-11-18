"""Every stated limit at the limit, one over and far over (H-35, D-1101; was lane V's V-16).

The integrator's words: "every stated limit at the limit, one over and far over: refused before work starts, in plain
words." This tool reports and fixes nothing. It has two halves.

**The list** (``build``). A *stated* limit is a number a document, a decision, a declared setting or the limits
register writes down as a bound on what a person, an operator or another service may do (D-1101). The list is made of
three parts, each re-run from the tree:

1. :data:`STATED`, the hand-read catalogue: each row names its source file and a phrase that must occur in it (the
   line number is found again on every run, so a row whose phrase is gone fails ``build``), its value and unit, where
   it is enforced (``file:function``, or ``not found``), who meets it, and either a driver or why it is not driven;
2. the limits register (``tools/limits_allow.yaml``, read by ``tools.limits_lint``): every row, with its line. These
   are waits and page sizes inside the box, not refusals a person meets; they are listed, not driven (the size test
   H-23 owns scale);
3. the declared settings (``libs/tb_common/config.py`` ``DECLARED``) whose name says a bound (``MAX``, ``LIMIT``,
   ``PER_HOUR``, ``PER_DAY``, ``BUDGET``) and that no catalogue row covers: listed, not driven.

A bound in code that none of these states is *unstated*: :func:`unstated` finds every module-level ``*MAX*`` constant
with a number in ``services/`` and ``libs/`` that no catalogue row claims, and lists it apart. It is not tested.

**The drivers** (``drive``). For each catalogue row with a driver: exactly AT the limit (must be accepted and work),
ONE OVER, and FAR OVER (ten times, or the largest sensible, said per row). Each case records accepted or refused;
whether the refusal came before any work (no job, no stored file, no stored row, no audit of work); the words in en,
zh-TW and ja where a page shows them; the status; the audit records; and that the box answers afterwards. The box is
in-process: the console app (``console.app.create_app``) on its stand-in orchestrator (the console tests'
``FakeBackend``) with its own PostgreSQL from ``tools.pglocal``, the real orchestrator's ``create`` on a job database,
and the services' own enforcement functions. A row driven against a function says so (``where``).

    TB_ENV=TEST PYTHONPATH=libs:services:. python -m tools.limits_edge --list            # the list, as JSON
    TB_ENV=TEST PYTHONPATH=libs:services:. python -m tools.limits_edge --drive --out F   # the list and the cases
    python -m tools.limits_edge --markdown F                                             # the page's tables from F

``tests/unit/test_limits_edge.py`` checks the list (every row has a source line) and the judging helpers with no
database; ``make limits-edge`` runs the drivers.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import html
import io
import json
import os
import re
import resource
import sys
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for _p in ("libs", "services", "."):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

SCHEMA = "limits-edge/1"
LANGS = ("en", "zh-TW", "ja")
REGISTER = ROOT / "tools" / "limits_allow.yaml"
CONFIG = ROOT / "libs" / "tb_common" / "config.py"
_BOUND_SETTING = re.compile(r"MAX|LIMIT|PER_HOUR|PER_DAY|BUDGET")
_CONST = re.compile(r"^(_?[A-Z][A-Z0-9_]*MAX[A-Z0-9_]*|_?MAX_[A-Z0-9_]+)$")


# ---------------------------------------------------------------------------------------------------------- the list
@dataclass(frozen=True)
class Stated:
    """One stated limit. ``anchor``: a phrase that occurs in ``source``; its first line is the row's line."""

    id: str
    what: str
    value: str
    unit: str
    source: str
    anchor: str
    enforced: str
    who: str
    driver: str = ""  # a key of DRIVERS, or empty
    not_driven: str = ""  # why not, when there is no driver
    constants: tuple[str, ...] = ()  # "path:NAME" of the code constants this row claims (so not "unstated")
    lane: str = ""  # the lane that owns the enforcement point


STATED: tuple[Stated, ...] = (
    Stated(
        "L01",
        "heavy jobs one account may start a day, each kind on its own (console)",
        "20",
        "jobs / 24 h",
        "docs/user-guide/03-the-everyday-work.md",
        "at most 20 runs of each kind",
        "services/orchestrator/core.py:Orchestrator.create",
        "a coordinator on New request; the console",
        driver="jobs_per_day",
        lane="C2",
    ),
    Stated(
        "L02",
        "heavy job requests one mailbox may send a day (mail)",
        "20",
        "requests / 24 h",
        "docs/DECISIONS.md",
        "`rate_limit_per_sender_per_day` (default 20)",
        "services/mail_gateway/intake.py:decide",
        "a requester by mail",
        driver="mail_jobs_per_day",
        lane="C2",
    ),
    Stated(
        "L03",
        "a daily limit of 0 is no limit",
        "0",
        "jobs / 24 h (0 = none)",
        "libs/tb_common/config.py",
        "0: no limit (D-146, D-775)",
        "libs/tb_common/authz.py:daily_limit",
        "an operator (settings.yaml)",
        driver="zero_is_no_limit",
        lane="C2",
    ),
    Stated(
        "L04",
        "an uploaded protocol, consent form, chart or attachment on the console",
        "50",
        "MB",
        "docs/plan/design/08-interface-control.md",
        "UP-SIZE",
        "services/console/app.py:protocol_submit",
        "a coordinator on New study (protocol)",
        driver="console_upload",
        constants=("services/console/app.py:MAX_UPLOAD",),
        lane="C2",
    ),
    Stated(
        "L05",
        "an ODM file imported into the EDC",
        "5000000",
        "bytes",
        "docs/decisions/D-435-odm-import-sponsor-readers.md",
        "TB_EDC_ODM_MAX_BYTES",
        "services/edc/odm_import.py:read",
        "a data manager on EDC import; the orchestrator",
        driver="odm_size",
        constants=("services/edc/odm_import.py:MAX_BYTES", "services/console/edc_pages.py:ODM_MAX"),
        lane="E",
    ),
    Stated(
        "L06",
        "the sponsor's weekly sheet",
        "2000000",
        "bytes",
        "docs/decisions/D-435-odm-import-sponsor-readers.md",
        "TB_SPONSOR_WEEKLY_MAX_BYTES",
        "services/datacore/sponsor.py:read_weekly",
        "an API caller (orchestrator POST /studies/{rs}/sponsor/weekly; no console page found)",
        driver="sponsor_size",
        constants=("services/datacore/sponsor.py:MAX_BYTES",),
        lane="E",
    ),
    Stated(
        "L07",
        "a file through the REDCap connector",
        "26214400",
        "bytes",
        "docs/data/13-redcap-and-the-edc-backend.md",
        "TB_REDCAP_FILE_MAX_BYTES",
        "services/edc_backend/connection.py:EdcConnection.import_file / export_file",
        "the EDC backend",
        driver="redcap_file",
        lane="E",
    ),
    Stated(
        "L08",
        "the reason for a feature-flag change",
        "500",
        "characters",
        "docs/decisions/D-207-feature-flags.md",
        "500 characters",
        "services/console/admin_flags.py:flags_set",
        "an administrator on Flags",
        driver="flag_reason",
        constants=("libs/tb_common/flags.py:MAX_REASON",),
        lane="C2",
    ),
    Stated(
        "L09",
        "an EDC reason or citation text (refused, never cut)",
        "300",
        "characters",
        "docs/decisions/D-854-a-long-reason-is-refused-never-cut.md",
        "300 characters",
        "services/edc/store.py:said",
        "a coordinator entering data",
        driver="edc_text",
        constants=("services/edc/store.py:TEXT_MAX",),
        lane="E",
    ),
    Stated(
        "L10",
        "a monitoring visit's findings",
        "2000",
        "characters",
        "docs/decisions/D-436-monitor-sdv.md",
        "2,000 characters",
        "services/console/teamstore.py:TeamStore.add_monitor_visit",
        "a monitor (CRA) on Monitoring",
        driver="monitor_findings",
        constants=("services/console/teamstore.py:FINDINGS_MAX",),
        lane="C2",
    ),
    Stated(
        "L11",
        "a break-glass note",
        "10 to 300",
        "characters",
        "docs/decisions/D-280-steward-and-break-glass.md",
        "10 to 300 characters",
        "services/console/breakglass_store.py:BreakGlassStore.open",
        "a coordinator or PI on Break glass",
        driver="breakglass_note",
        constants=("services/console/breakglass_store.py:NOTE_MAX",),
        lane="C2",
    ),
    Stated(
        "L12",
        "a local account's end date",
        "365",
        "days ahead",
        "docs/runbook/25-leavers.md",
        "at most 365",
        "services/console/admin_accounts.py:end_date",
        "an administrator on Users",
        driver="account_end",
        constants=("services/console/admin_accounts.py:MAX_END_DAYS",),
        lane="C2",
    ),
    Stated(
        "L13",
        "failed sign-ins before an account is locked for 15 minutes",
        "5",
        "failures",
        "docs/security/03-who-may-call-what.md",
        "lockout after 5 failures",
        "services/console/auth.py:UserStore.locked_until",
        "anyone at sign-in",
        driver="signin_lockout",
        constants=("services/console/auth.py:MAX_FAILURES",),
        lane="C2",
    ),
    Stated(
        "L14",
        "a password's least length",
        "12",
        "characters (a floor)",
        "docs/runbook/12-identity-and-tls.md",
        "at least 12 characters",
        "services/console/auth.py:check_password_policy",
        "anyone setting a password",
        driver="password_min",
        lane="C2",
    ),
    Stated(
        "L15",
        "minutes idle before a console session ends (setting range)",
        "1 to 60",
        "minutes",
        "docs/runbook/12-identity-and-tls.md",
        "at most 60",
        "services/console/identity.py:_int_in",
        "an operator (TB_CONSOLE_IDLE_MINUTES)",
        driver="idle_minutes",
        lane="D",
    ),
    Stated(
        "L16",
        "hours a console session lasts in all (setting range)",
        "1 to 12",
        "hours",
        "docs/security/03-who-may-call-what.md",
        "1 to 12",
        "services/console/identity.py:_int_in",
        "an operator (TB_CONSOLE_SESSION_HOURS)",
        driver="session_hours",
        lane="D",
    ),
    Stated(
        "L17",
        "a reveal for purpose 'other' needs a written why",
        "10",
        "characters (a floor)",
        "docs/security/03-who-may-call-what.md",
        "10 characters",
        "services/console/reveal.py:_reason_ok",
        "a coordinator revealing a chart number",
        driver="reveal_note",
        lane="C2",
    ),
    Stated(
        "L18",
        "a model call's prompt plus answer budget",
        "32768",
        "tokens (the RTX PRO 6000 builds)",
        "docs/decisions/D-357-context-aware-budgets.md",
        "32,768 tokens",
        "services/gateway/core.py:Gateway._try (tb_llm.budget.over_context)",
        "another service (every model caller)",
        driver="prompt_context",
        lane="A2",
    ),
    # stated, not driven here
    Stated(
        "L19",
        "chart numbers one person may reveal an hour",
        "60",
        "reveals / hour",
        "docs/security/03-who-may-call-what.md",
        "TB_REVEAL_MAX_PER_HOUR",
        "services/console/reveal.py:cap; services/orchestrator/app.py:reveal",
        "a coordinator",
        not_driven="needs listed candidates on the real orchestrator (the orch_box of the console tests, an ingested "
        "lake) and 61 reveals; not built in this card's time",
        lane="C2",
    ),
    Stated(
        "L20",
        "screening-log exports with chart numbers an hour",
        "10",
        "exports / hour",
        "docs/security/03-who-may-call-what.md",
        "TB_EXPORT_MAX_PER_HOUR",
        "services/orchestrator/app.py:registry_export",
        "a coordinator",
        not_driven="needs the real orchestrator with a finished SCREEN (orch_box); not built in this card's time",
        lane="C2",
    ),
    Stated(
        "L21",
        "pseudonym lookups by chart number an hour",
        "TB_REVEAL_MAX_PER_HOUR",
        "lookups / hour",
        "docs/decisions/D-487-identifiers-one-door.md",
        "TB_TO_PID_MAX_PER_HOUR",
        "services/orchestrator/identifiers.py:admit",
        "a coordinator (opt-out, to-pid)",
        not_driven="needs the real orchestrator with a site key and a lake (orch_box); not built in this card's time",
        lane="B2",
    ),
    Stated(
        "L22",
        "model calls on threads at once in the gateway",
        "64",
        "calls",
        "docs/decisions/D-445-gateway-under-load.md",
        "TB_GATEWAY_MAX_INFLIGHT",
        "services/gateway/app.py:chat",
        "another service",
        not_driven="needs 64 model calls held open at once; the stub answers at once, so a stand-in would test a "
        "counter, not the box",
        constants=("services/gateway/app.py:MAX_INFLIGHT",),
        lane="A2",
    ),
    Stated(
        "L23",
        "refusal replies one sender gets a day",
        "10",
        "replies / day",
        "docs/runbook/04-morning-mail-missing.md",
        "at most 10 refusal replies a day",
        "services/mail_gateway/gateway.py:Gateway._reject",
        "a requester by mail",
        not_driven="needs the mail gateway's outbox over a day of refused mail; not built in this card's time",
        lane="C2",
    ),
    Stated(
        "L24",
        "mails to one address in 24 hours",
        "200",
        "mails / 24 h",
        "docs/decisions/D-401-mail-outbox.md",
        "default 200",
        "services/mail_gateway/gateway.py:Gateway._over_limit",
        "the mail gateway",
        not_driven="the limit waits (the mail stays queued an hour), it does not refuse; needs 201 queued mails "
        "and the outbox's clock; not built in this card's time",
        lane="C2",
    ),
    Stated(
        "L25",
        "restarts a job survives before it is failed",
        "3",
        "restarts",
        "docs/runbook/04-troubleshooting.md",
        "TB_JOB_MAX_RESTARTS",
        "services/orchestrator/core.py:Orchestrator._recover",
        "an operator",
        not_driven="needs the box restarted under a running job: the failure drills (tools/failure_drill*.py) "
        "are another lane H card's",
        constants=("services/orchestrator/jobs.py:MAX_RESTARTS",),
        lane="B2",
    ),
    Stated(
        "L26",
        "patients screened a night by the microbatch",
        "2000",
        "patients / night",
        "docs/runbook/04-troubleshooting.md",
        "TB_MICROBATCH_NIGHT_BUDGET",
        "services/orchestrator/scenarios/microbatch.py:reserve",
        "the scheduler",
        not_driven="not a refusal: the rest is carried to the next night; needs a night of 2,001 changed patients "
        "(scale: H-23)",
        lane="B2",
    ),
    Stated(
        "L27",
        "a break-glass grant's length",
        "60",
        "minutes",
        "docs/user-guide/02-roles.md",
        "it ends after 60",
        "libs/tb_common/authz.py; services/console/breakglass_store.py:open",
        "a coordinator or PI",
        not_driven="a time limit, not a size: needs the clock moved past the grant; no refusal at the start",
        lane="C2",
    ),
    Stated(
        "L28",
        "the lake's spill to disk",
        "50",
        "GB at most",
        "docs/runbook/04-troubleshooting.md",
        "at most 50 GB",
        "services/lake/store.py (TB_LAKE_MAX_TEMP)",
        "a job (LAKE-LIMIT)",
        not_driven="needs a query that spills 50 GB: hours of data on a large disk",
        lane="B2",
    ),
    Stated(
        "L29",
        "container log files per service",
        "100m x 10",
        "size x files",
        "docs/runbook/02-daily-operation.md",
        "TB_LOG_MAX_SIZE",
        "deploy compose logging (TB_LOG_MAX_SIZE, TB_LOG_MAX_FILE)",
        "an operator",
        not_driven="compose's own log rotation; compose was not run (a box under Docker was not started)",
        lane="D",
    ),
    Stated(
        "L30",
        "studies per standard site",
        "20",
        "studies (CGMH 50)",
        "docs/plan/design/01-SRS.md",
        "Up to 20, CGMH 50",
        "not found (a capacity target, not a cap)",
        "a site",
        not_driven="a capacity target (NFR-CAP-02), not a refusal; enforced nowhere",
        lane="H",
    ),
    Stated(
        "L31",
        "a site's rule book for the judge",
        "2000",
        "characters",
        "docs/plan/design/01-SRS.md",
        "at most 2,000 characters",
        "not found (FR-JP-09 is not built: status N)",
        "a site's steward",
        not_driven="the feature is not built (FR-JP-09, status N); nothing to drive",
        lane="A2",
    ),
    Stated(
        "L32",
        "a CASE answer within 60 s for at most 200 notes and 20 note criteria",
        "200 / 20",
        "notes / note criteria",
        "docs/plan/design/01-SRS.md",
        "at most 200 notes",
        "not found (a performance condition, not a cap)",
        "a coordinator (CASE)",
        not_driven="a performance target with the judge loaded: needs a GPU and the real model",
        lane="A2",
    ),
    Stated(
        "L33",
        "raw extracts kept in the landing area",
        "7",
        "days at most",
        "docs/plan/design/01-SRS.md",
        "at most 7 days",
        "not checked here (retention)",
        "the adapter",
        not_driven="a retention time: needs a week of the clock; not a refusal",
        lane="B2",
    ),
    Stated(
        "L34",
        "a feed load's largest row drop",
        "20",
        "percent (default)",
        "docs/decisions/D-271-data-pipeline-integrity.md",
        "TB_FEED_MAX_DROP_PCT",
        "libs/tb_common/feedguard.py",
        "the nightly load",
        not_driven="a night's guard on a second load of the hospital's feed; the bad-file card H-34 owns bad feeds",
        lane="B2",
    ),
    Stated(
        "L35",
        "mail retries before a mail is failed",
        "12",
        "tries, at most an hour apart",
        "docs/runbook/04-morning-mail-missing.md",
        "at most an hour apart, 12 tries",
        "services/mail_gateway/gateway.py (MAX_ATTEMPTS, RETRY_MAX_S)",
        "the mail gateway",
        not_driven="needs twelve hours of a refusing mail server",
        constants=("services/mail_gateway/gateway.py:MAX_ATTEMPTS", "services/mail_gateway/gateway.py:RETRY_MAX_S"),
        lane="C2",
    ),
)


def _anchor_line(path: Path, anchor: str) -> int:
    """The first line of ``path`` holding ``anchor`` (1 when the anchor is empty and the file exists), else 0."""
    if not path.is_file():
        return 0
    if not anchor:
        return 1
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if anchor in line:
            return n
    return 0


def _find_source(row: Stated) -> tuple[str, int]:
    """The row's source and line. A decision named by its number alone is found by its prefix (``D-146-*``)."""
    p = ROOT / row.source
    if not p.is_file():
        m = re.match(r"(docs/decisions/D-\d+)-", row.source)
        hits = sorted(ROOT.glob(m.group(1) + "-*.md")) if m else []
        if hits:
            p = hits[0]
    return p.relative_to(ROOT).as_posix() if p.is_file() else row.source, _anchor_line(p, row.anchor)


def register_rows(path: Path = REGISTER) -> list[dict[str, Any]]:
    """Every row of the limits register, with its line."""
    out: list[dict[str, Any]] = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        m = re.match(r"\s*- \{path: ([^,]+), kind: (\w+), value: ([\d.]+), count: (\d+)", line)
        if m:
            out.append({"source": f"tools/limits_allow.yaml:{n}", "path": m.group(1), "kind": m.group(2),
                        "value": m.group(3), "count": int(m.group(4))})  # fmt: skip
    return out


def bound_settings(covered: set[str], path: Path = CONFIG) -> list[dict[str, Any]]:
    """The declared settings whose name says a bound, not named by a catalogue row's anchor."""
    out: list[dict[str, Any]] = []
    text = path.read_text(encoding="utf-8").splitlines()
    for n, line in enumerate(text, start=1):
        m = re.match(r'\s*"(TB_[A-Z0-9_]+)": Declared\(\s*"(\w+)",\s*"([^"]*)"', line)
        if not m:
            m2 = re.match(r'\s*"(TB_[A-Z0-9_]+)": Declared\($', line)
            if m2 and n < len(text):
                m = re.match(r'\s*"(\w+)",\s*"([^"]*)"', text[n])
                if m:
                    name, typ, default = m2.group(1), m.group(1), m.group(2)
                else:
                    continue
            else:
                continue
        else:
            name, typ, default = m.group(1), m.group(2), m.group(3)
        if _BOUND_SETTING.search(name) and name not in covered:
            out.append({"source": f"libs/tb_common/config.py:{n}", "setting": name, "type": typ, "default": default})
    return out


_OPS: dict[type, Callable[[float, float], float]] = {
    ast.Mult: lambda a, b: a * b,
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Pow: lambda a, b: a**b,
}


def _number(node: ast.expr | None) -> int | float | None:
    """The value of a number written as a literal or as plain arithmetic of literals (``50 * 1024 * 1024``)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        a, b = _number(node.left), _number(node.right)
        if a is not None and b is not None:
            v = _OPS[type(node.op)](a, b)
            return int(v) if isinstance(a, int) and isinstance(b, int) else v
    return None


def unstated(claimed: set[str]) -> list[dict[str, Any]]:
    """Module-level ``*MAX*`` constants with a number in services/ and libs/ that no catalogue row claims
    (``claimed``: ``path:NAME``)."""
    out: list[dict[str, Any]] = []
    for d in ("services", "libs"):
        for f in sorted((ROOT / d).rglob("*.py")):
            rel = f.relative_to(ROOT).as_posix()
            if "/tests/" in rel or "/generated/" in rel:
                continue
            try:
                tree = ast.parse(f.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    targets: list[ast.expr] = list(node.targets)
                elif isinstance(node, ast.AnnAssign) and node.value is not None:
                    targets = [node.target]
                else:
                    continue
                for t in targets:
                    if not isinstance(t, ast.Name) or not _CONST.match(t.id) or f"{rel}:{t.id}" in claimed:
                        continue
                    v = _number(node.value)
                    if v is not None:
                        out.append({"where": f"{rel}:{node.lineno}", "name": t.id, "value": v})
    return out


def build() -> dict[str, Any]:
    """The list: the catalogue with each source line found, the register's rows, the bound settings, the unstated."""
    rows = []
    problems = []
    for r in STATED:
        src, line = _find_source(r)
        if line == 0:
            problems.append(f"{r.id}: the phrase {r.anchor!r} is not in {r.source}")
        d = asdict(r)
        d["source"], d["line"] = src, line
        d["constants"] = list(r.constants)
        rows.append(d)
    covered = {r.anchor for r in STATED if r.anchor.startswith("TB_")} | {
        "TB_JOBS_PER_SENDER_PER_DAY", "TB_CONSOLE_SESSION_HOURS", "TB_REVEAL_MAX_PER_HOUR", "TB_EXPORT_MAX_PER_HOUR",
        "TB_TO_PID_MAX_PER_HOUR", "TB_MAIL_PER_RECIPIENT_PER_DAY", "TB_LOG_MAX_FILE"}  # fmt: skip
    claimed = {c for r in STATED for c in r.constants}
    return {
        "schema": SCHEMA,
        "stated": rows,
        "register": register_rows(),
        "settings": bound_settings(covered),
        "unstated": unstated(claimed),
        "problems": problems,
    }


# ------------------------------------------------------------------------------------------------------ the judging
@dataclass
class Case:
    case: str  # at | one_over | far_over
    size: str  # what was sent, in the limit's unit
    accepted: bool
    status: str = ""  # HTTP status, exit, or the exception's code
    before_work: bool | None = None  # refused before any work; None when accepted
    left_behind: str = ""
    words: dict[str, str] = field(default_factory=dict)
    names_limit: dict[str, bool] = field(default_factory=dict)
    plain: dict[str, str] = field(default_factory=dict)  # "" when plain, else why not
    audit: list[str] = field(default_factory=list)
    healthy: bool | None = None
    seconds: float = 0.0
    rss_mb: float = 0.0
    note: str = ""


_ENGLISH_RUN = re.compile(r"[A-Za-z]{2,}(?:[ ,;:'()-]+[A-Za-z]{2,}){2,}")
_NOT_PLAIN = re.compile(r"Traceback|Exception|Error\b|\b[a-z_]+\.[a-z_]+\.[a-z_]+\b|\b[a-z]+_[a-z_]+\b")


def plainness(text: str, lang: str) -> str:
    """Empty when ``text`` is plain words in ``lang``; else why not: a stack trace or exception name, a text key or a
    code-like token, empty words, or (on a zh-TW or ja page) a run of three or more English words."""
    t = text.strip()
    if not t:
        return "no words"
    m = _NOT_PLAIN.search(t)
    if m:
        return f"code-like: {m.group(0)!r}"
    if lang in ("ja", "zh-TW"):
        m = _ENGLISH_RUN.search(t)
        if m:
            return f"English inside {lang}: {m.group(0)!r}"
    return ""


def names_value(text: str, says: tuple[str, ...]) -> bool:
    """Whether the words name the limit's value (any of ``says``, written with or without a thousands comma)."""
    flat = text.replace(",", "").replace("，", "")
    return any(s.replace(",", "") in flat for s in says)


def judge_words(case: Case, says: tuple[str, ...]) -> None:
    for lang, w in case.words.items():
        case.names_limit[lang] = names_value(w, says)
        case.plain[lang] = plainness(w, lang)


def page_text(body: str) -> str:
    """The visible words of a console page's main part (the problem page's heading and text)."""
    m = re.search(r"<main\b.*?</main>", body, re.S)
    part = m.group(0) if m else body
    part = re.sub(r"<(script|style|nav|form)\b.*?</\1>", " ", part, flags=re.S)
    part = re.sub(r"<[^>]+>", " ", part)
    return " ".join(html.unescape(part).split())[:400]


def _rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


@contextlib.contextmanager
def _timed(case: Case) -> Iterator[None]:
    t0, r0 = time.monotonic(), _rss_mb()
    try:
        yield
    finally:
        case.seconds = round(time.monotonic() - t0, 3)
        case.rss_mb = round(max(0.0, _rss_mb() - r0), 1)


def refused_words(reason: str) -> dict[str, str]:
    """The words the console's problem page gives for ``request.refused`` with ``reason``, in each language, through
    the page's own functions (``console.refusals.localize_reason``, ``console.i18n.translate``)."""
    from console.i18n import translate
    from console.refusals import localize_reason

    return {lang: translate(lang, "request.refused", reason=localize_reason(reason, lang)) for lang in LANGS}


def key_words(key: str, **values: object) -> dict[str, str]:
    import console.app
    import console.copy_assist_page  # noqa: F401 - the EDC import page's words (D-435)
    from console.i18n import translate

    return {lang: translate(lang, key, **values) for lang in LANGS}


# ------------------------------------------------------------------------------------- drivers on the functions
Driver = Callable[["Ctx"], list[Case]]
DRIVERS: dict[str, tuple[str, Driver]] = {}


def driver(name: str, where: str) -> Callable[[Driver], Driver]:
    def wrap(fn: Driver) -> Driver:
        DRIVERS[name] = (where, fn)
        return fn

    return wrap


@dataclass
class Ctx:
    work: Path
    console: Any = None  # the console box, made on first use


def _three(at: Any, one: Any, far: Any) -> list[tuple[str, Any]]:
    return [("at", at), ("one_over", one), ("far_over", far)]


@driver("zero_is_no_limit", "function: tb_common.authz.daily_limit with settings.yaml's limit set to 0")
def _zero(ctx: Ctx) -> list[Case]:
    from tb_common.authz import daily_limit
    from tb_common.config import load_settings

    base = load_settings(ROOT / "deploy/settings.example.yaml")
    out = []
    for label, s in (("rate_limits_per_day FEAS: 0 (D-146)", {"rate_limits_per_day": {"FEAS": 0}}),
                     ("TB_JOBS_PER_SENDER_PER_DAY=0 (config.py)", {})):  # fmt: skip
        st = base.model_copy(update=s)
        env = {"TB_JOBS_PER_SENDER_PER_DAY": "0"} if label.startswith("TB_") else {}
        got = daily_limit(st, "FEAS", env=env)
        out.append(Case("at", label, accepted=got is None, status=f"daily_limit = {got}",
                        note="None is no limit; a number is a limit"))  # fmt: skip
    return out


@driver("mail_jobs_per_day", "function: mail_gateway.intake.decide, the day's count from a stand-in of MailDB")
def _mail_day(ctx: Ctx) -> list[Case]:
    from mail_gateway.intake import Inbound, decide
    from tb_common.authz import daily_limit
    from tb_common.config import load_settings

    settings = load_settings(ROOT / "deploy/settings.example.yaml")
    sender = next(iter(sorted(_senders(settings))))
    limit = daily_limit(settings, "FEAS", env={}) or 0

    class Db:
        def __init__(self, n: int) -> None:
            self.n = n

        def jobs_since(self, *_a: Any) -> int:
            return self.n

        def sent(self, _m: str) -> None:
            return None

    out = []
    for label, before in _three(limit - 1, limit, 10 * limit):
        m = Inbound(b"", "<m@x>", sender, "FEAS GZQO lookback=36", None, True, "", [])
        c = Case(label, f"request {before + 1} of the day", accepted=False)
        with _timed(c):
            d = decide(m, settings, Db(before), datetime(2026, 11, 18, 9, tzinfo=UTC))  # type: ignore[arg-type]
        c.accepted = d.action != "reject"
        c.status = d.action
        c.before_work = None if c.accepted else True  # decide stores nothing; a reject makes no job
        if not c.accepted:
            c.words = {"en": d.reason}
            c.note = "a mail reply is in English only (the reply's language is not the sender's choice)"
        judge_words(c, (str(limit),))
        out.append(c)
    return out


def _senders(settings: Any) -> set[str]:
    from tb_common.authz import allowed, known_senders

    return {s for s in known_senders(settings) if allowed(settings, "FEAS", s)}


@driver("odm_size", "function: edc.odm_import.read (the orchestrator's bound; the page's own 6 MiB cap is above it)")
def _odm(ctx: Ctx) -> list[Case]:
    from edc import odm_import

    limit = odm_import.max_bytes({})
    base = _odm_file()
    out = []
    for label, n in _three(limit, limit + 1, 10 * limit):
        data = _pad_xml(base, n)
        c = Case(label, f"{len(data)} bytes", accepted=False)
        with _timed(c):
            try:
                odm_import.read(data, "Project.GZQO", env={})
                c.accepted = True
            except odm_import.OdmRefused as e:
                c.status = e.code if hasattr(e, "code") else "OdmRefused"
                c.words = edc_page_words(getattr(e, "code", "odm.size"))
                c.before_work = "larger than" in str(e)  # the size is checked before the file is parsed
                c.note = str(e)
        judge_words(c, ("5000000", "5 MB", "5MB"))
        out.append(c)
    return out


def edc_page_words(code: str) -> dict[str, str]:
    """The EDC pages' words for an orchestrator refusal ``code``, by the rule of ``templates/_edc_err.html``:
    ``edc.err.<code>`` when the catalogue has it, ``edc.err.odm_file`` for an ``odm.*`` code, else ``edc.err.other``.
    (The rule is read from the template and applied here; the page itself is not rendered.)"""
    import console.app
    import console.copy_assist_page  # noqa: F401
    from console.i18n import lookup

    key = f"edc.err.{code}"
    if lookup("en", key) is not None:
        return key_words(key)
    if code.startswith("odm."):
        return key_words("edc.err.odm_file")
    if code.startswith("RC-") and lookup("en", f"rc.err.{code}") is not None:
        return key_words(f"rc.err.{code}", fields="", msg="")
    return key_words("edc.err.other")


def _odm_file() -> bytes:
    """A small, well-formed ODM file for the study GZQO (the shape of ``tests/unit/test_odm_import.py``)."""
    oid = "Project.GZQO"
    return (f'<?xml version="1.0" encoding="UTF-8"?><ODM xmlns="http://www.cdisc.org/ns/odm/v1.3" '
            f'FileType="Snapshot" FileOID="F.1" ODMVersion="1.3.2" CreationDateTime="2026-11-09T10:00:00+00:00">'
            f'<Study OID="{oid}"><MetaDataVersion OID="M.1" Name="m"></MetaDataVersion></Study>'
            f'<ClinicalData StudyOID="{oid}" MetaDataVersionOID="M.1"></ClinicalData></ODM>').encode()  # fmt: skip


def _pad_xml(base: bytes, n: int) -> bytes:
    """``base`` grown to exactly ``n`` bytes with an XML comment before the root's end."""
    if n <= len(base):
        return base
    head, sep, tail = base.rpartition(b"</ODM>")
    pad = n - len(base) - len(b"<!---->")
    return head + b"<!--" + b"x" * max(0, pad) + b"-->" + sep + tail


@driver("sponsor_size", "function: datacore.sponsor.read_weekly")
def _sponsor(ctx: Ctx) -> list[Case]:
    from datacore import sponsor

    limit = sponsor.max_bytes({})
    layout = {
        "weekly": {
            "subject": "Subject",
            "status": "Status",
            "date": "Date",
            "date_format": "%Y-%m-%d",
            "statuses": {"Enrolled": "enrolled"},
            "reasons": {},
        }
    }
    out = []
    for label, n in _three(limit, limit + 1, 10 * limit):
        data = _sheet(n)
        c = Case(label, f"{len(data)} bytes", accepted=False)
        with _timed(c):
            try:
                _sha, rows = sponsor.read_weekly(data, layout, env={})
                c.accepted = True
                c.note = f"{len(rows)} rows read"
            except sponsor.SponsorError as e:
                c.status = e.code
                c.before_work = e.code == "sponsor.size" and "bytes" in e.message
                c.words = {"en": e.message}
                c.note = e.message
        judge_words(c, ("2000000", "2 MB"))
        out.append(c)
    return out


def _sheet(n: int) -> bytes:
    """A weekly sheet of exactly ``n`` bytes and at most 20,000 rows (the rows' own bound), padded in a last
    column the layout does not read."""
    head = b"Subject,Status,Date,Pad\r\n"
    rows = 19_000
    body = [head]
    size = len(head)
    per = max(40, (n - size) // rows)
    for i in range(rows):
        stem = f"S{i:05d},Enrolled,2026-11-1{i % 9},".encode()
        line = stem + b"x" * max(0, per - len(stem) - 2) + b"\r\n"
        body.append(line)
        size += len(line)
    data = b"".join(body)
    if len(data) < n:  # the rest in the last row's pad
        data = data[:-2] + b"x" * (n - len(data)) + b"\r\n"
    return data[:n] if len(data) > n else data


class _RedcapStandIn:
    """A REDCap client that records each call and gives back ``body`` for a file export."""

    token = ""

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.calls: list[str] = []

    def import_file(self, *a: Any) -> None:
        self.calls.append("import_file")

    def export_file(self, *a: Any) -> tuple[bytes, str]:
        self.calls.append("export_file")
        return self.body, "f.pdf"

    def close(self) -> None:
        pass


@driver("redcap_file", "function: edc_backend.connection.EdcConnection.import_file / export_file, a stand-in REDCap")
def _redcap(ctx: Ctx) -> list[Case]:
    from edc_backend.connection import EdcConnection
    from rc_bridge.client import RcError

    limit = 26_214_400
    out = []
    for direction in ("import", "export"):
        for label, n in _three(limit, limit + 1, 10 * limit if direction == "import" else 4 * limit):
            body = b"\0" * n
            stand_in = _RedcapStandIn(body)
            calls = stand_in.calls
            conn = EdcConnection("redcap", stand_in)  # type: ignore[arg-type]
            c = Case(label, f"{direction} {n} bytes", accepted=False)
            with _timed(c):
                try:
                    if direction == "import":
                        conn.import_file("R1", "f", "f.pdf", body)
                    else:
                        conn.export_file("R1", "f")
                    c.accepted = True
                except RcError as e:
                    c.status = getattr(e, "code", "RcError")
                    c.words = edc_page_words(str(getattr(e, "code", "RC-UPSTREAM")))
                    c.note = f"the connector says: {e}"
                    c.before_work = not calls
                    c.left_behind = "" if not calls else f"the whole file was {calls[0].split('_')[0]}ed first"
            c.note = f"calls to REDCap: {calls}"
            judge_words(c, ("26214400", "25 MB", "25 MiB"))
            out.append(c)
    return out


@driver("edc_text", "function: edc.store.said (EDC-022)")
def _edc_text(ctx: Ctx) -> list[Case]:
    from edc.store import EdcError, said

    out = []
    for label, n in _three(300, 301, 3000):
        c = Case(label, f"{n} characters", accepted=False)
        with _timed(c):
            try:
                said("x" * n, "reason")
                c.accepted = True
            except EdcError as e:
                c.status, c.before_work = f"{e.status} {e.code}", "nothing was stored" in e.message
                c.words = edc_page_words(e.code)
                c.note = f"the service says: {e.message}"
        judge_words(c, ("300",))
        out.append(c)
    return out


@driver("account_end", "function: console.admin_accounts.end_date; words through the console's refusal path")
def _account_end(ctx: Ctx) -> list[Case]:
    from console.admin_accounts import end_date
    from console.auth import AuthError

    today = date(2026, 11, 18)
    out = []
    for label, d in _three(365, 366, 3650):
        c = Case(label, f"{d} days ahead", accepted=False)
        with _timed(c):
            try:
                end_date("coordinator", (today + timedelta(days=d)).isoformat(), today)
                c.accepted = True
            except AuthError as e:
                c.status, c.before_work = "AuthError", True
                c.words = refused_words(str(e))
                c.note = str(e)
        judge_words(c, ("365",))
        out.append(c)
    return out


@driver("password_min", "function: console.auth.check_password_policy; words through the console's refusal path")
def _password(ctx: Ctx) -> list[Case]:
    from console.auth import PasswordRejected, check_password_policy

    out = []
    for label, n in (("at", 12), ("one_over", 11), ("far_over", 1)):  # a floor: "over" is below it
        c = Case(label, f"{n} characters", accepted=False)
        pw = "Tq7#mZp2&Lw9vR4!"[:n] if n <= 16 else "x" * n
        with _timed(c):
            try:
                check_password_policy(pw)
                c.accepted = True
            except PasswordRejected as e:
                c.status, c.before_work = f"400 {e.code}", True
                c.words = key_words(e.code)  # the account page shows the rejection's key (D-447)
                c.note = str(e)
        judge_words(c, ("12",))
        out.append(c)
    return out


def _identity_case(key: str, label: str, value: int) -> Case:
    from console.identity import IdentityConfigError, IdentitySettings

    c = Case(label, f"{key}={value}", accepted=False)
    env = {"TB_ENV": "TEST", key: str(value)}
    with _timed(c):
        try:
            IdentitySettings.from_env(env, "TEST", Path(tempfile.gettempdir()))
            c.accepted = True
        except IdentityConfigError as e:
            c.status, c.before_work = "IdentityConfigError (the console does not start)", True
            c.words = {"en": str(e)}
    return c


@driver("idle_minutes", "function: console.identity.IdentitySettings.from_env (the console's start)")
def _idle(ctx: Ctx) -> list[Case]:
    from console.identity import IdentitySettings

    out = [_identity_case("TB_CONSOLE_IDLE_MINUTES", label, v) for label, v in _three(60, 61, 600)]
    for c in out:
        judge_words(c, ("60",))
    unset = IdentitySettings.from_env({"TB_ENV": "TEST"}, "TEST", Path(tempfile.gettempdir()))
    out[0].note = f"unset, the idle limit is {int(unset.idle.total_seconds() // 60)} minutes"
    return out


@driver("session_hours", "function: console.identity.IdentitySettings.from_env (the console's start)")
def _hours(ctx: Ctx) -> list[Case]:
    out = [_identity_case("TB_CONSOLE_SESSION_HOURS", label, v) for label, v in _three(12, 13, 120)]
    for c in out:
        judge_words(c, ("12",))
    return out


@driver(
    "reveal_note",
    "method: console.reveal.Reveal._reason_ok with a stand-in for its refusal (the audit write); "
    "words by the page's key reveal.note_needed",
)
def _reveal_note(ctx: Ctx) -> list[Case]:
    from console.reveal import Reveal

    class Refusal(Exception):
        pass

    class Me:
        def refuse(self, *a: Any, values: dict[str, Any] | None = None) -> Exception:
            return Refusal(a[9] if len(a) > 9 else "refused", values)

    out = []
    for label, n in (("at", 10), ("one_over", 9), ("far_over", 0)):
        c = Case(label, f"{n} characters", accepted=False)
        with _timed(c):
            try:
                Reveal._reason_ok(Me(), None, "/p", "GZQO", "PID00001", "screen", "other", "x" * n, "page")  # type: ignore[arg-type]
                c.accepted = True
            except Refusal as e:
                c.status, c.before_work = f"400 {e.args[0]}", True
                c.words = key_words("reveal.note_needed", n=10)
        judge_words(c, ("10",))
        out.append(c)
    return out


@driver(
    "prompt_context",
    "function: tb_llm.budget.over_context, the gateway's check before dispatch (stand-in "
    "for the gateway's call: a true test of the comparison, not of the token estimate)",
)
def _prompt(ctx: Ctx) -> list[Case]:
    from tb_llm.budget import over_context

    ctxlen = 32_768
    out = []
    for label, tokens in _three(ctxlen, ctxlen + 1, 10 * ctxlen):
        c = Case(label, f"{tokens} prompt tokens + 0 max_tokens", accepted=not over_context(ctxlen, tokens, 0))
        if not c.accepted:
            c.status, c.before_work = "413 prompt_too_long (raised before dispatch)", True
            c.words = {
                "en": f"about {tokens} prompt tokens + max_tokens 0 is over <alias>'s context of {ctxlen} "
                "tokens; size the prompt from GET /v1/models"
            }  # the gateway's own sentence (core.py)
        judge_words(c, (str(ctxlen),))
        out.append(c)
    return out


# ------------------------------------------------------------------------------ drivers on the in-process console
class ConsoleBox:
    """The console app on the console tests' stand-in orchestrator, with its own PostgreSQL (``tools.pglocal``)."""

    def __init__(self, work: Path) -> None:
        from console.app import create_app
        from console.auth import UserStore
        from console.cascade import CascadeRuns
        from tb_common.audit import AuditLog

        from tests.console.test_console_app import ADMIN_PW, PILOT_ENV, FakeBackend
        from tools import pglocal

        self.admin_pw = ADMIN_PW
        pg = work / "pg"
        pg.mkdir(parents=True, exist_ok=True)
        url = pglocal.ensure(pg)
        os.environ["TB_DB_URL"] = f"{url}{'&' if '?' in url else '?'}tb_prefix=le{os.getpid()}_"
        self.backend = FakeBackend()
        self.backend.audit_dir = work / "audit"
        self.audit_dir = work / "audit"
        audit = AuditLog(self.audit_dir)
        self.users = UserStore()
        if self.users.get("admin") is None:
            self.users.create("admin", "admin", ADMIN_PW, "admin@hospa.test")
        samples = work / "samples"
        samples.mkdir(exist_ok=True)
        (samples / "GZQO_ICF_v2.md").write_text("# Consent\n\nTaking part is voluntary.\n")
        src = work / "site-a"
        src.mkdir(exist_ok=True)
        (src / "patient.csv").write_text("pid\n")
        env = {**PILOT_ENV, "TB_CONSOLE_DIR": str(work / "console"), "TB_CONSOLE_SAMPLES_DIR": str(samples),
               "TB_CONSOLE_CONSENT_SAMPLE": str(samples / "GZQO_ICF_v2.md")}  # fmt: skip
        cascades = CascadeRuns(work / "cascade", src, lambda *a: {"passed": True})
        self.app = create_app(env, backend=self.backend, audit=audit, users=self.users, cascades=cascades)
        self.backend.clock = self._clock
        self.pg = pg

    def _clock(self) -> datetime:
        """The console's clock, read at each call (as the console tests' box fixture)."""
        return self.app.state.helpers.clock()  # type: ignore[no-any-return]

    def login(self, user: str, pw: str, lang: str = "en") -> tuple[Any, str]:
        from fastapi.testclient import TestClient

        c = TestClient(self.app)
        r = c.get("/login")
        tok = re.search(r'name="login_csrf" value="([^"]+)"', r.text)
        assert tok, "no sign-in form"
        r = c.post("/login", data={"username": user, "password": pw, "login_csrf": tok.group(1)},
                   follow_redirects=False)  # fmt: skip
        assert r.status_code == 303, f"sign-in as {user}: {r.status_code}"
        csrf = re.search(r'name="csrf" value="([^"]+)"', c.get("/").text)
        assert csrf
        if lang != "en":
            c.post("/lang", data={"lang": lang, "csrf": csrf.group(1), "back": "/"}, follow_redirects=False)
        return c, csrf.group(1)

    def events(self) -> list[str]:
        return audit_events(self.audit_dir)

    def healthy(self, c: Any) -> bool:
        return bool(c.get("/").status_code == 200)

    def close(self) -> None:
        from tools import pglocal

        with contextlib.suppress(Exception):
            pglocal.remove(self.pg)


def audit_events(folder: Path) -> list[str]:
    """The event names of an audit folder's records, in order."""
    out: list[str] = []
    for f in sorted(folder.rglob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            with contextlib.suppress(ValueError):
                out.append(str(json.loads(line).get("event", "")))
    return out


def _box(ctx: Ctx) -> ConsoleBox:
    if ctx.console is None:
        ctx.console = ConsoleBox(ctx.work / "console-box")
    box: ConsoleBox = ctx.console
    return box


@driver("console_upload", "console page: POST /pilot/protocol on the in-process console (stand-in orchestrator)")
def _upload(ctx: Ctx) -> list[Case]:
    b = _box(ctx)
    mib = 1024 * 1024
    limit = 50 * mib
    out = []
    for label, n in _three(limit, limit + 1, 4 * limit):  # 4x: a 200 MiB body held in memory by the test client
        c = Case(label, f"{n} bytes", accepted=False)
        if label == "far_over":
            c.note = "far over is 4x (200 MiB), not 10x: the test client holds the whole body in memory"
        for lang in LANGS:
            cl, csrf = b.login("admin", b.admin_pw, lang)
            jobs0, objs0, ev0 = len(b.backend.created), len(b.backend.objects), len(b.events())
            data = b"%PDF-1.4\n" + b"0" * (n - 9)
            with _timed(c):
                r = cl.post("/pilot/protocol", data={"csrf": csrf, "ruleset": "LIMIT-T"},
                            files={"protocol": ("p.pdf", io.BytesIO(data), "application/pdf")},
                            follow_redirects=False)  # fmt: skip
            del data
            made = len(b.backend.created) - jobs0
            stored = len(b.backend.objects) - objs0
            if lang == "en":
                c.accepted = r.status_code in (200, 303)
                c.status = str(r.status_code)
                c.audit = b.events()[ev0:]
            if r.status_code not in (200, 303):
                c.words[lang] = page_text(r.text)
                c.before_work = (made == 0 and stored == 0) if c.before_work in (None, True) else False
                if made or stored:
                    c.left_behind = f"{made} job(s), {stored} stored file(s)"
            c.healthy = b.healthy(cl) if c.healthy in (None, True) else False
        judge_words(c, ("50 MB", "50MB", "50"))
        out.append(c)
    return out


@driver("flag_reason", "console page: POST /ops/flags on the in-process console")
def _flag(ctx: Ctx) -> list[Case]:
    from tb_common.flags import DECLARED

    b = _box(ctx)
    name = sorted(DECLARED)[0]
    value = DECLARED[name].default
    out = []
    for label, n in _three(500, 501, 5000):
        c = Case(label, f"{n} characters", accepted=False)
        for lang in LANGS:
            cl, csrf = b.login("admin", b.admin_pw, lang)
            ev0 = len(b.events())
            with _timed(c):
                r = cl.post("/ops/flags", data={"csrf": csrf, "name": name, "value": value, "reason": "r" * n},
                            follow_redirects=False)  # fmt: skip
            ok = r.status_code in (200, 303) and "flags.err" not in r.text and 'name="confirm"' in r.text
            if lang == "en":
                c.accepted = r.status_code in (200, 303)
                c.status = str(r.status_code)
                c.audit = b.events()[ev0:]
                c.note = "accepted: the confirm sheet was shown" if ok else ""
            if r.status_code not in (200, 303):
                c.words[lang] = page_text(r.text)
                c.before_work = not [e for e in b.events()[ev0:] if "flag" in e]
            c.healthy = b.healthy(cl) if c.healthy in (None, True) else False
        judge_words(c, ("500",))
        out.append(c)
    return out


@driver("signin_lockout", "console page: POST /login on the in-process console")
def _lockout(ctx: Ctx) -> list[Case]:
    from fastapi.testclient import TestClient

    b = _box(ctx)
    out = []
    for label, wrong in _three(4, 5, 50):  # "at": four failures, the fifth try right; then five, then fifty
        user = f"lock{label.replace('_', '')}"
        pw = "lockout-password-0001"
        if b.users.get(user) is None:
            b.users.create(user, "coordinator", pw, f"{user}@hospa.test")
        c = Case(label, f"{wrong} wrong passwords, then the right one", accepted=False)
        statuses = []
        ev0 = len(b.events())

        def post(cl: Any, password: str, user: str = user) -> Any:
            tok = re.search(r'name="login_csrf" value="([^"]+)"', cl.get("/login").text)
            assert tok, "no sign-in form"
            return cl.post("/login", data={"username": user, "password": password, "login_csrf": tok.group(1)},
                           follow_redirects=False)  # fmt: skip

        with _timed(c):
            for lang in LANGS:
                cl = TestClient(b.app, headers={"accept-language": lang})
                if lang == "en":
                    for _ in range(wrong):
                        post(cl, "wrong-password-xx")
                r = post(cl, pw)
                statuses.append(r.status_code)
                if lang == "en":
                    c.accepted = r.status_code == 303
                    c.status = str(r.status_code)
                if r.status_code != 303:
                    c.words[lang] = page_text(r.text)
        c.audit = sorted(set(b.events()[ev0:]))
        c.before_work = None if c.accepted else True
        c.note = f"the right password after the failures: {statuses} (en, zh-TW, ja)"
        c.healthy = TestClient(b.app).get("/login").status_code == 200
        judge_words(c, ("15", "5"))
        out.append(c)
    return out


@driver(
    "monitor_findings",
    "store: console.teamstore.TeamStore.add_monitor_visit on PostgreSQL; words through the "
    "monitoring page's refusal path (request.refused with the store's sentence)",
)
def _monitor(ctx: Ctx) -> list[Case]:
    from console.teamstore import TeamError, TeamStore

    _box(ctx)  # the database
    store = TeamStore()
    out = []
    for label, n in _three(2000, 2001, 20000):
        c = Case(label, f"{n} characters", accepted=False)
        before = len(store.monitor_visits("LIMIT-T"))
        with _timed(c):
            try:
                store.add_monitor_visit(
                    "LIMIT-T", visit_ref="V1", visit_day="2026-11-18", cra="cra", subjects=["S-001"],
                    findings="f" * n, at="2026-11-18T09:00:00+00:00",
                )  # fmt: skip
                c.accepted = True
            except TeamError as e:
                c.status = "400 request.refused"
                c.words = refused_words(str(e))
                c.note = str(e)
        after = len(store.monitor_visits("LIMIT-T"))
        if not c.accepted:
            c.before_work = after == before
        c.healthy = True
        judge_words(c, ("2000", "2,000"))
        out.append(c)
    return out


@driver(
    "breakglass_note",
    "store: console.breakglass_store.BreakGlassStore.open on PostgreSQL; words by the page's "
    "keys (bg.err.long, bg.err.note)",
)
def _bg(ctx: Ctx) -> list[Case]:
    from console.breakglass_store import BreakGlassError, BreakGlassStore

    _box(ctx)
    store = BreakGlassStore()
    from tb_common.authz import BREAK_GLASS_REASONS

    reason = sorted(BREAK_GLASS_REASONS)[0]
    now = datetime(2026, 11, 18, 9, tzinfo=UTC)
    out = []
    cases = [("at", 300), ("one_over", 301), ("far_over", 3000), ("at (floor)", 10), ("one_over (floor)", 9),
             ("far_over (floor)", 0)]  # fmt: skip
    for label, n in cases:
        c = Case(label, f"{n} characters", accepted=False)
        with _timed(c):
            try:
                store.open(f"bg{n}", reason=reason, note="n" * n, kind="patient", ruleset="GZQO",
                           pid="PIDLIMIT0001", now=now)  # fmt: skip
                c.accepted = True
            except BreakGlassError as e:
                key = str(e)
                c.status = key
                c.words = key_words(key, n=300) if key in ("bg.err.long", "bg.err.note") else {"en": key}
                c.before_work = not store.active(f"bg{n}", now)
        judge_words(c, ("300",) if "floor" not in label else ("10",))
        out.append(c)
    return out


@driver(
    "jobs_per_day",
    "the real orchestrator's create (orchestrator.core.Orchestrator.create, tests.inproc_box) and "
    "the console's words for its refusal (the console's own mapping of the orchestrator's sentence)",
)
def _jobs(ctx: Ctx) -> list[Case]:
    from tb_contracts import JobCreate

    from tests.inproc_box import make_box

    _box(ctx)  # the database (TB_DB_URL)
    secrets = ctx.work / "secrets"
    secrets.mkdir(exist_ok=True)
    lake = ctx.work / "lake"
    lake.mkdir(exist_ok=True)
    box = make_box(ctx.work / "orch", lake, secrets)
    orch = box.orch
    from orchestrator.core import Rejected
    from tb_common.authz import daily_limit

    limit = daily_limit(orch.cfg.settings, "FEAS", env={}) or 20
    sender = "crc@hospa.test"
    out: list[Case] = []
    made = 0

    def one() -> tuple[bool, str]:
        nonlocal made
        try:
            orch.create(JobCreate(type="FEAS", ruleset="GZQO", requested_by=sender), by="crc", role="coordinator")
            made += 1
            return True, ""
        except Rejected as e:
            return False, str(e)

    tz = os.environ.get("TB_TZ")
    if not tz:
        raise RuntimeError("set TB_TZ to the site's zone (D-315: the code has no default zone); make limits-edge does")
    attempts = 0
    for _ in range(limit - 1):
        one()
        attempts += 1
    for label, upto in _three(limit, limit + 1, 10 * limit):
        c = Case(label, f"attempt {upto} of the day (attempts {attempts + 1} to {upto})", accepted=False)
        rows0 = _count_jobs(orch, sender)
        ev0 = len(audit_events(box.audit_dir))
        refusals = 0
        ok, msg = True, ""
        with _timed(c):
            while attempts < upto:
                ok, msg = one()
                attempts += 1
                refusals += 0 if ok else 1
        if refusals and ok:
            c.note = f"{refusals} refused, the last accepted"
        c.accepted = ok
        c.audit = sorted(set(audit_events(box.audit_dir)[ev0:]))
        rows1 = _count_jobs(orch, sender)
        if not ok:
            c.status = "403 Rejected"
            c.before_work = rows1 == rows0
            c.left_behind = "" if c.before_work else f"{rows1 - rows0} job row(s)"
            c.note = f"{refusals} attempt(s) refused: {msg}"
            c.words = _console_limit_words(msg)
        else:
            c.note = f"{rows1} jobs of this sender stored"
        c.healthy = True
        judge_words(c, (str(limit),))
        out.append(c)
    return out


def _count_jobs(orch: Any, sender: str) -> int:
    return int(orch.db.count_since(sender, "1970-01-01T00:00:00+00:00", "FEAS"))


def _console_limit_words(reason: str) -> dict[str, str]:
    """The console's page words for an orchestrator refusal (``console.app`` maps "rate limit reached (n kind jobs"
    to ``request.limit``)."""
    m = re.search(r"rate limit reached \((\d+) (\w+) jobs", reason)
    if not m:
        return refused_words(reason)
    out = {}
    for lang in LANGS:
        h = key_words("problem.h.request.limit")[lang]
        out[lang] = h + " " + key_words("request.limit", n=int(m.group(1)), kind=m.group(2))[lang]
    return out


# ------------------------------------------------------------------------------------------------------- the run
def drive(work: Path, only: tuple[str, ...] = ()) -> dict[str, Any]:
    ctx = Ctx(work)
    results: dict[str, Any] = {}
    try:
        for row in STATED:
            if not row.driver or (only and row.id not in only):
                continue
            where, fn = DRIVERS[row.driver]
            try:
                cases = fn(ctx)
                results[row.id] = {"where": where, "cases": [asdict(c) for c in cases]}
            except Exception as exc:
                results[row.id] = {"where": where, "error": f"{type(exc).__name__}: {exc}"[:400], "cases": []}
    finally:
        if ctx.console is not None:
            ctx.console.close()
    return results


def verdict(row_id: str, cases: list[dict[str, Any]]) -> str:
    """``holds`` when at is accepted and every over case is refused before work; else what broke."""
    if not cases:
        return "not driven"
    bad = []
    for c in cases:
        over = not c["case"].startswith("at")
        if not over and not c["accepted"]:
            bad.append(f"{c['case']} refused")
        if over and c["accepted"]:
            bad.append(f"{c['case']} accepted")
        if over and not c["accepted"] and c.get("before_work") is False:
            bad.append(f"{c['case']} refused after work")
        if c.get("healthy") is False:
            bad.append(f"{c['case']} left the box unhealthy")
    return "holds" if not bad else "; ".join(dict.fromkeys(bad))


def markdown(doc: Mapping[str, Any]) -> str:
    """The page's tables from a ``--drive`` result."""
    res = doc.get("results", {})
    out = ["| Id | Limit | Source | Value | Enforced | Driven on | At | One over | Far over | Refused before work? "
           "| Words name the limit (en / zh-TW / ja) | Verdict |",
           "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]  # fmt: skip
    for r in doc["stated"]:
        got = res.get(r["id"])
        cases = got["cases"] if got else []
        by = {c["case"]: c for c in cases}

        def cell(k: str, by: Mapping[str, Any] = by) -> str:
            c = by.get(k)
            if c is None:
                return "–"
            return ("accepted" if c["accepted"] else f"refused {c['status']}").replace("|", "/")

        refused = [c for c in cases if not c["accepted"]]
        before = ("yes" if all(c.get("before_work") for c in refused) else "no") if refused else "–"
        names = "–"
        if refused:
            c0 = refused[0]
            names = " / ".join(
                ("yes" if c0["names_limit"].get(lang) else "no") + ("" if not c0["plain"].get(lang) else " (not plain)")
                if lang in c0["words"]
                else "–"
                for lang in LANGS
            )
        where = (got or {}).get("where", r["not_driven"] and "not driven") or "not driven"
        out.append(f"| {r['id']} | {r['what']} | `{r['source']}:{r['line']}` | {r['value']} {r['unit']} | "
                   f"`{r['enforced']}` | {where} | {cell('at')} | {cell('one_over')} | {cell('far_over')} | {before} "
                   f"| {names} | {verdict(r['id'], cases) if got else 'not driven'} |")  # fmt: skip
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--list", action="store_true", help="print the list as JSON")
    ap.add_argument("--drive", action="store_true", help="drive every row with a driver")
    ap.add_argument("--only", nargs="*", default=[], help="row ids to drive (default: all)")
    ap.add_argument("--out", type=Path, help="write the list and the cases here (JSON)")
    ap.add_argument("--work", type=Path, help="the box's folder (default: a fresh one under TB_SCRATCH or the temp)")
    ap.add_argument("--markdown", type=Path, help="print the page's table from a --drive result")
    a = ap.parse_args(argv)
    if a.markdown:
        sys.stdout.write(markdown(json.loads(a.markdown.read_text(encoding="utf-8"))))
        return 0
    doc = build()
    if a.drive:
        base = a.work or Path(tempfile.mkdtemp(prefix="limits-edge-", dir=os.environ.get("TB_SCRATCH") or None))
        doc["results"] = drive(base, tuple(a.only))
        doc["verdicts"] = {k: verdict(k, v["cases"]) for k, v in doc["results"].items()}
    text = json.dumps(doc, ensure_ascii=False, indent=1, default=str)
    if a.out:
        a.out.write_text(text + "\n", encoding="utf-8")
    elif a.list or a.drive:
        print(text)
    n_driven = sum(1 for r in STATED if r.driver)
    print(f"limits_edge: {len(STATED)} stated rows ({n_driven} with a driver), {len(doc['register'])} register rows, "
          f"{len(doc['settings'])} bound settings, {len(doc['unstated'])} unstated constants; "
          f"{len(doc['problems'])} problem(s)", file=sys.stderr)  # fmt: skip
    for p in doc["problems"]:
        print(p, file=sys.stderr)
    return 1 if doc["problems"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
