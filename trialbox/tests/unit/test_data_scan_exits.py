"""NEW-B-46 (D-747): the exits scan for English phone numbers; the repository scan does not.

D-744's review: ``tools/data_scan`` is the scrub of every exit of the box (a support bundle before it leaves, the
console's comment export, the demo guard's scan of stored input), and it knew Taiwanese and Japanese phones only:
``Contact 555-0133`` passed a support bundle's scrub. The integrator's answer (#593): the English form in exit-path
mode only, no allow-list entries (the repository's tests and evaluation sets hold synthetic English phones by
design). Synthetic numbers only."""

from __future__ import annotations

from pathlib import Path

from tools import data_scan as ds

LINE = "Daughter's mobile 555-0133; call after six."


def test_the_english_phone_is_an_exit_pattern_only() -> None:
    assert "en_phone" not in {p.id for p in ds.load_patterns()}  # the repository scan, as before
    exits = ds.load_patterns(exits=True)
    assert "en_phone" in {p.id for p in exits}
    assert {p.id for p in ds.load_patterns()} <= {p.id for p in exits}  # an exit scans for everything else too
    assert ds.scan_text(LINE, "x", ds.load_patterns(), ds.Allow({}, [])) == []
    assert {h.pattern for h in ds.scan_text(LINE, "x", exits, ds.Allow({}, []))} == {"en_phone"}


def test_the_comment_export_withholds_an_english_phone() -> None:
    from console.feedback import _scanner

    scan = _scanner()
    assert scan is not None and "en_phone" in scan(LINE)


def test_the_support_bundle_removes_the_line() -> None:
    from tools.support_bundle import Bundle, clean_lines

    b = Bundle(members={"logs/app.log": f"first line\n{LINE}\nlast line\n"})
    said: list[str] = []
    clean_lines(b, said.append)
    assert "555-0133" not in b.members["logs/app.log"] and "first line" in b.members["logs/app.log"]
    assert any("en_phone" in s for s in said), said


def test_the_demo_guard_finds_it_in_stored_input(tmp_path: Path) -> None:
    from console.demo_guard import scan_stored

    (tmp_path / "upload.txt").write_text(LINE + "\n", encoding="utf-8")
    assert "en_phone" in {h.pattern for h in scan_stored([tmp_path])}


def test_the_bundles_last_look_uses_the_exit_patterns() -> None:
    """The finished archive is scanned once more before it leaves (D-723): with the exits' patterns too."""
    import ast
    import inspect

    from tools import support_bundle

    src = inspect.getsource(support_bundle)
    calls = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call) and ast.unparse(n.func) == "ds.run"]
    assert calls and all(any(k.arg == "patterns" for k in c.keywords) or len(c.args) >= 3 for c in calls)
    loads = [
        n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call) and ast.unparse(n.func) == "ds.load_patterns"
    ]
    assert loads and all(any(k.arg == "exits" for k in c.keywords) for c in loads)


# ---------------------------------------------------------------------------------------------- review (D-747)
LOG_LINES = [  # ordinary log and data text: no phone in it (the exits removed or withheld each)
    "job 001 2026-11-15 started; worker-001 2026-11-15 ok; batch 002 (2026-11-15)",
    "request_id=0012345678 seq 0012345678 file /data/001082795.xlsx",
    "call 1234567 ns; contact 2500000 rows; home: 1234567; HOME 4567890; Number is 7654321",
    "T: 2400000 ms; t: 1234567; m: 7654321",
    "tz +0800 2026-11-15 and +1 2026 11 15",
]


def test_ordinary_log_lines_are_no_phone() -> None:
    exits = ds.load_patterns(exits=True)
    for line in LOG_LINES:
        assert [h for h in ds.scan_text(line, "x", exits, ds.Allow({}, [])) if h.pattern == "en_phone"] == [], line


def test_the_phones_of_d744_are_still_found() -> None:
    from tests.unit.test_phi_english_phones import PHONES

    exits = ds.load_patterns(exits=True)
    for text, _phone in PHONES:
        assert "en_phone" in {h.pattern for h in ds.scan_text(text, "x", exits, ds.Allow({}, []))}, text


def test_the_command_line_scans_as_an_exit_when_asked(tmp_path: Path, capsys: object) -> None:
    f = tmp_path / "ticket.txt"
    f.write_text(LINE + "\n", encoding="utf-8")
    assert ds.main([str(f)]) == 0  # the repository's rules: as before
    assert ds.main(["--exits", str(f)]) == 2  # a file that leaves the box: the exits' rules


def test_the_bundles_last_look_finds_an_english_phone(tmp_path: Path) -> None:
    import io
    import tarfile

    from tools.support_bundle import last_look

    tgz = tmp_path / "support.tgz"
    data = (LINE + "\n").encode()
    with tarfile.open(tgz, "w:gz") as tar:
        info = tarfile.TarInfo("support/logs/app.log")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    assert "en_phone" in {h.pattern for h in last_look(tgz)}


def test_the_share_report_scans_as_an_exit() -> None:
    from tools import mapping_check

    scan = mapping_check._scan()
    assert scan is not None and scan(LINE)
