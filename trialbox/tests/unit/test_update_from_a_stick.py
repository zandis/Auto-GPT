"""10K-7 (D-1363, review 18 SO-7): an update from a stick inserted at the box, and the Japanese release note and
change-impact sheet in each bundle.

The card's proof is the drill (``tools/update_drill.py stick``): insert, verify, apply in the quiet hour, roll back,
through the operations runner the console's requests reach, on a frozen clock. The rest holds the parts: the bundle
maker's note and sheet (every change class stated), the verifier's report (a bundle without them is a warning, never
a refusal), and the runner's copy from the stick (only a regular file of a bundle's name; a different bundle of the
same name on the box is refused). The console's update page is ``tests/console/test_ops_pages.py``."""

from __future__ import annotations

import json
import os
import tarfile
from pathlib import Path
from typing import Any

import pytest

from tools import release_note, update_drill
from tools.sign_bundle import build, keygen
from tools.trialbox import ops as tb_ops
from tools.verify_update import main as verify_main
from tools.verify_update import summary, verify

pytestmark = pytest.mark.nodb
ROOT = Path(__file__).resolve().parents[2]


def test_the_drill_inserts_verifies_applies_in_the_quiet_hour_and_rolls_back(tmp_path: Path) -> None:
    out = update_drill.stick_drill(tmp_path)
    failed = [(name, detail) for name, ok, detail in out["checks"] if not ok]
    assert out["ok"] and not failed, failed
    names = " | ".join(name for name, _, _ in out["checks"])
    for step in ("insert:", "verify:", "quiet hour", "roll back:", "change classes CC1 to CC6"):
        assert step in names, step
    assert len(out["checks"]) == 12


def test_the_drill_runs_from_the_command_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TB_TZ", os.environ.get("TB_TZ") or "UTC")  # main adopts the site's zone into the process
    assert update_drill.main(["stick", "--dir", str(tmp_path / "drill")]) == 0
    assert "update-from-a-stick drill PASSED" in capsys.readouterr().out


# ------------------------------------------------------------------------------------------------ the bundle maker
def _source(**edit: Any) -> dict[str, Any]:
    src: dict[str, Any] = json.loads(json.dumps(update_drill.STICK_SOURCE))
    src.update(edit)
    return src


def test_the_next_release_source_states_every_change_class() -> None:
    assert release_note.source_problems(release_note.load_source(release_note.SOURCE)) == []
    assert release_note.main(["check"]) == 0


@pytest.mark.parametrize(
    ("edit", "problem"),
    [
        ({"changes": {k: {"changed": False} for k in ("CC1", "CC2", "CC4", "CC5", "CC6")}}, "changes.CC3: say changed"),
        ({"changes": {**update_drill.STICK_SOURCE["changes"], "CC2": {"changed": True}}}, "changes.CC2: changed, so"),
        ({"changes": {**update_drill.STICK_SOURCE["changes"], "CC7": {"changed": False}}}, "CC7: not a change class"),
        ({"title_ja": "Release notes"}, "title_ja: Japanese text is required"),
        ({"impact": {"downtime_minutes": -1}}, "downtime_minutes"),
        ({"format": "notes/0"}, "format is"),
    ],
)
def test_a_source_that_leaves_a_class_or_the_japanese_out_stops_the_bundle(
    tmp_path: Path, edit: dict[str, Any], problem: str
) -> None:
    f = tmp_path / "note.yaml"
    f.write_text(json.dumps(_source(**edit), ensure_ascii=False), encoding="utf-8")
    assert any(problem in p for p in release_note.source_problems(release_note.load_source(f)))
    with pytest.raises(release_note.NoteError, match="note.yaml"):
        release_note.build(f, "B1", 1, tmp_path / "out")
    assert not (tmp_path / "out").exists()
    assert release_note.main(["build", "--source", str(f), "--id", "B1", "--release-seq", "1",
                              "--out-dir", str(tmp_path / "out")]) == 1  # fmt: skip


def test_build_writes_the_japanese_note_and_a_sheet_listing_every_class(tmp_path: Path) -> None:
    f = tmp_path / "note.yaml"
    f.write_text(json.dumps(_source(), ensure_ascii=False), encoding="utf-8")
    note, imp = release_note.build(f, "2026.12-1", 7, tmp_path / "out")
    sheet = json.loads(imp.read_text(encoding="utf-8"))
    assert sheet["format"] == release_note.IMPACT_FORMAT and sheet["bundle_id"] == "2026.12-1"
    assert [c["class"] for c in sheet["classes"]] == list(release_note.CLASSES)
    assert [c["class"] for c in sheet["classes"] if c["changed"]] == ["CC4"] and sheet["backup_first"] is True
    text = note.read_text(encoding="utf-8")
    assert text.startswith("# ドリル用リリース") and "release_seq 7" in text
    assert all(f"| {cc} | {name} |" in text for cc, name in release_note.CLASSES.items())
    assert "約 20 分" in text and "適用の翌朝" in text


def test_make_bundle_requires_the_note_and_carries_both_files() -> None:
    sh = (ROOT / "tools" / "make_bundle.sh").read_text(encoding="utf-8")
    first_image = sh.index('echo "==> images"')
    assert sh.index("-m tools.release_note build") < first_image  # refused before minutes of image export
    assert "docs/releases/next-release.ja.yaml" in sh and "--release-note) NOTE_SRC=" in sh
    assert '"other:$STAGE/note/RELEASE-NOTE.ja.md=RELEASE-NOTE.ja.md"' in sh
    assert '"other:$STAGE/note/CHANGE-IMPACT.json=CHANGE-IMPACT.json"' in sh
    assert sh.index("CHANGE-IMPACT.json=CHANGE-IMPACT.json") < sh.index("-m tools.release build")  # in release.json


# ------------------------------------------------------------------------------------------------ the verifier
def _plain_bundle(tmp: Path, items: list[tuple[str, Path, str]] | None = None) -> tuple[Path, Path]:
    priv, pub = keygen(tmp / "k")
    (tmp / "x.txt").write_text("payload\n", encoding="utf-8")
    out = tmp / "plain.tar"
    build(priv, "B1", items or [("other", tmp / "x.txt", "x.txt")], out)
    return out, pub


def test_verify_accepts_a_bundle_without_a_note_and_warns(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bundle, pub = _plain_bundle(tmp_path)
    rn = summary(verify(bundle, pub))["release_note"]
    assert rn["note"] is False and rn["impact"] is False and len(rn["warnings"]) == 2
    assert verify_main([str(bundle), "--pubkey", str(pub)]) == 0  # accepted: it informs, it decides nothing
    err = capsys.readouterr().err
    assert "WARNING: no RELEASE-NOTE.ja.md in this bundle" in err and "WARNING: no CHANGE-IMPACT.json" in err


def test_verify_reports_the_note_and_the_changed_classes(tmp_path: Path) -> None:
    priv, pub = keygen(tmp_path / "k")
    bundle = update_drill.stick_bundle(tmp_path, priv, "2026.12-1", 3)
    rn = summary(verify(bundle, pub))["release_note"]
    assert rn == {"note": True, "impact": True, "changed": ["CC4"], "warnings": []}


def test_a_sheet_that_does_not_list_the_classes_is_a_warning_and_not_shown(tmp_path: Path) -> None:
    bad = tmp_path / release_note.IMPACT
    bad.write_text(json.dumps({"format": release_note.IMPACT_FORMAT, "classes": [{"class": "CC1", "changed": True}]}))
    (tmp_path / "n.md").write_text("# 合成のノート\n", encoding="utf-8")
    bundle, pub = _plain_bundle(tmp_path, [("other", bad, release_note.IMPACT),
                                           ("other", tmp_path / "n.md", release_note.NOTE)])  # fmt: skip
    rn = summary(verify(bundle, pub))["release_note"]
    assert rn["note"] is True and rn["impact"] is False
    assert rn["warnings"] == ["CHANGE-IMPACT.json does not list the change classes CC1 to CC6"]


def test_read_from_bundle_never_raises_on_a_bundle_that_is_not_one(tmp_path: Path) -> None:
    junk = tmp_path / "junk.tar"
    junk.write_bytes(b"not a tar")
    got = release_note.read_from_bundle(junk)
    assert got["note_ja"] is None and got["impact"] is None and got["warnings"]
    with tarfile.open(tmp_path / "empty.tar", "w"):
        pass
    assert release_note.read_from_bundle(tmp_path / "empty.tar")["warnings"]


# ------------------------------------------------------------------------------------------------ the runner
class _Runner(tb_ops.OpsRunner):
    def audit(self, res: Any) -> None:
        return None


def _runner(tmp: Path, verified: bool = True) -> tuple[_Runner, list[list[str]]]:
    calls: list[list[str]] = []

    def run(argv: Any, timeout: int | None) -> str:
        calls.append(list(argv))
        if not verified:
            raise tb_ops.OpsFailed("exit 1: REJECTED: signature does not verify with a trusted vendor key")
        return "verified\n"

    env = {"TB_UPDATE_STICK": str(tmp / "stick"), "TB_UPDATE_INCOMING": str(tmp / "incoming")}
    return _Runner(tb_ops.Box("compose", tmp / "deploy", env, run), tb_ops.OpsDir(tmp / "ops")), calls


def _check(r: _Runner, name: str) -> dict[str, Any]:
    rid = r.ops.submit("update_check", "console:admin", {"bundle": name, "from": "stick"})
    r.run_pending()
    res = r.ops.result(rid)
    assert res is not None
    return res


def test_no_stick_is_said_and_nothing_is_copied(tmp_path: Path) -> None:
    r, calls = _runner(tmp_path)
    st = r.write_status()
    assert st["stick"] == {"path": str(tmp_path / "stick"), "mounted": False, "bundles": []}
    res = _check(r, "trialbox-1.tar")
    assert res["ok"] is False and "is it inserted?" in res["summary"] and calls == []
    assert tb_ops.Box("compose", tmp_path, {}).stick() == Path(tb_ops.STICK_DEFAULT)


def test_a_bundle_on_the_stick_is_copied_verified_and_its_note_kept(tmp_path: Path) -> None:
    priv, _pub = keygen(tmp_path / "k")
    bundle = update_drill.stick_bundle(tmp_path, priv, "2026.12-1", 3)
    (tmp_path / "stick").mkdir()
    (tmp_path / "stick" / bundle.name).write_bytes(bundle.read_bytes())
    (tmp_path / "stick" / f"{bundle.name}.sha256").write_text("x\n")
    r, calls = _runner(tmp_path)
    assert r.write_status()["stick"]["bundles"][0]["sidecar"] is True
    res = _check(r, bundle.name)
    assert res["ok"] is True and "copied from the update stick" in res["lines"][0]
    assert calls[0][-1] == "--dry-run" and calls[0][-2] == str(tmp_path / "incoming" / bundle.name)
    st = json.loads((tmp_path / "ops" / "status.json").read_text(encoding="utf-8"))
    assert st["notes"][bundle.name]["bundle_id"] == "2026.12-1" and "ドリル用" in st["notes"][bundle.name]["note_ja"]
    assert _check(r, bundle.name)["lines"][0].endswith("not copied again")  # the same file: kept
    os.utime(tmp_path / "incoming" / bundle.name, (1, 1))  # the file on the box changed since: its note is not shown
    assert bundle.name not in r.write_status()["notes"]


def test_a_different_bundle_of_the_same_name_on_the_box_is_refused(tmp_path: Path) -> None:
    (tmp_path / "stick").mkdir()
    (tmp_path / "incoming").mkdir()
    (tmp_path / "stick" / "trialbox-1.tar").write_bytes(b"from the stick")
    (tmp_path / "incoming" / "trialbox-1.tar").write_bytes(b"already staged")
    r, calls = _runner(tmp_path)
    res = _check(r, "trialbox-1.tar")
    assert res["ok"] is False and "a different bundle named trialbox-1.tar" in res["summary"] and calls == []
    assert (tmp_path / "incoming" / "trialbox-1.tar").read_bytes() == b"already staged"


def test_a_refused_bundle_from_the_stick_is_not_left_on_the_box(tmp_path: Path) -> None:
    (tmp_path / "stick").mkdir()
    (tmp_path / "stick" / "trialbox-1.tar").write_bytes(b"not signed")
    r, _calls = _runner(tmp_path, verified=False)
    res = _check(r, "trialbox-1.tar")
    assert res["ok"] is False and "REJECTED" in res["summary"]
    assert not (tmp_path / "incoming" / "trialbox-1.tar").exists() and not list((tmp_path / "incoming").glob(".*"))
    assert (tmp_path / "stick" / "trialbox-1.tar").read_bytes() == b"not signed"  # the stick is only read


@pytest.mark.parametrize(("args", "why"), [({"bundle": "trialbox-1.tar", "from": "usb"}, "from is 'usb'"),
                                           ({"bundle": "../../etc/passwd", "from": "stick"}, "not a bundle's name")])  # fmt: skip
def test_the_source_and_the_name_are_checked(tmp_path: Path, args: dict[str, str], why: str) -> None:
    (tmp_path / "stick").mkdir()
    r, calls = _runner(tmp_path)
    rid = r.ops.submit("update_check", "console:admin", args)
    r.run_pending()
    res = r.ops.result(rid)
    assert res is not None and res["ok"] is False and why in res["summary"] and calls == []


def test_the_status_says_the_quiet_hour_and_the_setting_that_does_not_read(tmp_path: Path) -> None:
    r, _ = _runner(tmp_path)
    q = r.write_status()["quiet"]
    assert q == {"at": "05:00", "hours": "2", "zone": "", "wait_h": tb_ops.QUIET_WAIT_H, "bad": "TB_TZ"}
    r.box.env.update(update_drill.STICK_ENV)
    assert r.write_status()["quiet"]["bad"] == "" and r.write_status()["quiet"]["zone"] == "Asia/Tokyo"


# ------------------------------------------------------- review C: a file name on the stick is checked before use
GOOD = "trialbox-2026.12-1.tar"
BAD_NAMES = {
    "newline at the end": "trialbox-1.tar\n",
    "newline inside": "trialbox-1\n.tar",
    "carriage return": "trialbox-1\r.tar",
    "a control character (NUL-like)": "trialbox-\x01.tar",
    "DEL": "trialbox-\x7f.tar",
    "two dots": "trialbox..1.tar",
    "leading dash": "-rf.tar",
    "leading dot": ".hidden.tar",
    "not ASCII": "trialbox-１.tar",
    "very long": "t" * 200 + ".tar",
}


@pytest.mark.parametrize("name", list(BAD_NAMES.values()), ids=list(BAD_NAMES))
def test_a_bad_name_is_not_a_bundle_name(name: str) -> None:
    assert tb_ops.BUNDLE.match(name) is None
    assert tb_ops.BUNDLE.match(GOOD) is not None


def _stick_with_bad_names(tmp: Path) -> Path:
    stick = tmp / "stick"
    stick.mkdir()
    (stick / GOOD).write_bytes(b"a bundle")
    for name in BAD_NAMES.values():
        (stick / name).write_bytes(b"x")
    outside = tmp / "outside.tar"
    outside.write_bytes(b"a file outside the stick")
    (stick / "link-outside.tar").symlink_to(outside)
    (stick / f"{GOOD}.sha256").unlink(missing_ok=True)
    (stick / "folder.tar").mkdir()
    return stick


def test_the_stick_lists_only_regular_files_with_a_bundle_name(tmp_path: Path) -> None:
    _stick_with_bad_names(tmp_path)
    r, _ = _runner(tmp_path)
    st = r.write_status()
    assert [b["name"] for b in st["stick"]["bundles"]] == [GOOD]
    text = (tmp_path / "ops" / "status.json").read_text(encoding="utf-8")
    for name in [*BAD_NAMES.values(), "link-outside.tar", "folder.tar"]:
        assert json.dumps(name)[1:-1] not in text, repr(name)


def test_a_linked_sidecar_does_not_count(tmp_path: Path) -> None:
    stick = _stick_with_bad_names(tmp_path)
    (stick / f"{GOOD}.sha256").symlink_to(tmp_path / "outside.tar")
    r, _ = _runner(tmp_path)
    assert r.write_status()["stick"]["bundles"][0]["sidecar"] is False


def test_more_than_fifty_other_files_do_not_hide_a_bundle(tmp_path: Path) -> None:
    stick = tmp_path / "stick"
    stick.mkdir()
    for i in range(60):
        (stick / f"0-not-a-bundle-{i:02}\n.tar").write_bytes(b"x")
    (stick / "zz-trialbox.tar").write_bytes(b"a bundle")
    r, _ = _runner(tmp_path)
    assert [b["name"] for b in r.write_status()["stick"]["bundles"]] == ["zz-trialbox.tar"]


@pytest.mark.parametrize("name", [*BAD_NAMES.values(), "link-outside.tar", "folder.tar"],
                         ids=[*BAD_NAMES, "a link to a file outside the stick", "a folder"])  # fmt: skip
def test_a_bad_file_on_the_stick_is_never_copied_or_passed_to_a_command(tmp_path: Path, name: str) -> None:
    _stick_with_bad_names(tmp_path)
    r, calls = _runner(tmp_path)
    res = _check(r, name)
    assert res["ok"] is False and calls == []
    assert not (tmp_path / "incoming").exists() or list((tmp_path / "incoming").iterdir()) == []
    assert "\n" not in res["summary"] and "\r" not in res["summary"] and "\x01" not in res["summary"]


# ---------------------------------------------- review B: the status file is read bounded, and unreadable is said
def _status_file(tmp: Path, kind: str) -> Path:
    p = tmp / "ops" / "status.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    if kind == "64 KiB + 1":
        head = b'{"at": "x", "pad": "'
        p.write_bytes(head + b"a" * (tb_ops.MAX_JSON + 1 - len(head) - 2) + b'"}')
        assert p.stat().st_size == tb_ops.MAX_JSON + 1
    elif kind == "a FIFO":
        os.mkfifo(p)
    elif kind == "a folder":
        p.mkdir()
    elif kind == "not UTF-8":
        p.write_bytes(b'{"at": "\xff\xfe"}')
    elif kind == "nested past the recursion limit":
        p.write_bytes(b'{"a": ' + b"[" * 30000 + b"]" * 30000 + b"}")
        assert p.stat().st_size <= tb_ops.MAX_JSON
    elif kind == "nested deeper than the runner writes":
        p.write_bytes(b'{"a": ' + b"[" * 40 + b"]" * 40 + b"}")
    elif kind == "not an object":
        p.write_bytes(b"[1, 2]")
    elif kind == "a link":
        (tmp / "elsewhere.json").write_text('{"at": "x"}')
        p.symlink_to(tmp / "elsewhere.json")
    return p


STATUS_KINDS = ["64 KiB + 1", "a FIFO", "a folder", "not UTF-8", "nested past the recursion limit",
                "nested deeper than the runner writes", "not an object", "a link"]  # fmt: skip


@pytest.mark.timeout(20)
@pytest.mark.parametrize("kind", STATUS_KINDS)
def test_a_status_file_that_is_not_a_small_object_is_unreadable_never_a_crash(tmp_path: Path, kind: str) -> None:
    p = _status_file(tmp_path, kind)
    assert tb_ops.OpsDir(tmp_path / "ops").status() is None  # the old reader raised RecursionError on deep nesting
    assert tb_ops.read_json_state(p) == (None, "unreadable")
    assert tb_ops.OpsDir(tmp_path / "ops").status_state() == (None, "unreadable")


def test_a_missing_status_is_missing_and_a_good_one_reads(tmp_path: Path) -> None:
    ops = tb_ops.OpsDir(tmp_path / "ops")
    assert ops.status_state() == (None, "missing")
    p = tmp_path / "ops" / "status.json"
    p.parent.mkdir(parents=True)
    p.write_text('{"at": "2026-11-19T00:00:00+00:00"}', encoding="utf-8")
    assert ops.status_state() == ({"at": "2026-11-19T00:00:00+00:00"}, "")


def test_a_status_with_long_release_notes_stays_readable(tmp_path: Path) -> None:
    r, _ = _runner(tmp_path)
    big = {f"trialbox-{i}.tar": {"bundle_id": f"2026.12-{i}", "note_ja": "長い説明。" * 4000, "impact": None,
                                 "warnings": []} for i in range(3)}  # fmt: skip
    r._notes = lambda incoming: json.loads(json.dumps(big))  # type: ignore[method-assign]
    st = r.write_status()
    p = tmp_path / "ops" / "status.json"
    assert p.stat().st_size <= tb_ops.MAX_JSON
    got, why = r.ops.status_state()
    assert why == "" and got is not None and got["notes"]["trialbox-0.tar"]["note_trimmed"] is True
    assert st["notes"]["trialbox-0.tar"]["note_ja"] is None
    huge = {f"trialbox-{i}.tar": {"bundle_id": "x" * 2000, "warnings": ["w" * 2000] * 4} for i in range(20)}
    r._notes = lambda incoming: json.loads(json.dumps(huge))  # type: ignore[method-assign]
    st = r.write_status()
    assert p.stat().st_size <= tb_ops.MAX_JSON and st["notes"] == {} and st["notes_trimmed"] is True
