"""10K-7 (D-1363, review 18 SO-7): an update from a stick inserted at the box, and the Japanese release note and
change-impact sheet in each bundle.

The card's proof is the drill (``tools/update_drill.py stick``): insert, verify, apply in the quiet hour, roll back,
through the operations runner the console's requests reach, on a frozen clock. The rest holds the parts: the bundle
maker's note and sheet (every change class stated), the verifier's report (a bundle without them is a warning, never
a refusal), and the runner's copy from the stick (only a regular file of a bundle's name; a different bundle of the
same name on the box is refused). The console's update page is ``tests/console/test_ops_pages.py``."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import sys
import sysconfig
import tarfile
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from tools import release_note, update_drill
from tools.sign_bundle import build, keygen
from tools.trialbox import ops as tb_ops
from tools.verify_update import Rejected, summary, verify
from tools.verify_update import main as verify_main

pytestmark = pytest.mark.nodb
ROOT = Path(__file__).resolve().parents[2]


def test_the_drill_inserts_verifies_applies_in_the_quiet_hour_and_rolls_back(tmp_path: Path) -> None:
    out = update_drill.stick_drill(tmp_path)
    failed = [(name, detail) for name, ok, detail in out["checks"] if not ok]
    assert out["ok"] and not failed, failed
    names = " | ".join(name for name, _, _ in out["checks"])
    for step in ("insert:", "verify:", "quiet hour", "roll back:", "change classes CC1 to CC6"):
        assert step in names, step
    assert len(out["checks"]) == 13


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
    assert "docs/releases/next-release.ja.yaml" in sh and 'NOTE_SRC="$2"' in sh
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


def _signed_with_the_note(tmp: Path) -> tuple[Path, Path]:
    """A bundle laid out as tools/make_bundle.sh lays one out: the note and the sheet built by tools/release_note.py
    from this checkout's next-release source, then signed by the real signer with the other payloads."""
    priv, pub = keygen(tmp / "k")
    note, imp = release_note.build(release_note.SOURCE, "2026.12-1", 4, tmp / "note")
    (tmp / "rules.json").write_text('{"synthetic": true}\n', encoding="utf-8")
    items = [("other", tmp / "rules.json", "rulesets/rules.json"), ("other", ROOT / "NOTICE", "NOTICE"),
             ("other", note, release_note.NOTE), ("other", imp, release_note.IMPACT)]  # fmt: skip
    out = tmp / "trialbox-2026.12-1.tar"
    build(priv, "2026.12-1", items, out, release_seq=4)
    return out, pub


def _rehearsal_verifier_modules() -> list[str]:
    """The modules the box-run rehearsal copies into its build checkout beside the verifier (its b06 runs
    tools/verify_update.py there): read from the rehearsal itself, so this test follows it."""
    sh = (ROOT / "tests" / "rehearsal" / "box-run" / "rehearse-box-run.sh").read_text(encoding="utf-8")
    line = sh[sh.index('cp "$ROOT/tools/verify_update.py"') :].split('"$r/trialbox/tools/"')[0]
    return re.findall(r'"\$ROOT/tools/(\w+\.py)"', line)


def test_the_verifier_with_only_its_own_modules_verifies_a_bundle_with_the_note(tmp_path: Path) -> None:
    """Train 100: b06 of the box-run's build ran tools/verify_update.py in a checkout holding only the verifier's own
    modules, and the verifier's report of the note imported tools/release_note.py: exit 1 on a correctly signed
    bundle. Run the same way here, in a python that sees no other module of this checkout (no site: the venv's
    editable install would find this checkout's tools/), it verifies and reports the note and the sheet."""
    bundle, pub = _signed_with_the_note(tmp_path)
    mods = _rehearsal_verifier_modules()
    assert "verify_update.py" in mods and "release_note.py" not in mods, mods
    tools = tmp_path / "ck" / "trialbox" / "tools"
    tools.mkdir(parents=True)
    for m in mods:
        (tools / m).write_bytes((ROOT / "tools" / m).read_bytes())
    (tools / "__init__.py").write_text("")
    libs = sorted({sysconfig.get_paths()["purelib"], sysconfig.get_paths()["platlib"]})  # cryptography, nothing else
    code = f"import runpy, sys; sys.path += {libs!r}; sys.argv = sys.argv[1:]; runpy.run_path(sys.argv[0], run_name='__main__')"
    run = subprocess.run([sys.executable, "-S", "-c", code, str(tools / "verify_update.py"), str(bundle),
                          "--pubkey", str(pub), "--stage", str(tmp_path / "stage")],
                         cwd=tmp_path, capture_output=True, text=True, check=False, env={"PATH": os.environ["PATH"]})  # fmt: skip
    assert run.returncode == 0, run.stderr
    got = json.loads(run.stdout)["release_note"]
    assert got["note"] is True and got["impact"] is True and got["warnings"] == [], got
    with tarfile.open(bundle) as tf:
        names = tf.getnames()
    assert f"files/{release_note.NOTE}" in names and f"files/{release_note.IMPACT}" in names


def _rewrite(bundle: Path, out: Path, change: dict[str, bytes]) -> None:
    with tarfile.open(bundle) as src, tarfile.open(out, "w", format=tarfile.PAX_FORMAT) as dst:
        for m in src.getmembers():
            data = change.get(m.name) or src.extractfile(m).read()  # type: ignore[union-attr]
            m.size = len(data)
            dst.addfile(m, io.BytesIO(data))


@pytest.mark.parametrize("how", ["same size", "longer"])
def test_a_note_altered_after_signing_fails_verification(
    tmp_path: Path, how: str, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle, pub = _signed_with_the_note(tmp_path)
    with tarfile.open(bundle) as tf:
        body = tf.extractfile(f"files/{release_note.NOTE}").read()  # type: ignore[union-attr]
    assert b"CC4" in body
    altered = body.replace(b"CC4", b"CC9", 1) if how == "same size" else body + "追記\n".encode()
    bad = tmp_path / "altered.tar"
    _rewrite(bundle, bad, {f"files/{release_note.NOTE}": altered})
    with pytest.raises(Rejected):
        verify(bad, pub)
    assert verify_main([str(bad), "--pubkey", str(pub)]) == 1
    assert "REJECTED" in capsys.readouterr().err
    assert verify_main([str(bundle), "--pubkey", str(pub)]) == 0  # the bundle as signed still verifies


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
    assert r.write_status()["stick"] is None  # the third review, M2: not read until a listing is asked for
    st = {"stick": _listing(r)}
    assert st["stick"] == {"path": str(tmp_path / "stick"), "mounted": False, "bundles": [], "cut": False, "refused": 0}
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
    assert _listing(r)["bundles"][0]["sidecar"] is True
    res = _check(r, bundle.name)
    assert res["ok"] is True and "copied from the update stick" in res["lines"][0]
    # H1/H3 (D-1363): apply_update.sh verifies the runner's private copy of the file it hashed, gone afterwards
    held = tmp_path / "deploy" / "updates" / tb_ops.HELD_DIR
    assert calls[0][-1] == "--dry-run" and Path(calls[0][-2]).name == bundle.name
    assert Path(calls[0][-2]).parent.parent == held and not list(held.iterdir())
    assert stat.S_IMODE(held.stat().st_mode) == 0o700
    st = json.loads((tmp_path / "ops" / "status.json").read_text(encoding="utf-8"))
    sha = hashlib.sha256(bundle.read_bytes()).hexdigest()
    assert st["verified"][bundle.name]["sha256"] == sha and st["verified"][bundle.name]["bundle_id"] == "2026.12-1"
    assert "notes" not in st and "note_ja" not in json.dumps(st)  # the note stays out of the status
    state, rec = r.ops.note_record(bundle.name, sha)  # the file the console reads, bound to the sha256
    assert state == "ok" and rec is not None and "ドリル用" in rec["note_ja"]
    assert r.ops.note_record(bundle.name, "0" * 64) == ("none", None)  # another file's sha256: no note
    assert _check(r, bundle.name)["lines"][0].endswith("not copied again")  # the same file: kept
    os.utime(tmp_path / "incoming" / bundle.name, (1, 1))  # the file on the box changed since: not "verified"
    assert bundle.name not in r.write_status()["verified"]


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


# ------------------------------------------------------------------------------------------------ the review (D-1363)
@pytest.mark.parametrize(
    "name", ["x.tar\n", "x.tar\r", "a\x00b.tar", "aリリース.tar", "x.tar ", "ｘ.tar", ".x.tar", "x.TAR"]
)
def test_a_name_with_a_newline_a_control_character_or_a_look_alike_is_no_bundle(tmp_path: Path, name: str) -> None:
    """Review B3: ``$`` matched before a trailing newline (``x.tar\n`` was copied, and apply_update.sh's basename
    verified the genuine ``x.tar``), and ``\\w`` took any letter."""
    assert not tb_ops.bundle_name(name)
    r, calls = _runner(tmp_path)
    rid = r.ops.submit("update_check", "console:admin", {"bundle": name, "from": "stick"})
    r.run_pending()
    res = r.ops.result(rid)
    assert res is not None and res["ok"] is False and calls == [] and not (tmp_path / "incoming").exists()


def test_a_name_refused_on_the_stick_is_not_listed_and_is_counted(tmp_path: Path) -> None:
    stick = tmp_path / "stick"
    stick.mkdir()
    for n in ("trialbox-1.tar", "x.tar\n", "aリリース.tar"):
        (stick / n).write_bytes(b"x")
    st = _listing(_runner(tmp_path)[0])
    assert [b["name"] for b in st["bundles"]] == ["trialbox-1.tar"] and st["refused"] == 2 and st["cut"] is False


def test_the_status_stays_readable_with_many_verified_bundles_through_the_file(tmp_path: Path) -> None:
    """Review B2: the notes were copied into status.json, which the console reads with a 64 KiB cap; 26 bundles made
    the whole Operations page lose its status. Read here as the console reads it: the file, not the runner's dict."""
    priv, _ = keygen(tmp_path / "k")
    bundle = update_drill.stick_bundle(tmp_path, priv, "2026.12-1", 3)
    (tmp_path / "incoming").mkdir()
    r, _ = _runner(tmp_path)
    for n in range(1, 41):
        (tmp_path / "incoming" / f"trialbox-{n}.tar").write_bytes(bundle.read_bytes())
        r.ops.submit("update_check", "console:admin", {"bundle": f"trialbox-{n}.tar"})
    r.run_pending()
    st = tb_ops.OpsDir(tmp_path / "ops").status()  # what the console's status() reads
    assert st is not None and len(st["verified"]) == 40 and st["version"]["trialbox"]
    assert (tmp_path / "ops" / "status.json").stat().st_size < tb_ops.MAX_JSON


def test_a_note_too_large_is_said_and_never_built(tmp_path: Path) -> None:
    ops = tb_ops.OpsDir(tmp_path / "ops")
    ops.notes.mkdir(parents=True)
    (ops.notes / "trialbox-1.tar.json").write_text(
        json.dumps({"sha256": "a" * 64, "note_ja": "x" * tb_ops.NOTE_RECORD_MAX})
    )
    assert ops.note_record("trialbox-1.tar", "a" * 64) == ("too_large", None)
    f = tmp_path / "note.yaml"
    f.write_text(json.dumps(_source(summary_ja="長い" * 20000), ensure_ascii=False), encoding="utf-8")
    with pytest.raises(release_note.NoteError, match="at most"):
        release_note.build(f, "B1", 1, tmp_path / "out")
    big = tmp_path / release_note.NOTE
    big.write_text("# 大きい\n" + "あ" * 20000, encoding="utf-8")
    bundle, _pub = _plain_bundle(tmp_path, [("other", big, release_note.NOTE)])
    got = release_note.read_from_bundle(bundle)
    assert got["note_ja"] is None and any("too large" in w for w in got["warnings"])


def test_a_verified_file_replaced_or_failing_later_is_no_longer_verified(tmp_path: Path) -> None:
    (tmp_path / "incoming").mkdir()
    f = tmp_path / "incoming" / "trialbox-1.tar"
    f.write_bytes(b"first")
    r, _ = _runner(tmp_path)
    r.ops.submit("update_check", "console:admin", {"bundle": f.name})
    r.run_pending()
    assert r.write_status()["verified"][f.name]["sha256"] == hashlib.sha256(b"first").hexdigest()
    f.write_bytes(b"other")  # replaced under the same name: the record is of the other file
    assert f.name not in r.write_status()["verified"]
    bad, _ = _runner(tmp_path, verified=False)
    bad.ops.submit("update_check", "console:admin", {"bundle": f.name})
    bad.run_pending()
    assert not (tmp_path / "ops" / "verified" / f"{f.name}.json").exists()  # a failed check leaves no pass


def test_an_apply_for_a_verified_sha256_refuses_another_file(tmp_path: Path) -> None:
    (tmp_path / "incoming").mkdir()
    f = tmp_path / "incoming" / "trialbox-1.tar"
    f.write_bytes(b"verified bytes")
    r, calls = _runner(tmp_path)
    good = hashlib.sha256(b"verified bytes").hexdigest()
    _verified_record(r, f.name, good)  # (c): the runner's own record of the check of this file
    assert r.do_update_apply({"bundle": f.name, "sha256": good})[0].endswith("applied") and len(calls) == 1
    with pytest.raises(tb_ops.OpsFailed, match="not the file that was verified"):
        r.do_update_apply({"bundle": f.name, "sha256": "b" * 64})
    with pytest.raises(tb_ops.OpsFailed, match="not the file that was verified"):
        r.do_update_apply({"bundle": f.name, "sha256": "not a sha"})
    assert len(calls) == 1


def test_a_quiet_apply_of_another_file_than_the_verified_one_is_refused(tmp_path: Path) -> None:
    (tmp_path / "incoming").mkdir()
    f = tmp_path / "incoming" / "trialbox-1.tar"
    f.write_bytes(b"what is staged")
    r, calls = _runner(tmp_path)
    r.box.env.update(update_drill.STICK_ENV)
    r.now = lambda: datetime.fromisoformat(update_drill.STICK_QUIET)  # type: ignore[method-assign]
    r.jobs_running = lambda: 0  # type: ignore[method-assign]
    rid = r.ops.submit("update_apply", "console:admin", {"bundle": f.name, "when": "quiet", "sha256": "c" * 64})
    r.run_pending()
    res = r.ops.result(rid)
    assert res is not None and "not the file that was verified" in res["summary"] and calls == []


def test_the_copy_keeps_a_minimum_free_and_says_the_numbers(tmp_path: Path) -> None:
    (tmp_path / "stick").mkdir()
    (tmp_path / "stick" / "trialbox-1.tar").write_bytes(b"x" * 1000)
    r, calls = _runner(tmp_path)
    r.disk_free = lambda path: tb_ops.STICK_MIN_FREE + 500  # type: ignore[method-assign]
    res = _check(r, "trialbox-1.tar")
    assert res["ok"] is False and "must stay free" in res["summary"] and calls == []
    assert not list((tmp_path / "incoming").iterdir())


class _Slow:
    """A stick file whose reads hang (a stick that stops answering), or give more than its size."""

    def __init__(self, hang: bool, data: bytes = b"") -> None:
        self.hang, self.data, self.closed = hang, data, False

    def read(self, n: int) -> bytes:
        if self.hang:
            time.sleep(30)
            return b""
        return self.data[:n] if self.data else b"y" * n  # never ends by itself

    def seek(self, _n: int) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> _Slow:
        return self

    def __exit__(self, *_a: object) -> None:
        self.close()


def test_a_stick_that_hangs_is_stopped_and_the_runner_goes_on(tmp_path: Path) -> None:
    (tmp_path / "stick").mkdir()
    real = tmp_path / "stick" / "trialbox-1.tar"
    real.write_bytes(b"x" * 4096)
    r, calls = _runner(tmp_path)
    r.stall_s = 0.5
    r._open_stick = lambda src: (_Slow(hang=True), os.stat(real))  # type: ignore[method-assign]
    t0 = time.monotonic()
    res = _check(r, "trialbox-1.tar")
    assert res["ok"] is False and "gave no byte" in res["summary"] and time.monotonic() - t0 < 10 and calls == []
    assert not list((tmp_path / "incoming").glob("*"))  # the part file is removed
    rid = r.ops.submit("backup_check", "console:admin")  # the lock is free: the next request runs
    r.run_pending()
    assert r.ops.result(rid) is not None


def test_the_copy_stops_at_the_size_seen_at_open(tmp_path: Path) -> None:
    (tmp_path / "stick").mkdir()
    real = tmp_path / "stick" / "trialbox-1.tar"
    real.write_bytes(b"x" * 3000)
    r, _calls = _runner(tmp_path)
    r._open_stick = lambda src: (_Slow(hang=False), os.stat(real))  # type: ignore[method-assign]
    res = _check(r, "trialbox-1.tar")
    assert res["ok"] is True and (tmp_path / "incoming" / "trialbox-1.tar").stat().st_size == 3000


def test_a_folder_or_a_pipe_named_like_a_bundle_is_refused_without_opening_it(tmp_path: Path) -> None:
    (tmp_path / "stick" / "trialbox-1.tar").mkdir(parents=True)
    os.mkfifo(tmp_path / "stick" / "trialbox-2.tar")  # opened, a pipe would block the runner
    r, calls = _runner(tmp_path)
    assert "is a folder, not a bundle" in _check(r, "trialbox-1.tar")["summary"]
    assert "not a regular file" in _check(r, "trialbox-2.tar")["summary"] and calls == []
    assert _listing(r)["bundles"] == []


def test_the_real_bundle_is_found_among_thousands_of_other_files_and_a_cut_list_says_so(tmp_path: Path) -> None:
    stick = tmp_path / "stick"
    stick.mkdir()
    for i in range(3000):
        (stick / f"aaa-{i:04d}.txt").write_bytes(b"")
    (stick / "trialbox-2026.12-1.tar").write_bytes(b"x")
    st = _listing(_runner(tmp_path)[0])
    assert [b["name"] for b in st["bundles"]] == ["trialbox-2026.12-1.tar"] and st["cut"] is False
    for i in range(tb_ops.STICK_LIST_MAX + 5):
        (stick / f"trialbox-{i:03d}.tar").write_bytes(b"x")
    st = _listing(_runner(tmp_path)[0])
    assert len(st["bundles"]) == tb_ops.STICK_LIST_MAX and st["cut"] is True


def test_a_waiting_quiet_update_can_be_cancelled_and_then_never_runs(tmp_path: Path) -> None:
    (tmp_path / "incoming").mkdir()
    (tmp_path / "incoming" / "trialbox-1.tar").write_bytes(b"x")
    r, calls = _runner(tmp_path)
    r.box.env.update(update_drill.STICK_ENV)
    r.now = lambda: datetime.fromisoformat(update_drill.STICK_QUIET)  # type: ignore[method-assign]
    r.jobs_running = lambda: 0  # type: ignore[method-assign]
    rq = r.ops.submit("update_apply", "console:admin", {"bundle": "trialbox-1.tar", "when": "quiet"})
    rc = r.ops.submit("update_cancel", "console:admin", {"target": rq})
    r.run_pending()  # in the quiet hour: the cancel is taken first, the update does not run
    res, cres = r.ops.result(rq), r.ops.result(rc)
    assert res is not None and res["state"] == "cancelled" and cres is not None and cres["ok"] is True
    assert calls == [] and r.write_status()["waiting"] == []
    again = r.ops.submit("update_cancel", "console:admin", {"target": rq})
    r.run_pending()
    assert "nothing to cancel" in (r.ops.result(again) or {})["summary"]


def test_make_bundle_says_how_to_give_the_release_note() -> None:
    r = subprocess.run(["bash", str(ROOT / "tools" / "make_bundle.sh"), "--release-note"], check=False,
                       capture_output=True, text=True, timeout=60)  # fmt: skip
    assert r.returncode == 2 and "--release-note needs a file" in r.stderr


# --------------------------------------------- the second review: C (names on the stick) and B (the status file)
GOOD = "trialbox-2026.12-1.tar"
BAD_NAMES = {
    "newline at the end": "trialbox-1.tar\n",
    "newline inside": "trialbox-1\n.tar",
    "carriage return": "trialbox-1\r.tar",
    "a control character (NUL-like)": "trialbox-\x01.tar",
    "DEL": "trialbox-\x7f.tar",
    "two dots": "trialbox..1.tar",
    "two dots before tar": "trialbox-1..tar",
    "leading dash": "-rf.tar",
    "leading dot": ".hidden.tar",
    "very long": "t" * 200 + ".tar",
}


@pytest.mark.parametrize("name", list(BAD_NAMES.values()), ids=list(BAD_NAMES))
def test_a_bad_name_is_not_a_bundle_name(name: str) -> None:
    assert not tb_ops.bundle_name(name) and tb_ops.bundle_name(GOOD)


def _stick_with_bad_names(tmp: Path) -> Path:
    stick = tmp / "stick"
    stick.mkdir()
    (stick / GOOD).write_bytes(b"a bundle")
    for name in BAD_NAMES.values():
        (stick / name).write_bytes(b"x")
    (tmp / "outside.tar").write_bytes(b"a file outside the stick")
    (stick / "link-outside.tar").symlink_to(tmp / "outside.tar")
    (stick / "folder.tar").mkdir()
    return stick


def test_the_stick_lists_only_regular_files_with_a_bundle_name(tmp_path: Path) -> None:
    _stick_with_bad_names(tmp_path)
    r, _ = _runner(tmp_path)
    st = {"stick": _listing(r)}
    assert [b["name"] for b in st["stick"]["bundles"]] == [GOOD]
    text = (tmp_path / "ops" / "status.json").read_text(encoding="utf-8")
    for name in [*BAD_NAMES.values(), "link-outside.tar", "folder.tar"]:
        assert json.dumps(name)[1:-1] not in text, repr(name)


def test_a_linked_sidecar_does_not_count(tmp_path: Path) -> None:
    stick = _stick_with_bad_names(tmp_path)
    (stick / f"{GOOD}.sha256").symlink_to(tmp_path / "outside.tar")
    r, _ = _runner(tmp_path)
    (row,) = [b for b in _listing(r)["bundles"] if b["name"] == GOOD]
    assert row["sidecar"] is False


@pytest.mark.parametrize("name", [*BAD_NAMES.values(), "link-outside.tar", "folder.tar"],
                         ids=[*BAD_NAMES, "a link to a file outside the stick", "a folder"])  # fmt: skip
def test_a_bad_file_on_the_stick_is_never_copied_or_passed_to_a_command(tmp_path: Path, name: str) -> None:
    _stick_with_bad_names(tmp_path)
    r, calls = _runner(tmp_path)
    res = _check(r, name)
    assert res["ok"] is False and calls == []
    assert not (tmp_path / "incoming").exists() or list((tmp_path / "incoming").iterdir()) == []
    assert not any(c in res["summary"] for c in "\n\r\x01\x7f")


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


# --------------------------------------------- the integrator's review of d314d016: H1, H3, H4, H5 at the real call
def _sheet_changing(tmp: Path, cc: str) -> Path:
    rows = [{"class": c, "changed": c == cc} for c in ("CC1", "CC2", "CC3", "CC4", "CC5", "CC6")]
    p = tmp / release_note.IMPACT
    p.write_text(json.dumps({"format": release_note.IMPACT_FORMAT, "classes": rows}), encoding="utf-8")
    return p


def test_h1_the_note_reported_is_read_from_the_signed_bytes_even_when_the_path_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H1: the verifier opened the bundle a second time for the note and the sheet and read them against a manifest
    whose signature that read never checked. Signed bundle A (CC4 changed) is swapped for bundle B (CC1 changed,
    signed by a key the box does not trust) between the two opens: the report must still be A's."""
    priv, pub = keygen(tmp_path / "k")
    a = update_drill.stick_bundle(tmp_path / "a", priv, "2026.12-1", 3)
    other, _ = keygen(tmp_path / "k2")
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "n.md").write_text("# 別のリリース\n", encoding="utf-8")
    b = tmp_path / "b" / "b.tar"
    build(other, "2026.12-2", [("other", _sheet_changing(tmp_path / "b", "CC1"), release_note.IMPACT),
                               ("other", tmp_path / "b" / "n.md", release_note.NOTE)], b, release_seq=3)  # fmt: skip
    real = tarfile.open
    opened: list[Any] = []

    def swapping(name: Any = None, *args: Any, **kw: Any) -> Any:
        opened.append(name)
        if len(opened) > 1 and name is not None and Path(name) == a:
            name = b  # the path now names another file
        return real(name, *args, **kw)

    monkeypatch.setattr(tarfile, "open", swapping)
    rn = summary(verify(a, pub))["release_note"]
    assert rn == {"note": True, "impact": True, "changed": ["CC4"], "warnings": []}, rn


def _apply_runner(tmp: Path, verified: bool = True) -> tuple[_Runner, Path, str, list[bytes]]:
    (tmp / "incoming").mkdir()
    f = tmp / "incoming" / "trialbox-1.tar"
    f.write_bytes(b"release A, verified and confirmed")
    seen: list[bytes] = []

    def run(argv: Any, timeout: int | None) -> str:
        seen.append(Path(argv[2]).read_bytes())  # what the installer would read, at the moment it starts
        return "applied\n"

    env = {"TB_UPDATE_STICK": str(tmp / "stick"), "TB_UPDATE_INCOMING": str(tmp / "incoming")}
    r = _Runner(tb_ops.Box("compose", tmp / "deploy", env, run), tb_ops.OpsDir(tmp / "ops"))
    sha = hashlib.sha256(f.read_bytes()).hexdigest()
    if verified:  # (c): the runner applies only a file of its own verified record, as a check leaves it
        _verified_record(r, f.name, sha)
    return r, f, sha, seen


def _swap(f: Path) -> None:
    nxt = f.with_name(".next")
    nxt.write_bytes(b"release B, another signed release")
    os.replace(nxt, f)


def test_h3_a_file_swapped_while_the_databases_are_asked_is_never_installed(tmp_path: Path) -> None:
    """H3: the runner hashed the approved file, then handed the installer a pathname; ``update.tar`` replaced while
    ``apply_limit()`` queried the databases was what the installer opened."""
    r, f, good, seen = _apply_runner(tmp_path)

    def limit() -> int | None:
        _swap(f)
        return None

    r.apply_limit = limit  # type: ignore[method-assign]
    with contextlib.suppress(tb_ops.OpsFailed):
        r.do_update_apply({"bundle": f.name, "sha256": good})
    assert all(s == b"release A, verified and confirmed" for s in seen), seen


def test_h3_the_installer_gets_the_bytes_of_the_descriptor_that_was_hashed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cure: the file is opened once; a swap of the path right after that open changes nothing installed."""
    r, f, good, seen = _apply_runner(tmp_path)
    real = os.open
    done: list[bool] = []

    def opening(path: Any, *args: Any, **kw: Any) -> int:
        fd = real(path, *args, **kw)
        if not done and Path(os.fsdecode(path)) == f:
            done.append(True)
            _swap(f)
        return fd

    monkeypatch.setattr(os, "open", opening)
    assert r.do_update_apply({"bundle": f.name, "sha256": good})[0].endswith("applied")
    assert done and seen == [b"release A, verified and confirmed"]
    assert f.read_bytes() == b"release B, another signed release"  # the path names B; A was installed
    assert not list((tmp_path / "deploy" / "updates" / tb_ops.HELD_DIR).iterdir())  # the private copy is gone


def test_h3_an_apply_without_a_verified_sha256_is_refused(tmp_path: Path) -> None:
    r, f, _good, seen = _apply_runner(tmp_path)
    with pytest.raises(tb_ops.OpsFailed, match="not the file that was verified"):
        r.do_update_apply({"bundle": f.name})
    assert seen == []


def _drill_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_TZ", os.environ.get("TB_TZ") or "UTC")
    ok = {"ok": True, "checks": [], "skipped": [], "seconds": 0.0}
    monkeypatch.setattr(update_drill, "stick_drill", lambda d: ok)
    monkeypatch.setattr(update_drill, "run", lambda d: ok)


@pytest.mark.parametrize("which", [["stick"], []], ids=["stick drill", "update drill"])
def test_h4_dir_that_the_drill_did_not_make_is_refused_and_nothing_in_it_is_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, which: list[str]
) -> None:
    """H4: ``--dir`` pointing at an existing folder (a backup folder) was deleted before anything checked it."""
    _drill_stubs(monkeypatch)
    d = tmp_path / "backups"
    d.mkdir()
    (d / "nightly.tbk").write_bytes(b"a backup")
    assert update_drill.main([*which, "--dir", str(d)]) == 2
    assert (d / "nightly.tbk").read_bytes() == b"a backup"
    (tmp_path / "link").symlink_to(d)  # a link is never followed, even to a folder the drill made
    (d / update_drill.DRILL_MARK).write_text("x")
    assert update_drill.main([*which, "--dir", str(tmp_path / "link")]) == 2
    assert (d / "nightly.tbk").read_bytes() == b"a backup"
    (tmp_path / "file").write_bytes(b"x")
    assert update_drill.main([*which, "--dir", str(tmp_path / "file")]) == 2
    assert (tmp_path / "file").read_bytes() == b"x"


@pytest.mark.parametrize("which", [["stick"], []], ids=["stick drill", "update drill"])
def test_h4_a_folder_the_drill_made_is_emptied_and_used_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, which: list[str]
) -> None:
    _drill_stubs(monkeypatch)
    d = tmp_path / "drill"
    assert update_drill.main([*which, "--dir", str(d)]) == 0
    assert (d / update_drill.DRILL_MARK).is_file()
    (tmp_path / "outside.txt").write_bytes(b"outside")
    (d / "left-over").mkdir()
    (d / "left-over" / "link").symlink_to(tmp_path / "outside.txt")
    assert update_drill.main([*which, "--dir", str(d)]) == 0
    assert (d / update_drill.DRILL_MARK).is_file() and not (d / "left-over").exists()
    assert (tmp_path / "outside.txt").read_bytes() == b"outside"  # never deleted outside it


def _quiet_runner(tmp: Path) -> tuple[_Runner, list[list[str]], str]:
    (tmp / "incoming").mkdir()
    f = tmp / "incoming" / "trialbox-1.tar"
    f.write_bytes(b"x")
    r, calls = _runner(tmp)
    r.box.env.update(update_drill.STICK_ENV)
    r.now = lambda: datetime.fromisoformat(update_drill.STICK_QUIET)  # type: ignore[method-assign]
    r.jobs_running = lambda: 0  # type: ignore[method-assign]
    _verified_record(r, f.name, hashlib.sha256(b"x").hexdigest())  # (c): as a check of that file leaves it
    return r, calls, hashlib.sha256(b"x").hexdigest()


def test_h5_a_cancel_accepted_while_a_backup_runs_stops_the_update(tmp_path: Path) -> None:
    """H5: a cancel took priority only when it was there at the start of the runner's pass; one accepted while a
    backup ran first was read after the update had been applied."""
    r, calls, sha = _quiet_runner(tmp_path)
    rb = r.ops.submit("backup", "console:admin", {"mode": "running"})
    rq = r.ops.submit("update_apply", "console:admin", {"bundle": "trialbox-1.tar", "when": "quiet", "sha256": sha})

    def backup(args: Any) -> tuple[str, list[str]]:  # the administrator cancels on the console meanwhile
        r.ops.submit("update_cancel", "console:admin", {"target": rq})
        return "backup written", []

    r.do_backup = backup  # type: ignore[method-assign]
    r.run_pending()
    res = r.ops.result(rq)
    assert (r.ops.result(rb) or {}).get("ok") is True
    assert res is not None and res["state"] == "cancelled", res
    assert not [c for c in calls if "apply_update.sh" in " ".join(c)], calls


def test_h5_a_cancel_accepted_just_before_the_installer_starts_stops_it(tmp_path: Path) -> None:
    """The cancel's own record (``OpsDir.decide``, written once by whichever comes first) is read again immediately
    before the installer starts: a cancel accepted after the runner took the request still stops it."""
    r, calls, sha = _quiet_runner(tmp_path)
    rq = r.ops.submit("update_apply", "console:admin", {"bundle": "trialbox-1.tar", "when": "quiet", "sha256": sha})

    def limit() -> int | None:  # the runner asks the databases; the console accepts the cancel meanwhile
        assert r.ops.decide(rq, "cancel", "console:admin") == "cancel"
        r.ops.submit("update_cancel", "console:admin", {"target": rq})
        return None

    r.apply_limit = limit  # type: ignore[method-assign]
    r.run_pending()
    res = r.ops.result(rq)
    assert res is not None and res["state"] == "cancelled" and res["ok"] is False, res
    assert calls == []
    # and once the runner has taken the start, a cancel is no longer accepted
    rq2 = r.ops.submit("update_apply", "console:admin", {"bundle": "trialbox-1.tar", "when": "quiet", "sha256": sha})
    r.apply_limit = lambda: None  # type: ignore[method-assign]
    r.run_pending()
    assert (r.ops.result(rq2) or {}).get("ok") is True
    assert r.ops.decide(rq2, "cancel", "console:admin") == "start"


# ------------------------------------- the integrator's review of d314d016, items 6 to 12, and the H fixes looked at again
class _Stuck(io.RawIOBase):
    """A stick's file as the kernel gives it when the stick stops answering: a read that never returns until
    ``free`` is set. Wrapped in a real ``io.BufferedReader`` (what ``os.fdopen(fd, "rb")`` gives), whose ``close()``
    waits for the lock that the blocked read holds."""

    def __init__(self, free: Any, data: bytes = b"") -> None:
        self.free, self.data, self.reads = free, data, 0

    def readable(self) -> bool:
        return True

    def readinto(self, b: Any) -> int:
        self.reads += 1
        self.free.wait(60)
        return 0


def _stuck_check(r: _Runner, name: str, real: Path) -> tuple[dict[str, Any] | None, float]:
    import threading

    free = threading.Event()
    r.stall_s = 0.5
    r._open_stick = lambda src: (io.BufferedReader(_Stuck(free)), os.stat(real))  # type: ignore[method-assign]
    got: list[dict[str, Any]] = []
    t = threading.Thread(target=lambda: got.append(_check(r, name)), daemon=True)
    t0 = time.monotonic()
    t.start()
    t.join(15)
    took = time.monotonic() - t0
    free.set()  # the stick answers again: the copy's thread ends (the test's own clean-up)
    t.join(5)
    return (got[0] if got else None), took


def test_6_a_stick_whose_close_waits_for_the_blocked_read_still_frees_the_runner(tmp_path: Path) -> None:
    """Item 6: the watchdog raised, then ``with fh:`` closed the buffered file in the runner's thread, and that
    close waited for the copy thread's blocked read: the runner (and its lock, so every backup) stayed held."""
    (tmp_path / "stick").mkdir()
    real = tmp_path / "stick" / "trialbox-1.tar"
    real.write_bytes(b"x" * 4096)
    r, calls = _runner(tmp_path)
    res, took = _stuck_check(r, "trialbox-1.tar", real)
    assert res is not None and took < 10, f"the runner was still held after {took:.1f} s"
    assert res["ok"] is False and "gave no byte" in res["summary"] and calls == []
    assert not list((tmp_path / "incoming").glob("*"))
    rid = r.ops.submit("backup_check", "console:admin")  # the lock is free
    r.run_pending()
    assert r.ops.result(rid) is not None


def test_6_the_same_name_comparison_with_a_stuck_stick_is_watched_too(tmp_path: Path) -> None:
    """The bundle of that name already on the box was compared by hashing the stick's file in the runner's own
    thread, with no watchdog at all."""
    (tmp_path / "stick").mkdir()
    real = tmp_path / "stick" / "trialbox-1.tar"
    real.write_bytes(b"x" * 4096)
    (tmp_path / "incoming").mkdir()
    (tmp_path / "incoming" / "trialbox-1.tar").write_bytes(b"x" * 4096)
    r, calls = _runner(tmp_path)
    res, took = _stuck_check(r, "trialbox-1.tar", real)
    assert res is not None and took < 10, f"the runner was still held after {took:.1f} s"
    assert res["ok"] is False and "gave no byte" in res["summary"] and calls == []
    assert (tmp_path / "incoming" / "trialbox-1.tar").read_bytes() == b"x" * 4096  # the box's file untouched


def _verified_record(r: tb_ops.OpsRunner, name: str, sha: str) -> None:
    """The runner's own record of a bundle it verified (``OpsRunner._keep``), as a check of that file leaves it."""
    r.ops.verified.mkdir(parents=True, exist_ok=True)
    (r.ops.verified / f"{name}.json").write_text(json.dumps({"bundle": name, "sha256": sha}), encoding="utf-8")


def test_7_the_private_copy_budgets_for_the_installers_staging_on_the_same_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 7: the free-space check counted the private copy but not the second copy apply_update.sh stages (in
    ``$TMPDIR``) on the same disk: the 10 GiB promised to the databases and the audit was not kept."""
    r, f, good, seen = _apply_runner(tmp_path)
    stage = tmp_path / "deploy" / "tmp"
    stage.mkdir(parents=True)
    monkeypatch.setenv("TMPDIR", str(stage))  # where apply_update.sh stages: the same disk as the private copy
    monkeypatch.setattr(tempfile, "tempdir", None)  # read again from $TMPDIR, not a value cached earlier
    size = f.stat().st_size
    r.disk_free = lambda path: tb_ops.STICK_MIN_FREE + int(size * tb_ops.STICK_MARGIN * 1.5)  # type: ignore[method-assign]
    with pytest.raises(tb_ops.OpsFailed, match="must stay free"):
        r.do_update_apply({"bundle": f.name, "sha256": good})
    assert seen == []
    r.disk_free = lambda path: tb_ops.STICK_MIN_FREE + int(size * tb_ops.STICK_MARGIN * 2) + 2  # type: ignore[method-assign]
    assert r.do_update_apply({"bundle": f.name, "sha256": good})[0].endswith("applied")


def test_8_a_deeply_nested_impact_sheet_is_a_warning_never_a_failed_verify(tmp_path: Path) -> None:
    """Item 8: a ``RecursionError`` decoding the sheet escaped after the staged files were finalised. No longer so:
    H1's rewrite catches it where the sheet is decoded, and this python decodes the deepest sheet the 16 KiB cap lets
    in; kept at the real call (a signed bundle, the verifier's own summary): a warning, the bundle verified."""
    deep = tmp_path / release_note.IMPACT
    deep.write_text("[" * 8000 + "]" * 8000, encoding="utf-8")
    (tmp_path / "n.md").write_text("# 合成のノート\n", encoding="utf-8")
    bundle, pub = _plain_bundle(tmp_path, [("other", deep, release_note.IMPACT),
                                           ("other", tmp_path / "n.md", release_note.NOTE)])  # fmt: skip
    rn = summary(verify(bundle, pub, stage=tmp_path / "stage"))["release_note"]
    assert rn["note"] is True and rn["impact"] is False
    assert len(rn["warnings"]) == 1 and rn["warnings"][0].startswith("CHANGE-IMPACT.json"), rn
    assert list((tmp_path / "stage").iterdir())  # staged and finalised: the install goes on


def _full_sheet(**edit: Any) -> dict[str, Any]:
    rows = [{"class": c, "changed": c == "CC4"} for c in ("CC1", "CC2", "CC3", "CC4", "CC5", "CC6")]
    sheet: dict[str, Any] = {"format": release_note.IMPACT_FORMAT, "classes": rows, "downtime_minutes": 20,
                             "database_migration": False, "ruleset_reapproval": True}  # fmt: skip
    for k, v in edit.items():
        if v is None:
            sheet.pop(k)
        else:
            sheet[k] = v
    return sheet


@pytest.mark.parametrize(
    "edit",
    [{"ruleset_reapproval": None}, {"database_migration": None}, {"downtime_minutes": None},
     {"ruleset_reapproval": "yes"}, {"database_migration": 0}, {"downtime_minutes": -1},
     {"downtime_minutes": True}, {"downtime_minutes": "20"}],
    ids=["no reapproval", "no migration", "no downtime", "reapproval a string", "migration a number",
         "negative downtime", "downtime a bool", "downtime a string"],
)  # fmt: skip
def test_9_a_sheet_without_the_migration_reapproval_or_downtime_is_a_warning_and_not_shown(
    tmp_path: Path, edit: dict[str, Any]
) -> None:
    """Item 9: the sheet's check took six good class rows and no ``ruleset_reapproval``; the page then said
    "Rulesets to approve again: No"."""
    assert release_note.sheet_problems(_full_sheet()) == []  # a whole sheet passes
    sheet = tmp_path / release_note.IMPACT
    sheet.write_text(json.dumps(_full_sheet(**edit)), encoding="utf-8")
    (tmp_path / "n.md").write_text("# 合成のノート\n", encoding="utf-8")
    bundle, pub = _plain_bundle(tmp_path, [("other", sheet, release_note.IMPACT),
                                           ("other", tmp_path / "n.md", release_note.NOTE)])  # fmt: skip
    rn = summary(verify(bundle, pub))["release_note"]
    assert rn["note"] is True and rn["impact"] is False, rn
    assert rn["warnings"] == [
        "CHANGE-IMPACT.json: the minutes down, the migration or the re-approval is missing or not a plain value"
    ]
    got = release_note.read_from_bundle(bundle)  # the runner's read of the private copy says the same
    assert got["impact"] is None and got["warnings"] == rn["warnings"]


class _Audited(tb_ops.OpsRunner):
    """The real ``audit``: each event's detail is what the box's audit chain would get (``console.ops``)."""


def _audit_details(calls: list[list[str]]) -> list[dict[str, Any]]:
    return [json.loads(c[-1]) for c in calls if "exec" in c and "orchestrator" in c]


def test_10_a_cancelled_update_has_its_own_completion_audit_event(tmp_path: Path) -> None:
    """Item 10: the cancel wrote the update's result itself; the runner then skipped the update and its
    ``update_apply.done`` event was never written, only the cancel's."""
    (tmp_path / "incoming").mkdir()
    (tmp_path / "incoming" / "trialbox-1.tar").write_bytes(b"x")
    calls: list[list[str]] = []

    def run(argv: Any, timeout: int | None) -> str:
        calls.append(list(argv))
        return ""

    env = {"TB_UPDATE_STICK": str(tmp_path / "stick"), "TB_UPDATE_INCOMING": str(tmp_path / "incoming"),
           **update_drill.STICK_ENV}  # fmt: skip
    r = _Audited(tb_ops.Box("compose", tmp_path / "deploy", env, run), tb_ops.OpsDir(tmp_path / "ops"))
    r.now = lambda: datetime.fromisoformat(update_drill.STICK_QUIET)  # type: ignore[method-assign]
    r.jobs_running = lambda: 0  # type: ignore[method-assign]
    rq = r.ops.submit("update_apply", "console:admin", {"bundle": "trialbox-1.tar", "when": "quiet"})
    rc = r.ops.submit("update_cancel", "console:admin", {"target": rq})
    r.run_pending()
    events = {(d["action"], d["request"]): d for d in _audit_details(calls)}
    assert ("update_cancel.done", rc) in events and events[("update_cancel.done", rc)]["ok"] is True
    assert ("update_apply.done", rq) in events, sorted(events)
    assert (
        events[("update_apply.done", rq)]["state"] == "cancelled" and events[("update_apply.done", rq)]["ok"] is False
    )
    assert not [c for c in calls if "apply_update.sh" in " ".join(c)]


def test_11_a_relative_release_note_is_read_from_where_it_was_named(tmp_path: Path) -> None:
    """Item 11: ``--release-note notes.ja.yaml`` was looked for in the caller's folder and then read from the project
    root (the build runs there), so the builder could sign another note than the one the vendor chose."""
    work = tmp_path / "release-work"
    work.mkdir()
    (work / "notes.ja.yaml").write_text(json.dumps(update_drill.STICK_SOURCE, ensure_ascii=False), encoding="utf-8")
    (work / "gates.json").write_text("{}")
    (work / "key.pem").write_text("synthetic, never read here")
    (work / "sbom").mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "py.log"
    (bin_dir / "docker").write_text("#!/bin/sh\nexit 1\n")  # the image export after the note stops the build
    (bin_dir / "py").write_text(f'#!/bin/sh\necho "$PWD|$*" >> {log}\nexec {sys.executable} "$@"\n')
    for x in ("docker", "py"):
        (bin_dir / x).chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "PY": str(bin_dir / "py")}
    r = subprocess.run(["bash", str(ROOT / "tools" / "make_bundle.sh"), "--key", "key.pem", "--id", "2026.12-1",
                        "--release-seq", "3", "--out", str(tmp_path / "out.tar"), "--gates", "gates.json",
                        "--sbom-dir", "sbom", "--allow-dirty", "a test", "--release-note", "notes.ja.yaml"],
                       cwd=work, env=env, capture_output=True, text=True, check=False, timeout=300)  # fmt: skip
    assert "could not be built" not in r.stderr, r.stderr
    builds = [ln for ln in log.read_text().splitlines() if "tools.release_note build" in ln]
    assert len(builds) == 1 and f"--source {work / 'notes.ja.yaml'} " in builds[0], builds


def test_12_a_verified_bundle_past_the_listing_limit_keeps_its_record(tmp_path: Path) -> None:
    """Item 12: the status kept the verified records of the first 50 staged bundles only: ``release-051.tar``,
    verified, stayed "not verified yet" on the page, with no note and no Apply."""
    inc = tmp_path / "incoming"
    inc.mkdir()
    for i in range(1, tb_ops.STICK_LIST_MAX + 2):
        (inc / f"release-{i:03d}.tar").write_bytes(b"r%d" % i)
    r, _calls = _runner(tmp_path)
    last = f"release-{tb_ops.STICK_LIST_MAX + 1:03d}.tar"
    rid = r.ops.submit("update_check", "console:admin", {"bundle": last})
    r.run_pending()
    assert (r.ops.result(rid) or {}).get("ok") is True
    st = r.write_status()
    assert last in st["verified"], sorted(st["verified"])
    assert st["verified"][last]["sha256"] == hashlib.sha256(b"r%d" % (tb_ops.STICK_LIST_MAX + 1)).hexdigest()


def test_a_held_folder_planted_as_a_link_or_open_to_others_is_refused(tmp_path: Path) -> None:
    """(a) ``deploy/updates/.ops-held`` is the runner's own: one planted as a link is never written through, one
    open to others is refused, and the copy is made through the folder's own descriptor."""
    r, f, good, seen = _apply_runner(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir(mode=0o700)
    updates = tmp_path / "deploy" / "updates"
    updates.mkdir(parents=True)
    (updates / tb_ops.HELD_DIR).symlink_to(elsewhere)
    with pytest.raises(tb_ops.OpsFailed, match="only the runner can open"):
        r.do_update_apply({"bundle": f.name, "sha256": good})
    assert seen == [] and list(elsewhere.iterdir()) == []
    (updates / tb_ops.HELD_DIR).unlink()
    (updates / tb_ops.HELD_DIR).mkdir(mode=0o700)
    os.chmod(updates / tb_ops.HELD_DIR, 0o770)
    with pytest.raises(tb_ops.OpsFailed, match="only the runner can open"):
        r.do_update_apply({"bundle": f.name, "sha256": good})
    assert seen == []


def test_a_held_folder_made_under_a_wide_umask_is_0700(tmp_path: Path) -> None:
    r, f, good, _seen = _apply_runner(tmp_path)
    old = os.umask(0)
    try:
        assert r.do_update_apply({"bundle": f.name, "sha256": good})[0].endswith("applied")
    finally:
        os.umask(old)
    assert stat.S_IMODE((tmp_path / "deploy" / "updates" / tb_ops.HELD_DIR).stat().st_mode) == 0o700


def test_a_private_copy_left_by_a_crash_is_removed_on_the_next_pass(tmp_path: Path) -> None:
    r, _calls = _runner(tmp_path)
    held = tmp_path / "deploy" / "updates" / tb_ops.HELD_DIR
    (held / "held-crashed").mkdir(parents=True, mode=0o700)
    os.chmod(held, 0o700)
    (held / "held-crashed" / "trialbox-1.tar").write_bytes(b"x" * 100)
    r.run_pending()
    assert not (held / "held-crashed").exists()


@pytest.mark.parametrize("kind", ["not JSON", "another decision", "a link", "a folder"])
def test_b_a_malformed_or_foreign_decision_record_never_starts_the_update(tmp_path: Path, kind: str) -> None:
    """(b) ``requests/<id>.decided`` lives where the console's account writes: whatever is there that is not the
    runner's own ``start`` stops the update (cancelled, nothing changed), never a crash, never a start."""
    r, calls, sha = _quiet_runner(tmp_path)
    rq = r.ops.submit("update_apply", "console:admin", {"bundle": "trialbox-1.tar", "when": "quiet", "sha256": sha})
    p = r.ops.root / "requests" / f"{rq}.decided"
    if kind == "not JSON":
        p.write_text("{nope")
    elif kind == "another decision":
        p.write_text(json.dumps({"decision": "go"}))
    elif kind == "a link":
        (tmp_path / "start.json").write_text(json.dumps({"decision": "start"}))
        p.symlink_to(tmp_path / "start.json")
    else:
        p.mkdir()
    r.run_pending()
    res = r.ops.result(rq)
    assert res is not None and res["ok"] is False and res["state"] == "cancelled", res
    assert not [c for c in calls if "apply_update.sh" in " ".join(c) and "--dry-run" not in c], calls
    with pytest.raises(tb_ops.OpsFailed):
        r.ops.decision("../x")


def test_c_an_apply_of_a_file_the_runner_never_verified_is_refused(tmp_path: Path) -> None:
    """(c) The console compares what the page showed with the verified record, but a console that skips that
    comparison could send any sha256: the runner applies only a file whose sha256 is its OWN verified record
    (``<ops>/verified/<bundle>.json``, root's)."""
    r, f, good, seen = _apply_runner(tmp_path, verified=False)
    with pytest.raises(tb_ops.OpsRefused, match="not the file that was verified") as got:
        r.do_update_apply({"bundle": f.name, "sha256": good})
    assert got.value.why == "unverified" and seen == []
    _verified_record(r, f.name, "0" * 64)  # a record of another file of that name
    with pytest.raises(tb_ops.OpsRefused, match="not the file that was verified"):
        r.do_update_apply({"bundle": f.name, "sha256": good})
    assert seen == []
    _verified_record(r, f.name, "1" * 64)  # a record and a request that agree, but the file's bytes are other
    with pytest.raises(tb_ops.OpsFailed, match="verify it again"):
        r.do_update_apply({"bundle": f.name, "sha256": "1" * 64})
    assert seen == []
    _verified_record(r, f.name, good)
    assert r.do_update_apply({"bundle": f.name, "sha256": good})[0].endswith("applied")


def test_d_a_request_without_a_sha256_is_refused_with_its_reason_kept_and_audited(tmp_path: Path) -> None:
    """(d) A request an older console queued names no sha256: refused, the result carries ``why: unverified`` (the
    page says it in the administrator's language) and so does its ``update_apply.done`` event."""
    (tmp_path / "incoming").mkdir()
    (tmp_path / "incoming" / "trialbox-1.tar").write_bytes(b"x")
    calls: list[list[str]] = []

    def run(argv: Any, timeout: int | None) -> str:
        calls.append(list(argv))
        return "60\n" if "apply_limit" in " ".join(argv) else ""

    env = {"TB_UPDATE_STICK": str(tmp_path / "stick"), "TB_UPDATE_INCOMING": str(tmp_path / "incoming")}
    r = _Audited(tb_ops.Box("compose", tmp_path / "deploy", env, run), tb_ops.OpsDir(tmp_path / "ops"))
    r.apply_limit = lambda: None  # type: ignore[method-assign]
    rq = r.ops.submit("update_apply", "console:admin", {"bundle": "trialbox-1.tar"})
    r.run_pending()
    res = r.ops.result(rq)
    assert res is not None and res["ok"] is False and res.get("why") == "unverified", res
    (ev,) = [d for d in _audit_details(calls) if d["request"] == rq]
    assert ev["action"] == "update_apply.done" and ev["why"] == "unverified" and ev["ok"] is False
    assert not [c for c in calls if "apply_update.sh" in " ".join(c)]


# ------------------------------------------------------- the third review of PR #1213: M1 to M3 and L1 to L9 (D-1363)
def test_r3_m1_a_drill_folder_swapped_for_a_link_after_its_check_empties_nothing_outside(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M1: ``drill_dir`` checked ``--dir`` by lstat, then emptied it by path: another account that swaps the folder
    for a link between the two (its parent was theirs) had the link's target emptied by root. The swap is made in
    that window, at the first listing of the folder, however it is listed."""
    base = tmp_path / "parent"
    base.mkdir(mode=0o700)
    d = base / "tb-update-drill"
    d.mkdir()
    (d / update_drill.DRILL_MARK).write_text("mark")
    (d / "old-run.txt").write_text("the drill's own left-over")
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "precious.txt").write_text("keep me")
    (victim / "sub").mkdir()
    (victim / "sub" / "x").write_text("x")
    real = os.scandir
    swapped: list[bool] = []

    def racing(*a: Any, **kw: Any) -> Any:
        if not swapped:
            swapped.append(True)
            os.rename(d, base / "moved-away")
            os.symlink(victim, d)
        return real(*a, **kw)

    monkeypatch.setattr(os, "scandir", racing)
    update_drill.drill_dir(d)
    monkeypatch.setattr(os, "scandir", real)
    assert sorted(p.name for p in victim.iterdir()) == ["precious.txt", "sub"]
    assert (victim / "sub" / "x").read_text() == "x"


def test_r3_m1_a_parent_another_account_could_write_or_owns_is_refused(tmp_path: Path) -> None:
    """M1: the default ``--dir`` sits in ``/var/tmp/trialbox-<uid>``, which any local account can make first; a
    parent folder open to others' writes (no sticky bit), or another account's, is refused before anything is
    removed, and nothing is made in it."""
    base = tmp_path / "open"
    base.mkdir()
    os.chmod(base, 0o777)
    d = base / "tb-update-drill"
    d.mkdir()
    (d / update_drill.DRILL_MARK).write_text("mark")
    (d / "keep.txt").write_text("x")
    why = update_drill.drill_dir(d)
    assert why is not None and "others" in why and (d / "keep.txt").exists()
    assert update_drill.drill_dir(base / "new") is not None and not (base / "new").exists()
    if os.geteuid() == 0:  # another account's folder (only root can make one here)
        theirs = tmp_path / "theirs"
        theirs.mkdir(mode=0o755)
        os.chown(theirs, 10001, 10001)
        why = update_drill.drill_dir(theirs / "tb-update-drill")
        assert why is not None and "owned" in why and not (theirs / "tb-update-drill").exists()
    mine = tmp_path / "mine"
    mine.mkdir(mode=0o700)
    assert update_drill.drill_dir(mine / "d") is None and (mine / "d" / update_drill.DRILL_MARK).is_file()


def _listing(r: tb_ops.OpsRunner) -> dict[str, Any]:
    """M2: the stick is read only when a listing is asked for (``update_stick_list``), then shown from the status."""
    rid = r.ops.submit("update_stick_list", "console:admin")
    r.run_pending()
    assert r.ops.result(rid) is not None
    st = r.ops.status()
    assert st is not None
    return dict(st["stick"])


def test_r3_m2_a_runner_pass_never_reads_the_stick_unless_a_listing_was_asked_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M2: every pass of the runner listed the stick in its own thread, under the runner's lock: a stick that hangs
    in the kernel stopped every backup. Now a pass (and the status it writes) does not touch the stick."""
    stick = tmp_path / "stick"
    stick.mkdir()
    (stick / "trialbox-1.tar").write_bytes(b"x")
    r, _calls = _runner(tmp_path)
    touched: list[str] = []
    real_scandir, real_lstat = os.scandir, os.lstat

    def scandir(p: Any = ".") -> Any:
        if isinstance(p, str | os.PathLike) and str(stick) in str(p):
            touched.append(f"scandir {p}")
        return real_scandir(p)

    def lstat(p: Any, *a: Any, **kw: Any) -> Any:
        if isinstance(p, str | os.PathLike) and str(stick) in str(p):
            touched.append(f"lstat {p}")
        return real_lstat(p, *a, **kw)

    monkeypatch.setattr(os, "scandir", scandir)
    monkeypatch.setattr(os, "lstat", lstat)
    r.ops.submit("backup_check", "console:admin")
    r.run_pending()
    st = r.write_status()
    assert touched == [] and st.get("stick") is None, touched
    monkeypatch.setattr(os, "scandir", real_scandir)
    monkeypatch.setattr(os, "lstat", real_lstat)
    assert [b["name"] for b in _listing(r)["bundles"]] == ["trialbox-1.tar"]
    assert [b["name"] for b in r.write_status()["stick"]["bundles"]] == ["trialbox-1.tar"]  # kept until asked again


def test_r3_m2_a_listing_that_hangs_is_stopped_and_said_and_the_runner_goes_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    (tmp_path / "stick").mkdir()
    r, _calls = _runner(tmp_path)
    r.list_s = 0.5
    free = threading.Event()
    monkeypatch.setattr(tb_ops, "_read_stick", lambda root: free.wait(30) and {})
    t0 = time.monotonic()
    rid = r.ops.submit("update_stick_list", "console:admin")
    r.run_pending()
    res = r.ops.result(rid)
    free.set()
    assert res is not None and res["ok"] is False and "did not answer" in res["summary"], res
    assert time.monotonic() - t0 < 10
    st = r.ops.status() or {}
    assert st["stick"]["hung"] is True and st["stick"]["bundles"] == []
    rb = r.ops.submit("backup_check", "console:admin")  # the lock is free: the next request runs
    r.run_pending()
    assert r.ops.result(rb) is not None


def test_r3_l1_the_runners_start_record_reads_for_the_console(tmp_path: Path) -> None:
    """L1: the runner's ``start`` record was 0600 root's: the console (uid 10001) read it as ``unreadable``, so a
    refused cancel was audited with the wrong reason. It holds only the decision, who and when."""
    import shutil

    # as root, a folder the console's account can reach (the test's own parents are root's 0700)
    base = Path(tempfile.mkdtemp(prefix="tb-l1-", dir="/var/tmp")) if os.geteuid() == 0 else tmp_path
    try:
        os.chmod(base, 0o755)
        ops = tb_ops.OpsDir(base / "ops")
        tb_ops.prepare(ops)
        rid = "20261120T000000Z-abcdef"
        assert ops.decide(rid, "start", "trialbox-ops") == "start"
        p = ops.root / "requests" / f"{rid}.decided"
        assert stat.S_IMODE(p.stat().st_mode) == 0o644
        assert set(json.loads(p.read_text())) == {"decision", "by", "at"}
        if os.geteuid() == 0:  # read as the console's account reads it
            rd, wr = os.pipe()
            pid = os.fork()
            if pid == 0:
                try:
                    os.close(rd)
                    os.setgid(tb_ops.SERVICE_UID)
                    os.setuid(tb_ops.SERVICE_UID)
                    o = tb_ops.OpsDir(base / "ops")
                    os.write(wr, f"{o.decision(rid)} {o.decide(rid, 'cancel', 'console:admin')}".encode())
                except BaseException as exc:  # said to the parent, never raised in the forked child
                    os.write(wr, repr(exc).encode()[:200])
                finally:
                    os._exit(0)
            os.close(wr)
            os.waitpid(pid, 0)
            assert os.read(rd, 1000).decode() == "start start"
    finally:
        if base != tmp_path:
            shutil.rmtree(base, ignore_errors=True)


def test_r3_l2_a_cancelled_update_names_who_cancelled_it(tmp_path: Path) -> None:
    """L2: the update's cancelled result and its ``update_apply.done`` event carried only who ASKED for the update;
    the console's cancel record names who cancelled, and the runner now says it."""
    (tmp_path / "incoming").mkdir()
    (tmp_path / "incoming" / "trialbox-1.tar").write_bytes(b"x")
    calls: list[list[str]] = []

    def run(argv: Any, timeout: int | None) -> str:
        calls.append(list(argv))
        return ""

    env = {"TB_UPDATE_STICK": str(tmp_path / "stick"), "TB_UPDATE_INCOMING": str(tmp_path / "incoming"),
           **update_drill.STICK_ENV}  # fmt: skip
    r = _Audited(tb_ops.Box("compose", tmp_path / "deploy", env, run), tb_ops.OpsDir(tmp_path / "ops"))
    r.now = lambda: datetime.fromisoformat(update_drill.STICK_QUIET)  # type: ignore[method-assign]
    r.jobs_running = lambda: 0  # type: ignore[method-assign]
    rq = r.ops.submit("update_apply", "console:alice", {"bundle": "trialbox-1.tar", "when": "quiet"})
    assert r.ops.decide(rq, "cancel", "console:bob") == "cancel"  # the console died before it queued the cancel
    r.run_pending()
    res = r.ops.result(rq)
    assert res is not None and res["state"] == "cancelled" and res["by"] == "console:alice"
    assert res["cancelled_by"] == "console:bob"
    (ev,) = [d for d in _audit_details(calls) if d["request"] == rq]
    assert ev["cancelled_by"] == "console:bob" and ev["state"] == "cancelled"


def test_r3_l3_an_empty_mount_point_is_no_stick_and_an_empty_stick_is_said_apart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L3: the mount point is there with nothing mounted on it: that read "the stick holds no bundle"."""
    (tmp_path / "stick").mkdir()
    r, _calls = _runner(tmp_path)
    assert _listing(r)["mounted"] is False  # an empty folder, nothing mounted: no stick inserted
    monkeypatch.setattr(os.path, "ismount", lambda p: str(p) == str(tmp_path / "stick"))
    got = _listing(r)
    assert got["mounted"] is True and got["bundles"] == []  # a stick is mounted and holds no bundle


def test_r3_l4_a_check_that_copied_from_the_stick_does_not_say_nothing_was_changed(tmp_path: Path) -> None:
    priv, _pub = keygen(tmp_path / "k")
    bundle = update_drill.stick_bundle(tmp_path, priv, "2026.12-1", 3)
    (tmp_path / "stick").mkdir()
    (tmp_path / "stick" / bundle.name).write_bytes(bundle.read_bytes())
    r, _calls = _runner(tmp_path)
    res = _check(r, bundle.name)
    assert res["ok"] is True and "nothing was changed" not in res["summary"], res["summary"]
    assert "copied to the box" in res["summary"] and "nothing was installed" in res["summary"]
    again = _check(r, bundle.name)  # the same file already on the box: nothing was copied this time
    assert "nothing was changed" in again["summary"]


def test_r3_l5_a_verified_bundle_the_installer_would_now_refuse_says_why(tmp_path: Path) -> None:
    """L5: "verified" (and Apply) stayed on a bundle whose release is installed, older, or checked against keys the
    box no longer trusts as then."""
    (tmp_path / "incoming").mkdir()
    f = tmp_path / "incoming" / "trialbox-1.tar"
    f.write_bytes(b"x")
    r, _calls = _runner(tmp_path)
    upd = tmp_path / "deploy" / "updates"
    upd.mkdir(parents=True)
    (upd / "trust.json").write_text('{"keys": {"a": 1}}')
    st = os.stat(f)
    r._keep(f, hashlib.sha256(b"x").hexdigest(), (st.st_size, st.st_mtime_ns, st.st_ino, st.st_dev),
            {"bundle_id": "2026.12-1", "release_seq": 7, "warnings": []})  # fmt: skip
    assert "refuse" not in r.write_status()["verified"][f.name]
    (upd / "installed.json").write_text(json.dumps({"release_seq": 7, "bundle_id": "2026.12-1"}))
    assert r.write_status()["verified"][f.name]["refuse"] == "installed"
    (upd / "installed.json").write_text(json.dumps({"release_seq": 9, "bundle_id": "2027.01-1"}))
    assert r.write_status()["verified"][f.name]["refuse"] == "older"
    (upd / "installed.json").write_text(json.dumps({"release_seq": 6, "bundle_id": "2026.11-1"}))
    assert "refuse" not in r.write_status()["verified"][f.name]
    (upd / "trust.json").write_text('{"keys": {"b": 1}}')  # a key rotation since the check
    assert r.write_status()["verified"][f.name]["refuse"] == "trust"


def _applied(upd: Path, *bundles: str) -> None:
    upd.mkdir(parents=True, exist_ok=True)
    lines = [{"at": f"2026-11-{10 + i:02d}T05:30:00+00:00", "bundle": b, "step": "audited update.applied", "ok": True}
             for i, b in enumerate(bundles)]  # fmt: skip
    (upd / "history.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")


def test_r3_l6_the_previous_release_is_the_last_other_release_applied_and_only_when_known(tmp_path: Path) -> None:
    """L6: "the release before this one" was the second-last applied line: after the same release was applied again
    it named the current release itself."""
    r, _calls = _runner(tmp_path)
    upd = tmp_path / "deploy" / "updates"
    _applied(upd, "2026.11-1", "2026.12-1", "2026.12-1")
    assert r.write_status()["version"]["previous"] == "2026.11-1"
    _applied(upd, "2026.12-1")
    assert r.write_status()["version"]["previous"] == ""  # not known on this box: none is named
    _applied(upd, "2026.11-1", *(["2026.12-1"] * 500))  # the earlier one is past what is read: not guessed
    assert r.write_status()["version"]["previous"] == ""


def test_r3_l7_a_part_file_left_by_a_crash_in_the_incoming_folder_is_swept(tmp_path: Path) -> None:
    (tmp_path / "incoming").mkdir()
    part = tmp_path / "incoming" / ".trialbox-1.tar.part"
    part.write_bytes(b"x" * 1000)
    keep = tmp_path / "incoming" / "trialbox-2.tar"
    keep.write_bytes(b"a staged bundle")
    r, _calls = _runner(tmp_path)
    r.run_pending()
    assert not part.exists() and keep.read_bytes() == b"a staged bundle"


def test_r3_l8_the_status_stays_under_its_cap_with_hundreds_of_long_named_verified_bundles(tmp_path: Path) -> None:
    """L8: the staged-bundle list was unbounded: about 170 verified bundles with long names took the status past
    64 KiB and the page then showed only "status unreadable"."""
    inc = tmp_path / "incoming"
    inc.mkdir()
    r, _calls = _runner(tmp_path)
    for i in range(400):
        f = inc / f"trialbox-{i:03d}-{'n' * 100}.tar"
        f.write_bytes(b"x")
        fs = os.stat(f)
        r._keep(f, hashlib.sha256(b"x").hexdigest(), (fs.st_size, fs.st_mtime_ns, fs.st_ino, fs.st_dev),
                {"bundle_id": "b" * 120, "release_seq": i, "warnings": ["w" * 300] * 9})  # fmt: skip
    r.write_status()
    st, why = r.ops.status_state()
    assert why == "" and st is not None, why
    assert (tmp_path / "ops" / "status.json").stat().st_size < tb_ops.MAX_JSON
    assert st["incoming_cut"] is True and 0 < len(st["incoming"]) <= tb_ops.STICK_LIST_MAX
    assert set(st["verified"]) <= {b["name"] for b in st["incoming"]}


def test_r3_l9_two_applies_asked_at_once_queue_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """L9: the console's busy check and its submit were two steps: two posts at once both passed the check and both
    updates were queued. ``submit_once`` makes the check and the write one step under a lock: one wins."""
    import threading

    ops = tb_ops.OpsDir(tmp_path / "ops")
    tb_ops.prepare(ops)
    real = tb_ops._write_json

    def slow(path: Path, data: Any) -> None:
        time.sleep(0.3)  # widen the window between the check and the write
        real(path, data)

    monkeypatch.setattr(tb_ops, "_write_json", slow)
    got: list[str | None] = []
    ts = [threading.Thread(target=lambda n=n: got.append(ops.submit_once(
        "update_apply", "console:admin", {"bundle": f"trialbox-{n}.tar"}, busy=("update_apply",))))
        for n in range(2)]  # fmt: skip
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert sorted(x is None for x in got) == [False, True], got
    assert len([q for q in ops.pending() if q["action"] == "update_apply"]) == 1
