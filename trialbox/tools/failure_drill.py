"""The failure drill (card H-31, plan 8 V12; D-1109): kill each part of the box during a night's work, then the
database, then fill the data disk, and check from the product's own records that no job was lost, no mail went
twice and the audit chain is intact.

    python -m tools.failure_drill plan                                   # the targets and when each is killed
    python -m tools.failure_drill run --out build/drill [--target NAME]  # on the compose test stack (Docker)
    python -m tools.failure_drill report build/drill                     # the table of a run, as Markdown
    make failure-drill                                                   # the same as run, every target

**The box.** The compose test stack (``make up-test``: ``deploy/docker-compose.yml`` with the test file, the stub
model, GreenMail for mail into the box and Mailpit as the hospital's mail server). Every target gets a fresh stack
(``down -v`` then ``up``) so that one target's damage is not read as the next one's. A run needs Docker and ``make
images``; nothing leaves the machine and nothing costs money.

**A night's work** (:data:`STAGES`), in order: ``mailed`` (a FEAS and a SCREEN mailed in for each study of
:data:`STUDIES`, through GreenMail, the mail gateway's intake and the orchestrator, to their result mails);
``ingest`` (the timer's INGEST: the drill sets ``schedule.ingest`` two minutes ahead in the stack's settings file, as
a site's night would start it; the adapter's ingest, the lake's rebuild and publish, then the chain the orchestrator
starts by itself: MICROBATCH per study with a pool, NAV on its day, RETENTION); ``notices`` (the morning notices N1
and N2, ``python -m console.notify`` in the console container, as the box's timer runs it).

**A kill** is ``kill -9`` of the container's first process from the host (``docker inspect`` gives its pid), which
is what an out-of-memory kill or a crash does: the container exits and Docker's restart policy
(``restart: unless-stopped``) is the box's own recovery. ``docker kill`` is not used: Docker counts it as a person's
stop and does not restart the container. The database is killed the same way. The disk target caps the database's
data volume with a size-limited tmpfs (a compose override; no loop device, no quota) and fills it from inside the
container until a write fails, during the ingest, then frees the space after :data:`FULL_FOR_S` seconds. That is the
product's view of a full disk; it is not the host's disk filling.

**The three checks** (D-1109) read the product's records after the night is finished (or the finish window ends):

1. *no lost job* (:func:`check_jobs`): every unit of work the control night ran (the same night, no kill) is, in the
   drilled night, ``done`` exactly once, or ``failed`` with a reason a person can read and act on; a unit with no
   job, a job left in a state that is not terminal, a ``failed`` with no reason, and a unit done twice are counted;
2. *no double mail* (:func:`check_mail`): the hospital's mail server (Mailpit) holds at most one message per
   recipient and subject; the gateway's outbox (``mail.send_keys``) has no key left ``sending`` and lists every key
   ``uncertain`` or ``failed`` (held for a person); a mail the control night sent that the drilled night neither sent
   nor holds is counted as missing;
3. *an intact audit chain* (:func:`check_audit`): the product's verifier (``tools/audit_verify.py``, in the
   orchestrator's container) exits 0, the audit journal is drained (no event waits in it) and the chain gained
   events after the kill (a box that stopped auditing is not intact).

Each target's record is ``<out>/<target>.json``; :func:`render` writes the table of the measurement page from them.
The logic is tested on stand-ins in ``tests/unit/test_failure_drill.py`` (no box); the run itself is ``make
failure-drill``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

#: the stages of the night, in order (module text)
STAGES = ("mailed", "ingest", "notices")
#: the studies the night mails FEAS and SCREEN for (shipped synthetic examples of ``rulesets/``)
STUDIES = ("GZQO", "RA-JAK")
#: a job in one of these states has ended
TERMINAL = ("done", "failed")
#: a job in this state waits for a person by design (an approval); it is settled, not stuck
WAITS = ("awaiting_approval",)
#: the outbox states that wait for a person (``services/mail_gateway/store.py``)
HELD = ("uncertain", "failed")
#: how long the disk stays full, seconds
FULL_FOR_S = 90
#: how long the box has to recover by itself after a kill (Docker's restart, the services' own retries), seconds
RECOVER_S = 300
#: how long the night has to finish after the recovery, seconds
FINISH_S = 900


@dataclass(frozen=True)
class Target:
    """One thing the drill kills: ``name`` (the record's), ``kind`` (``service``, ``db`` or ``disk``), the compose
    ``service`` it acts on, the ``stage`` of the night it is killed in, and ``when``: what the drill waits for in
    that stage before it kills (said in the record)."""

    name: str
    kind: str
    service: str
    stage: str
    when: str


#: Each service of the compose test stack in turn, then the database, then the disk. The kill point of each is the
#: stage in which it is doing the night's work; ``when`` says what the drill waits for inside that stage.
TARGETS: tuple[Target, ...] = (
    Target("adapter", "service", "adapter", "ingest", "the adapter's ingest run is running"),
    Target("lake", "service", "lake", "ingest", "the ingest has ended and the lake is rebuilding"),
    Target("criteria-compiler", "service", "criteria-compiler", "mailed", "a mailed FEAS is running"),
    Target("orchestrator", "service", "orchestrator", "mailed", "a mailed job is running"),
    Target("gateway", "service", "gateway", "mailed", "a mailed SCREEN is running (it asks the model)"),
    Target("llm-stub", "service", "llm-stub", "mailed", "a mailed SCREEN is running (it asks the model)"),
    Target("mail-gateway", "service", "mail-gateway", "mailed", "the first result mail is in the outbox"),
    Target("audit-writer", "service", "audit-writer", "mailed", "a mailed job is running"),
    Target("doc-parser", "service", "doc-parser", "mailed", "a mailed job is running"),
    Target("embed-service", "service", "embed-service", "mailed", "a mailed SCREEN is running"),
    Target("fhir-store", "service", "fhir-store", "ingest", "the adapter's ingest run is running"),
    Target("console", "service", "console", "notices", "the morning notices are being sent"),
    Target("db", "db", "db", "mailed", "a mailed job is running"),
    Target("disk", "disk", "db", "ingest", "the adapter's ingest run is running"),
)


def target(name: str) -> Target:
    for t in TARGETS:
        if t.name == name:
            return t
    raise KeyError(f"no target {name!r}: {', '.join(t.name for t in TARGETS)}")


# ---------------------------------------------------------------------------------------------- the three checks
@dataclass
class Check:
    """One check's result: ``ok`` and the counts and lines that decided it."""

    ok: bool
    counts: dict[str, int] = field(default_factory=dict)
    lines: list[str] = field(default_factory=list)


def unit_of(job: Mapping[str, Any]) -> str:
    """The unit of the night's work a job is (D-1109): its type and study, and where it came from: ``mail`` (a
    mailed command), ``timer`` (the scheduler's own, the chain's included) or ``person``. A retry, a requeue and a
    second start of the same unit are the same unit: that is what makes "exactly once" countable."""
    by = str(job.get("requested_by") or "")
    origin = "mail" if job.get("message_id") else ("timer" if by in ("scheduler", "system") else "person")
    return f"{job.get('type')}:{job.get('ruleset') or '-'}:{origin}"


def check_jobs(control: Sequence[Mapping[str, Any]], drilled: Sequence[Mapping[str, Any]]) -> Check:
    """Check 1, no lost job (D-1109). ``control``: the jobs of the night without a kill; ``drilled``: the jobs of the
    drilled night, both as the orchestrator's ``GET /jobs`` gives them. A unit of the control is *lost* when the
    drilled night has no job for it, when its job is not in a terminal state, or when it failed with no reason; it
    is *visibly failed* (not lost) when it failed with a reason; *done twice* when two of its jobs are done."""
    want = sorted({unit_of(j) for j in control})
    chain = {unit_of(j) for j in control if (j.get("options") or {}).get("step")}  # the units the ingest's chain starts
    ingest_failed = any(
        j.get("type") == "INGEST" and unit_of(j).endswith(":timer") and j.get("state") == "failed" and _reason(j)
        for j in drilled
    ) and not any(j.get("type") == "INGEST" and j.get("state") == "done" for j in drilled)
    by_unit: dict[str, list[Mapping[str, Any]]] = {}
    for j in drilled:
        by_unit.setdefault(unit_of(j), []).append(j)
    c = Counter({"units": len(want), "done_once": 0, "visibly_failed": 0, "missing": 0, "stuck": 0,
                 "failed_no_reason": 0, "done_twice": 0, "behind_failed_ingest": 0})  # fmt: skip
    lines: list[str] = []
    for u in want:
        jobs = by_unit.get(u, [])
        done = [j for j in jobs if j.get("state") == "done"]
        open_ = [j for j in jobs if j.get("state") not in (*TERMINAL, *WAITS)]
        waits = [j for j in jobs if j.get("state") in WAITS]
        failed = [j for j in jobs if j.get("state") == "failed"]
        if len(done) > 1:
            c["done_twice"] += 1
            lines.append(f"{u}: done {len(done)} times ({', '.join(str(j.get('job_id')) for j in done)})")
        if done or (waits and not open_):
            c["done_once"] += len(done) == 1 or not done
            continue
        if open_:
            c["stuck"] += 1
            lines.append(f"{u}: stuck in {', '.join(sorted({str(j.get('state')) for j in open_}))}")
        elif failed:
            reason = _reason(failed[-1])
            if reason:
                c["visibly_failed"] += 1
                lines.append(f"{u}: failed with a reason: {reason}")
            else:
                c["failed_no_reason"] += 1
                lines.append(f"{u}: failed with no reason")
        elif u in chain and ingest_failed:
            c["behind_failed_ingest"] += 1
            lines.append(f"{u}: no job: the chain waits behind the night's ingest, which failed with a reason")
        else:
            c["missing"] += 1
            lines.append(f"{u}: no job")
    lost = c["missing"] + c["stuck"] + c["failed_no_reason"]
    return Check(lost == 0 and c["done_twice"] == 0, {**c, "lost": lost}, lines)


def _reason(job: Mapping[str, Any]) -> str:
    err = job.get("error") or {}
    msg = err.get("message") if isinstance(err, Mapping) else str(err)
    return str(msg or "").strip()


_JOB_ID = re.compile(r"\b[0-9A-HJKMNP-TV-Z]{26}\b|\b[0-9a-f]{8}-[0-9a-f-]{27}\b|\bJ-[0-9A-Za-z-]+\b")


def mail_event(subject: str) -> str:
    """The event a subject names, without the job's id (ids differ between the control and the drilled night)."""
    return _JOB_ID.sub("<job>", " ".join(subject.split()))


def check_mail(
    control: Sequence[Mapping[str, Any]], drilled: Sequence[Mapping[str, Any]], outbox: Sequence[Mapping[str, Any]]
) -> Check:
    """Check 2, no double mail (D-1109). ``control`` and ``drilled``: the messages the hospital's mail server holds
    (``to``: list of addresses, ``subject``); ``outbox``: the gateway's send keys (``key``, ``state``). Double: one
    recipient got one subject twice. Missing: a (recipient, event) the control night mailed that the drilled night
    neither mailed nor holds in the outbox. ``sending`` left after the night is stuck."""
    got = Counter((r, str(m.get("subject") or "")) for m in drilled for r in m.get("to") or [])
    doubles = sorted((r, s, n) for (r, s), n in got.items() if n > 1)
    want = {(r, mail_event(str(m.get("subject") or ""))) for m in control for r in m.get("to") or []}
    have = {(r, mail_event(s)) for (r, s) in got}
    states = Counter(str(k.get("state")) for k in outbox)
    held = sum(states[s] for s in HELD)
    missing = sorted(want - have)
    lines = [f"{r}: {s!r} {n} times" for r, s, n in doubles]
    lines += [f"{r}: {e!r} not sent" for r, e in missing]
    lines += [f"outbox key {k.get('key')}: {k.get('state')}" for k in outbox if k.get("state") in (*HELD, "sending")]
    counts = {"messages": sum(got.values()), "double": len(doubles), "missing": len(missing), "held": held,
              "sending": states["sending"], "queued": states["queued"]}  # fmt: skip
    return Check(not doubles and not states["sending"], counts, lines)


def check_audit(
    verify_rc: int, verify_out: str, lines_before: int, lines_after: int, journal_left: int, work_after: bool = True
) -> Check:
    """Check 3, an intact chain (D-1109): the product's verifier exits 0, no journal row is missing from the chain
    (``journal_left``), and, when a job ended after the kill (``work_after``), the chain grew after it
    (``lines_before``: at the kill; ``lines_after``: at the end): a box that stopped auditing is not intact."""
    lines = []
    if verify_rc != 0:
        lines.append(f"audit_verify exit {verify_rc}: {verify_out.strip()[-300:]}")
    if journal_left:
        lines.append(f"{journal_left} journal rows are not in the chain")
    stopped = work_after and lines_after <= lines_before
    if stopped:
        lines.append(
            f"jobs ended after the kill but no event was added to the chain ({lines_before} lines at the kill, "
            f"{lines_after} at the end)"
        )
    counts = {"verify_rc": verify_rc, "lines_at_kill": lines_before, "lines_at_end": lines_after,
              "journal_left": journal_left, "work_after": int(work_after)}  # fmt: skip
    return Check(verify_rc == 0 and not journal_left and not stopped, counts, lines)


# ------------------------------------------------------------------------------------------------- one record
@dataclass
class Record:
    """What happened to one target (``<out>/<target>.json``)."""

    target: str
    kind: str
    service: str
    stage: str
    when: str
    killed: str = ""  # what was killed, exactly
    killed_at_s: float = 0.0  # seconds into the night
    recovered_by: str = ""  # "docker restart policy", "itself", "a person: <what>", "not recovered"
    recover_s: float | None = None
    finished: bool = False  # the night's work ended within the window
    jobs: Check | None = None
    mail: Check | None = None
    audit: Check | None = None
    notes: list[str] = field(default_factory=list)
    run: int = 1

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, d: Mapping[str, Any]) -> Record:
        kw = dict(d)
        for k in ("jobs", "mail", "audit"):
            if kw.get(k) is not None:
                kw[k] = Check(**kw[k])
        return cls(**kw)


def needs_person(r: Record) -> bool:
    return r.recovered_by.startswith("a person") or r.recovered_by == "not recovered"


def verdict(c: Check | None) -> str:
    if c is None:
        return "not run"
    return "pass" if c.ok else "FAIL"


def render(records: Iterable[Record]) -> str:
    """The table of the measurement page: one row per target and run."""
    head = (
        "| Target | Killed (exactly) | Stage, when | Recovery | Recover s | Night finished | Lost jobs | "
        "Double mails | Audit chain |\n| --- | --- | --- | --- | --- | --- | --- | --- | --- |"
    )
    rows = []
    for r in records:
        rec = "" if r.recover_s is None else f"{r.recover_s:.0f}"
        lost, mail = "not run", "not run"
        if r.jobs is not None:
            jc = r.jobs.counts
            lost = (f"{verdict(r.jobs)}: {jc.get('lost', 0)} lost, {jc.get('visibly_failed', 0)} failed with a "
                    f"reason, {jc.get('done_twice', 0)} twice")  # fmt: skip
        if r.mail is not None:
            mc = r.mail.counts
            mail = f"{verdict(r.mail)}: {mc.get('double', 0)} double, {mc.get('missing', 0)} missing, " \
                f"{mc.get('held', 0)} held"  # fmt: skip
        aud = "not run" if r.audit is None else f"{verdict(r.audit)}: verify exit {r.audit.counts.get('verify_rc')}"
        run = f" (run {r.run})" if r.run > 1 else ""
        rows.append(
            f"| {r.target}{run} | {r.killed or 'not killed'} | {r.stage}, {r.when} | {r.recovered_by} | {rec} | "
            f"{'yes' if r.finished else 'no'} | {lost} | {mail} | {aud} |"
        )
    return "\n".join([head, *rows])


def load(out: Path) -> list[Record]:
    order = {t.name: i for i, t in enumerate(TARGETS)}
    raw = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(out.glob("*.json"))]
    recs = [Record.from_json(d) for d in raw if isinstance(d, dict) and d.get("target") in order]
    return sorted(recs, key=lambda r: (order[r.target], r.run))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools.failure_drill", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan")
    r = sub.add_parser("run")
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--target", action="append", default=[])
    r.add_argument("--run", type=int, default=1, help="the run's number, for a target run twice")
    p = sub.add_parser("report")
    p.add_argument("out", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "plan":
        for t in TARGETS:
            print(f"{t.name:18} {t.kind:8} {t.service:18} {t.stage:8} {t.when}")
        return 0
    if a.cmd == "report":
        print(render(load(a.out)))
        return 0
    from tools.failure_drill_box import drill  # the live part: Docker only

    return drill(a.out, [target(n) for n in a.target] or list(TARGETS), a.run)


if __name__ == "__main__":
    sys.exit(main())
