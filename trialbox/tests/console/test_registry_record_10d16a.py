"""10D-16a (D-1373): a study's jRCT record from the person's own file, never fetched.

* **The invariant:** an intake never opens a network connection and never writes outside its own folder. Every
  internet socket the process tries to make raises (a Unix socket pair, which the test client's event loop needs,
  is allowed and is not a network connection); the box's folder, a private temporary folder and the folders around
  them are compared before and after a run of hostile file names and hostile contents; inside its own folder only
  ``<sha256>.json`` files (0600) in study folders (0700) appear.
* **The hostile-file table** through the page: oversize, wrong type, entity expansion, deep nesting, path-like names,
  markup in fields, the same file twice; each refused with its true message in en, ja and zh-TW, or kept once.
* **Who:** every role walked on the page and its ``/api/v1`` twin (``study.state`` with the study's delegation log:
  a coordinator, the logged PI); CSRF; the intake audited (who, the file's SHA-256, what was kept or why refused),
  never the file's content or name; a file with investigators' names stores none of them.

Synthetic data only (``example.invalid`` addresses, ``+1-555-01xx`` numbers, made-up jRCT numbers)."""

from __future__ import annotations

import json
import socket
import stat
import tempfile
from pathlib import Path
from typing import Any

import pytest
from console import registry_record_page as page
from console.i18n import CATALOGUES
from fastapi.testclient import TestClient
from tb_common import registry_file as rf

from tests.console.test_console_app import box, login, name_pi  # noqa: F401 - box is a fixture
from tests.console.test_role_pages import PW, _csrf, _user
from tests.unit.test_registry_file_10d16a import ENTITIES, GOOD, HEAD, PERSONS, ROW, WITH_NAMES

URL = "/studies/GZQO/registry-record"
API = "/api/v1/studies/GZQO/registry-record"
LANGS = ("en", "ja", "zh-TW")


def _events(b: dict[str, Any], name: str = page.EVENT) -> list[dict[str, Any]]:
    out = []
    for f in sorted((b["dir"] / "audit").glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line and json.loads(line).get("event") == name:
                out.append(json.loads(line))
    return out


def _folder(b: dict[str, Any]) -> Path:
    return Path(b["app"].state.registry_records.root)


def _crc(b: dict[str, Any], name: str = "crc1") -> TestClient:
    if b["users"].get(name) is None:
        return _user(b, name, "coordinator")
    return login(b["app"], name, PW)[0]


def _post(c: TestClient, data: bytes, name: str = "record.csv", csrf: str | None = None) -> Any:
    token = csrf if csrf is not None else _csrf(c.get(URL).text)
    return c.post(URL, data={"csrf": token}, files={"record": (name, data, "text/csv")}, follow_redirects=False)


def _error(text: str) -> str:
    import html
    import re

    m = re.search(r'<p class="fm-err" id="rrec-record-err"><span class="sr">[^<]*</span> (.*?)</p>', text, re.S)
    assert m, text[-1500:]
    return html.unescape(m.group(1))


# ---------------------------------------------------------------------------------------------- who
#: (column, role, scope, on the study's log as, may read the page, may read a file in)
COLUMNS: tuple[tuple[str, str, dict[str, str], str, bool, bool], ...] = (
    ("admin", "admin", {}, "", True, False),
    ("crc", "coordinator", {}, "", True, True),
    ("smo_in", "coordinator", {"affiliation": "smo", "studies": "GZQO", "expires": "2099-12-31"}, "", True, True),
    ("smo_out", "coordinator", {"affiliation": "smo", "studies": "RA-BIO", "expires": "2099-12-31"}, "", False, False),
    ("inv", "investigator", {}, "", True, False),
    ("pi", "investigator", {}, "pi", True, True),
    ("sub", "investigator", {}, "sub_pi", True, False),
    ("viewer", "viewer", {}, "", False, False),
    ("cro_in", "cro", {"affiliation": "cro", "studies": "GZQO"}, "", False, False),
    ("steward", "steward", {}, "", True, False),
    ("privacy", "privacy", {}, "", True, False),
)  # fmt: skip


def test_every_role_walked_on_the_page_and_its_api_twin(box: dict[str, Any]) -> None:  # noqa: F811
    h = box["app"].state.helpers
    for col, role, scope, log, reads, takes in COLUMNS:
        name = f"rr{col.replace('_', '')}"
        c = _user(box, name, role, **scope)
        if log == "pi":
            name_pi(box, name)
        elif log:
            h.team.add_entry("GZQO", username=name, name=name, role=log, tasks=("screen",), start="2026-01-01",
                             end=None, training_day="2026-01-01", training_ref=None, by="admin",
                             at="2026-01-01T00:00:00+00:00")  # fmt: skip
        r = c.get(URL)
        assert (r.status_code == 200) == reads, (col, r.status_code)
        if reads:
            assert ('data-testid="rrec-form"' in r.text) == takes, col
            assert ('data-testid="rrec-who"' in r.text) == (not takes), col
        csrf = _csrf(c.get("/").text)
        before = len(list(_folder(box).rglob("*.json"))) if _folder(box).exists() else 0
        r = _post(c, GOOD, csrf=csrf)
        assert (r.status_code == 303) == takes, (col, r.status_code)
        if not takes:
            assert r.status_code in (403, 404), (col, r.status_code)
            now = len(list(_folder(box).rglob("*.json"))) if _folder(box).exists() else 0
            assert now == before, col
        token, _ = box["users"].new_session(box["users"].get(name), via="api")
        api = TestClient(box["app"], headers={"Authorization": f"Bearer {token}", "content-type": "text/csv"})
        r = api.post(API, content=GOOD)
        assert (r.status_code == 200) == takes, (col, r.status_code, r.text[:300])
        if takes:
            assert r.json()["record"]["id"] == "jRCT2031260901" and r.json()["outcome"] in ("taken", "same")
    anon = TestClient(box["app"])
    assert anon.post(API, content=GOOD, headers={"content-type": "text/csv"}).status_code == 401
    assert anon.post(URL, files={"record": ("r.csv", GOOD, "text/csv")}, follow_redirects=False).status_code in (
        303, 401, 403)  # fmt: skip
    refused = [e for e in _events(box, "console.denied") if URL in json.dumps(e) or API in json.dumps(e)]
    assert refused  # a refused right is audited


def test_csrf_is_enforced_and_nothing_is_kept(box: dict[str, Any]) -> None:  # noqa: F811
    c = _crc(box)
    for token in ("", "x" * 32):
        r = _post(c, GOOD, csrf=token)
        assert r.status_code in (400, 403), r.status_code
    assert not _events(box) and not _events(box, page.REFUSED_EVENT) and not list(_folder(box).rglob("*.json"))


def test_a_good_file_is_kept_audited_and_shown(box: dict[str, Any]) -> None:  # noqa: F811
    c = _crc(box)
    r = _post(c, GOOD)
    assert r.status_code == 303 and r.headers["location"] == f"{URL}?saved=1"
    (ev,) = _events(box)  # audited by the time the page says so
    assert ev["actor"] == "console:crc1" and ev["ruleset"] == "GZQO"
    assert ev["detail"]["action"] == "taken" and ev["detail"]["file_sha256"] == rf.sha256(GOOD)
    assert ev["detail"]["jrct"] == "jRCT2031260901" and ev["detail"]["kept"] == ",".join(rf.KEPT)
    text = c.get(r.headers["location"]).text
    assert 'data-testid="rrec-saved"' in text and "A synthetic study of drug X" in text
    assert 'data-testid="rrec-id">jRCT2031260901<' in text and rf.sha256(GOOD) in text
    assert "jrct.mhlw.go.jp" in text and 'href="https://jrct' not in text and 'href="http://jrct' not in text


def test_the_same_file_twice_is_kept_once(box: dict[str, Any]) -> None:  # noqa: F811
    c = _crc(box)
    assert _post(c, GOOD).status_code == 303
    files = sorted(_folder(box).rglob("*"))
    stamps = {p: p.stat().st_mtime_ns for p in files}
    r = _post(c, GOOD, name="another-name.csv")
    assert r.status_code == 303 and r.headers["location"] == f"{URL}?saved=1"
    assert sorted(_folder(box).rglob("*")) == files and {p: p.stat().st_mtime_ns for p in files} == stamps
    assert [e["detail"]["action"] for e in _events(box)] == ["taken", "same"]
    assert [p.name for p in _folder(box).rglob("*.json")] == [f"{rf.sha256(GOOD)}.json"]


def test_a_file_with_investigator_names_stores_none(box: dict[str, Any]) -> None:  # noqa: F811
    """The card's proof (plan 10 row 10D-16), through the page: nothing of the persons reaches the box's folder,
    the audit trail or the page."""
    c = _crc(box)
    r = _post(c, WITH_NAMES)
    assert r.status_code == 303
    kept = "".join(p.read_text(encoding="utf-8") for p in _folder(box).rglob("*.json"))
    trail = "".join(f.read_text(encoding="utf-8") for f in (box["dir"] / "audit").glob("*"))
    shown = c.get(URL).text
    assert "jRCT2031260902" in kept and "A synthetic trial" in shown
    for p in (*PERSONS, "Synthetic-One", "example.invalid", "555-01"):
        assert p not in kept and p not in trail and p not in shown, p


def test_markup_in_a_field_is_shown_as_text(box: dict[str, Any]) -> None:  # noqa: F811
    c = _crc(box)
    evil = f"{HEAD}\n{ROW.replace('A synthetic study of drug X', '<script>alert(1)</script><img src=x onerror=y>')}\n"
    assert _post(c, evil.encode()).status_code == 303
    text = c.get(URL).text
    assert "<script>alert(1)" not in text and "<img src=x" not in text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;&lt;img src=x onerror=y&gt;" in text


@pytest.mark.parametrize("lang", LANGS)
def test_each_refusal_is_its_true_message_in_three_languages(box: dict[str, Any], lang: str) -> None:  # noqa: F811
    c = _crc(box)
    r = c.post("/lang", data={"csrf": _csrf(c.get("/").text), "lang": lang, "back": "/"}, follow_redirects=False)
    assert r.status_code == 303
    cat = CATALOGUES[lang]
    cases = {
        "markup": ENTITIES, "json": b"[" * 50_000 + b"]" * 50_000, "archive": b"PK\x03\x04" + b"\x00" * 32,
        "many_records": f"{HEAD}\n{ROW}\n{ROW.replace('0901', '0904')}\n".encode(), "no_header": b"a,b\n1,2\n",
        "too_large": b"a" * (rf.MAX_BYTES + 1),
    }  # fmt: skip
    for code, data in cases.items():
        r = _post(c, data)
        assert r.status_code == 400, (code, r.status_code)
        assert _error(r.text) == cat[f"rrec.err.{code}"], code
        assert 'data-testid="rrec-error"' in r.text and 'aria-invalid="true"' in r.text
    r = c.post(URL, data={"csrf": _csrf(c.get(URL).text)}, files={"record": ("", b"", "text/csv")})
    assert r.status_code == 400 and _error(r.text) == cat["rrec.err.no_file"]
    refused = _events(box, page.REFUSED_EVENT)
    assert set(cases) <= {e["detail"].get("code") for e in refused} and not _events(box)
    assert all(e["detail"]["action"] == "refused" and e["actor"] == "console:crc1" for e in refused)
    assert not list(_folder(box).rglob("*.json"))


def test_a_body_larger_than_the_cap_is_refused_unread(box: dict[str, Any]) -> None:  # noqa: F811
    c = _crc(box)
    big = b"x" * (page.BODY_MAX + 1)
    r = _post(c, big)
    assert r.status_code == 400 and _error(r.text) == CATALOGUES["en"]["rrec.err.too_large"]
    (ev,) = _events(box, page.REFUSED_EVENT)
    assert ev["detail"] == {"action": "refused", "code": "too_large", "file_sha256": "", "bytes": page.BODY_MAX}


def test_a_file_of_another_studys_number_is_refused(box: dict[str, Any]) -> None:  # noqa: F811
    c = _crc(box)
    state = c.get("/studies/GZQO/state").text
    r = c.post("/studies/GZQO/identity", data={"csrf": _csrf(state), "registry_jrct": "jRCT2031260999"},
               follow_redirects=False)  # fmt: skip
    if r.status_code != 303:
        pytest.skip(f"no study store on this box ({r.status_code})")
    r = _post(c, GOOD)
    assert r.status_code == 400 and _error(r.text) == CATALOGUES["en"]["rrec.err.other_study"]
    assert 'data-testid="rrec-want"' in r.text and "jRCT2031260999" in r.text


def test_the_api_refuses_a_body_that_is_not_text_csv(box: dict[str, Any]) -> None:  # noqa: F811
    _crc(box)
    token, _ = box["users"].new_session(box["users"].get("crc1"), via="api")
    api = TestClient(box["app"], headers={"Authorization": f"Bearer {token}"})
    assert api.post(API, content=GOOD, headers={"content-type": "application/json"}).status_code == 415
    assert api.post(API, content=b"a" * (page.BODY_MAX + 1), headers={"content-type": "text/csv"}).status_code == 413
    r = api.post(API, content=ENTITIES, headers={"content-type": "text/csv"})
    assert r.status_code == 400
    assert not list(_folder(box).rglob("*.json")) if _folder(box).exists() else True


# ---------------------------------------------------------------------------------------------- the invariant
def _tree(root: Path, skip: tuple[Path, ...] = ()) -> dict[str, tuple[int, int, int]]:
    out: dict[str, tuple[int, int, int]] = {}
    if not root.exists():
        return out
    for p in root.rglob("*"):
        if any(p == s or s in p.parents for s in skip):
            continue
        st = p.lstat()
        out[str(p.relative_to(root))] = (st.st_mode, st.st_size, 0 if p.is_dir() else st.st_mtime_ns)
    return out


HOSTILE_NAMES = ("../../escape-10d16a.csv", "/etc/escape-10d16a.csv", "..\\..\\escape-10d16a.csv",
                 "a/b/escape-10d16a.csv", "escape-10d16a.csv;rm -rf", "%2e%2e%2fescape-10d16a.csv",
                 "GZQO/../../escape-10d16a.json", ".escape-10d16a.json")  # fmt: skip
HOSTILE_FILES = (GOOD, WITH_NAMES, ENTITIES, b"[" * 100_000 + b"]" * 100_000, b"PK\x03\x04" + b"\x00" * 64,
                 b"a" * (rf.MAX_BYTES + 1), b"x" * (page.BODY_MAX + 1), b"", b"\x00" * 128,
                 f"{HEAD}\n{ROW.replace('jRCT2031260901', '../../etc/passwd')}\n".encode(),
                 f"{HEAD}\n{ROW.replace('A synthetic study', '<x>')}\n".encode())  # fmt: skip


def test_an_intake_never_opens_a_network_connection_and_never_writes_outside_its_own_folder(
    box: dict[str, Any],  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-1373's invariant, for hostile file names and hostile contents through the page and the API."""
    c = _crc(box)
    token, _ = box["users"].new_session(box["users"].get("crc1"), via="api")
    api = TestClient(box["app"], headers={"Authorization": f"Bearer {token}", "content-type": "text/csv"})
    c.get(URL)  # every lazy start-up of the page before the snapshot
    own = _folder(box)
    private_tmp = tmp_path / "private-tmp"
    private_tmp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(private_tmp))  # a spooled upload that rolled to disk lands here
    watched = {"box": (box["dir"], (own, box["dir"] / "audit", private_tmp)), "tmp": (private_tmp, ())}
    before = {k: _tree(root, skip) for k, (root, skip) in watched.items()}
    around = {p: sorted(x.name for x in p.iterdir()) for p in (box["dir"].parent, Path("/etc"))}
    tried: list[Any] = []
    real_init = socket.socket.__init__

    def no_network(self: socket.socket, family: Any = -1, *a: Any, **k: Any) -> None:
        fam = socket.AF_INET if family == -1 else family
        if fam in (socket.AF_INET, socket.AF_INET6) and k.get("fileno") is None and not (len(a) >= 3 and a[2]):
            tried.append(fam)
            raise AssertionError("an intake opened an internet socket")
        real_init(self, family, *a, **k)

    def no_connect(*a: Any, **k: Any) -> None:
        tried.append(a)
        raise AssertionError("an intake connected")

    monkeypatch.setattr(socket.socket, "__init__", no_network)
    monkeypatch.setattr(socket, "create_connection", no_connect)
    monkeypatch.setattr(socket, "getaddrinfo", no_connect)
    statuses = []
    for i, data in enumerate(HOSTILE_FILES):
        for name in HOSTILE_NAMES:
            statuses.append(_post(c, data, name=name).status_code)
        statuses.append(api.post(API, content=data).status_code)
        if i == 0:
            statuses.append(api.post(API, content=data, headers={"content-type": "application/xml"}).status_code)
    monkeypatch.undo()
    assert not tried, tried
    assert set(statuses) <= {303, 200, 400, 413, 415}, statuses
    after = {k: _tree(root, skip) for k, (root, skip) in watched.items()}
    # only the console's own folder may appear, as the parent of the intake's folder (the box makes it on first use)
    made = {str(p.relative_to(box["dir"])) for p in own.parents if box["dir"] in p.parents}
    assert set(after["box"]) - set(before["box"]) <= made, set(after["box"]) - set(before["box"])
    assert {k: v for k, v in after["box"].items() if k not in made} == before["box"]
    assert after["tmp"] == before["tmp"] == {}
    assert {p: sorted(x.name for x in p.iterdir()) for p in around} == around
    assert not [p for p in box["dir"].parent.rglob("escape-10d16a*")]
    # inside its own folder: study folders 0700 holding <sha256>.json files 0600 owned by this process's user
    kept = sorted(p for p in own.rglob("*"))
    assert stat.S_IMODE(own.stat().st_mode) == 0o700
    assert {p.relative_to(own).parts[0] for p in kept} == {"GZQO"}
    for p in kept:
        st = p.lstat()
        assert st.st_uid == __import__("os").getuid() and not stat.S_ISLNK(st.st_mode)
        if p.is_dir():
            assert p.name == "GZQO" and stat.S_IMODE(st.st_mode) == 0o700
        else:
            assert page._SHA.match(p.stem) and p.suffix == ".json" and stat.S_IMODE(st.st_mode) == 0o600, p
    assert {p.stem for p in kept if p.is_file()} == {rf.sha256(GOOD), rf.sha256(WITH_NAMES),
                                                    rf.sha256(HOSTILE_FILES[-1])}  # fmt: skip
