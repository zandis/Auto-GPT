"""H-33 (D-1122): back up a box, wipe every volume, restore it by the restore page alone, timed; then compare.

    python -m tools.restore_drill extract [--json]       # the restore page's commands, in order, with their place
    python -m tools.restore_drill plan                   # the path the follower walks, and what it may supply
    python -m tools.restore_drill run --work DIR --out RECORD.json [--keep]   # make restore-drill: the compose box
    python -m tools.restore_drill compare RECORD.json    # the record's before/after against D-1122's rules
    python -m tools.restore_drill findings RECORD.json --out FINDINGS.json   # the findings, in --add-from form

**What is followed.** The restore page of the box owner: the paragraph **Restore.** of RUNBOOK §5
(``docs/runbook/05-updates-backup-restore-secrets.md``) up to its section ``## Secrets``, its numbered steps and the
paragraph "Database roles after a restore". The hub's convention holds (commands from the release folder, as root).
The backup before it is taken as §5's **Backup** paragraph says (``backup-keygen`` once, the targets in
``deploy/.env``, ``backup-nightly``, which the cron runs and a person may run by hand).

**The extraction rule** is H-22's (``tools.runbook_install.extract``, D-1136), imported, with one head added:
``trialbox `` (the restore page names its commands ``trialbox restore``, ``trialbox backup-verify``). Each command
keeps its place, its block and the sentence that introduces it.

**The follower** runs each command of the path as written, from the release folder, as root, and supplies only what
the page names: the backup file and its key (step 3), the pack folder (step 1), the role script's variable (the
"Database roles" paragraph), the command a restore prints for a person to run. Anything else it needed is a finding
with the page's sentence quoted, then *lifted* (``LIFTS``): the smallest remedy another page of the repository or the
tool's own message states, applied once and recorded; every later result is "after lifts". A lift never changes the
verdict "did the page alone restore the box". A machine stand-in (the test stack in place of §1's reinstall) is a lift
of kind ``machine``: not a finding.

**The box** (``ComposeDrill``): the compose test stack (``make up-test``: the stub model, synthetic site A), the
machine's own Docker. A night's work fills every store (``seed``). *Wipe every volume* is ``docker compose down
--volumes`` (every named volume of the project: the database, lake, audit, orchestrator, rules, mail, secrets,
console, terminology and traces volumes) and the bind-mounted object folder emptied; the host's release folder
(``deploy/``, its ``.env``, ``secrets/`` and ``site/``) stays, as on a box whose disks for data were lost and whose
release folder was reinstalled the same.

**The comparison** (D-1122): every database table by row count and content hash, every volume's files by sha256, the
audit chain's head and a verify of the whole chain, the opt-out list (and that the opted-out patient is still
withheld), the approved rule sets (version and files) and that a job after the restore runs on the same version, and
sign-in for each of the four roles (password and code), with a session opened before the wipe refused after it.
What the restore itself writes (its audit events, the hold flag, the failed jobs) is named in ``EXPECTED_CHANGES``.

Not T-730d's ``trialbox restore-drill`` (D-892, ``tools/trialbox/restore_drill.py``: a backup restored into scratch
databases on a live box); this drill wipes a test box and restores it by the page.

Nothing here prints or records a password, a key, a code, a token or a row: names, counts, sizes and hashes only.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from tools import runbook_install as ri  # noqa: E402  (H-22's extraction rule, imported)

PAGE = "docs/runbook/05-updates-backup-restore-secrets.md"
START = "**Restore.**"
END = "## Secrets"
HEADS = (*ri.HEADS, "trialbox ")
CARD = "H33"
DATE = "2026-11-18"
RECORD_DIR = "docs/plan/measurements/restore-drill-2026-11-18"
PAGE_OUT = "docs/plan/measurements/restore-drill-2026-11-18.md"
DECISION = "D-1122"


# ------------------------------------------------------------------------------------------------ extraction
@contextlib.contextmanager
def _heads(heads: tuple[str, ...]) -> Any:
    """H-22's rule with this card's heads: ``ri.is_command`` reads ``ri.HEADS`` at call time."""
    old = ri.HEADS
    ri.HEADS = heads  # type: ignore[assignment]
    try:
        yield
    finally:
        ri.HEADS = old


def section_lines(root: Path = ROOT) -> tuple[int, int]:
    """The 1-based first and last line of the restore page (``**Restore.**`` up to ``## Secrets``)."""
    lines = (root / PAGE).read_text(encoding="utf-8").split("\n")
    first = next(i for i, ln in enumerate(lines, 1) if ln.startswith(START))
    last = next(i for i, ln in enumerate(lines, 1) if i > first and ln.startswith(END)) - 1
    return first, last


def restore_commands(root: Path = ROOT) -> list[ri.Command]:
    """Every command of the restore page, in the order written (H-22's rule, plus ``trialbox ``)."""
    first, last = section_lines(root)
    with _heads(HEADS):
        cmds = ri.extract(PAGE, root)
    return [c for c in cmds if first <= c.line <= last]


def find(cmds: Sequence[ri.Command], starts: str) -> ri.Command:
    for c in cmds:
        if c.text.startswith(starts):
            return c
    raise LookupError(f"the restore page has no command starting {starts!r}")


def sentence(root: Path, needle: str) -> tuple[str, str]:
    """The place (``file:line``) and the folded sentence of the restore page that holds ``needle``."""
    first, last = section_lines(root)
    lines = (root / PAGE).read_text(encoding="utf-8").split("\n")
    for n in range(first, last + 1):
        if needle in lines[n - 1]:
            para = " ".join(ln.strip() for ln in lines[n - 1 : min(n + 2, last)])
            i = para.index(needle)
            return f"{PAGE}:{n}", ri._sentence(para, i, i + len(needle))
    raise LookupError(f"the restore page does not say {needle!r}")


# ------------------------------------------------------------------------------------------------ the path
@dataclass(frozen=True)
class PathStep:
    """One step of the restore path: the page's command (or ``None``: the page gives none) and what may fill it."""

    key: str
    starts: str | None  # the page command it runs (its text starts so), or None
    what: str
    supplies: tuple[str, ...] = ()


PATH: tuple[PathStep, ...] = (
    PathStep(
        "verify",
        "trialbox backup-verify",
        "the preamble: see which vendor pack the backup names",
        ("<file>: the newest backup on the off-box target", "<private key>: the key from the envelope"),
    ),
    PathStep("reinstall", None, "step 1: reinstall (§1) and put each named pack in deploy/refdata/loaded"),
    PathStep("stop", "docker compose stop", "step 2: stop every service but the database"),
    PathStep(
        "restore",
        "trialbox restore",
        "step 3: the restore",
        (
            "<file>",
            "<private key>",
            "--refdata <folder>: deploy/refdata/loaded",
            "TB_DB_ROLES_CMD: as the paragraph 'Database roles after a restore' writes it",
        ),
    ),
    PathStep("roles", None, "Database roles after a restore: the command the restore prints, when it prints one"),
    PathStep(
        "migrate", "python3 -m tools.trialbox migrate", "Database roles: after a restore, once after the role script"
    ),
    PathStep("start", None, "step 2's last sentence: start them again after the restore"),
)


@dataclass(frozen=True)
class Lift:
    """The smallest remedy for a stop the page leaves, from another page or the tool's own message (D-1122)."""

    key: str
    kind: str  # "page" (the page is silent or wrong: a finding) or "machine" (this machine lacks what §1 names)
    needle: str  # the words of the restore page the lift is against (quoted in the finding)
    remedy: str
    source: str


LIFTS: dict[str, Lift] = {
    "trialbox-command": Lift(
        "trialbox-command",
        "page",
        "`trialbox restore <file> --key <private key> --yes",
        "run `python3 -m tools.trialbox <subcommand>` where the page says `trialbox <subcommand>`",
        "§5's own Backup paragraph (`python -m tools.trialbox backup-keygen`, `python3 -m tools.trialbox "
        "backup-status`) and the hub (commands from /opt/trialbox); no `trialbox` program is installed on the host",
    ),
    "compose-project": Lift(
        "compose-project",
        "page",
        "`docker compose stop $(docker compose ps --services | grep -vx db)`",
        "add `--project-directory deploy` to each `docker compose` of the line",
        "the rest of §5 (`docker compose --project-directory deploy ...`) and H-22's finding 11 (§1 step 7)",
    ),
    "restore-db-url": Lift(
        "restore-db-url",
        "page",
        "`trialbox restore <file> --key <private key> --yes",
        "TB_DB_URL and TB_HAPI_DB_URL for the restore's process, naming the database where the host reaches it "
        "(the test stack publishes it on 127.0.0.1:5433), with the passwords of deploy/.env",
        "the restore's own message (`TB_DB_URL is not set: nothing to back up from the database`) and the module's "
        "opening text (`tools/trialbox/backup.py`: `trial and HAPI databases ... TB_DB_URL ... TB_HAPI_DB_URL`)",
    ),
    "host-python": Lift(
        "host-python",
        "page",
        "`trialbox restore <file> --key <private key> --yes",
        "run the page's commands with a python3 that has the release's packages (here the release's own virtual "
        "environment first on PATH)",
        "the tool's own message (`ModuleNotFoundError: No module named 'zstandard'`); `pyproject.toml` names "
        "zstandard; §1 step 1 names only `python3-yaml` and `python3-cryptography` for the host",
    ),
    "objects-bind": Lift(
        "objects-bind",
        "machine",
        "`trialbox restore <file> --key <private key> --yes",
        "TB_BACKUP_DIRS naming every default volume folder, with `objects` at the test stack's bind folder "
        "(deploy/.objects): on this machine only, the object volume is a bind mount (docker-compose.test.yml)",
        "the restore's own option (`--dir` / `TB_BACKUP_DIRS`, tools/trialbox/backup.py `layout`); run 2 of this "
        "card restored the objects under the volume's mount point, where the bind mount hid them",
    ),
    "reinstall-test-stack": Lift(
        "reinstall-test-stack",
        "machine",
        "Reinstall (§1)",
        "`make up-test` on empty volumes in place of §1's install from the bundle (H-22/H-24 follow §1 itself)",
        "D-1122: this card follows the restore page; §1 is H-22's card",
    ),
}


# ------------------------------------------------------------------------------------------------ runner
@dataclass
class Ran:
    key: str
    written: str  # the page's command as written (or the step's words)
    run: str  # as run, secrets replaced by their names
    rc: int
    seconds: float
    out: str  # the last lines, redacted
    lifts: list[str] = field(default_factory=list)
    supplied: list[str] = field(default_factory=list)


Runner = Callable[[str, Mapping[str, str], float | None], tuple[int, str]]


def shell(cmd: str, env: Mapping[str, str], timeout: float | None = None, cwd: Path = ROOT) -> tuple[int, str]:
    """``cmd`` with bash in ``cwd`` (the release folder), the process environment plus ``env``; (exit, output). The
    page's ``docker compose`` lines name no project: here they reach the test stack (H-139), whatever the caller's
    COMPOSE_PROJECT_NAME says."""
    try:
        r = subprocess.run(
            ["bash", "-c", cmd],
            cwd=cwd,
            env={**os.environ, "PWD": str(cwd), "COMPOSE_PROJECT_NAME": TEST_PROJECT, **env},
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        got = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return 124, f"timed out after {timeout} s: {got[-400:]}"
    return r.returncode, (r.stdout or "") + (r.stderr or "")


SECRET_ARG = re.compile(r"(postgresql://[^:/@\s]+:)[^@\s]+@")


def scrub(text: str, hide: Iterable[str] = ()) -> str:
    """No password, key path content or token in a record: URLs lose their password; named values are replaced."""
    out = SECRET_ARG.sub(r"\1[redacted]@", text)
    for h in hide:
        if h:
            out = out.replace(h, "[redacted]")
    return ri.redact(out)


def tail(text: str, n: int = 1500) -> str:
    t = text.strip()
    return t if len(t) <= n else "…" + t[-n:]


class Follower:
    """Runs the restore path; a stop the page leaves is lifted only by ``LIFTS`` and recorded."""

    def __init__(
        self, run: Runner, root: Path = ROOT, hide: Sequence[str] = (), clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.run_cmd, self.root, self.hide, self.clock = run, root, list(hide), clock
        self.cmds = restore_commands(root)
        self.steps: list[Ran] = []
        self.lifted: list[str] = []
        self.stopped: str | None = None  # the first stop the page alone could not pass (the verdict)
        self.base: dict[str, str] = {}  # what a lift puts in every later command's environment
        self.machine: dict[str, str] = {}  # what the machine (not the page) needs in the restore's environment

    def lift(self, key: str, why: str) -> None:
        if key not in self.lifted:
            self.lifted.append(key)
        if self.stopped is None and LIFTS[key].kind == "page":
            self.stopped = f"{key}: {why}"

    def run(
        self,
        key: str,
        written: str,
        cmd: str,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
        supplied: Sequence[str] = (),
    ) -> Ran:
        t0 = self.clock()
        rc, out = self.run_cmd(cmd, {**self.base, **(env or {})}, timeout)
        r = Ran(
            key,
            written,
            scrub(cmd, self.hide),
            rc,
            round(self.clock() - t0, 2),
            tail(scrub(out, self.hide)),
            list(self.lifted),
            list(supplied),
        )
        self.steps.append(r)
        return r

    def trialbox(self, text: str) -> str:
        """The page's ``trialbox <sub>`` as run: as written until the host says there is no such program."""
        if "trialbox-command" in self.lifted and text.startswith("trialbox "):
            return "python3 -m tools.trialbox " + text[len("trialbox ") :]
        return text

    def compose(self, text: str) -> str:
        if "compose-project" in self.lifted:
            return text.replace("docker compose ", "docker compose --project-directory deploy ")
        return text

    @staticmethod
    def no_program(r: Ran) -> bool:
        return r.rc == 127 or "command not found" in r.out

    def python_lift(self, r: Ran, venv_bin: str) -> bool:
        if "ModuleNotFoundError" in r.out and "host-python" not in self.lifted:
            self.lift("host-python", "the host's python3 lacks a package the tool imports")
            self.base["PATH"] = f"{venv_bin}:{os.environ.get('PATH', '')}"
            return True
        return False

    def follow(
        self,
        backup: Path,
        key: Path,
        packs: Path,
        db_env: Callable[[], dict[str, str]],
        reinstall: Callable[[], Ran],
        after_restore: Callable[[], None] = lambda: None,
        venv_bin: str = str(ROOT / ".venv" / "bin"),
    ) -> dict[str, Any]:
        """The restore path, in the page's order. ``db_env`` gives the lift ``restore-db-url``'s values;
        ``reinstall`` is the machine's stand-in for §1. Returns the verdict and the times."""
        t0 = self.clock()
        fill = {
            "<file>": shlex.quote(str(backup)),
            "<private key>": shlex.quote(str(key)),
            "<folder>": shlex.quote(str(packs)),
        }

        def filled(text: str) -> str:
            for k, v in fill.items():
                text = text.replace(k, v)
            return text.replace("[--refdata ", "--refdata ").replace("]", "") if "[--refdata" in text else text

        # the preamble: backup-verify (the pack the backup names)
        v = find(self.cmds, "trialbox backup-verify")
        r = self.run("verify", v.text, filled(self.trialbox(v.text)), supplied=PATH[0].supplies)
        if self.no_program(r):
            self.lift("trialbox-command", "the host has no program `trialbox`")
            r = self.run("verify", v.text, filled(self.trialbox(v.text)), supplied=PATH[0].supplies)
        if self.python_lift(r, venv_bin):
            r = self.run("verify", v.text, filled(self.trialbox(v.text)), supplied=PATH[0].supplies)
        named = re.findall(r'"pack_id":\s*"([^"]+)"', r.out)
        # step 1: reinstall (machine stand-in), the packs in deploy/refdata/loaded
        self.lift("reinstall-test-stack", "this machine installs the test stack, not a bundle")
        self.steps.append(reinstall())
        # step 2: stop every service but db
        s = find(self.cmds, "docker compose stop")
        r = self.run("stop", s.text, self.compose(s.text))
        if r.rc != 0 and ("no configuration file" in r.out or "not found" in r.out):
            self.lift("compose-project", "`docker compose` from the release folder finds no compose file")
            r = self.run("stop", s.text, self.compose(s.text))
        # step 3: the restore
        rs = find(self.cmds, "trialbox restore")
        # the "Database roles after a restore" paragraph names the variable for the restore's environment
        roles = find(self.cmds, "TB_DB_ROLES_CMD=")
        env: dict[str, str] = {"TB_DB_ROLES_CMD": shlex.split(roles.text.split("=", 1)[1])[0], **self.machine}
        if self.machine:
            self.lift("objects-bind", "the test stack's object volume is a bind mount")
        r = self.run("restore", rs.text, filled(self.trialbox(rs.text)), env, supplied=PATH[3].supplies)
        if self.python_lift(r, venv_bin):
            r = self.run("restore", rs.text, filled(self.trialbox(rs.text)), env, supplied=PATH[3].supplies)
        if "TB_DB_URL is not set" in r.out or ("could not translate host name" in r.out and "db" in r.out):
            self.lift("restore-db-url", "the restore needs the databases' URLs, which the page does not name")
            env = {**env, **db_env()}
            r = self.run("restore", rs.text, filled(self.trialbox(rs.text)), env, supplied=PATH[3].supplies)
        restore_rc = r.rc
        after_restore()
        # the role script, when the restore prints it (the "Database roles" paragraph)
        m = re.search(r"Run, from the release folder: (docker compose [^\n]*?30-service-roles\.sh)", r.out)
        if m:
            self.run("roles", "the line the restore prints (Database roles after a restore)", m.group(1))
        mg = find(self.cmds, "python3 -m tools.trialbox migrate")
        self.run("migrate", mg.text, mg.text, env)
        start = "docker compose start"  # the page: "Start them again after the restore." (no command given)
        self.run(
            "start", "Start them again after the restore. (no command on the page)", self.compose(start), timeout=900
        )
        return {
            "packs_named": named,
            "restore_rc": restore_rc,
            "total_s": round(self.clock() - t0, 2),
            "lifts": list(self.lifted),
            "page_alone": self.stopped is None,
            "stopped_at": self.stopped,
        }


# ------------------------------------------------------------------------------------------------ fingerprints
# one line per table, "schema.table|rows|hash": the hash of the sorted hashes of each row's text (D-1122)
FP_SQL = r"""SELECT format('SELECT %L, count(*), coalesce(md5(string_agg(md5(t::text), '''' '
  'ORDER BY md5(t::text))), '''') FROM %I.%I t', n.nspname || '.' || c.relname, n.nspname, c.relname)
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p') AND n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg\_toast%'
ORDER BY 1
\gexec
"""


def parse_tables(out: str) -> dict[str, list[Any]]:
    """``psql -At`` lines ``name|count|hash`` -> {name: [count, hash]}."""
    res: dict[str, list[Any]] = {}
    for ln in out.splitlines():
        parts = ln.split("|")
        if len(parts) == 3 and parts[1].isdigit():
            res[parts[0]] = [int(parts[1]), parts[2]]
    return res


def tree(root: Path, skip: Callable[[str], bool] = lambda rel: False) -> dict[str, str]:
    """{relative path: sha256} of every regular file under ``root`` (a missing root: empty)."""
    out: dict[str, str] = {}
    if not root.is_dir():
        return out
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.is_symlink():
            rel = p.relative_to(root).as_posix()
            if skip(rel):
                continue
            h = hashlib.sha256()
            with p.open("rb") as fh:
                for b in iter(lambda: fh.read(1 << 20), b""):
                    h.update(b)
            out[rel] = h.hexdigest()
    return out


def digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


# ------------------------------------------------------------------------------------------------ comparison
# D-1122: what the restore itself writes or what the layout leaves out on purpose (§5), so "equal" holds without it.
# Each key is a store; each value says which of its parts may differ and why. Anything else that differs is unequal.
EXPECTED_CHANGES: dict[str, dict[str, str]] = {
    "db:hapi": {
        "public.bt2_": "the FHIR server's own batch jobs, run again when it starts (after the restore's row check)",
        "public.trm_valueset": "the FHIR server's terminology pre-expansion, redone when it starts",
    },
    "db:trialbox_wf": {
        "new:edc.": "the EDC's tables, made empty by `python3 -m tools.trialbox migrate`, which the page says to run "
        "after a restore; the test stack had never run it, so they were not there before",
        "app.flag": "the hold `screening.after_restore` set and released by the restore (D-522), with its events",
        "audit.": "the restore's own audit events (backup.restored, the hold) go through the journal (D-394)",
        "flags.": "the hold `screening.after_restore` (D-522) is a row the restore writes",
        "orch.pool": "the opt-out worker clears the opted-out patient's rows again after a restore (§5: 'after a "
        "restore the opt-out worker deletes again the rows of every patient on the register')",
        "orch.judged_pairs": "the same: the judged-pair store of a patient on the register is cleared again (D-908)",
        "orch.answers": "the same: the answer store of a patient on the register is cleared again (D-1360)",
    },
    "volume:audit-data": {
        "": "the chain after the restore = the chain before it, then the restore's own events (the head moves on)",
    },
    "volume:lake-data": {
        "tmp/": "the lake's spill is left out on purpose (§5)",
        "db/gen/": "older lake generations: the backup leaves them out (its manifest: 'lake generations (the newest "
        "is db/<snapshot>.duckdb)'); §5's list of what is left out does not name them",
        "db/.open/": "the lake's reader links (the same files as db/): left out by the backup's manifest",
        ".rebuild.lock": "the lake's lock file: an empty file, made again by the lake",
        ".ndjson": "only CURRENT's and the two newest snapshots' NDJSON are kept (§5)",
    },
}


def compare_tables(
    before: Mapping[str, Sequence[Any]], after: Mapping[str, Sequence[Any]], allowed: Mapping[str, str]
) -> dict[str, Any]:
    """Tables equal by count and hash; a difference under an allowed prefix is ``expected``, any other ``unequal``."""
    diff = sorted(k for k in set(before) | set(after) if list(before.get(k) or []) != list(after.get(k) or []))

    def fits(k: str) -> bool:
        for p in allowed:
            if p.startswith("new:"):
                if k not in before and k.startswith(p[4:]):
                    return True
            elif k.startswith(p):
                return True
        return False

    expected = [k for k in diff if fits(k)]
    unequal = [k for k in diff if k not in expected]
    rows = {k: [(before.get(k) or [None])[0], (after.get(k) or [None])[0]] for k in diff}
    return {
        "tables": len(set(before) | set(after)),
        "equal": len(set(before) | set(after)) - len(diff),
        "expected": expected,
        "unequal": unequal,
        "rows": rows,
        "ok": not unequal,
    }


def compare_files(
    before: Mapping[str, str], after: Mapping[str, str], allowed: Mapping[str, str], append_only: Sequence[str] = ()
) -> dict[str, Any]:
    """Files equal by sha256; a file only before under an allowed part is ``expected`` (left out by the layout); a
    file new after the restore is ``added`` (fine only under an allowed part); ``append_only`` files may grow."""
    missing = sorted(set(before) - set(after))
    added = sorted(set(after) - set(before))
    changed = sorted(k for k in set(before) & set(after) if before[k] != after[k])

    def ok_part(k: str) -> bool:
        return any((p and (k.startswith(p) or k.endswith(p))) or p == "" for p in allowed)

    bad = [k for k in missing if not ok_part(k)] + [k for k in changed if not (ok_part(k) or k in append_only)]
    return {
        "files": len(before),
        "equal": len(set(before) & set(after)) - len(changed),
        "missing": missing,
        "added": added,
        "changed": changed,
        "unequal": bad,
        "ok": not bad,
    }


def compare(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The comparison table: one row per store (D-1122)."""
    rows: list[dict[str, Any]] = []
    for db in sorted(set(before.get("db", {})) | set(after.get("db", {}))):
        c = compare_tables(
            before["db"].get(db, {}), after.get("db", {}).get(db, {}), EXPECTED_CHANGES.get(f"db:{db}", {})
        )
        rows.append(
            {
                "store": f"database {db}",
                "before": f"{c['tables']} tables",
                "after": f"{c['equal']} equal, {len(c['expected'])} changed as expected, {len(c['unequal'])} unequal",
                "equal": c["ok"],
                "detail": c,
            }
        )
    for vol in sorted(set(before.get("volumes", {})) | set(after.get("volumes", {}))):
        b, a = before["volumes"].get(vol, {}), after.get("volumes", {}).get(vol, {})
        c = compare_files(b, a, EXPECTED_CHANGES.get(f"volume:{vol}", {}))
        rows.append(
            {
                "store": f"volume {vol}",
                "before": f"{len(b)} files",
                "after": f"{len(a)} files, {len(c['unequal'])} unequal",
                "equal": c["ok"],
                "detail": c,
            }
        )
    for key, label in (
        ("audit_head", "the audit chain's head"),
        ("optouts", "the opt-out list"),
        ("rulesets", "the approved rule sets"),
        ("accounts", "the accounts"),
    ):
        b, a = before.get(key), after.get(key)
        if key == "audit_head":
            ok = bool(a and a.get("verified") and a.get("prefix_of_after")) and bool(b)
            rows.append(
                {
                    "store": label,
                    "before": (b or {}).get("hash", "-")[:16],
                    "after": (a or {}).get("hash", "-")[:16],
                    "equal": ok,
                    "detail": {"before": b, "after": a},
                }
            )
            continue
        rows.append(
            {
                "store": label,
                "before": digest(b)[:16] if b is not None else "-",
                "after": digest(a)[:16] if a is not None else "-",
                "equal": b == a and b is not None,
                "detail": {"before_n": len(b or {}), "after_n": len(a or {})},
            }
        )
    return rows


# ------------------------------------------------------------------------------------------------ findings
SEVERITY_RULE = (
    "plan 8's register rule (docs/handover/findings-register.md): High: a box that cannot be installed or restored, "
    "data not erased, an audit trail that can be wrong; Medium: a person slowed or misled, or a document's claim not "
    "true; Low: wording only"
)


def findings_doc(found: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The findings in the register's ``--add-from`` form (as ``module-walks-findings-2026-11-17.json``)."""
    return {
        "card": CARD,
        "title": "the restore by the runbook alone, timed, and compared",
        "date": DATE,
        "source": PAGE_OUT,
        "decision": DECISION,
        "findings": [dict(f) for f in found],
    }


def check_findings(doc: Mapping[str, Any], root: Path = ROOT) -> list[str]:
    """The findings file is well formed for the register: each id ``H33-<nn>``, the fields the register takes."""
    from tools import findings_register as fr

    probs: list[str] = []
    seen: set[str] = set()
    for f in doc.get("findings", []):
        fid = str(f.get("id", ""))
        if fid in seen:
            probs.append(f"{fid}: twice")
        seen.add(fid)
        if p := fr.id_problem(CARD, fid):
            probs.append(p)
        if str(f.get("severity", "")).split(" ")[0] not in fr.SEVERITIES:
            probs.append(f"{fid}: severity {f.get('severity')!r}")
        if f.get("lane") not in fr.LANES:
            probs.append(f"{fid}: lane {f.get('lane')!r}")
        if f.get("basis") not in fr.BASES:
            probs.append(f"{fid}: basis {f.get('basis')!r}")
        for k in ("claim", "step", "page_says", "happened", "expected", "expected_from"):
            if not str(f.get(k, "")).strip():
                probs.append(f"{fid}: no {k}")
    src = doc.get("source", "")
    if not (root / str(src)).is_file():
        probs.append(f"source {src} is not a file")
    return probs


# ------------------------------------------------------------------------------------------------ the compose box
VOLUMES = (
    "db-pg",
    "console-data",
    "objects-data",
    "lake-data",
    "audit-data",
    "orch-data",
    "rulesets-data",
    "mail-data",
    "tb-secrets",
    "tb-terminology",
    "traces-data",
)
NOT_FILES = ("db-pg",)  # the database's files: compared by its tables, not by its bytes
DOCKER_VOLUMES = Path(os.environ.get("TB_DOCKER_VOLUMES") or "/var/lib/docker/volumes")
#: H-139: the Makefile's TEST_PROJECT, the compose project `make up-test` brings up. The drill's compose commands and
#: the volumes it reads or removes are that project's, never the ``trialbox`` project of a box on the same host.
TEST_PROJECT = "trialbox-test"
ROLES = (
    ("drill-admin", "admin"),
    ("drill-crc", "coordinator"),
    ("drill-pi", "investigator"),
    ("drill-viewer", "viewer"),
    ("drill-steward", "steward"),
)
FOUR = ("drill-admin", "drill-crc", "drill-pi", "drill-viewer")  # the card's four roles; the steward keeps opt-outs


def console() -> str:
    """H-139: the console's address, from the test stack's own console container (tests/stack.py), never a constant."""
    from tests.stack import url

    return url("CONSOLE")


KEY = Path("/media/usb/trialbox-backup.key")  # where §5's backup-keygen line writes the private key
RELEASE = Path("/opt/trialbox")  # the hub: commands run on the box from /opt/trialbox as root
MAIL_AUTH = "mx.hospa.test; spf=pass smtp.mailfrom=hospa.test; dkim=pass header.d=hospa.test; dmarc=pass"
SCREEN_VERSION = "1.0.0"  # the shipped example rule set a TEST box seeds approved (D-640)


def env_file(path: Path) -> dict[str, str]:
    from tools.trialbox import update

    return dict(update._env_file(path))


class ComposeDrill:
    """The compose test stack on this machine's Docker, as ``make up-test`` brings it up (the stub model)."""

    def __init__(self, work: Path, log: Callable[[str], None] = print) -> None:
        self.work = work
        self.log = log
        self.deploy = ROOT / "deploy"
        self.env = env_file(self.deploy / ".env")
        self.objects = Path(self.env.get(objects_var()) or self.deploy / ".objects")
        self.passwords = {u: secrets.token_urlsafe(18) for u, _ in ROLES}
        self.totp: dict[str, str] = {}
        self._step: dict[str, int] = {}

    # -- plumbing
    def sh(self, cmd: str, timeout: float | None = 1800, env: Mapping[str, str] | None = None) -> tuple[int, str]:
        return shell(cmd, env or {}, timeout)

    def compose(
        self, args: str, timeout: float | None = 1800, stdin: str | None = None, env: Mapping[str, str] | None = None
    ) -> tuple[int, str]:
        cmd = f"docker compose --project-directory deploy -p {TEST_PROJECT} {args}"
        if stdin is None:
            return self.sh(cmd, timeout, env)
        r = subprocess.run(
            ["bash", "-c", cmd],
            cwd=ROOT,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, **(env or {})},
            check=False,
        )
        return r.returncode, r.stdout + r.stderr

    def psql(self, db: str, user: str, sql: str) -> str:
        rc, out = self.compose(f"exec -T db psql -X -At -v ON_ERROR_STOP=1 -U {user} -d {db}", stdin=sql)
        if rc != 0:
            raise RuntimeError(f"psql {db}: {tail(scrub(out), 400)}")
        return out

    def py(self, service: str, script: str, env: Mapping[str, str] | None = None) -> str:
        names = " ".join(f"-e {k}" for k in (env or {}))
        rc, out = self.compose(f"exec -T {names} {service} python -", stdin=script, env=env)
        if rc != 0:
            raise RuntimeError(f"python in {service}: {tail(scrub(out, (env or {}).values()), 600)}")
        return out

    def vol(self, name: str) -> Path:
        if name == "objects-data":
            return self.objects
        return DOCKER_VOLUMES / f"{TEST_PROJECT}_{name}" / "_data"

    # -- the box
    def up(self) -> tuple[int, str]:
        return self.sh("make up-test", timeout=1800)

    def wipe(self) -> dict[str, Any]:
        """Every named volume of the project removed; the bind-mounted object folder emptied. A volume compose does not
        remove (one a one-off container made first, such as the backup job's ``<project>_tb-secrets``) is removed by
        name; ``removed_by_name`` lists them."""
        rc, out = self.compose("down --volumes --remove-orphans", timeout=900)
        by_name = [v for v in VOLUMES if (DOCKER_VOLUMES / f"{TEST_PROJECT}_{v}").exists()]
        for v in by_name:
            self.sh(f"docker volume rm -f {TEST_PROJECT}_{v}", timeout=120)
        left = [v for v in VOLUMES if (DOCKER_VOLUMES / f"{TEST_PROJECT}_{v}").exists()]
        if self.objects.is_dir():
            for p in self.objects.iterdir():
                shutil.rmtree(p) if p.is_dir() else p.unlink()
        return {
            "rc": rc,
            "removed_by_name": by_name,
            "volumes_left": left,
            "objects_left": sorted(p.name for p in self.objects.glob("*")),
            "out": tail(out, 400),
        }

    # -- the night's work
    def seed_accounts(self) -> dict[str, Any]:
        """Four accounts (one per role), each with its own password and an authenticator (TOTP)."""
        for u, _ in ROLES:
            self.totp[u] = __import__("base64").b32encode(secrets.token_bytes(20)).decode().rstrip("=")
        env = {f"TBD_PW_{i}": self.passwords[u] for i, (u, _) in enumerate(ROLES)}
        env.update({f"TBD_TOTP_{i}": self.totp[u] for i, (u, _) in enumerate(ROLES)})
        script = (
            "import os\nfrom pathlib import Path\nfrom console.auth import UserStore\nfrom console import totp\n"
            "from console.identity import IdentitySettings\n"
            "s = IdentitySettings.from_env(os.environ, os.environ.get('TB_ENV', 'TEST'),\n"
            "                              Path(os.environ['TB_CONSOLE_DIR']))\n"
            "box = totp.SecretBox(s.totp_key_file)\nus = UserStore()\n"
            f"for i, (u, role) in enumerate({list(ROLES)!r}):\n"
            "    if us.get(u) is None:\n"
            "        us.create(u, role, os.environ[f'TBD_PW_{i}'], f'{u}@hospa.test', must_change=False)\n"
            "    else:\n"
            "        us.set_password(u, os.environ[f'TBD_PW_{i}'], must_change=False, owner=True)\n"
            "    if us.totp_state(u)[0] is not None:\n"
            "        us.reset_totp(u)\n"
            "    us.set_totp(u, box.seal(u, os.environ[f'TBD_TOTP_{i}']), 0)\n"
            "print('accounts', len(us.list_users()) if hasattr(us, 'list_users') else 'made')\n"
        )
        return {"out": tail(self.py("console", script, env), 300)}

    def sign_in(self, user: str) -> dict[str, Any]:
        """Password then code, as a browser does; the session cookie is returned (kept in the drill's memory only)."""
        import httpx

        with httpx.Client(base_url=console(), follow_redirects=False, timeout=30) as c:
            g = c.get("/login")
            csrf = re.search(r'name="login_csrf" value="([^"]+)"', g.text)
            r = c.post(
                "/login",
                data={"username": user, "password": self.passwords[user], "login_csrf": csrf.group(1) if csrf else ""},
            )
            if r.status_code != 303 or not r.headers.get("location", "").startswith("/login/totp"):
                return {"user": user, "password": r.status_code, "code": None, "ok": False}
            p = c.get("/login/totp")
            m = re.search(r'name="mfa_csrf" value="([^"]+)"', p.text)
            code = self.code(user)
            r2 = c.post("/login/totp", data={"code": code, "mfa_csrf": m.group(1) if m else ""})
            cookie = c.cookies.get("tb_console")
            home = c.get("/account") if cookie else None
            ok = r2.status_code == 303 and bool(cookie) and home is not None and home.status_code == 200
            return {
                "user": user,
                "password": 303,
                "code": r2.status_code,
                "home": home.status_code if home else None,
                "ok": ok,
                "_cookie": cookie,
            }

    @staticmethod
    def session_works(cookie: str | None) -> int | None:
        import httpx

        if not cookie:
            return None
        r = httpx.get(f"{console()}/account", cookies={"tb_console": cookie}, follow_redirects=False, timeout=30)
        return r.status_code

    # -- fingerprints
    def fingerprint(self) -> dict[str, Any]:
        fp: dict[str, Any] = {"db": {}, "volumes": {}}
        fp["db"]["trialbox_wf"] = parse_tables(self.psql("trialbox_wf", "trialbox", FP_SQL))
        fp["db"]["hapi"] = parse_tables(self.psql("hapi", "hapi", FP_SQL))
        for v in VOLUMES:
            if v not in NOT_FILES:
                fp["volumes"][v] = tree(self.vol(v))
        head = self.vol("audit-data") / "HEAD.json"
        fp["audit_head"] = json.loads(head.read_text()) if head.is_file() else None
        rc, out = self.sh(f"{sys.executable} tools/audit_verify.py {shlex.quote(str(self.vol('audit-data')))} --json")
        fp["audit_verify"] = {"rc": rc, "out": tail(out, 400)}
        fp["optouts"] = self.psql(
            "trialbox_wf",
            "trialbox",
            "SELECT pid || '|' || action || '|' || coalesce(source,'')"
            " || '|' || by || '|' || at FROM optout.optout_events ORDER BY id",
        ).splitlines()
        fp["accounts"] = self.psql(
            "trialbox_wf",
            "trialbox",
            "SELECT username || '|' || role || '|' || md5(u::text) FROM auth.users u ORDER BY username",
        ).splitlines()
        fp["rulesets"] = self.rulesets()
        return fp

    def rulesets(self) -> dict[str, Any]:
        from tb_common.ruleset import load_approved

        root = self.vol("rulesets-data")
        out: dict[str, Any] = {}
        for d in (
            sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")) if root.is_dir() else []
        ):
            try:
                ver = load_approved(root, d.name).version
            except Exception as e:
                ver = f"none ({type(e).__name__})"
            out[d.name] = {"version": ver, "files": digest(tree(d))}
        return out

    # -- the night's work through the box's own doors (mail in, the console)
    def mail_in(self, subject: str) -> str:
        import smtplib
        from email.message import EmailMessage
        from email.utils import make_msgid

        from tests.stack import host_port

        m = EmailMessage()
        m["From"], m["To"], m["Subject"] = "crc1@hospa.test", "trialbox@hospa.test", subject
        m["Message-ID"] = mid = make_msgid(domain="hospa.test")
        m["Authentication-Results"] = MAIL_AUTH  # what the hospital's MTA adds in front of the intake mailbox
        m.set_content("H-33 restore drill (synthetic)")
        with smtplib.SMTP("127.0.0.1", host_port("SMTP"), timeout=30) as s:
            s.send_message(m)
        return mid

    def job_by_tag(self, jtype: str, tag: str, timeout: float = 300) -> dict[str, Any]:
        import httpx
        from tb_common.service_auth import auth_headers

        from tests.stack import url

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            jobs = httpx.get(
                url("ORCH", "/jobs"), headers=auth_headers(), params={"type": jtype, "limit": 50}, timeout=30
            ).json()
            job = next((j for j in jobs if j.get("comment") == tag), None)
            if job:
                return dict(job)
            time.sleep(2)
        raise RuntimeError(f"no {jtype} job with the tag {tag} after {timeout} s")

    def job(self, job_id: str, until: Sequence[str] = ("done", "failed"), timeout: float = 1800) -> dict[str, Any]:
        import httpx
        from tb_common.service_auth import auth_headers

        from tests.stack import url

        deadline = time.monotonic() + timeout
        while True:
            j = dict(httpx.get(url("ORCH", f"/jobs/{job_id}"), headers=auth_headers(), timeout=30).json())
            if j.get("state") in until or time.monotonic() > deadline:
                return j
            time.sleep(2)

    def screen_list(self, job_id: str, timeout: float = 600) -> list[str]:
        """The pseudonyms of the SCREEN list the box mailed for ``job_id`` (the 7z and its password mail)."""
        import io
        import tempfile

        import py7zr

        from tests.stack import outbound_mail

        deadline = time.monotonic() + timeout
        lst = pw = None
        while time.monotonic() < deadline and not (lst and pw):
            msgs = outbound_mail()
            lst = next(
                (
                    m
                    for m in msgs
                    if str(m["Subject"]).startswith("[GZQO] SCREEN candidates") and str(m["Subject"]).endswith(job_id)
                ),
                None,
            )
            pw = lst and next(
                (
                    m
                    for m in msgs
                    if str(m["Subject"]).startswith("Password") and str(lst["Subject"]) in str(m["Subject"])
                ),
                None,
            )
            if not (lst and pw):
                time.sleep(3)
        if not (lst and pw):
            raise RuntimeError(f"no SCREEN list mail for {job_id}")
        ((_name, data),) = [(p.get_filename(), p.get_payload(decode=True)) for p in lst.iter_attachments()]
        body = pw.get_body(("plain",))
        text = str(body.get_content()) if body is not None else ""
        password = next(ln.strip() for ln in text.splitlines() if ln.startswith("    "))
        if not isinstance(data, bytes):
            raise RuntimeError("the SCREEN list mail carries no file")
        with tempfile.TemporaryDirectory() as td, py7zr.SevenZipFile(io.BytesIO(data), password=password) as z:
            z.extractall(td)
            js = next(p for p in Path(td).rglob("*.json"))
            rows = json.loads(js.read_text(encoding="utf-8")).get("rows") or []
        return sorted({str(r.get("pid")) for r in rows if r.get("pid")})

    def screen(self, tag: str) -> dict[str, Any]:
        """A SCREEN of the pinned rule set by mail; its job, the version it ran on, and its list."""
        self.mail_in(f"SCREEN GZQO version={SCREEN_VERSION} -- {tag}")
        j = self.job_by_tag("SCREEN", tag)
        final = self.job(str(j["job_id"]))
        listed = self.screen_list(str(j["job_id"])) if final.get("state") == "done" else []
        return {
            "job_id": j["job_id"],
            "state": final.get("state"),
            "ruleset": final.get("ruleset"),
            "ruleset_version": final.get("ruleset_version"),
            "listed": listed,
        }

    def console(self, user: str) -> Any:
        """A signed-in console client (password and code)."""
        import httpx

        r = self.sign_in(user)
        if not r.get("ok"):
            raise RuntimeError(f"{user} could not sign in: {r | {'_cookie': None}}")
        return httpx.Client(
            base_url=console(), cookies={"tb_console": r["_cookie"]}, follow_redirects=False, timeout=60
        )

    def opt_out(self, pid: str) -> int:
        from tools import feas_demo as fd

        with self.console("drill-steward") as c:
            page = c.get("/site/opt-outs")
            r = c.post(
                "/site/opt-outs",
                data={
                    "csrf": fd._csrf(page.text),
                    "pid": pid,
                    "source": "office",
                    "note": "H-33 drill: synthetic patient",
                },
            )
            return int(r.status_code)

    def new_ruleset(self) -> dict[str, Any]:
        """A study's criteria pasted by the coordinator, drafted by the stub and approved by the investigator (named
        PI on the study's delegation log by the steward): one rule set approved through the box, as e2e_simple's
        stage 12 does it in process."""
        from tools import e2e_simple as es
        from tools import feas_demo as fd

        out: dict[str, Any] = {"ruleset": es.SITE_RS}
        with self.console("drill-crc") as crc:
            form = crc.get("/pilot/protocol")
            r = crc.post(
                "/pilot/protocol",
                data={"csrf": fd._csrf(form.text), "ruleset": es.SITE_RS, "criteria": es.SITE_CRITERIA},
            )
            out["pasted"] = r.status_code
        deadline = time.monotonic() + 300
        waiting: list[str] = []
        while time.monotonic() < deadline and not waiting:
            waiting = self.psql(
                "trialbox_wf",
                "trialbox",
                f"SELECT job_id FROM orch.jobs WHERE ruleset = '{es.SITE_RS}' AND state = 'awaiting_approval'",
            ).split()
            if not waiting:
                time.sleep(3)
        out["drafted"] = bool(waiting)
        if not waiting:
            return out
        with self.console("drill-steward") as stw:
            log = stw.get(f"/studies/{es.SITE_RS}/team")
            r = stw.post(
                f"/studies/{es.SITE_RS}/team",
                data={
                    "csrf": fd._csrf(log.text),
                    "username": "drill-pi",
                    "role": "pi",
                    "start": "2026-01-01",
                    "training_day": "2025-06-01",
                },
            )
            out["pi_named"] = r.status_code
        with self.console("drill-pi") as pi:
            page = pi.get(f"/pilot/jobs/{waiting[0]}/approval")
            for cid in re.findall(r'data-testid="label-missing-([A-Z0-9-]+)"', page.text):
                pi.post(
                    f"/pilot/jobs/{waiting[0]}/approval/label",
                    data={"csrf": fd._csrf(page.text), "crit": cid, "text": cid},
                )
            page = pi.get(f"/pilot/jobs/{waiting[0]}/approval")
            r = pi.post(f"/pilot/jobs/{waiting[0]}/approve", data={"csrf": fd._csrf(page.text), "confirm": "yes"})
            out["approved"] = r.status_code
        out["state"] = self.job(waiting[0], until=("done", "failed", "approved"), timeout=300).get("state")
        return out

    def code(self, user: str) -> str:
        """A code from the account's authenticator, in a step not used yet (the box refuses a replayed step)."""
        from console import totp as T

        step = int(time.time() // 30)
        last = self._step.get(user, -1)
        if step <= last:
            time.sleep((last + 1) * 30 - time.time() + 0.5)
            step = int(time.time() // 30)
        self._step[user] = step
        return T.hotp(self.totp[user], step)

    def setup_files(self) -> dict[str, Any]:
        """The site set-up's uploads: two charts pasted, the IT dump and the PI's sheet uploaded (synthetic)."""
        from sitesetup import help as site_help

        from tools import e2e_simple as es
        from tools import feas_demo as fd

        q = f"ws={es.SITE_WS}&study={es.SITE_RS}"
        out: dict[str, Any] = {}
        with self.console("drill-crc") as crc:

            def csrf() -> str:
                return fd._csrf(crc.get(f"/site/charts?{q}").text)

            out["charts"] = [
                crc.post(
                    "/site/charts",
                    data={"csrf": csrf(), "ws": es.SITE_WS, "study": es.SITE_RS, "chart_no": no, "text": text},
                ).status_code
                for no, text in site_help.PRACTICE_CHARTS
            ]
            ins = site_help.practice_inputs()
            for kind, mime in (
                ("dump", "text/csv"),
                ("sheet", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            ):
                name, data = ins[kind]
                out[kind] = crc.post(
                    "/site/sheets",
                    data={"csrf": csrf(), "ws": es.SITE_WS, "study": es.SITE_RS, "kind": kind},
                    files={"file": (name, data, mime)},
                ).status_code
        return out

    def wait_healthy(self, timeout: float = 900) -> bool:
        import httpx

        from tests.stack import StackNotRunning

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with contextlib.suppress(httpx.HTTPError, StackNotRunning):  # H-139: not yet published while it starts
                if httpx.get(f"{console()}/healthz", timeout=5).status_code == 200:
                    rc, out = self.compose("ps --format '{{.Service}} {{.Health}}'", timeout=60)
                    if rc == 0 and "starting" not in out and "unhealthy" not in out:
                        return True
            time.sleep(5)
        return False

    def db_env(self) -> dict[str, str]:
        """The lift ``restore-db-url``: the two databases where this host reaches them (the test stack's port)."""
        from tests.stack import host_port

        port = host_port("WORKFLOW_DB")
        wf = self.env.get("POSTGRES_WF_PASSWORD") or self.env.get("POSTGRES_PASSWORD", "")
        return {
            "TB_DB_URL": f"postgresql://trialbox:{wf}@127.0.0.1:{port}/trialbox_wf",
            "TB_HAPI_DB_URL": f"postgresql://hapi:{self.env.get('POSTGRES_PASSWORD', '')}@127.0.0.1:{port}/hapi",
        }

    def machine_dirs(self) -> dict[str, str]:
        """The lift ``objects-bind``: the restore's default folders, the object folder where this stack binds it."""
        from tools.trialbox import backup as bk

        dirs = {k: str(self.vol(v)) for k, v in bk.DEFAULT_DIRS.items()}
        return {"TB_BACKUP_DIRS": ",".join(f"{k}={v}" for k, v in dirs.items())}

    def audit_files(self) -> dict[str, tuple[int, str]]:
        root = self.vol("audit-data")
        return {
            p.relative_to(root).as_posix(): (p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest())
            for p in sorted(root.rglob("*"))
            if p.is_file()
        }

    def chain_prefix(self, before: Mapping[str, Sequence[Any]]) -> dict[str, Any]:
        """Each audit file of before is the start of the same file after (the chain only grew)."""
        root = self.vol("audit-data")
        bad = []
        for rel, (size, sha) in before.items():
            if rel == "HEAD.json":
                continue
            p = root / rel
            if not p.is_file() or hashlib.sha256(p.read_bytes()[:size]).hexdigest() != sha:
                bad.append(rel)
        return {"files": len(before), "not_prefix": bad, "ok": not bad}


# ------------------------------------------------------------------------------------------------ the run
def _t(steps: list[dict[str, Any]], name: str, fn: Callable[[], Any]) -> Any:
    t0 = time.monotonic()
    try:
        res = fn()
        ok = True
    except Exception as e:
        res, ok = {"error": f"{type(e).__name__}: {tail(scrub(str(e)), 600)}"}, False
    steps.append({"step": name, "seconds": round(time.monotonic() - t0, 2), "ok": ok})
    print(f"restore-drill: {name}: {'ok' if ok else 'FAILED'} ({steps[-1]['seconds']} s)", flush=True)
    return res


def _clean(obj: Any) -> Any:
    """No session cookie in a record."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj


def run(work: Path, out: Path, *, fresh: bool = True, key: Path = KEY, release: Path = RELEASE) -> dict[str, Any]:
    """The whole drill on the compose test stack; the record is written to ``out`` (no secret, no row)."""
    work.mkdir(parents=True, exist_ok=True)
    box = ComposeDrill(work)
    steps: list[dict[str, Any]] = []
    rec: dict[str, Any] = {
        "card": CARD,
        "decision": DECISION,
        "machine": "compose test stack on this machine's Docker",
        "head": ri._git_head(ROOT),
        "started": datetime.now(UTC).isoformat(timespec="seconds"),
        "steps": steps,
    }
    nas, usb = work / "nas", work / "usbt"
    # -- a fresh box and its night
    from tools.trialbox.backup_schedule import set_env as _set

    rec["box_settings"] = prepare(_set)
    if fresh:
        rec["wipe_first"] = _t(steps, "box: wipe before the night (a clean start)", box.wipe)
    rec["up"] = _t(steps, "box: up (make up-test)", lambda: {"rc": box.up()[0]})
    rec["ingest"] = _t(
        steps,
        "night: ingest synthetic site A (adapter -> lake, FHIR store)",
        lambda: {"rc": box.sh(f"PYTHONPATH=libs:services:. {sys.executable} -m tests.stack", 1800)[0]},
    )
    rec["accounts"] = _t(steps, "night: five accounts with an authenticator", box.seed_accounts)
    s1 = _t(steps, "night: SCREEN by mail (the pinned rule set)", lambda: box.screen("h33-night-1"))
    pid = (s1.get("listed") or [None])[0]
    rec["optout"] = _t(steps, "night: the steward opts a listed patient out", lambda: {"status": box.opt_out(pid)})
    s2 = _t(steps, "night: SCREEN again: the patient withheld", lambda: box.screen("h33-night-2"))
    rec["screens_before"] = [_summ(s1, pid), _summ(s2, pid)]
    rec["new_ruleset"] = _t(steps, "night: a rule set drafted and approved in the console", box.new_ruleset)
    rec["setup_files"] = _t(steps, "night: set-up files uploaded", box.setup_files)
    sessions = {u: box.sign_in(u) for u in FOUR}
    rec["sign_in_before"] = _clean(sessions)
    before = _t(steps, "fingerprint before", box.fingerprint)
    audit_before = box.audit_files()
    # -- the backup, as §5's Backup paragraph says
    for d in (nas, usb):
        d.mkdir(parents=True, exist_ok=True)
    (nas / ".trialbox-offbox").touch()
    from tools.trialbox.backup_schedule import set_env

    set_env(ROOT / "deploy" / ".env", "TB_BACKUP_TARGETS", f"{nas} {usb}")  # §5 Backup step 1
    set_env(ROOT / "deploy" / ".env", "TB_BACKUP_OFFBOX", str(nas))
    if not key.is_file():
        key.parent.mkdir(parents=True, exist_ok=True)
        _t(
            steps,
            "backup: backup-keygen (once)",
            lambda: box.sh(
                f"{sys.executable} -m tools.trialbox backup-keygen --private {shlex.quote(str(key))} "
                "--public deploy/secrets/backup.pub"
            ),
        )
    rec["backup"] = _t(steps, "backup: backup-nightly (by hand, as §5 says)", lambda: _backup(box))
    files = sorted(nas.glob("trialbox-*.tbbak"))
    backup = files[-1] if files else nas / "missing.tbbak"
    rec["backup_file"] = {"name": backup.name, "bytes": backup.stat().st_size if backup.is_file() else None}
    # -- wipe every volume
    rec["wipe"] = _t(steps, "wipe every volume (down --volumes, objects folder emptied)", box.wipe)
    # -- restore by the page alone
    packs = ROOT / "deploy" / "refdata" / "loaded"
    opt = release_folder(release)
    fol = Follower(
        lambda c, e, t: shell(c, e, t or 3600, cwd=opt),
        hide=[*box.passwords.values(), *box.totp.values(), *box.db_env().values(), str(key)],
    )
    fol.machine = box.machine_dirs()

    def reinstall() -> Ran:
        t0 = time.monotonic()
        rc, o = box.up()
        packs.mkdir(parents=True, exist_ok=True)
        return Ran(
            "reinstall",
            "Reinstall (§1) and put each <pack_id>.tar in deploy/refdata/loaded",
            "make up-test (machine stand-in: lift reinstall-test-stack)",
            rc,
            round(time.monotonic() - t0, 2),
            tail(scrub(o), 300),
            list(fol.lifted),
        )

    t0 = time.monotonic()
    rec["follow"] = fol.follow(backup, key, packs, box.db_env, reinstall)
    healthy = box.wait_healthy()
    rec["restore_total_s"] = round(time.monotonic() - t0, 2)
    rec["healthy_after"] = healthy
    rec["follow_steps"] = [asdict(r) for r in fol.steps]
    steps.append(
        {
            "step": "restore by the page (every step below, to a healthy box)",
            "seconds": rec["restore_total_s"],
            "ok": bool(healthy),
        }
    )
    # -- compare
    after = _t(steps, "fingerprint after", box.fingerprint)
    rec["chain_prefix"] = box.chain_prefix(audit_before)
    if isinstance(after, dict) and isinstance(before, dict):
        if after.get("audit_head") is not None:
            after["audit_head"] = {
                **after["audit_head"],
                "verified": after["audit_verify"]["rc"] == 0,
                "prefix_of_after": rec["chain_prefix"]["ok"],
            }
        rec["comparison"] = compare(before, after)
    rec["old_sessions_after"] = {u: box.session_works(s.get("_cookie")) for u, s in sessions.items()}
    time.sleep(31)  # a new step for each authenticator
    rec["sign_in_after"] = _clean({u: box.sign_in(u) for u in FOUR})
    s3 = _t(steps, "after: SCREEN by mail on the restored box", lambda: box.screen("h33-after-1"))
    rec["screen_after"] = _summ(s3, pid)
    rec["rulesets_after_job"] = {
        "before": (s1 or {}).get("ruleset_version"),
        "after": (s3 or {}).get("ruleset_version"),
    }
    rec["fingerprints"] = {"before": _summary_fp(before), "after": _summary_fp(after)}
    _clean_kept()
    # -- B: a backup taken while a job runs, then the same wipe and restore
    rec["during_job"] = _t(
        steps,
        "B: a backup while a SCREEN runs, wipe, restore by the page, the job after",
        lambda: during_job(box, key, nas, usb, opt, packs),
    )
    _clean_kept()
    rec["finished"] = datetime.now(UTC).isoformat(timespec="seconds")
    rec["machine_versions"] = {
        "docker": box.sh("docker version --format '{{.Server.Version}}'")[1].strip(),
        "compose": box.sh("docker compose version --short")[1].strip(),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(_clean(rec), indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    return rec


def prepare(set_env: Callable[[Path, str, str], None]) -> list[str]:
    """The test stack named as a box names it (deploy/.env, made from .env.example when missing): its compose files
    and profiles (COMPOSE_FILE, COMPOSE_PROFILES, as an installed box's deploy/.env has them), TEST, TOTP on, the
    stub answering at once. Returns the names set (never a value that is a secret: there is none here)."""
    envf = ROOT / "deploy" / ".env"
    if not envf.is_file():
        shutil.copyfile(ROOT / ".env.example", envf)
        envf.chmod(0o600)
    d = ROOT / "deploy"
    values = {
        "TB_ENV": "TEST",
        "TB_CONSOLE_MFA": "totp",
        "COMPOSE_FILE": f"{d / 'docker-compose.yml'}:{d / 'docker-compose.test.yml'}",
        "COMPOSE_PROFILES": "stub,test",
        objects_var(): str(d / ".objects"),
        "TB_SETTINGS_FILE": "../.cache/test-settings.yaml",
        "TB_STUB_LATENCY_S": "",
        # H-139 (OCR 1498-1): the box file names the test stack's project, so the product commands the drill runs
        # (the nightly backup's host part) read the test stack's volumes, never a box's on the same host
        "COMPOSE_PROJECT_NAME": TEST_PROJECT,
    }
    for k, v in values.items():
        set_env(envf, k, v)
    return sorted(values)


def objects_var() -> str:
    """The variable the test stack's compose file names for its bind-mounted object folder (read from the file)."""
    text = (ROOT / "deploy" / "docker-compose.test.yml").read_text(encoding="utf-8")
    m = re.search(r'device: "\$\{(\w+):-', text)
    if not m:
        raise RuntimeError("docker-compose.test.yml names no folder for its object volume")
    return m.group(1)


def release_folder(opt: Path = RELEASE) -> Path:
    """The hub's release folder (``/opt/trialbox``, or ``--release``): a link to this checkout, made when missing, so
    the page's commands run where a box runs them (and ``docker compose`` finds no other project's file in a parent
    folder). Anything else at that path is refused."""
    if not opt.exists() and not opt.is_symlink():
        opt.symlink_to(ROOT)
    if opt.resolve() != ROOT.resolve():
        raise RuntimeError(f"{opt} is not this checkout: give --release a free path")
    return opt


def _clean_kept() -> None:
    """The restore keeps the box it replaced in deploy/pre-restore (its default --keep-to): removed after each run, so
    no copy of the synthetic box stays in the checkout."""
    shutil.rmtree(ROOT / "deploy" / "pre-restore", ignore_errors=True)


def during_job(box: ComposeDrill, key: Path, nas: Path, usb: Path, opt: Path, packs: Path) -> dict[str, Any]:
    """§5 Backup step 2 and Restore step 6: the nightly goes on beside a running job (TB_BACKUP_JOB_WAIT_S=0 here,
    so the drill does not wait 6 h), the restore fails that job and lists it, and nobody is mailed for it again."""
    from tests.stack import outbound_mail
    from tools.trialbox.backup_schedule import set_env

    envf = ROOT / "deploy" / ".env"
    out: dict[str, Any] = {}
    set_env(envf, "TB_STUB_LATENCY_S", "2")  # each model answer takes 2 s, so the job is still running at the snapshot
    box.compose("up -d --wait llm-stub", timeout=600)
    tag = "h33-during"
    box.mail_in(f"SCREEN GZQO version={SCREEN_VERSION} -- {tag}")
    j = box.job_by_tag("SCREEN", tag)
    jid = str(j["job_id"])
    running = box.job(jid, until=("running", "done", "failed"), timeout=300)
    out["state_at_backup"] = running.get("state")
    files_before = set(nas.glob("trialbox-*.tbbak"))
    rc, o = box.sh(f"{sys.executable} -m tools.trialbox backup-nightly", 3600, env={"TB_BACKUP_JOB_WAIT_S": "0"})
    out["backup"] = {"rc": rc, "out": tail(scrub(o), 300)}
    last = json.loads((ROOT / "deploy" / "site" / "backup-last.json").read_text(encoding="utf-8"))
    out["beside_jobs"] = (last.get("point_in_time") or {}).get("beside_jobs")
    new = sorted(set(nas.glob("trialbox-*.tbbak")) - files_before)
    final = box.job(jid, timeout=1800)
    out["state_before_wipe"] = final.get("state")

    def mails() -> int:
        return sum(
            1
            for m in outbound_mail()
            if str(m["Subject"]).startswith("[GZQO] SCREEN candidates") and str(m["Subject"]).endswith(jid)
        )

    out["list_mails_before_wipe"] = mails()
    set_env(envf, "TB_STUB_LATENCY_S", "")
    out["wipe"] = box.wipe()
    fol = Follower(
        lambda c, e, t: shell(c, e, t or 3600, cwd=opt),
        hide=[*box.passwords.values(), *box.totp.values(), *box.db_env().values(), str(key)],
    )
    fol.machine = box.machine_dirs()

    def reinstall() -> Ran:
        t0 = time.monotonic()
        rc2, o2 = box.up()
        return Ran(
            "reinstall",
            "Reinstall (§1)",
            "make up-test (machine stand-in)",
            rc2,
            round(time.monotonic() - t0, 2),
            tail(scrub(o2), 200),
            list(fol.lifted),
        )

    t0 = time.monotonic()
    out["follow"] = fol.follow(new[-1] if new else nas / "missing.tbbak", key, packs, box.db_env, reinstall)
    out["healthy_after"] = box.wait_healthy()
    out["restore_total_s"] = round(time.monotonic() - t0, 2)
    rs = next((r for r in reversed(fol.steps) if r.key == "restore"), None)
    out["jobs_failed_listed"] = bool(rs and jid in rs.out)
    out["restore_rc"] = rs.rc if rs else None
    time.sleep(60)  # the orchestrator would have picked a re-run up by now
    out["state_after_restore"] = box.job(jid, until=("done", "failed", "queued", "running"), timeout=60).get("state")
    out["list_mails_after_restore"] = mails()  # the sink is wiped with the stack: any mail here is a second one
    out["follow_steps"] = [{"key": r.key, "rc": r.rc, "seconds": r.seconds, "lifts": r.lifts} for r in fol.steps]
    return out


def _backup(box: ComposeDrill) -> dict[str, Any]:
    rc, out = box.sh(f"{sys.executable} -m tools.trialbox backup-nightly", 3600)
    return {"rc": rc, "out": tail(scrub(out), 400)}


def _summ(s: Any, pid: str | None) -> dict[str, Any]:
    if not isinstance(s, dict) or "error" in s:
        return {"error": (s or {}).get("error") if isinstance(s, dict) else str(s)}
    return {
        "state": s.get("state"),
        "ruleset": s.get("ruleset"),
        "ruleset_version": s.get("ruleset_version"),
        "listed": len(s.get("listed") or []),
        "opted_out_listed": pid in (s.get("listed") or []),
    }


def _summary_fp(fp: Any) -> dict[str, Any]:
    """The fingerprint as recorded: counts and hashes per store, never a row or a pseudonym."""
    if not isinstance(fp, dict) or "db" not in fp:
        return {"error": str(fp)[:300]}
    return {
        "db": {
            db: {"tables": len(t), "rows": sum(v[0] for v in t.values()), "hash": digest(t)}
            for db, t in fp["db"].items()
        },
        "volumes": {v: {"files": len(f), "hash": digest(f)} for v, f in fp["volumes"].items()},
        "audit_head": {k: fp["audit_head"].get(k) for k in ("file", "lines", "hash")} if fp.get("audit_head") else None,
        "audit_verify_rc": fp.get("audit_verify", {}).get("rc"),
        "optouts": {"events": len(fp.get("optouts") or []), "hash": digest(fp.get("optouts"))},
        "accounts": {"n": len(fp.get("accounts") or []), "hash": digest(fp.get("accounts"))},
        "rulesets": fp.get("rulesets"),
    }


# ------------------------------------------------------------------------------------------------ the command
def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.restore_drill", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract")
    e.add_argument("--json", action="store_true")
    sub.add_parser("plan")
    r = sub.add_parser("run")
    r.add_argument("--work", type=Path, default=Path.home() / "h33-drill")
    r.add_argument("--key", type=Path, default=KEY, help="the backup's private key (made there once when missing)")
    r.add_argument("--release", type=Path, default=RELEASE, help="the hub's release folder (a link to this checkout)")
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--keep", action="store_true", help="the box as it is: no wipe before the night")
    c = sub.add_parser("compare")
    c.add_argument("record", type=Path)
    f = sub.add_parser("findings")
    f.add_argument("file", type=Path)
    a = ap.parse_args(list(argv) if argv is not None else None)
    if a.cmd == "extract":
        cmds = restore_commands()
        if a.json:
            print(json.dumps([asdict(x) for x in cmds], indent=1, ensure_ascii=False))
        else:
            for x in cmds:
                print(f"{x.place}  [{x.block}]  {x.text}")
        return 0
    if a.cmd == "plan":
        for s in PATH:
            print(f"{s.key:10} {s.starts or '(no command on the page)'}: {s.what}")
            for v in s.supplies:
                print(f"{'':12}supplies {v}")
        for lf in LIFTS.values():
            print(f"lift {lf.key} ({lf.kind}): {lf.remedy} [from {lf.source}]")
        return 0
    if a.cmd == "run":
        rec = run(a.work, a.out, fresh=not a.keep, key=a.key, release=a.release)
        bad = [row["store"] for row in rec.get("comparison", []) if not row["equal"]]
        print(
            f"restore-drill: page alone: {rec['follow']['page_alone']}; restore {rec['restore_total_s']} s; "
            f"unequal: {bad or 'none'}; record {a.out}"
        )
        return 0
    if a.cmd == "compare":
        rec = json.loads(a.record.read_text(encoding="utf-8"))
        for row in rec.get("comparison", []):
            print(f"{'equal' if row['equal'] else 'UNEQUAL':8} {row['store']}: {row['before']} -> {row['after']}")
        return 0
    doc = json.loads(a.file.read_text(encoding="utf-8"))
    probs = check_findings(doc)
    for p in probs:
        print(f"findings: {p}")
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main())
