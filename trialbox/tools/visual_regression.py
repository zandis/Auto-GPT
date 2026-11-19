"""9k-17 (D-1377): visual regression of the console, the pull request against master, with no picture in git.

Review 09 §5.3: twelve pages (each role's home, the week page, the patient sheet and the full patient page, the
registry, the SAE register, set-up, the administrator's health page, help) at a desktop and a phone width
in English, Japanese and Traditional Chinese: 72 first screens, drawn at one pinned instant from the test suite's
synthetic box (``tests/console/visual_pages.py``) and photographed in Chromium (``tests/console/visual_shots.js``).
The same job shoots master in a second checkout with the same scripts, so both sets come from one machine, one
browser and one set of fonts; nothing is stored between runs.

A shot differs when more than 0.1 % of its pixels differ (or it exists on one side only, or could not be drawn). A
difference is reviewed when ``tests/console/visual_accepted.txt`` holds the line ``<shot> <hash>`` for the new
picture's hash (sha256 of its size and RGBA pixels): a person looked at the side-by-side page the job keeps
(``index.html``: master, the pull request, and the changed pixels in red) and committed the line the job printed. A
line accepts that one picture only: the next change to the same page differs again. Any unreviewed difference makes
the job fail.

    python -m tools.visual_regression shoot --tree . --out DIR
    python -m tools.visual_regression compare --base DIR --head DIR --out DIR
    python -m tools.visual_regression run --base-tree ../master --out DIR      # both, then compare (CI)

Exit codes: 0 no unreviewed difference, 1 an unreviewed difference, 2 a shot of the pull request's own tree could
not be taken (the job cannot judge).
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "tests" / "console" / "visual_pages.py"
SHOTS_JS = ROOT / "tests" / "console" / "visual_shots.js"
ACCEPTED = ROOT / "tests" / "console" / "visual_accepted.txt"
THRESHOLD = 0.001  # review 09 §5.3: a difference over 0.1 % of the pixels
EXPECTED_SHOTS = 72


# ------------------------------------------------------------------------------------------- comparing


def picture_hash(path: Path) -> str:
    """sha256 of the picture's size and RGBA pixels (not of the PNG bytes, which an encoder may vary)."""
    with Image.open(path) as im:
        rgba = im.convert("RGBA")
        return hashlib.sha256(f"{rgba.width}x{rgba.height}\n".encode() + rgba.tobytes()).hexdigest()


def changed_fraction(a: Path, b: Path) -> tuple[float, Image.Image | None]:
    """The share of pixels that differ (1.0 when the sizes differ) and a picture of them: the new screen faded, the
    changed pixels in red."""
    with Image.open(a) as ia, Image.open(b) as ib:
        x, y = ia.convert("RGB"), ib.convert("RGB")
        if x.size != y.size:
            return 1.0, None
        mask = ImageChops.difference(x, y).convert("L").point(lambda v: 255 if v else 0)
        n = sum(mask.histogram()[255:])
        if n == 0:
            return 0.0, None
        red = Image.new("RGB", y.size, (220, 0, 0))
        faded = Image.blend(y, Image.new("RGB", y.size, (255, 255, 255)), 0.7)
        return n / (y.width * y.height), Image.composite(red, faded, mask)


def read_accepted(path: Path) -> set[tuple[str, str]]:
    """``<shot> <hash>`` pairs; ``#`` starts a comment (the reason a person accepted it)."""
    out: set[tuple[str, str]] = set()
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].split()
        if len(line) >= 2:
            out.add((line[0], line[1]))
    return out


@dataclass
class Shot:
    name: str
    state: str  # same, below (under the threshold), differs, accepted
    fraction: float = 0.0
    head_hash: str = ""
    why: str = ""


@dataclass
class Result:
    shots: list[Shot] = field(default_factory=list)

    @property
    def unreviewed(self) -> list[Shot]:
        return [s for s in self.shots if s.state == "differs"]


def _manifest(d: Path) -> tuple[list[str], dict[str, str]]:
    p = d / "shots.json"
    m: dict[str, Any] = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    return [str(n) for n in m.get("names") or []], {str(k): str(v) for k, v in (m.get("errors") or {}).items()}


def compare(base: Path, head: Path, out: Path, accepted: set[tuple[str, str]], threshold: float = THRESHOLD) -> Result:
    """Compare two shot folders (``shoot``'s output) and write ``index.html`` and ``report.md`` into ``out``."""
    out.mkdir(parents=True, exist_ok=True)
    (bnames, berr), (hnames, herr) = _manifest(base), _manifest(head)
    names = sorted(set(bnames) | set(hnames) | set(berr) | set(herr))
    res = Result()
    for name in names:
        bp, hp = base / "png" / f"{name}.png", head / "png" / f"{name}.png"
        hh = picture_hash(hp) if hp.is_file() else ""
        if not hp.is_file():
            s = Shot(name, "differs", 1.0, "", f"not drawn on the pull request: {herr.get(name, 'missing')}")
        elif not bp.is_file():
            s = Shot(name, "differs", 1.0, hh, f"not drawn on master: {berr.get(name, 'missing')}")
        else:
            frac, diff = changed_fraction(bp, hp)
            if frac == 0:
                s = Shot(name, "same", 0.0, hh)
            elif frac <= threshold:
                s = Shot(name, "below", frac, hh, f"{frac:.4%} of the pixels, at or under {threshold:.1%}")
            else:
                s = Shot(name, "differs", frac, hh, f"{frac:.2%} of the pixels")
            if diff is not None:
                (out / "img").mkdir(exist_ok=True)
                diff.save(out / "img" / f"{name}-diff.png")
        if s.state == "differs" and hh and (name, hh) in accepted:
            s.state = "accepted"
        if s.state in ("differs", "accepted", "below"):
            (out / "img").mkdir(exist_ok=True)
            for side, p in (("master", bp), ("pr", hp)):
                if p.is_file():
                    shutil.copyfile(p, out / "img" / f"{name}-{side}.png")
        res.shots.append(s)
    _write_report(res, out, threshold)
    return res


def _write_report(res: Result, out: Path, threshold: float) -> None:
    counts = {k: sum(1 for s in res.shots if s.state == k) for k in ("same", "below", "accepted", "differs")}
    md = [
        "# Visual regression (9k-17)",
        "",
        f"{len(res.shots)} shots: {counts['same']} the same, {counts['below']} under {threshold:.1%}, "
        f"{counts['accepted']} accepted, **{counts['differs']} not reviewed**.",
        "",
    ]
    if res.unreviewed:
        md += [
            "Look at each in `index.html` of the job's files (master, the pull request, the changed pixels in red).",
            "If the change is meant, add these lines to `trialbox/tests/console/visual_accepted.txt` with a reason:",
            "",
            "```",
            *[f"{s.name} {s.head_hash or '-'}  # <why this change is meant>" for s in res.unreviewed],
            "```",
            "",
        ]
    md += ["| Shot | State | Why |", "| --- | --- | --- |"]
    md += [f"| {s.name} | {s.state} | {s.why} |" for s in res.shots if s.state != "same"]
    (out / "report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    rows = []
    for s in res.shots:
        if s.state == "same":
            continue
        cells = "".join(
            f'<figure><figcaption>{lab}</figcaption><img src="img/{html.escape(s.name)}-{k}.png" alt="{lab}"></figure>'
            for k, lab in (("master", "master"), ("pr", "pull request"), ("diff", "changed pixels"))
            if (out / "img" / f"{s.name}-{k}.png").is_file()
        )
        rows.append(
            f"<section><h2>{html.escape(s.name)} <small>{html.escape(s.state)}: {html.escape(s.why)}</small></h2>"
            f"<p><code>{html.escape(s.name)} {html.escape(s.head_hash)}</code></p>"
            f'<div class="row">{cells}</div></section>'
        )
    page = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Visual regression</title>'
        "<style>body{font:15px system-ui,sans-serif;margin:16px}.row{display:flex;gap:12px;align-items:flex-start;"
        "overflow-x:auto}figure{margin:0}img{max-width:640px;border:1px solid #888}small{font-weight:400}</style>"
        f"</head><body><h1>Visual regression</h1><p>{html.escape(md[2].replace('**', ''))}</p>{''.join(rows)}"
        "</body></html>"
    )
    (out / "index.html").write_text(page, encoding="utf-8")


# ------------------------------------------------------------------------------------------- shooting


def _node() -> str:
    node = shutil.which("node")
    if not node:
        raise SystemExit("node is not installed: the shots need Node Playwright (tools/package.json)")
    return node


def photograph(
    pages: Path, png: Path, shots: list[dict[str, object]], measure: bool = False
) -> dict[str, dict[str, Any]]:
    """The first screen of each written page, one PNG per shot. Returns ``failed`` (why a shot was not taken) and,
    with ``measure``, ``small`` (per shot, each visible button under 44 x 44 px: 9k-3)."""
    arg = json.dumps({"dir": str(pages), "out": str(png), "shots": shots, "measure": measure})
    n = subprocess.run(
        [_node(), str(SHOTS_JS), arg], cwd=ROOT, capture_output=True, text=True, timeout=1800, check=False
    )
    try:
        got = json.loads(n.stdout.strip().splitlines()[-1])
        return {"failed": dict(got["failed"]), "small": dict(got.get("small") or {})}
    except (IndexError, ValueError, KeyError):
        return {"failed": {"*": (n.stderr or n.stdout)[-1500:]}, "small": {}}


def shoot(tree: Path, out: Path, only: list[str] | None = None) -> dict[str, Any]:
    """Render the pages of ``tree`` with its own console and photograph them; writes ``out/png`` and
    ``out/shots.json`` (the names drawn and, per shot, why one was not)."""
    tree, out = tree.resolve(), out.resolve()
    pages, png = out / "pages", out / "png"
    for d in (pages, png):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(str(tree / p) for p in ("libs", "services", "."))}
    cmd = [sys.executable, str(PAGES), "--out", str(pages), *(["--only", *only] if only else [])]
    r = subprocess.run(cmd, cwd=tree, env=env, capture_output=True, text=True, timeout=1800, check=False)
    errors: dict[str, str] = {}
    shots: list[dict[str, object]] = []
    if r.returncode != 0 or not (pages / "pages.json").is_file():
        errors["*"] = (r.stderr or r.stdout)[-1500:]
    else:
        m = json.loads((pages / "pages.json").read_text(encoding="utf-8"))
        shots, errors = m["shots"], dict(m["errors"])
    if shots:
        errors.update(photograph(pages, png, shots)["failed"])
    names = sorted(p.stem for p in png.glob("*.png"))
    manifest: dict[str, Any] = {"names": names, "errors": errors}
    (out / "shots.json").write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    return manifest


# ------------------------------------------------------------------------------------------- command line


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.visual_regression", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("shoot")
    s.add_argument("--tree", type=Path, default=ROOT)
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--only", nargs="*", default=None)
    c = sub.add_parser("compare")
    c.add_argument("--base", type=Path, required=True)
    c.add_argument("--head", type=Path, required=True)
    c.add_argument("--out", type=Path, required=True)
    c.add_argument("--accepted", type=Path, default=ACCEPTED)
    r = sub.add_parser("run")
    r.add_argument("--base-tree", type=Path, required=True)
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--accepted", type=Path, default=ACCEPTED)
    a = ap.parse_args(argv)
    if a.cmd == "shoot":
        m = shoot(a.tree, a.out, a.only)
        print(json.dumps({"shots": len(m["names"]), "errors": m["errors"]}, sort_keys=True))
        return 2 if m["errors"] else 0
    if a.cmd == "run":
        head = shoot(ROOT, a.out / "pr")
        shoot(a.base_tree, a.out / "master")
        if head["errors"] or len(head["names"]) != EXPECTED_SHOTS:
            print(json.dumps({"pull_request_shots": len(head["names"]), "errors": head["errors"]}))
            return 2
        a.base, a.head = a.out / "master", a.out / "pr"
        a.out = a.out / "report"
    res = compare(a.base, a.head, a.out, read_accepted(a.accepted))
    print((a.out / "report.md").read_text(encoding="utf-8"))
    return 1 if res.unreviewed else 0


if __name__ == "__main__":
    raise SystemExit(main())
