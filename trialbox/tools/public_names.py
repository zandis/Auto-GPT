"""The public-names check (hygiene item 4): no tracked file of this public repository names a person, host, home
folder or machine of the project's own.

    TB_PUBLIC_NAMES_FILE=<file outside the repository> python -m tools.public_names check [BUNDLE_ARGS]

The real pattern list is held by the integrator and is not in the repository.

The pattern list is never in the repository: it is a file kept outside it, named by ``TB_PUBLIC_NAMES_FILE``, one
regular expression per line (case-insensitive), ``#`` starts a comment line, blank lines are skipped. The check reads
every file ``git ls-files`` lists (text files; a UTF-16 file is read by its BOM; a file with a NUL byte in its first
8 KiB is binary and skipped; a symlink is read as its target path) and every tracked path. A hit is reported by its
place and the pattern's number in the list, never by the text it matched: ``path:line: pattern N``, or
``tracked path K (git ls-files | sed -n Kp)`` where the path itself matches.

Exit 0: no hit. Exit 1: a hit. Exit 2: not checked (the variable unset or empty, the list unreadable, empty, inside
the repository, a pattern that does not compile, or a tracked file that cannot be read), said plainly on stderr; a
release gate never reads exit 2 as a pass. ``make release-bundle`` runs it first (``make public-names``) with its
``BUNDLE_ARGS``: for a bundle that is not a release (``--rehearsal`` or ``--allow-dirty``, as
``tools/security_contact.py`` reads them) a variable that is unset or empty is a warning and exit 0 (any other
not-checked case is still exit 2); a hit is exit 1 there too.

Standard library only.
"""

from __future__ import annotations

import argparse
import codecs
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
ENV = "TB_PUBLIC_NAMES_FILE"
# what a bundle that is not a release carries in make_bundle.sh's arguments (tools/security_contact.py)
NOT_A_RELEASE = ("--rehearsal", "--allow-dirty")
BINARY_PROBE = 8192
EXIT_HIT = 1
EXIT_NOT_CHECKED = 2


class NotChecked(Exception):
    """The tree could not be checked; the message says why without echoing a pattern or a path."""


class NotSet(NotChecked):
    """The variable is unset or empty: the one not-checked case a non-release bundle may pass with a warning."""


def load_patterns(value: str | None, repo: Path) -> list[re.Pattern[str]]:
    """The compiled patterns of the list the variable names; raises NotChecked when there is none to use."""
    if not value:
        raise NotSet(f"{ENV} is not set: tracked files NOT checked (name a pattern file kept outside the repository)")
    path = Path(value).expanduser().resolve()
    try:
        path.relative_to(repo.resolve())
    except ValueError:
        pass
    else:
        raise NotChecked(
            "the pattern file is inside the repository: tracked files NOT checked (keep it outside the repository)"
        )
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise NotChecked(
            f"the pattern file {ENV} names is not readable ({type(exc).__name__}): tracked files NOT checked"
        ) from exc
    patterns: list[re.Pattern[str]] = []
    for line in lines:
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        try:
            patterns.append(re.compile(text, re.IGNORECASE))
        except re.error as exc:
            raise NotChecked(f"pattern {len(patterns) + 1} does not compile: tracked files NOT checked") from exc
    if not patterns:
        raise NotChecked(f"the pattern file {ENV} names holds no patterns: tracked files NOT checked")
    return patterns


def tracked(repo: Path) -> list[str]:
    proc = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], capture_output=True, check=False)
    if proc.returncode != 0:
        raise NotChecked(f"git ls-files failed (exit {proc.returncode}): tracked files NOT checked")
    return [p for p in proc.stdout.decode("utf-8", "surrogateescape").split("\0") if p]


def first_hit(patterns: list[re.Pattern[str]], text: str) -> int | None:
    """The 1-based number of the first pattern that matches ``text``, or None."""
    for number, pattern in enumerate(patterns, start=1):
        if pattern.search(text):
            return number
    return None


def file_text(path: Path, index: int) -> str | None:
    """What git publishes of one tracked path as text, or None when there is nothing to scan.

    A symlink is its target path; a UTF-16 file (BOM) is decoded before the binary test; a path missing from the work
    tree or a submodule folder is nothing to read; any other read error raises NotChecked.
    """
    try:
        if path.is_symlink():
            return os.fsdecode(os.readlink(path))
        if path.is_dir():
            return None  # a submodule folder
        data = path.read_bytes()
    except FileNotFoundError:
        return None  # a tracked path deleted in the work tree
    except OSError as exc:
        raise NotChecked(
            f"tracked path {index} is not readable ({type(exc).__name__}): tracked files NOT checked"
        ) from exc
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16", "replace")
    if b"\0" in data[:BINARY_PROBE]:
        return None
    return data.decode("utf-8", "replace")


def scan(repo: Path, patterns: list[re.Pattern[str]]) -> tuple[list[str], int]:
    """The hit lines (place and pattern number only) and the number of tracked files read."""
    hits: list[str] = []
    paths = tracked(repo)
    for index, rel in enumerate(paths, start=1):
        place = rel
        number = first_hit(patterns, rel)
        if number is not None:
            place = f"tracked path {index} (git ls-files | sed -n {index}p)"
            hits.append(f"{place}: file name matches pattern {number}")
        text = file_text(repo / rel, index)
        if text is None:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            number = first_hit(patterns, line)
            if number is not None:
                hits.append(f"{place}:{lineno}: pattern {number}")
    return hits, len(paths)


def not_a_release(bundle_args: list[str]) -> str | None:
    """The flag that makes these make_bundle.sh arguments a non-release bundle, if any."""
    return next((arg for arg in bundle_args if arg in NOT_A_RELEASE), None)


def check(repo: Path, value: str | None, bundle_args: list[str] | None = None) -> int:
    try:
        patterns = load_patterns(value, repo)
        hits, count = scan(repo, patterns)
    except NotChecked as exc:
        flag = not_a_release(bundle_args or []) if isinstance(exc, NotSet) else None
        if flag:
            print(f"public-names: WARNING, not a release ({flag}): {exc}", file=sys.stderr)
            return 0
        print(f"public-names: {exc}", file=sys.stderr)
        return EXIT_NOT_CHECKED
    noun = "pattern" if len(patterns) == 1 else "patterns"
    if hits:
        print("\n".join(hits))
        print(f"public-names: FAIL, {len(hits)} hit(s) of {len(patterns)} {noun} in {count} tracked files")
        return EXIT_HIT
    print(f"public-names: PASS, {len(patterns)} {noun} over {count} tracked files")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    ap.add_argument("--repo", type=Path, default=REPO, help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)
    # check takes make_bundle.sh's arguments (BUNDLE_ARGS) as they are, after the command
    sub.add_parser("check", help=f"exit 1 on a hit, 2 when not checked ({ENV} unset)")
    args, bundle_args = ap.parse_known_args(argv)
    return check(args.repo, os.environ.get(ENV), bundle_args)


if __name__ == "__main__":
    raise SystemExit(main())
