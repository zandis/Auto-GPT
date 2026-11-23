"""T-210c (CR-041 last third, D-354): uploads and outputs sealed at rest under ``objects.key``, itself wrapped under
the site KEK (D-347). No plaintext of a sealed bucket on disk; a service that cannot open the key fails closed."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from tb_common import kek as K
from tb_common import objstore as O
from tb_common.crypto import create_key

from tools import keys as keys_cli

PATIENT = "王小明 A123456789 chart 00012345".encode()


@pytest.fixture
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """A secrets folder with a KEK (file back end) unsealed to a runtime file outside it, and an empty store."""
    for var in ("TB_KEK_FILE", "TB_KEK_PASSPHRASE", "CREDENTIALS_DIRECTORY", "TB_SECRETS_DIR", "TB_OBJECT_STORE"):
        monkeypatch.delenv(var, raising=False)
    sec = tmp_path / "secrets"
    sec.mkdir()
    create_key(sec / "site_hmac.key")
    run = tmp_path / "run"
    run.mkdir()
    monkeypatch.setenv("TB_KEK_FILE", str(run / "kek"))
    kek_out = tmp_path / "usb" / "trialbox.kek"
    assert keys_cli.main(["init", "--secrets", str(sec), "--backend", "file", "--kek-out", str(kek_out)]) == 0
    assert keys_cli.main(["unseal", "--secrets", str(sec), "--from", str(kek_out)]) == 0
    root = tmp_path / "obj"
    root.mkdir()
    return {"sec": sec, "root": root, "kek": run / "kek", "tmp": tmp_path}


def _cli(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    rc = keys_cli.main(list(argv))
    out = capsys.readouterr()
    return rc, out.out + out.err


def _seal(box: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> str:
    rc, out = _cli(capsys, "seal-objects", "--secrets", str(box["sec"]), "--store", str(box["root"]))
    assert rc == 0, out
    return out


def _disk(root: Path) -> bytes:
    return b"".join(p.read_bytes() for p in root.rglob("*") if p.is_file())


def test_a_plain_store_is_unchanged(tmp_path: Path) -> None:
    st = O.FsStore(tmp_path / "obj")
    st.put("outputs/J1/list.xlsx", PATIENT)
    assert (tmp_path / "obj/outputs/J1/list.xlsx").read_bytes() == PATIENT
    assert st.get("outputs/J1/list.xlsx") == PATIENT and not st.sealed()


def test_sealed_store_round_trips_and_leaves_no_plaintext_on_disk(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    out = _seal(box, capsys)
    assert "objects.key made" in out
    assert (box["sec"] / "objects.key.wrapped").exists() and not (box["sec"] / "objects.key").exists()
    st = O.FsStore(box["root"], box["sec"])
    for key in ("attachments/J1/chart.md", "outputs/J1/phi_list.xlsx", "twpas/J1/bundle.json"):
        st.put(key, PATIENT)
        assert O.is_sealed_blob((box["root"] / key).read_bytes())
        assert st.get(key) == PATIENT
    st.put("rulesets/GZQO/doc.txt", b"public criteria")  # not a patient bucket: plain as before
    assert (box["root"] / "rulesets/GZQO/doc.txt").read_bytes() == b"public criteria"
    assert b"A123456789" not in _disk(box["root"])
    assert not list(box["root"].rglob("*.tmp"))
    assert [i.key for i in st.list("outputs/J1/")] == ["outputs/J1/phi_list.xlsx"]
    rc, out = _cli(capsys, "seal-objects", "--secrets", str(box["sec"]), "--store", str(box["root"]), "--check")
    assert rc == 0 and "no plain object" in out


def test_a_sealed_file_moved_to_another_key_or_changed_is_refused(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _seal(box, capsys)
    st = O.FsStore(box["root"], box["sec"])
    st.put("outputs/J1/a.xlsx", PATIENT)
    (box["root"] / "outputs/J2").mkdir(parents=True)
    os.replace(box["root"] / "outputs/J1/a.xlsx", box["root"] / "outputs/J2/a.xlsx")
    with pytest.raises(O.SealError, match="moved"):
        st.get("outputs/J2/a.xlsx")
    st.put("outputs/J1/b.xlsx", PATIENT)
    p = box["root"] / "outputs/J1/b.xlsx"
    blob = bytearray(p.read_bytes())
    blob[-1] ^= 1
    p.write_bytes(bytes(blob))
    with pytest.raises(O.SealError, match="damaged"):
        st.get("outputs/J1/b.xlsx")


def test_a_service_without_the_kek_or_the_secrets_folder_fails_closed(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _seal(box, capsys)
    O.FsStore(box["root"], box["sec"]).put("attachments/J1/chart.md", PATIENT)
    box["kek"].unlink()  # not unsealed on this boot
    locked = O.FsStore(box["root"], box["sec"])
    with pytest.raises(K.KekLockedError):
        locked.put("attachments/J2/chart.md", PATIENT)
    with pytest.raises(K.KekLockedError):
        locked.get("attachments/J1/chart.md")
    assert not (box["root"] / "attachments/J2").exists()  # nothing written, plain or otherwise
    nosec = O.FsStore(box["root"])  # a service with no secrets folder mounted
    with pytest.raises(O.SealError, match="no secrets folder"):
        nosec.put("outputs/J3/x.xlsx", PATIENT)
    assert not (box["root"] / "outputs/J3").exists()


def test_seal_objects_converts_older_plain_objects_and_is_idempotent(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    plain = O.FsStore(box["root"])
    plain.put("attachments/J0/message.eml", PATIENT)
    plain.put("outputs/J0/list.xlsx", PATIENT)
    (box["root"] / "outputs/J0/left.xlsx.tmp").write_bytes(PATIENT)  # an interrupted write
    rc, out = _cli(capsys, "seal-objects", "--secrets", str(box["sec"]), "--store", str(box["root"]), "--check")
    assert rc == 1 and "not sealed" in out
    out = _seal(box, capsys)
    assert "2 object(s) sealed now" in out
    assert not O.plain_objects(box["root"]) and b"A123456789" not in _disk(box["root"])
    st = O.FsStore(box["root"], box["sec"])
    assert st.get("attachments/J0/message.eml") == PATIENT and st.get("outputs/J0/list.xlsx") == PATIENT
    fp = json.loads((box["root"] / O.SEAL_FILE).read_text())["fingerprint"]
    out = _seal(box, capsys)
    assert "already there" in out and "0 object(s) sealed now" in out
    assert json.loads((box["root"] / O.SEAL_FILE).read_text())["fingerprint"] == fp
    # a plain file put back by hand (or written by an old service) is caught by the check
    (box["root"] / "outputs/J9").mkdir()
    (box["root"] / "outputs/J9/x.json").write_bytes(PATIENT)
    rc, out = _cli(capsys, "seal-objects", "--secrets", str(box["sec"]), "--store", str(box["root"]), "--check")
    assert rc == 1 and "1 plain object" in out and "outputs/J9/x.json" in out
    assert "A123456789" not in out


def test_sealing_needs_a_kek_and_the_object_key_is_never_plain(
    tmp_path: Path, box: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    bare = tmp_path / "bare-secrets"
    bare.mkdir()
    rc, out = _cli(capsys, "seal-objects", "--secrets", str(bare), "--store", str(box["root"]))
    assert rc == 1 and "no KEK" in out and not (box["root"] / O.SEAL_FILE).exists()
    _seal(box, capsys)
    (box["sec"] / "objects.key").write_bytes(os.urandom(32))  # a plain copy beside the wrapped one
    with pytest.raises(K.KekError):
        O.FsStore(box["root"], box["sec"]).put("outputs/J1/a.xlsx", PATIENT)
    (box["sec"] / "objects.key").unlink()
    (box["sec"] / "objects.key.wrapped").rename(box["tmp"] / "away.wrapped")
    with pytest.raises(O.SealError, match="not here"):
        O.FsStore(box["root"], box["sec"]).put("outputs/J1/a.xlsx", PATIENT)


def test_another_object_key_than_the_sealed_one_is_refused(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _seal(box, capsys)
    w = box["sec"] / "objects.key.wrapped"
    w.unlink()
    K.store_key(box["sec"] / "objects.key", os.urandom(32), K.load_kek(box["sec"]))  # a new key under the same KEK
    with pytest.raises(O.SealError, match="not the key the store was sealed with"):
        O.FsStore(box["root"], box["sec"]).put("outputs/J1/a.xlsx", PATIENT)


def test_custody_lists_the_object_key_once_made_and_rotate_kek_keeps_objects_readable(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    assert "objects.key" not in K.custody(box["sec"]).keys  # optional until the store is sealed
    _seal(box, capsys)
    c = K.custody(box["sec"])
    assert c.keys["objects.key"] == "wrapped" and not c.problems
    O.FsStore(box["root"], box["sec"]).put("outputs/J1/a.xlsx", PATIENT)
    new_out = box["tmp"] / "usb2" / "trialbox.kek"
    (box["tmp"] / "audit").mkdir(exist_ok=True)  # every rotation is an audit event (ruling 7114085298)
    rc, out = _cli(capsys, "rotate-kek", "--secrets", str(box["sec"]), "--backend", "file", "--kek-out", str(new_out),
                   "--audit-dir", str(box["tmp"] / "audit"))  # fmt: skip
    assert rc == 0 and "2 key(s) re-wrapped" in out, out
    assert O.FsStore(box["root"], box["sec"]).get("outputs/J1/a.xlsx") == PATIENT


def test_from_env_passes_the_secrets_folder(box: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    _seal(box, capsys)
    st = O.from_env(f"fs:{box['root']}", "/data", str(box["sec"]))
    st.put("attachments/J1/chart.md", PATIENT)
    assert st.get("attachments/J1/chart.md") == PATIENT
    assert O.is_sealed_blob((box["root"] / "attachments/J1/chart.md").read_bytes())


def test_the_inventory_names_the_object_key(capsys: pytest.CaptureFixture[str]) -> None:
    rc, out = _cli(capsys, "inventory", "--json")
    row = next(r for r in json.loads(out) if r["key"] == "objects.key")
    assert rc == 0 and "wrapped" in row["where"] and row["rotation"] and row["compromise"]
