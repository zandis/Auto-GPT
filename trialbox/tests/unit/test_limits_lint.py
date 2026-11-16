"""The limits lint (T-687, D-471, D-534; OD-10): every `timeout=` (whatever its length) and every `LIMIT` / `limit=` literal in
`services/` has a line with a reason in `tools/limits_allow.yaml`; a new one fails, and so does a stale line."""

from __future__ import annotations

from pathlib import Path

from tools import limits_lint as ll

ROOT = Path(__file__).resolve().parents[2]


def _lits(src: str) -> list[tuple[str, str]]:
    return [(x.kind, x.value) for x in ll.scan_source(src, "services/x.py")]


def test_the_services_tree_is_clean_against_the_allow_list() -> None:
    problems = ll.check(ll.scan(ROOT), ll.load_allow())
    assert problems == [], "\n".join(problems)


def test_every_line_names_its_finding_card_or_why_it_is_not_a_cut() -> None:
    for e in ll.load_allow():
        assert ll._REASON.search(e.reason), e
        if e.kind == "timeout" and "not a cut" not in e.reason:
            assert "F-" in e.reason and "T-" in e.reason, e  # a growing time limit names its finding and card


def test_a_new_timeout_of_600_without_a_line_fails(tmp_path: Path) -> None:
    """The row's acceptance test: a new `timeout=600` without an allow-list line fails the lint."""
    svc = tmp_path / "services" / "newsvc"
    svc.mkdir(parents=True)
    (svc / "client.py").write_text("import httpx\nc = httpx.Client(timeout=600)\n", encoding="utf-8")
    found = ll.scan(tmp_path)
    assert [(x.path, x.line, x.kind, x.value) for x in found] == [("services/newsvc/client.py", 2, "timeout", "600")]
    problems = ll.check(found, [])
    assert len(problems) == 1 and "new fixed timeout 600" in problems[0] and "client.py:2" in problems[0]
    ok = ll.Entry("services/newsvc/client.py", "timeout", "600", 1, "F-99: a test line; T-999")
    assert ll.check(found, [ok]) == []
    # a second one in the same file is new again
    (svc / "client.py").write_text("import httpx\nc = httpx.Client(timeout=600)\nd = httpx.Client(timeout=600)\n")
    assert any("2 found, 1 allowed" in p for p in ll.check(ll.scan(tmp_path), [ok]))
    (tmp_path / "empty.yaml").write_text("allow: []\n")
    assert ll.main(["--allow", str(tmp_path / "empty.yaml")]) == 1  # the real tree against an empty list: red
    assert ll.main([]) == 0


def test_a_stale_line_or_a_line_without_a_reason_fails() -> None:
    gone = ll.Entry("services/lake/client.py", "timeout", "9999", 1, "F-01; T-690")
    assert any("found 0" in p for p in ll.check([], [gone]))
    bare = ll.Entry("services/x.py", "limit", "5", 1, "because")
    found = [ll.Literal("services/x.py", 1, "limit", "5")]
    assert any("has no reason" in p for p in ll.check(found, [bare]))
    assert any(
        "listed twice" in p for p in ll.check(found, [ll.Entry("services/x.py", "limit", "5", 1, "not a cut")] * 2)
    )


def test_what_counts_and_what_does_not() -> None:
    src = '''
"""Module text: LIMIT 5 and timeout=900 in prose do not count."""
import httpx, subprocess

def f(base, timeout: float = 330, limit: int = 500, read_timeout=120, short=30):
    """SELECT x FROM t LIMIT 7 in a docstring does not count."""
    subprocess.run(["x"], timeout=1800)
    httpx.Client(timeout=httpx.Timeout(600.0, connect=5))
    httpx.Client(timeout=30)  # a short wait counts too (NEW-B-12, D-534): it is listed with why it is not a cut
    rows = db.find(limit=200)
    n = min(limit, 1000)
    q = "SELECT * FROM jobs ORDER BY at DESC LIMIT 1"
    words = "the limit 3 of a sentence"
    return q
'''
    assert sorted(_lits(src)) == sorted(
        [
            ("timeout", "330"),
            ("limit", "500"),
            ("timeout", "120"),
            ("timeout", "1800"),
            ("timeout", "600"),
            ("timeout", "30"),
            ("limit", "200"),
            ("limit", "1000"),
            ("limit", "1"),
        ]
    )


def test_the_list_command_prints_allow_lines(capsys: object) -> None:
    assert ll.main(["--list"]) == 0
    out = capsys.readouterr().out  # type: ignore[attr-defined]
    assert out.startswith("allow:\n") and "services/lake/client.py, kind: timeout, value: 330" in out


def test_a_wait_of_two_seconds_without_a_line_fails_too(tmp_path: Path) -> None:
    """NEW-B-12 (D-534; PERF-002, PLAN-012): the lint had a floor of 60 s, so a 45 s limit around a model call or
    a 10 s limit around a call that grows was never listed. Every fixed wait is on the list."""
    svc = tmp_path / "services" / "x"
    svc.mkdir(parents=True)
    (svc / "a.py").write_text("import threading\n\ndef f(e: threading.Event) -> None:\n    e.wait(timeout=2.0)\n")
    found = ll.scan(tmp_path)
    assert [(x.kind, x.value) for x in found] == [("timeout", "2")]
    assert any("new fixed timeout 2" in p for p in ll.check(found, []))


def test_a_four_digit_decision_number_is_a_reason() -> None:
    """A decision number may have four digits (the owner's rulings from D-1020); no reference is still no reason."""
    found = [ll.Literal("services/x.py", 1, "limit", "5")]
    cited = ll.Entry("services/x.py", "limit", "5", 1, "D-1021")
    assert ll._REASON.search(cited.reason)
    assert ll.check(found, [cited]) == []
    bare = ll.Entry("services/x.py", "limit", "5", 1, "the owner said so")
    assert any("has no reason" in p for p in ll.check(found, [bare]))
