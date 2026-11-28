# ruff: noqa: F811 - the box fixture is imported from test_console_app and taken by name
"""``/about`` (T-617a, STD-044): the third-party notices of NOTICE, without a sign-in, in the reader's language around
the licences' own English text; ``/about/NOTICE.txt`` is the same file as plain text."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

import pytest
from console import about
from console.auth import ROLES
from fastapi.testclient import TestClient

from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name

ROOT = Path(__file__).resolve().parents[2]


def test_about_shows_the_notice_without_a_sign_in(box: dict[str, Any]) -> None:
    c = TestClient(box["app"])
    r = c.get("/about", follow_redirects=False)
    assert r.status_code == 200
    page = html.unescape(r.text)
    assert 'data-testid="about-notice"' in page and 'lang="en"' in page
    for needle in (
        "This material contains content from LOINC (http://loinc.org)",
        "subject to a license from Regenstrief Institute, Inc. and The UCUM Organization",
        "1. CODE SYSTEMS AND VOCABULARIES",
        "8. SHIPPED VOCABULARY FOLDERS",
        "SIL Open Font License 1.1",
    ):
        assert needle in page, needle
    t = c.get("/about/NOTICE.txt")
    assert t.status_code == 200 and t.headers["content-type"].startswith("text/plain")
    assert t.text == (ROOT / "NOTICE").read_text(encoding="utf-8")


@pytest.mark.parametrize("role", ["anonymous", *ROLES])
def test_about_answers_200_with_the_notice_for_every_role(box: dict[str, Any], role: str) -> None:
    """P2-02: the installed box answered 503 on /about for every reader (no /app/NOTICE in the image)."""
    if role == "anonymous":
        c = TestClient(box["app"])
    else:
        box["users"].create("reader", role, "reader-password-0001", "reader@hospa.test")
        c, _ = login(box["app"], "reader", "reader-password-0001")
    page = c.get("/about", follow_redirects=False)
    assert page.status_code == 200 and 'data-testid="about-missing"' not in page.text
    assert "This material contains content from LOINC (http://loinc.org)" in html.unescape(page.text)
    text = c.get("/about/NOTICE.txt", follow_redirects=False)
    assert text.status_code == 200 and text.text == (ROOT / "NOTICE").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("lang", "title"), [("ja", "第三者の権利表示"), ("zh-TW", "第三方聲明"), ("en", "third-party")]
)
def test_about_follows_the_reader_language(box: dict[str, Any], lang: str, title: str) -> None:
    c, csrf = login(box["app"])
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
    page = c.get("/about").text
    assert title in page and "Regenstrief Institute" in page


def test_a_missing_notice_is_said_plainly(box: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(about, "NOTICE", tmp_path / "NOTICE")
    c = TestClient(box["app"])
    r = c.get("/about")
    assert r.status_code == 503 and 'data-testid="about-missing"' in r.text
    assert c.get("/about/NOTICE.txt").status_code == 503


def test_sections_split_on_underlined_headings() -> None:
    text = "Title\n=====\n\nintro line\n  more\n\n=====\n1. ONE\n=====\n\na\n\nb\n"
    assert about.sections(text) == [
        {"title": "Title", "blocks": [["intro line", "more"]]},
        {"title": "1. ONE", "blocks": [["a"], ["b"]]},
    ]


# T-110b (D-340): the page names the release the box runs


def test_about_shows_the_release(box: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tools.release import version

    rel = tmp_path / "release.json"
    rel.write_text('{"release_id": "2026.11-1", "release_seq": 3, "version": "' + version() + '"}', encoding="utf-8")
    monkeypatch.setenv("TB_REVISION", "0123456789abcdef0123456789abcdef01234567")
    monkeypatch.setenv("TB_RELEASE_FILE", str(rel))
    page = html.unescape(TestClient(box["app"]).get("/about").text)
    assert f'data-testid="about-version">{version()}<' in page
    assert ">0123456789abcdef0123456789abcdef01234567<" in page
    assert ">2026.11-1 (seq 3)<" in page


def test_release_info_without_a_release_file(tmp_path: Path) -> None:
    py = tmp_path / "pyproject.toml"
    py.write_text('[project]\nname = "trialbox"\nversion = "1.2.3"\n', encoding="utf-8")
    assert about.release_info(py, {"TB_REVISION": "not a sha"}) == {
        "version": "1.2.3",
        "revision": None,
        "release_id": None,
    }
    broken = tmp_path / "missing.json"
    assert about.release_info(tmp_path / "none.toml", {"TB_RELEASE_FILE": str(broken)})["version"] is None
