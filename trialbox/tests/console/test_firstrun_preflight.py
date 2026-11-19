"""10K-3 (D-1361, review 18 SO-3): the box's first-run page shows the live preflight the installer ran. A fixture per
failing check shows a red line with its next action, in ja; a green line has no action; without the installer's file
the page says the checks have not run. The page checks nothing itself and the lines are shown only after the code."""

from __future__ import annotations

import html
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tb_common import firstrun
from tb_common import preflight as text
from tb_common.wording import check

from tests.console.test_firstrun import _box, _with_code

DETAIL = {
    "name_cert": "trialbox.hospital.test does not resolve here (OSError: Name or service not known)",
    "clock": "the kernel clock is not NTP-synchronised (timedatectl; on WSL2 the host's time sync task)",
    "backup_share": "/mnt/backup is not there (not mounted?) (1 target(s), 0 off the box)",
    "audit_share": "/srv/anchor is on the box's own disk",
    "feed": "/srv/feed holds no file yet",
    "mail_relay": "relay.hospital.test:587 did not answer (ConnectionRefusedError: refused)",
    "disk": "/opt/trialbox/deploy: 40 GiB free (5%), below 10%",
    "tpm_tang": "keys: KEK_BACKEND=tpm but this board has no usable TPM 2.0; disk unlock: not bound to Tang",
    "gpu_tier": "tier record rtx5090: the card is 'NVIDIA RTX A2000', the record names 5090 or RTX PRO 4500",
}


def _write(folder: Path, status: dict[str, str]) -> None:
    lines = [{"id": cid, "status": status.get(cid, "PASS"), "detail": DETAIL[cid]} for cid in text.IDS]
    firstrun.write_private(folder / text.FILE, text.document(lines, "2026-11-19T01:02:03+00:00"))


def _line(page: str, cid: str) -> str:
    m = re.search(rf'<li data-testid="pf-{cid}" data-status="(\w+)">(.*?)</li>', page, re.S)
    assert m, cid
    return m.group(0)


@pytest.mark.parametrize("cid", text.IDS)
def test_a_fixture_per_failing_check_shows_a_red_line_with_its_action_in_ja(tmp_path: Path, cid: str) -> None:
    b = _box(tmp_path)
    _write(b["folder"], {cid: "FAIL"})
    c = _with_code(b)
    page = c.get("/login/first-run/answers?lang=ja").text
    li = _line(page, cid)
    assert 'data-status="FAIL"' in li and '<p class="error">' in li  # red
    assert "未完了" in li and text.label(cid, "ja") in li
    assert f'data-testid="pf-action-{cid}">次にすること： {text.action(cid, "ja")}</p>' in li
    others = [x for x in text.IDS if x != cid]
    for other in others:  # the green lines: no action
        assert 'class="ok"' in _line(page, other) and "pf-action-" not in _line(page, other)
    assert not check(page)


def test_every_line_red_in_each_language(tmp_path: Path) -> None:
    b = _box(tmp_path)
    _write(b["folder"], dict.fromkeys(text.IDS, "FAIL"))
    c = _with_code(b)
    for lang in text.LANGS:
        page = c.get(f"/login/first-run/answers?lang={lang}").text
        assert page.count('data-status="FAIL"') == len(text.IDS)
        for cid in text.IDS:
            assert text.action(cid, lang) in html.unescape(_line(page, cid)), (lang, cid)
        assert "2026-11-19T01:02:03" in page


def test_a_warning_is_amber_with_its_action(tmp_path: Path) -> None:
    b = _box(tmp_path)
    _write(b["folder"], {"mail_relay": "WARN"})
    page = _with_code(b).get("/login/first-run/answers?lang=ja").text
    li = _line(page, "mail_relay")
    assert '<p class="warn">' in li and "要確認" in li and text.action("mail_relay", "ja") in li


def test_without_the_installer_s_file_the_page_says_the_checks_have_not_run(tmp_path: Path) -> None:
    b = _box(tmp_path)
    page = _with_code(b).get("/login/first-run/answers?lang=ja").text
    assert 'data-testid="firstrun-preflight-none"' in page and "まだ確認を行っていません" in page
    assert 'data-testid="pf-' not in page


def test_the_lines_are_not_shown_before_the_code(tmp_path: Path) -> None:
    b = _box(tmp_path)
    _write(b["folder"], dict.fromkeys(text.IDS, "FAIL"))
    page = TestClient(b["app"]).get("/login/first-run?lang=ja").text
    assert "firstrun-preflight" not in page and "/srv/anchor" not in page


def test_a_hostile_or_broken_file_is_shown_escaped_and_never_green(tmp_path: Path) -> None:
    """The file is the installer's, but the page trusts none of it: markup is escaped, an id the list does not know
    is red with the "call the supplier" action, a status the list does not know is red, broken files show nothing."""
    b = _box(tmp_path)
    doc = {"format": text.FORMAT, "at": "<script>alert(1)</script>",
           "lines": [{"id": "<script>x</script>", "status": "PASS", "detail": "<script>alert(2)</script>"},
                     {"id": "feed", "status": "<b>", "detail": "<img src=x onerror=alert(3)>"}, "notadict", 5, None]}  # fmt: skip
    firstrun.write_private(b["folder"] / text.FILE, doc)
    c = _with_code(b)
    page = c.get("/login/first-run/answers?lang=ja").text
    assert "<script>alert" not in page and "<img src=x" not in page and "<script>x" not in page
    assert page.count('data-status="FAIL"') == 2 and text.UNKNOWN["ja"] in html.unescape(page)
    for raw in ("{not json", "[]", '{"format":"tb-preflight/1","lines":"abc"}',
                '{"format":"tb-preflight/1","lines":{"a":1}}',
                '{"format":"tb-preflight/1","lines":[{"id":["x"],"status":{"a":1},"detail":{"k":"v"}}]}'):  # fmt: skip
        (b["folder"] / text.FILE).write_text(raw, encoding="utf-8")
        r = c.get("/login/first-run/answers?lang=ja")
        assert r.status_code == 200, (raw, r.text[-500:])


def test_a_check_that_timed_out_shows_the_time_out_action(tmp_path: Path) -> None:
    b = _box(tmp_path)
    lines = [{"id": "backup_share", "status": "FAIL", "detail": f"{text.TIMEOUT_PREFIX} after 20 s: no answer"}]
    firstrun.write_private(b["folder"] / text.FILE, text.document(lines, "2026-11-19T01:02:03+00:00"))
    li = html.unescape(_line(_with_code(b).get("/login/first-run/answers?lang=ja").text, "backup_share"))
    assert '<p class="error">' in li and text.TIMED_OUT["ja"] in li
