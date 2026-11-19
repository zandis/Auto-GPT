"""9k-17 (D-1377): the first screens the visual regression compares, rendered by the tree it runs in.

``python <this file> --out DIR [--only NAME ...]`` is run with the tree to be shot as its working directory (the pull
request's, or master's in a second checkout): it imports that tree's console and its in-process test box
(``tests/console/test_console_app.py``: a fake orchestrator and synthetic data only; the account store in a
throwaway PostgreSQL of ``tools/pglocal.py``, or in ``TB_TEST_DB_URL``), pins the console's clock to one instant,
signs in as each role in each language, and writes every page's HTML beside that tree's ``console.css`` into
``DIR`` (the script is inline in each page), with ``pages.json`` naming the 72 shots (12 pages, desktop and phone,
en, ja and zh-TW). ``tools/visual_regression.py`` opens them in Chromium and compares. It reads no patient data: the
box holds the test suite's synthetic study GZQO and nothing else.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PAGE_LANGS = ("en", "ja", "zh-TW")
SIZES = {"desktop": (1280, 860), "phone": (390, 844)}
PW = "visual-regression-password-0001"
B = "b" * 32
NOW = datetime(2026, 10, 7, 9, 30, tzinfo=UTC)  # the one instant every page is drawn at
# (shot name, user, path): the twelve pages of review 09 §5.3; each role's home, then the clinical and the
# administrative pages the journeys meet first
PAGES: tuple[tuple[str, str, str], ...] = (
    ("home-pi", "drsato", "/"),
    ("home-crc", "crc", "/"),
    ("home-steward", "stew", "/"),
    ("home-admin", "admin", "/"),
    ("week", "crc", "/studies/GZQO/week"),
    ("patient-sheet", "drsato", f"/studies/GZQO/week?pid={B}"),
    ("patient", "drsato", f"/studies/GZQO/patients/{B}"),
    ("registry", "crc", "/pilot/registry/GZQO"),
    ("sae", "crc", "/sae"),
    ("setup", "crc", "/studies/GZQO/setup"),
    ("health", "admin", "/admin"),
    ("help", "crc", "/help"),
)


def shot_names() -> list[str]:
    """Every shot's name: ``<page>-<lang>-<size>``, 72 of them."""
    return [f"{p}-{lang}-{size}" for p, _, _ in PAGES for lang in PAGE_LANGS for size in SIZES]


def _box(tmp: Path) -> dict[str, Any]:
    from tests.console import test_console_app as tca

    fixture = getattr(tca.box, "__wrapped__", tca.box)  # the pytest fixture's own function
    b: dict[str, Any] = fixture(tmp)
    h = b["app"].state.helpers
    h.clock = lambda: NOW
    tca._done_screen(b["backend"], tca._ulid(961))
    b["users"].create("drsato", "investigator", PW, "drsato@hospa.test")
    b["users"].create("crc", "coordinator", PW, "crc@hospa.test")
    b["users"].create("stew", "steward", PW, "stew@hospa.test")
    tca.name_pi(b, "drsato")
    h.life_sae = lambda rid: [
        {"record": "S-0001", "event": "ae1", "ae_term": "synthetic event", "ae_onset": "2026-10-01", "fatal": False}
    ]
    h.life_reports = lambda rid: [{"record": "S-0001", "event": "ae1", "party": "sponsor", "due": "2026-10-03"}]
    h.team_due = lambda rid: True
    return b


def _client(b: dict[str, Any], user: str, lang: str) -> Any:
    from tests.console import test_console_app as tca

    pw = tca.ADMIN_PW if user == "admin" else PW
    login = tca.login_totp if user == "admin" and hasattr(tca, "login_totp") else tca.login
    try:
        c, csrf = login(b["app"], user, pw)
    except AssertionError:
        c, csrf = tca.login(b["app"], user, pw)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
    return c


# per-session values that differ between two runs of the same tree: blanked before the page is written
_VOLATILE = (
    re.compile(r'(name="(?:csrf|login_csrf)" value=")[^"]+'),
    re.compile(r'(<meta name="csrf" content=")[^"]+'),
    re.compile(r"(nonce=\")[^\"]+"),
)


def _database() -> tuple[str, Any]:
    """A trial database for the box's stores: ``TB_TEST_DB_URL`` when given (as the test suite reads it), else a
    throwaway cluster of ``tools/pglocal.py`` that is removed afterwards."""
    given = os.environ.get("TB_TEST_DB_URL", "")
    if given:
        return given, None
    import tempfile

    from tools import pglocal

    pglocal.scratch_root().mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="tb-pgvisual-", dir=pglocal.scratch_root()))
    pglocal.claim(root)
    root.chmod(0o755)
    return pglocal.ensure(root), root


def render(out: Path, only: list[str] | None = None) -> dict[str, Any]:
    url, cluster = _database()
    sep = "&" if "?" in url else "?"
    os.environ["TB_DB_URL"] = f"{url}{sep}tb_prefix=vr{os.getpid()}_"
    try:
        return _render(out, only)
    finally:
        if cluster is not None:
            from tools import pglocal

            pglocal.remove(cluster)


def _render(out: Path, only: list[str] | None = None) -> dict[str, Any]:
    import tempfile

    out.mkdir(parents=True, exist_ok=True)
    shots: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="tb-visual-") as tmp:
        b = _box(Path(tmp))
        clients: dict[tuple[str, str], Any] = {}
        css = ""
        for page, user, path in PAGES:
            for lang in PAGE_LANGS:
                names = [f"{page}-{lang}-{size}" for size in SIZES]
                if only and not any(n in only for n in names):
                    continue
                key = (user, lang)
                try:
                    if key not in clients:
                        clients[key] = _client(b, user, lang)
                    c = clients[key]
                    r = c.get(path)
                    if r.status_code != 200:
                        raise RuntimeError(f"HTTP {r.status_code}")
                    text = r.text
                    css = css or c.get("/static/console.css").text
                except Exception as e:  # a page that cannot be drawn is a shot that differs
                    for n in names:
                        errors[n] = f"{path}: {type(e).__name__}: {e}"[:300]
                    continue
                for rx in _VOLATILE:
                    text = rx.sub(r"\1-", text)
                text = text.replace('href="/static/console.css"', 'href="console.css"')
                fname = f"{page}-{lang}.html"
                (out / fname).write_text(text, encoding="utf-8")
                for size, (w, hgt) in SIZES.items():
                    shots.append({"name": f"{page}-{lang}-{size}", "file": fname, "width": w, "height": hgt})
        (out / "console.css").write_text(css, encoding="utf-8")
    manifest = {"shots": shots, "errors": errors}
    (out / "pages.json").write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--only", nargs="*", default=None)
    a = ap.parse_args(argv)
    m = render(a.out.resolve(), a.only)
    print(json.dumps({"shots": len(m["shots"]), "errors": m["errors"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    tree = Path.cwd()
    for p in ("libs", "services", "."):
        sys.path.insert(0, str(tree / p))
    os.environ.setdefault("TB_ENV", "TEST")
    raise SystemExit(main())
