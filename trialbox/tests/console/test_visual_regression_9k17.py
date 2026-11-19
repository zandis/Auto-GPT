"""9k-17 (D-1377; review 09 DS-17, §5.3): visual regression in CI, 72 first screens compared with master.

The plan's proof is "the job fails on an unreviewed difference". Held here in three layers:

* the comparison (no browser, no database): equal pictures pass; a change of at most 0.1 % of the pixels passes as
  "below"; a larger one, a picture on one side only, or one that could not be drawn is a difference, and
  ``python -m tools.visual_regression compare`` exits 1 on it, until ``visual_accepted.txt`` holds the line for that
  picture's hash, which accepts that picture only;
* the job: ``.github/workflows/trialbox-visual.yml`` runs on a pull request that touches the console, shoots the pull
  request's tree and its base branch's in a second checkout on one runner, fails with the tool's exit code and keeps
  the side-by-side page; the page list is 12 pages x desktop and phone x en, ja, zh-TW = 72;
* in Chromium (skipped where Node Playwright is missing, as ``test_cjk_layout``): two shootings of this tree give the
  same 72 pictures (the clock is pinned; nothing of a session shows), and a planted change of the style sheet is a
  difference that fails the comparison until a person's line accepts it.

Synthetic data only: the test suite's box (study GZQO), no patient data.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from PIL import Image

from tests.console import visual_pages
from tools import visual_regression as vr

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT.parent / ".github" / "workflows" / "trialbox-visual.yml"


def _node_playwright() -> bool:
    node = shutil.which("node")
    if not node:
        return False
    r = subprocess.run([node, "-e", "require('playwright')"], cwd=ROOT, capture_output=True, timeout=60, check=False)
    return r.returncode == 0


def _png(path: Path, size: tuple[int, int] = (200, 100), box: tuple[int, int, int, int] | None = None) -> Path:
    im = Image.new("RGB", size, (246, 247, 249))
    if box:
        im.paste((29, 95, 168), box)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)
    return path


def _set(d: Path, pics: dict[str, Path | None], errors: dict[str, str] | None = None) -> Path:
    (d / "png").mkdir(parents=True, exist_ok=True)
    for name, src in pics.items():
        if src is not None:
            shutil.copyfile(src, d / "png" / f"{name}.png")
    names = sorted(n for n, s in pics.items() if s is not None)
    (d / "shots.json").write_text(json.dumps({"names": names, "errors": errors or {}}), encoding="utf-8")
    return d


# ------------------------------------------------------------------------------------------- the comparison


@pytest.mark.nodb
def test_9k17_the_comparison_fails_on_an_unreviewed_difference(tmp_path: Path) -> None:
    plain = _png(tmp_path / "src" / "plain.png")
    dot = _png(tmp_path / "src" / "dot.png", box=(10, 10, 11, 11))  # 1 pixel of 20,000: 0.005 %
    block = _png(tmp_path / "src" / "block.png", box=(10, 10, 50, 50))  # 1,600 pixels: 8 %
    bigger = _png(tmp_path / "src" / "bigger.png", size=(200, 120))
    base = _set(tmp_path / "base", {"a": plain, "b": plain, "c": plain, "d": plain, "e": None, "f": plain})
    head = _set(
        tmp_path / "head",
        {"a": plain, "b": dot, "c": block, "d": bigger, "e": plain, "f": None},
        errors={"f": "/x: RuntimeError: HTTP 500"},
    )
    res = vr.compare(base, head, tmp_path / "out", set())
    state = {s.name: s.state for s in res.shots}
    assert state == {"a": "same", "b": "below", "c": "differs", "d": "differs", "e": "differs", "f": "differs"}
    assert [s.name for s in res.unreviewed] == ["c", "d", "e", "f"]
    why = {s.name: s.why for s in res.shots}
    assert "not drawn on master" in why["e"] and "HTTP 500" in why["f"]
    report = (tmp_path / "out" / "report.md").read_text(encoding="utf-8")
    assert "**4 not reviewed**" in report and f"c {vr.picture_hash(block)}  # <why" in report
    page = (tmp_path / "out" / "index.html").read_text(encoding="utf-8")
    for k in ("c-master.png", "c-pr.png", "c-diff.png"):
        assert f'src="img/{k}"' in page and (tmp_path / "out" / "img" / k).is_file()
    with Image.open(tmp_path / "out" / "img" / "c-diff.png") as diff:
        assert diff.convert("RGB").getpixel((20, 20)) == (220, 0, 0)  # the changed pixels in red
        assert diff.convert("RGB").getpixel((150, 80)) != (220, 0, 0)


@pytest.mark.nodb
def test_9k17_a_reviewed_line_accepts_that_one_picture_only(tmp_path: Path) -> None:
    plain = _png(tmp_path / "src" / "plain.png")
    block = _png(tmp_path / "src" / "block.png", box=(10, 10, 50, 50))
    other = _png(tmp_path / "src" / "other.png", box=(60, 10, 100, 50))
    base = _set(tmp_path / "base", {"home-pi-ja-phone": plain})
    head = _set(tmp_path / "head", {"home-pi-ja-phone": block})
    args = ["compare", "--base", str(base), "--head", str(head), "--out", str(tmp_path / "out")]
    acc = tmp_path / "accepted.txt"
    assert vr.main([*args, "--accepted", str(acc)]) == 1  # no file: nothing reviewed
    acc.write_text(f"# reviewed\nhome-pi-ja-phone {vr.picture_hash(other)}  # another picture\n", encoding="utf-8")
    assert vr.main([*args, "--accepted", str(acc)]) == 1  # a line for another picture accepts nothing here
    acc.write_text(f"home-pi-ja-phone {vr.picture_hash(block)}  # the new menu, meant (9k-3)\n", encoding="utf-8")
    assert vr.main([*args, "--accepted", str(acc)]) == 0
    assert vr.compare(base, head, tmp_path / "o2", vr.read_accepted(acc)).shots[0].state == "accepted"
    # the hash is the pixels', not the file's: the same picture saved again is the same picture
    again = tmp_path / "again.png"
    with Image.open(block) as im:
        im.convert("RGBA").save(again, optimize=True)
    assert vr.picture_hash(again) == vr.picture_hash(block)


@pytest.mark.nodb
def test_9k17_the_accepted_lines_name_real_shots() -> None:
    names = set(visual_pages.shot_names())
    for raw in vr.ACCEPTED.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].split()
        if line:
            assert len(line) == 2 and line[0] in names and re.fullmatch(r"[0-9a-f]{64}", line[1]), raw


# ------------------------------------------------------------------------------------------- the job


@pytest.mark.nodb
def test_9k17_seventy_two_first_screens() -> None:
    names = visual_pages.shot_names()
    assert len(names) == len(set(names)) == vr.EXPECTED_SHOTS == 72
    assert len(visual_pages.PAGES) == 12 and visual_pages.PAGE_LANGS == ("en", "ja", "zh-TW")
    assert visual_pages.SIZES == {"desktop": (1280, 860), "phone": (390, 844)}
    homes = [u for p, u, path in visual_pages.PAGES if p.startswith("home-")]
    assert homes == ["drsato", "crc", "stew", "admin"]  # each role's home: investigator, coordinator, steward, admin


@pytest.mark.nodb
def test_9k17_the_job_runs_on_a_pull_request_and_fails_with_the_tool() -> None:
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    on = wf.get("on") or wf.get(True)  # YAML 1.1 reads a bare `on` as true
    assert on["pull_request"]["paths"] == [  # the integrator's ruling: only these four
        "trialbox/services/console/**",
        "trialbox/tools/visual_regression.py",
        "trialbox/tests/console/visual_accepted.txt",
        ".github/workflows/trialbox-visual.yml",
    ]
    assert "NOT A REQUIRED CHECK" in WORKFLOW.read_text(encoding="utf-8")
    required = re.search(
        r"^REQUIRED = \(([^)]*)\)", (ROOT / "tests/unit/test_ci_required_gates.py").read_text("utf-8"), re.M
    )
    assert required and "visual" not in required.group(1)  # nothing in the repository marks it required
    assert wf["permissions"] == {"contents": "read"}
    (job,) = wf["jobs"].values()
    assert 0 < int(job["timeout-minutes"]) <= 30
    steps = job["steps"]
    assert steps[0]["uses"].startswith("actions/checkout@") and steps[0]["with"]["fetch-depth"] == 0
    text = json.dumps(steps)
    assert "git worktree add --detach" in text and "origin/$BASE_REF" in text
    run = next(s["run"] for s in steps if "tools.visual_regression run" in str(s.get("run", "")))
    assert '--base-tree "$RUNNER_TEMP/base/trialbox"' in run and 'exit "$rc"' in run  # the tool's code is the job's
    keep = next(s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact@"))
    assert keep["if"] == "always()"
    assert "playwright install" in text and "tools/package-lock.json" in text  # the locked Playwright, as the walks
    assert "npm ci" in text and "npm install" not in text  # exactly the locked versions
    # the Playwright version is one exact number, written once (tools/package.json) and equal in its hashed lock
    pkg = json.loads((ROOT / "tools" / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "tools" / "package-lock.json").read_text(encoding="utf-8"))
    version = pkg["devDependencies"]["playwright"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), version
    assert lock["packages"]["node_modules/playwright"]["version"] == version


# ------------------------------------------------------------------------------------------- in Chromium


@pytest.fixture
def shots(tmp_path: Path, pg_cluster_url: str) -> Path:
    """This tree rendered and photographed once (72 pictures), with the session's database for the box's stores."""
    os.environ["TB_TEST_DB_URL"] = pg_cluster_url  # read by the renderer's child process
    try:
        m = vr.shoot(ROOT, tmp_path / "one")
    finally:
        os.environ.pop("TB_TEST_DB_URL", None)
    assert m["errors"] == {} and len(m["names"]) == 72, m["errors"]
    return tmp_path / "one"


@pytest.mark.skipif(not _node_playwright(), reason="Node Playwright is not available")
def test_9k17_the_job_fails_on_an_unreviewed_difference_in_chromium(
    shots: Path, tmp_path: Path, pg_cluster_url: str
) -> None:
    os.environ["TB_TEST_DB_URL"] = pg_cluster_url
    try:
        again = vr.shoot(ROOT, tmp_path / "two")
    finally:
        os.environ.pop("TB_TEST_DB_URL", None)
    assert again["errors"] == {}
    same = vr.compare(shots, tmp_path / "two", tmp_path / "rep-same", set())
    assert [s.state for s in same.shots] == ["same"] * 72  # one tree, two runs: the same pixels
    with Image.open(shots / "png" / "home-pi-ja-phone.png") as im:
        assert im.size == (390, 844) and len(im.convert("RGB").getcolors(1 << 20) or ()) > 20  # a drawn page, not blank
    # a planted change: the primary button's colour, in the pages of the second run, photographed again
    planted = tmp_path / "two" / "pages" / "console.css"
    planted.write_text(planted.read_text(encoding="utf-8") + "\nbutton, .button { background: var(--bad); }\n", "utf-8")
    m = json.loads((tmp_path / "two" / "pages" / "pages.json").read_text(encoding="utf-8"))
    assert vr.photograph(tmp_path / "two" / "pages", tmp_path / "two" / "png", m["shots"])["failed"] == {}
    args = ["compare", "--base", str(shots), "--head", str(tmp_path / "two"), "--out", str(tmp_path / "rep")]
    acc = tmp_path / "accepted.txt"
    assert vr.main([*args, "--accepted", str(acc)]) == 1
    res = vr.compare(shots, tmp_path / "two", tmp_path / "rep", set())
    assert len(res.unreviewed) >= 12 and all(s.fraction > vr.THRESHOLD for s in res.unreviewed)
    # the person's lines, as the report prints them, make it pass; nothing else does
    lines = [
        ln
        for ln in (tmp_path / "rep" / "report.md").read_text("utf-8").splitlines()
        if re.match(r"^\S+ [0-9a-f]{64}  #", ln)
    ]
    assert len(lines) == len(res.unreviewed)
    acc.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    assert vr.main([*args, "--accepted", str(acc)]) == 1  # one left unreviewed
    acc.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert vr.main([*args, "--accepted", str(acc)]) == 0


@pytest.mark.skipif(not _node_playwright(), reason="Node Playwright is not available")
def test_9k17_the_command_line_shoots_this_tree(tmp_path: Path, pg_cluster_url: str) -> None:
    """``shoot`` from the command line, as the job runs it (a few pages; the full set is above)."""
    env = {**os.environ, "TB_TEST_DB_URL": pg_cluster_url, "PYTHONPATH": "libs:services:."}
    env.pop("PYTHONUNBUFFERED", None)
    cmd = [
        sys.executable,
        "-m",
        "tools.visual_regression",
        "shoot",
        "--out",
        str(tmp_path / "s"),
        "--only",
        "help-ja-phone",
    ]
    r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=600, check=False)
    assert r.returncode == 0, r.stderr[-2000:]
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out == {"errors": {}, "shots": 2}  # the help page in Japanese, desktop and phone
