"""J-7 (D-1251), the coordinator's review: with the flag off, every page against master's rendered bytes.

    python -m tests.console.j7_master_bytes [--base REV] [--out DIR]

One set of pages is rendered twice, each time in a pytest process of its own on the same fixtures: from this checkout
and from a worktree of ``REV`` (default: the merge base with ``origin/master``). The set is every column of the role
matrix, in en, ja and zh-TW, on the pages of ``test_plain_menu.OFF_PAGES``, the audit trail and the administrator's
home. Before the bytes are compared, what differs between any two renders of the same code is taken out: a form's
CSRF token, a time of day, an id made when the page was asked. The only differences allowed are named in
:data:`ALLOWED`: the flag's own card on ``/ops/flags``, and the audit event that seeds the flag.

Not a test of the suite: a CI shard checks out one commit (no master to render), and once the card is merged master
*is* this code. The suite keeps ``test_with_the_flag_off_every_page_is_byte_for_byte_the_page_without_this_card``,
which holds on every later commit; this script is the proof against master, run once per head and reported in the
pull request. It never runs in a cloud and writes only under ``--out`` and a temporary worktree it removes.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]  # trialbox/
#: the pytest file written into each tree (never committed): renders the pages and writes them to $J7_DUMP
DUMP = """
from __future__ import annotations

import json
import os
from typing import Any

from tests.console.test_console_app import _done_feas, _done_screen, _ulid, box  # noqa: F401
from tests.console.test_role_route_matrix import COLUMNS, _clients, _for

PAGES = {pages!r}
LANGS = ("en", "ja", "zh-TW")


def test_dump(box: dict[str, Any]) -> None:
    _done_feas(box["backend"])
    _done_screen(box["backend"], _ulid(990))
    clients = _clients(box)
    out = {{}}
    for col in COLUMNS:
        page, csrf, _ = clients[col]
        for lang in LANGS:
            page.post("/lang", data={{"csrf": csrf, "lang": lang, "back": "/"}})
            for p in PAGES:
                _for(box, p)
                r = page.get(p)
                out[f"{{col}} {{lang}} {{p}}"] = [r.status_code, r.text]
        page.post("/lang", data={{"csrf": csrf, "lang": "en", "back": "/"}})
    with open(os.environ["J7_DUMP"], "w", encoding="utf-8") as fh:
        json.dump(out, fh)
"""
#: what differs between two renders of the same code, taken out before the comparison
VOLATILE = (
    (re.compile(r'name="csrf" value="[^"]+"'), 'name="csrf" value="-"'),
    (re.compile(r'data-csrf="[^"]+"'), 'data-csrf="-"'),
    (re.compile(r'data-(idle|abs)-left="\d+"'), r'data-\1-left="N"'),  # the session's seconds left (D-1370)
    (re.compile(r"\b\d{1,2}:\d{2}(:\d{2})?(\.\d+)?\b"), "HH:MM"),  # a time of day
    (re.compile(r"\b[0-9A-HJKMNP-TV-Z]{26}\b"), "ULID"),  # an id made when the page was asked
    (re.compile(r"\b[0-9a-f]{64}\b"), "SHA256"),  # a chain hash over those
    (re.compile(r'title="[0-9a-f]{12}">[0-9a-f]{8}<'), 'title="HASH">HASH<'),  # an audit event's place in the chain
    (re.compile(r"(\d+(\.\d+)?) ?(ms|s)\b"), "N ms"),  # a duration
)
#: the differences this card makes with the flag off, by page: the flag's own card and its seed row on the flags
#: page, and in the audit trail the event that seeds it (its row, where the trail reaches it, and the one more event
#: the "Older events" cursor counts). Each is taken out of both renders (it occurs only in this checkout's) before the
#: bytes are compared; everything else must be the same
ALLOWED: dict[str, tuple[tuple[re.Pattern[str], str], ...]] = {
    "/ops/flags": (
        (re.compile(r'<section class="card" id="flag-layout\.plain_menu".*?</section>\n\n', re.S), ""),
        (re.compile(r'<tr data-kind="seed">(?:(?!</tr>).)*?>layout\.plain_menu<.*?</tr>', re.S), ""),
    ),
    "/audit": (
        (re.compile(r'<tr data-event="flag\.[a-z_]+">(?:(?!</tr>).)*?layout\.plain_menu.*?</tr>', re.S), ""),
        (re.compile(r"(before=[0-9-]+%3A)\d+"), r"\1N"),
    ),
}


def normal(text: str) -> str:
    for pattern, repl in VOLATILE:
        text = pattern.sub(repl, text)
    return text


def render(tree: Path, pages: list[str], dump: Path, root: Path) -> None:
    test = tree / "tests" / "console" / "test_j7_dump_tmp.py"
    test.write_text(DUMP.format(pages=pages), encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": "libs:services:.", "J7_DUMP": str(dump), "TB_TEST_ROOT": str(root),
           "TMPDIR": str(root / "tmp")}  # fmt: skip
    py = str(ROOT / ".venv" / "bin" / "python")
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run([py, "-m", "tools.pglocal", "mark", str(root)], cwd=tree, env=env, check=True,
                   stdout=subprocess.DEVNULL)  # fmt: skip
    (root / "tmp").mkdir(exist_ok=True)
    try:
        r = subprocess.run([py, "-m", "pytest", "-q", "-p", "no:randomly", "-p", "no:cacheprovider", "--basetemp",
                            str(root / "pytest"), str(test.relative_to(tree))], check=False, cwd=tree, env=env,
                           text=True,
                           capture_output=True)  # fmt: skip
    finally:
        test.unlink()
    if r.returncode != 0:
        sys.exit(f"rendering in {tree} failed:\n{r.stdout[-4000:]}\n{r.stderr[-2000:]}")


def compare(base: dict[str, list[Any]], head: dict[str, list[Any]]) -> tuple[int, list[str], list[str]]:
    """(renders identical, renders that differ only as :data:`ALLOWED` says, renders that differ otherwise)."""
    problems: list[str] = []
    named: list[str] = []
    same = 0
    for key in sorted(set(base) | set(head)):
        if key not in base or key not in head:
            problems.append(f"{key}: rendered on one side only")
            continue
        (s0, t0), (s1, t1) = base[key], head[key]
        if s0 != s1:
            problems.append(f"{key}: status {s0} on master, {s1} here")
            continue
        a, b = normal(t0), normal(t1)
        if a == b:
            same += 1
            continue
        path = key.split(" ", 2)[2]
        for pattern, repl in ALLOWED.get(path, ()):
            a, b = pattern.sub(repl, a), pattern.sub(repl, b)
        if a == b:
            named.append(key)
            continue
        lines = [ln for ln in difflib.unified_diff(a.splitlines(), b.splitlines(), lineterm="", n=0)
                 if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]  # fmt: skip
        problems.append(f"{key}:\n" + "\n".join(ln[:300] for ln in lines[:12]))
    return same, named, problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--base", default="", help="the master commit (default: merge base with origin/master)")
    ap.add_argument("--out", default="", help="where the two dumps and the report go (default: a temporary folder)")
    args = ap.parse_args()
    sys.path[:0] = [str(ROOT / "libs"), str(ROOT / "services"), str(ROOT)]
    from tests.console.test_plain_menu import OFF_PAGES

    pages = [*OFF_PAGES, "/audit"]  # the administrator's /home is in OFF_PAGES and compared here too
    base = args.base or subprocess.run(["git", "merge-base", "HEAD", "origin/master"], cwd=ROOT, text=True,
                                       capture_output=True, check=True).stdout.strip()  # fmt: skip
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True)
    out = Path(args.out or tempfile.mkdtemp(prefix="j7-bytes-"))
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="j7-master-"))
    tree = work / "tree"
    subprocess.run(["git", "worktree", "add", "--detach", str(tree), base], cwd=ROOT, check=True,
                   capture_output=True)  # fmt: skip
    try:
        render(tree / "trialbox", pages, out / "master.json", out / "root-master")
        render(ROOT, pages, out / "head.json", out / "root-head")
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=ROOT, check=False)
        shutil.rmtree(work, ignore_errors=True)
    same, named, problems = compare(
        json.loads((out / "master.json").read_text()), json.loads((out / "head.json").read_text())
    )
    report = [
        f"master {base} · this checkout {head.stdout.strip()}",
        f"{same} renders identical byte for byte; {len(named)} differ only as named (the flag's own row, its seed"
        f" event): {', '.join(named) or 'none'}",
        f"{len(problems)} differ otherwise" + (":" if problems else ""),
        *problems,
    ]
    (out / "report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report[:3]))
    print(f"report: {out / 'report.txt'}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
