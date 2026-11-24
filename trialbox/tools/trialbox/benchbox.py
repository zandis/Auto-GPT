"""The bench mark (card H-116, D-1357; the owner's ruling relayed as 7124664930, the design as 7124901315). Standard
library only: the host's python3 runs it.

A box with the bench mark is a PRODUCTION box on the owner's bench host: real data, every PRODUCTION protection
(TB_ENV stays PRODUCTION, so no PoC leniency applies anywhere), and the one thing that changes is H-106's "one box per
host": test boxes may run beside it. It is shown everywhere as :data:`LABEL`.

THE MARK IS AN INSTALL OPTION, recorded in the box's own settings (``deploy/install.sh --bench``, written to
``deploy/site/bench-box.env``, then ``TB_BENCH=1`` to ``deploy/.env``). Every check reads the record; a caller's
environment variable never makes a box a bench box. A mark the install option did not write is refused
(:func:`check`): the record must be a regular file (not a link) owned by root (or by the user who runs the check),
writable by its owner only, carry the install's trace (its first line, the folder it was written for, the time),
and name this folder; ``TB_BENCH`` in ``deploy/.env`` with no record is refused. The mark is refused on a box that is
not PRODUCTION, on a test box, and on a box with a sending identity (a mail relay off the host, or a relay login):
a bench box sends no mail outside the host.

    python3 -m tools.trialbox.benchbox write --deploy D     # the record (deploy/install.sh --bench only)
    python3 -m tools.trialbox.benchbox check --deploy D     # "bench" on a bench box, nothing on another; 2 refused
    python3 -m tools.trialbox.benchbox words --deploy D     # what the box says it is, on a bench box

Exit codes: 0 done; 2 refused (the reason on stderr, nothing changed).
"""

from __future__ import annotations

import argparse
import os
import re
import stat
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

RECORD = Path("site") / "bench-box.env"  # under the deploy folder
TEST_RECORD = Path("site") / "test-box.env"  # H-106's: a test box is never a bench box
HEADER = "# deploy/install.sh --bench (H-116, D-1357): this folder's PRODUCTION box on the bench host; never edited"
KEYS = ("TB_BENCH", "TB_BENCH_ROOT", "TB_BENCH_AT")
AT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
LABEL = "PRODUCTION · BENCH (real data, bench host)"
#: a relay on the host itself, or the test stack's sinks: no mail leaves the host
LOCAL_RELAYS = frozenset({"", "localhost", "127.0.0.1", "::1", "mailpit", "mailhog", "greenmail"})
WHO = "bench"


class Refused(Exception):
    """A refusal: nothing was changed."""


@dataclass(frozen=True)
class Mark:
    root: str
    at: str

    def words(self) -> str:
        """What the box says it is, on every page and in every operator's output."""
        return (f"{LABEL}: every PRODUCTION protection; test boxes may run beside it on this host, sharing nothing "
                f"with it; it sends no mail outside the host (marked by install --bench at {self.at})")  # fmt: skip


def read_env(path: Path) -> dict[str, str]:
    """KEY=VALUE lines, as compose reads a plain file (the last line wins); {} when there is none."""
    out: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return out
    for line in text.splitlines():
        m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).strip().strip("\"'")
    return out


def environment(env: dict[str, str]) -> str:
    """TB_ENV as Python reads it (no quotes, no blanks, upper case); none is PRODUCTION (D-127)."""
    return (env.get("TB_ENV") or "PRODUCTION").strip().strip("\"'").strip().upper() or "PRODUCTION"


def sending_identity(env: dict[str, str]) -> str:
    """Why the box would send mail outside the host ("" when it would not): a relay that is not on the host, or a
    relay login (the hospital's sending identity)."""
    host = (env.get("SMTP_HOST") or "").strip().strip("\"'").strip().lower()
    if host not in LOCAL_RELAYS:
        return f"SMTP_HOST={host} (a mail relay off the host)"
    if (env.get("SMTP_USER") or "").strip().strip("\"'").strip():
        return "SMTP_USER is set (a login to a mail relay)"
    return ""


def _refuse_record(rec: Path) -> None:
    """The record must be the one the install option wrote: a regular file, not a link, owned by root (or by the
    user who runs the check), writable by its owner only."""
    st = rec.lstat()
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise Refused(f"{rec} is not a regular file (a link, or another kind): the bench mark is written by "
                      "deploy/install.sh --bench only")  # fmt: skip
    if st.st_uid not in (0, os.geteuid()):
        raise Refused(f"{rec} is owned by uid {st.st_uid}, not root: the bench mark is written by deploy/install.sh "
                      "--bench (as root) only")  # fmt: skip
    if st.st_mode & 0o022:
        raise Refused(f"{rec} may be written by others (mode {stat.S_IMODE(st.st_mode):04o}): the bench mark is "
                      "written by deploy/install.sh --bench only, readable by all, writable by root only")  # fmt: skip


def check(deploy: Path, env: dict[str, str] | None = None) -> Mark | None:
    """The box's bench mark, None on a box with none; :class:`Refused` for a mark the install option did not write,
    or one this box may not carry."""
    env = read_env(deploy / ".env") if env is None else env
    rec = deploy / RECORD
    named = (env.get("TB_BENCH") or "").strip()
    if not (rec.exists() or rec.is_symlink()):
        if named:
            raise Refused(f"TB_BENCH={named} in deploy/.env with no record (deploy/{RECORD}): the bench mark is "
                          "written by deploy/install.sh --bench only")  # fmt: skip
        return None
    _refuse_record(rec)
    try:
        text = rec.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise Refused(f"{rec} cannot be read ({exc}): the box's mark is not known") from None
    lines = [ln for ln in text.splitlines() if ln.strip()]
    values = read_env(rec)
    if not lines or lines[0] != HEADER or sorted(values) != sorted(KEYS) or len(lines) != 1 + len(KEYS):
        raise Refused(f"{rec} does not carry the install's trace (its first line and {', '.join(KEYS)} only): the "
                      "bench mark is written by deploy/install.sh --bench only")  # fmt: skip
    if values["TB_BENCH"] != "1" or not AT.fullmatch(values["TB_BENCH_AT"]) or not values["TB_BENCH_ROOT"]:
        raise Refused(f"{rec} does not carry the install's trace (TB_BENCH=1, its folder, its time): the bench mark "
                      "is written by deploy/install.sh --bench only")  # fmt: skip
    # the record names the host folder it was written for; a copy is a record whose folder is on this machine and is
    # not this one (inside the box's own container the tree is mounted elsewhere and the host folder is not there)
    folder = Path(values["TB_BENCH_ROOT"])
    if folder.exists() and folder.resolve() != deploy.parent.resolve():
        raise Refused(f"{rec} was written for {folder}, not this folder: a bench mark is never copied between "
                      "folders")  # fmt: skip
    if named and named != "1":
        raise Refused(f"TB_BENCH={named} in deploy/.env is not the record's (1): run deploy/install.sh --bench again")
    if (deploy / TEST_RECORD).exists():
        raise Refused(f"this folder is a test box (deploy/{TEST_RECORD}): a test box never carries the bench mark")
    env_name = environment(env)
    if env_name != "PRODUCTION":
        raise Refused(f"this box is {env_name} (deploy/.env TB_ENV): the bench mark is a PRODUCTION box's only")
    why = sending_identity(env)
    if why:
        raise Refused(f"this box has a sending identity ({why}): a bench box sends no mail outside the host; leave "
                      "SMTP_HOST empty (or the host's own) and SMTP_USER empty")  # fmt: skip
    return Mark(values["TB_BENCH_ROOT"], values["TB_BENCH_AT"])


def write(deploy: Path, now: datetime | None = None) -> Mark:
    """Write (or keep) the record, after the box is shown to be one that may carry it (PRODUCTION, no test box, no
    sending identity): a refusal writes nothing. A record already there is kept as it is when it holds."""
    env = read_env(deploy / ".env")
    if (deploy / TEST_RECORD).exists():
        raise Refused(f"this folder is a test box (deploy/{TEST_RECORD}): a test box never carries the bench mark")
    env_name = environment(env)
    if env_name != "PRODUCTION":
        raise Refused(f"this box is {env_name} (deploy/.env TB_ENV): the bench mark is a PRODUCTION box's only")
    why = sending_identity(env)
    if why:
        raise Refused(f"this box has a sending identity ({why}): a bench box sends no mail outside the host; leave "
                      "SMTP_HOST empty (or the host's own) and SMTP_USER empty")  # fmt: skip
    try:
        old = check(deploy, env | {"TB_BENCH": ""})
    except Refused:
        old = None  # one the install option did not write: written again by the option, as the option writes it
        if (deploy / RECORD).is_symlink() or ((deploy / RECORD).exists() and not (deploy / RECORD).is_file()):
            raise
    if old is not None:
        return old
    at = (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    mark = Mark(str(deploy.parent.resolve()), at)
    path = deploy / RECORD
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".new")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:  # on the disk, then renamed: a power cut never empties it
        fh.write(f"{HEADER}\nTB_BENCH=1\nTB_BENCH_ROOT={mark.root}\nTB_BENCH_AT={mark.at}\n")
        fh.flush()
        os.fsync(fh.fileno())
    tmp.chmod(0o644)
    tmp.replace(path)
    dfd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)
    return mark


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m tools.trialbox.benchbox", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("write", "check", "words"):
        sub.add_parser(name).add_argument("--deploy", type=Path, required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "write":
            print(write(a.deploy).words())
        elif a.cmd == "check":
            if check(a.deploy) is not None:
                print("bench")
        else:
            mark = check(a.deploy)
            if mark is not None:
                print(mark.words())
    except Refused as exc:
        print(f"{WHO}: refused: {exc}; nothing was changed", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    if not __package__:
        sys.path[:0] = [str(Path(__file__).resolve().parents[2])]
    os.umask(0o022)
    raise SystemExit(main())
