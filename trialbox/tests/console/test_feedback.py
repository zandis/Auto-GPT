# ruff: noqa: F811 - the box fixture is imported from test_console_app and taken by name
"""T-510 (D-331; UX-006): in-product feedback, a flag, a rating and a comment on every page in three languages.

The card's acceptance tests: an entry from any page is stored (with its path, language, role and time); the CSV
export; the planted-identifier scan of T-502 covers the comment field; one test per language. And: no field asks for
a patient example, and the "no patient details" line is visible beside the comment."""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any

import pytest
from console import demo_guard as dg
from console import feedback as fb
from console import i18n_feedback
from console.i18n import CATALOGUES
from fastapi.testclient import TestClient

from tests.console.test_console_app import _done_case, _done_feas, box, login  # noqa: F401 - fixture by name
from tests.console.test_wording_walk import VALUES, _pages

PW = "feedback-test-password-01"
LANGS = ("en", "ja", "zh-TW")
CATS = {"en": i18n_feedback.EN, "ja": i18n_feedback.JA, "zh-TW": i18n_feedback.ZH}
FORM = re.compile(r'<form method="post" action="/feedback".*?</form>', re.S)


def _planted() -> str:
    """A chart number in a sentence, built here so the repository scan stays clean."""
    return "seen in clinic, chart no " + str(4_417_239 * 10 + 1)


def _signed_in(b: dict[str, Any], name: str, role: str, lang: str = "en") -> tuple[TestClient, str]:
    if name != "admin":
        b["users"].create(name, role, PW, f"{name}@hospa.test")
    c, csrf = login(b["app"], name, PW if name != "admin" else "correct-horse-battery-1")
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
    return c, csrf


def _send(c: TestClient, csrf: str, path: str, **fields: str) -> Any:
    return c.post("/feedback", data={"csrf": csrf, "path": path, **fields}, follow_redirects=False)


def _events(b: dict[str, Any], name: str) -> list[dict[str, Any]]:
    out = []
    for f in sorted((b["dir"] / "audit").glob("*.jsonl")):
        out += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x]
    return [e for e in out if e["event"] == name]


def _export(b: dict[str, Any]) -> list[dict[str, str]]:
    c, _ = login(b["app"])
    r = c.get("/feedback/export.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.content.startswith(b"\xef\xbb\xbf")  # the byte order mark: Excel reads the file as UTF-8
    return list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig"))))


# ---------------------------------------------------------------------------------------------- every page
def test_an_entry_from_any_page_is_stored_with_path_language_role_and_time(box: dict[str, Any]) -> None:
    _done_feas(box["backend"])
    _done_case(box["backend"])
    c, csrf = _signed_in(box, "admin", "admin")
    paths = _pages(box["app"], VALUES)
    for job in list(box["backend"].jobs):
        paths += _pages(box["app"], {**VALUES, "job_id": job})
    sent: list[str] = []
    public: list[str] = []
    for path in sorted(set(paths)):
        r = c.get(path)
        if r.status_code != 200 or "text/html" not in r.headers.get("content-type", ""):
            continue
        if 'data-testid="whoami"' not in r.text:  # a public page, drawn without the account: no control to send
            public.append(path)
            continue
        form = FORM.search(r.text)
        assert form, f"no feedback control on {path}"
        page = re.search(r'name="path" value="([^"]+)"', form.group(0))
        assert page and page.group(1) == r.url.path, path
        assert 'data-testid="feedback-nopatient"' in form.group(0)
        r2 = _send(c, csrf, page.group(1), flag="wording", rating="4", comment=f"synthetic note on {path}")
        assert r2.status_code == 303 and "feedback=thanks" in r2.headers["location"], (path, r2.text[:300])
        sent.append(r.url.path)
    assert len(sent) > 20  # the walk reached the pages
    assert public == ["/about"]
    stored = box["app"].state.feedback.entries()
    assert [e.path for e in stored] == sent
    for e in stored:
        assert (e.lang, e.role, e.account, e.flag, e.rating) == ("en", "admin", "admin", "wording", 4)
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00", e.at)
    events = _events(box, fb.EVENT)  # one audit event per entry, naming the page, never the comment
    assert len(events) == len(sent) and all("comment" not in json.dumps(e) for e in events)
    assert "synthetic note" not in json.dumps(events)


def test_the_page_comes_back_with_a_thank_you_and_nothing_else_changes(box: dict[str, Any]) -> None:
    c, csrf = _signed_in(box, "admin", "admin")
    before = c.get("/home").text
    r = _send(c, csrf, "/home?x=1#y", rating="5")
    assert r.status_code == 303 and r.headers["location"] == "/home?feedback=thanks#feedback"
    after = c.get(r.headers["location"]).text
    assert 'data-testid="feedback-thanks"' in after and 'data-testid="feedback-thanks"' not in before
    (e,) = box["app"].state.feedback.entries()
    assert e.path == "/home" and e.rating == 5 and e.flag is None and e.comment is None
    # a page that answers no GET (a form's post) sends the tester home, not to an error
    r = _send(c, csrf, "/feedback", flag="slow")
    assert r.status_code == 303 and r.headers["location"] == "/?feedback=thanks#feedback"


def test_empty_bad_and_forged_posts_store_nothing(box: dict[str, Any]) -> None:
    c, csrf = _signed_in(box, "admin", "admin")
    assert _send(c, csrf, "/home").status_code == 400
    assert CATS["en"]["feedback.empty"] in _send(c, csrf, "/home", comment="   ").text
    assert _send(c, csrf, "/home", flag="nonsense").status_code == 400
    assert _send(c, csrf, "/home", rating="9").status_code == 400
    assert _send(c, csrf, "/home", rating="x").status_code == 400
    assert _send(c, csrf, "/home", comment="a" * (fb.COMMENT_MAX + 1)).status_code == 400
    assert _send(c, "forged", "/home", rating="3").status_code == 400
    anon = TestClient(box["app"]).post("/feedback", data={"csrf": "", "path": "/home", "rating": "3"},
                                       follow_redirects=False)  # fmt: skip
    assert anon.status_code == 303 and anon.headers["location"] == "/login"
    assert box["app"].state.feedback.entries() == []
    assert fb.clean_path("//elsewhere.test/x") == "/" and fb.clean_path("https://x.test/") == "/"
    assert fb.clean_path("/a\\b") == "/" and len(fb.clean_path("/" + "a" * 500)) == fb.PATH_MAX


def test_a_cro_account_and_the_sign_in_page(box: dict[str, Any]) -> None:
    """A CRO account, whose role opens the reports pages only, may still send feedback on them; a signed-out page has
    no control."""
    c, csrf = _signed_in(box, "cro1", "cro")
    assert FORM.search(c.get("/reports").text)
    assert _send(c, csrf, "/reports", flag="confusing").status_code == 303
    (e,) = box["app"].state.feedback.entries()
    assert (e.role, e.path) == ("cro", "/reports")
    assert 'data-testid="feedback"' not in TestClient(box["app"]).get("/login").text


# ---------------------------------------------------------------------------------------------- no patient field
def test_no_patient_example_field_and_a_visible_no_patient_details_line(box: dict[str, Any]) -> None:
    c, _ = _signed_in(box, "admin", "admin")
    form = FORM.search(c.get("/home").text)
    assert form
    names = re.findall(r'name="([^"]+)"', form.group(0))
    assert sorted(names) == ["comment", "csrf", "flag", "path", "rating"]  # nothing asks for a patient or an example
    assert not re.search(r"patient|example|pseudonym|chart", " ".join(names), re.I)
    body = form.group(0)
    assert body.index('data-testid="feedback-nopatient"') < body.index('data-testid="feedback-comment"')
    assert 'aria-describedby="feedback-nopatient"' in body  # read out with the comment box
    assert set(fb.CSV_COLUMNS).isdisjoint({"patient", "example", "pseudonym"})


# ---------------------------------------------------------------------------------------------- one test per language
@pytest.mark.parametrize("lang", LANGS)
def test_one_entry_per_language_reaches_the_owners_export_with_its_page(box: dict[str, Any], lang: str) -> None:
    _done_feas(box["backend"])
    role = {"en": "coordinator", "ja": "investigator", "zh-TW": "investigator"}[lang]
    c, csrf = _signed_in(box, f"tester-{lang.lower()}", role, lang)
    page = c.get("/studies/GZQO/feasibility").text
    cat = CATS[lang]
    for k in ("feedback.open", "feedback.nopatient", "feedback.send", "feedback.flag.wrong", "feedback.rating.5"):
        assert cat[k] in page, (lang, k)
    r = _send(c, csrf, "/studies/GZQO/feasibility", flag="wrong", rating="2", comment=f"{lang}: the count reads oddly")
    assert r.status_code == 303
    assert cat["feedback.thanks"] in c.get(r.headers["location"]).text
    (row,) = _export(box)
    assert (row["path"], row["lang"], row["role"], row["flag"], row["rating"]) == (
        "/studies/GZQO/feasibility", lang, role, "wrong", "2")  # fmt: skip
    assert row["comment"] == f"{lang}: the count reads oddly" and row["scan"] == ""
    assert row["tester"] == "T1" and f"tester-{lang.lower()}" not in json.dumps(row)  # a code, never the account
    assert f"lang:{lang}" in row["labels"].split(",") and "/studies/GZQO/feasibility" in row["title"]


def test_the_catalogues_have_every_string_in_three_languages() -> None:
    assert set(i18n_feedback.EN) == set(i18n_feedback.JA) == set(i18n_feedback.ZH)
    for lang in LANGS:
        assert set(i18n_feedback.EN) <= set(CATALOGUES[lang]), lang
    template = (Path(fb.__file__).parent / "templates" / "_feedback.html").read_text(encoding="utf-8")
    used = {k for k in re.findall(r"t\('(feedback\.[\w.]+)'", template) if not k.endswith(".")}
    used |= {f"feedback.flag.{f}" for f in fb.FLAGS} | {f"feedback.rating.{n}" for n in fb.RATINGS}
    assert used <= set(i18n_feedback.EN)


# ---------------------------------------------------------------------------------------------- the export
def test_the_csv_export_is_for_the_owner_and_one_row_per_issue(box: dict[str, Any], tmp_path: Path) -> None:
    pi, pcsrf = _signed_in(box, "pi1", "investigator", "ja")
    crc, ccsrf = _signed_in(box, "crc1", "coordinator", "zh-TW")
    assert _send(pi, pcsrf, "/home", flag="missing", comment="依頼の一覧がほしい").status_code == 303
    assert _send(crc, ccsrf, "/home", rating="3").status_code == 303
    assert _send(pi, pcsrf, "/help", comment=_planted()).status_code == 303
    r = pi.get("/feedback/export.csv")
    assert r.status_code == 403  # the owner's export: an admin account only
    rows = _export(box)
    assert list(rows[0]) == list(fb.CSV_COLUMNS)
    assert [(x["tester"], x["lang"], x["path"]) for x in rows] == [("T1", "ja", "/home"), ("T2", "zh-TW", "/home"),
                                                                   ("T1", "ja", "/help")]  # fmt: skip
    assert rows[0]["comment"] == "依頼の一覧がほしい" and "flag:missing" in rows[0]["labels"]
    assert rows[1]["title"] == "[poc] rating 3 · /home (zh-TW)"
    # the data-handling scan runs before anything leaves: the planted chart number is withheld and named
    assert rows[2]["comment"] == "" and rows[2]["scan"] == "chart_number"
    assert "44172391" not in json.dumps(rows) and "comment withheld: chart_number" in rows[2]["body"]
    assert all(n not in json.dumps(rows) for n in ("pi1", "crc1"))
    (ev,) = _events(box, "feedback.export")
    assert ev["detail"] == {"entries": 3}
    # the same file from the command line (the owner's evening export)
    out = tmp_path / "feedback.csv"
    assert fb.main(["export", "--out", str(out)]) == 0
    assert out.read_bytes().startswith(b"\xef\xbb\xbf")  # the owner opens it in a spreadsheet: the mark here too
    assert list(csv.DictReader(out.open(encoding="utf-8-sig"))) == rows


# ---------------------------------------------------------------------------------------------- the scan of T-502
def test_the_demo_scan_covers_the_comment_field(
    box: dict[str, Any], db_url: str, pg_cluster_url: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert "feedback.entry.comment" in dg.MUST_SCAN
    c, csrf = _signed_in(box, "crc1", "coordinator")
    base = tmp_path / "baseline.txt"
    assert dg.main(["scan", "--db", "--write-baseline", str(base)]) == 0
    assert _send(c, csrf, "/home", comment=_planted()).status_code == 303  # stored: the scan is what finds it
    seen: set[str] = set()
    hits = dg.scan_stored([], db_url, seen)
    assert "feedback.entry.comment" in seen
    found = [h for h in hits if h.pattern == "chart_number" and "_feedback.entry.comment#" in h.where]
    assert found, hits
    assert "44172391" not in str(found[0])  # masked, never the whole value
    capsys.readouterr()
    assert dg.main(["scan", "--db", "--baseline", str(base)]) == 2
    out = capsys.readouterr().out
    assert "feedback.entry.comment" in out and "1 new hit(s)" in out
    # a database the console never started on has no feedback table: the scan says so instead of passing
    sep = "&" if "?" in pg_cluster_url else "?"
    empty = f"{pg_cluster_url}{sep}tb_prefix=fbempty{abs(hash(str(tmp_path))) % 10**6}_"
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("TB_DB_URL", empty)
        assert dg.main(["scan", "--db"]) == 1
    assert "not scanned: feedback.entry.comment" in capsys.readouterr().err
