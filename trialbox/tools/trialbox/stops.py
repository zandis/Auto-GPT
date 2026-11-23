"""H-94 (the owner's ruling, relayed as 7092087958; D-1091): on a PoC box the install, start and update paths stop
for five things only.

KEPT AS REFUSALS, everywhere: (1) the bundle's or update's signature or hashes do not hold; (2) the machine physically
cannot run it (disk, memory, card); (3) a PoC box would load real patient data or become PRODUCTION; (4) the step
needs root and does not have it; (5) a secret would be read from, or written to, a place others can read
(7095256773). Each such stop names its number in a comment (``H-94 (1)`` ...). A stop the next lines depend on is
kept only if it protects one of the five on the input that reaches it (7096436960).

EVERY OTHER STOP calls the helper: :func:`stop_or_warn` here, the shell function ``stop_or_warn`` in the scripts (the
same rule, the same list). On a PoC box it warns, appends one line to :data:`LIST` and the step goes on; on any other
box it stops exactly as before (the same words, the same exit code).

WHAT A PoC BOX IS (:func:`poc_box`), read only from what a caller cannot forge into a looser state on a PRODUCTION
box. A caller's environment variable is never read for it:

* the box's recorded environment, ``TB_ENV`` in ``deploy/.env`` (written by the installer, 0600); a file that is there
  but cannot be read, or a value that is none of the four, is a box that cannot be told: PRODUCTION;
* an installed box (``deploy/settings.yaml`` or ``deploy/updates/installed.json``) with no ``TB_ENV`` is PRODUCTION
  (D-127);
* the rehearsal mark ``deploy/site/rehearsal.json``, on a box that records no environment yet: VALIDATION (D-887);
* the command line of this run, which a fresh box has nothing to set against: ``--environment`` and ``--rehearsal``
  (VALIDATION). The stricter of the record and the command line wins, so ``--environment VALIDATION`` never loosens
  a box that records PRODUCTION;
* nothing at all (a fresh box, no environment given): PRODUCTION, the D-127 default.

A PoC box is one whose every speaking source says DEV, TEST or VALIDATION (TEST: the integrator, 7096436960).

THE LIST (:data:`LIST`, ``deploy/site/poc-stops.jsonl``): one JSON object per line, ``key`` (the script and a stable
name of the point), ``what`` (the stop's own words), ``skipped`` (what was not done because of it, or empty), ``at``
(UTC), ``by`` (the script). It lives with the site's own files, so it survives the run from the signed tree, an
update and a second install. Only root or the installing user writes it; a link is never followed; a secret's value
or a path under ``uploads/`` is never written. ``trialbox doctor`` shows it as WARN lines (:func:`doctor_lines`), one
action each. A list made by hand, or one that cannot be read, never stops anything: it is a WARN line too.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

LIST = Path("site") / "poc-stops.jsonl"  # under the deploy folder
POC_ENVS = ("DEV", "TEST", "VALIDATION")
ENVS = (*POC_ENVS, "PRODUCTION")
ACTION = "fix what it names before this box serves a site, then run the step again"
_SECRET = re.compile(r"\b([a-z0-9_]*(?:password|passphrase|token|secret|_key))=\S*", re.I)
_UPLOADS = re.compile(r"\S*/uploads/\S*")


def _norm(value: str) -> str:
    """As install.sh reads TB_ENV: no quotes, no blanks, upper case."""
    return "".join(c for c in value if c not in "\"' \r\t").upper()


def recorded(deploy: Path) -> str | None:
    """The environment the box records: '' when it records none yet, None when it cannot be told."""
    env = deploy / ".env"
    rec = ""
    if env.exists() or env.is_symlink():
        try:
            text = env.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        for line in text.splitlines():
            if line.startswith("TB_ENV="):
                rec = _norm(line.removeprefix("TB_ENV="))
    if not rec and ((deploy / "settings.yaml").exists() or (deploy / "updates" / "installed.json").exists()):
        rec = "PRODUCTION"  # D-127: an installed box that names none
    if not rec and (deploy / "site" / "rehearsal.json").is_file():
        rec = "VALIDATION"
    return rec


def poc_box(deploy: Path, *, environment: str = "", rehearsal: bool = False) -> bool:
    """True on a PoC box (DEV, TEST or VALIDATION by every source that speaks); False on PRODUCTION and on a box
    whose state cannot be told. ``environment`` and ``rehearsal`` are this run's command line, never a variable."""
    rec = recorded(deploy)
    if rec is None:
        return False
    arg = _norm(environment) or ("VALIDATION" if rehearsal else "")
    if any(v not in ("", *POC_ENVS) for v in (rec, arg)):
        return False
    return bool(rec or arg)


def clean(text: str) -> str:
    """One line, with no secret's value and no path under uploads/."""
    text = "".join(c for c in text if c >= " ")
    return _SECRET.sub(r"\1=<hidden>", _UPLOADS.sub("<a path under uploads/>", text))


def append(deploy: Path, key: str, what: str, skipped: str = "", *, by: str) -> bool:
    """One line of the list. False (and a line on stderr) when it cannot be written: never a stop."""
    path = deploy / LIST
    entry = {"key": clean(key), "what": clean(what), "skipped": clean(skipped),
             "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "by": clean(by)}  # fmt: skip
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o640)
        try:
            st = os.fstat(fd)
            if st.st_uid not in (0, os.getuid()):
                raise PermissionError(f"owned by uid {st.st_uid}, not root or the installer")
            os.write(fd, (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8"))
        finally:
            os.close(fd)
    except OSError as e:
        print(f"{by}: warning: the PoC list {path} cannot be written ({type(e).__name__}); the step goes on",
              file=sys.stderr)  # fmt: skip
        return False
    return True


def stop_or_warn(
    key: str,
    what: str,
    *,
    deploy: Path,
    by: str,
    stop: Callable[[str], NoReturn],
    skipped: str = "",
    environment: str = "",
    rehearsal: bool = False,
) -> None:
    """On a PoC box: one warning on stderr, one line of the list, and return. Elsewhere: ``stop(what)``, the caller's
    own stop, unchanged."""
    if not poc_box(deploy, environment=environment, rehearsal=rehearsal):
        stop(what)
    tail = f"; skipped: {skipped}" if skipped else ""
    print(f"{by}: warning (PoC box, H-94): {what}{tail}", file=sys.stderr)
    append(deploy, key, what, skipped, by=by)


@dataclass(frozen=True)
class Entry:
    key: str
    what: str
    skipped: str
    at: str
    by: str


def read(deploy: Path) -> tuple[list[Entry], list[str]]:
    """The list's entries, the newest per key, and what could not be read (never raised)."""
    path = deploy / LIST
    problems: list[str] = []
    if not (path.exists() or path.is_symlink()):
        return [], []
    try:
        if path.is_symlink():
            raise OSError("a link (never followed)")
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()  # a cut byte never hides the rest
    except OSError as e:
        return [], [f"{path} cannot be read: {e}"]
    newest: dict[str, Entry] = {}
    bad = 0
    for line in lines:
        if not line.strip():
            continue
        try:
            d = json.loads(line)
            entry = Entry(*(clean(str(d[k])) for k in ("key", "what", "skipped", "at", "by")))
        except (ValueError, KeyError, TypeError):
            bad += 1
            continue
        newest[entry.key] = entry
    if bad:
        problems.append(f"{bad} line(s) of {path} are not entries of the list (made by hand?): not shown")
    return sorted(newest.values(), key=lambda x: (x.at, x.key)), problems


def doctor_lines(deploy: Path) -> Iterable[tuple[str, str]]:
    """(name, detail) of each WARN line ``trialbox doctor`` shows: one per point on the list, then one per problem."""
    entries, problems = read(deploy)
    for e in entries:
        skipped = f"; skipped: {e.skipped}" if e.skipped else ""
        yield "poc_stop", f"{e.key} ({e.at}): {e.what}{skipped}. Action: {ACTION}"
    for p in problems:
        yield "poc_stop", f"{p}. Action: remove the file or the lines; the next install writes it again"
