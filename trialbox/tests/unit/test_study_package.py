"""10D-3 (D-1372; review 14 M14-2): the study package, format v1.

Proved by: a changed byte fails verification: every single byte of a package flipped, each position class named
(header, hash list, signature, protocol part, a protocol file, a tar header, padding, the end blocks), and bytes
appended or cut, is refused. Also: the same study written twice is the same bytes; every shipped study packs and
verifies with its criteria hash; the checks run in their stated order with one sentence each; a study folder with
planted names, addresses, codes and comments in its site fields packs none of them; the command-line tool.
Keys are made at run time (``tb_common.crypto.ed25519_generate``); no key material is in the repository.
"""

from __future__ import annotations

import builtins
import contextlib
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from tb_common import study_manifest as sm
from tb_common import study_package as sp
from tb_common.crypto import ed25519_generate, ed25519_sign
from tb_common.ruleset import SEED_RULESETS

pytestmark = [pytest.mark.nodb]
ROOT = Path(__file__).resolve().parents[2]
SHIPPED = sorted(p.parent.name for p in SEED_RULESETS.glob("*/manifest.yaml"))
DAY = "2026-11-19"
PRIV, PUB = ed25519_generate()
OTHER_PRIV, OTHER_PUB = ed25519_generate()


def _folder(ruleset: str) -> dict[str, bytes]:
    d = SEED_RULESETS / ruleset
    return {p.relative_to(d).as_posix(): p.read_bytes() for p in d.rglob("*") if p.is_file()}


def _small() -> dict[str, bytes]:
    """A small study: RA-JAK's manifest, two criteria (one rejected), a value set and two synthetic test patients."""
    full = _folder("RA-JAK")
    files = {p: full[p] for p in ("manifest.yaml", "ir/RA-JAK-INC-01.json", "valuesets/VS_HBSAG.json")}
    exc = json.loads(full["ir/RA-JAK-EXC-01.json"])
    exc["review"] = {"status": "rejected", "by": "crc1@hospa.test", "at": "2026-11-11T04:31:43+08:00"}
    files["ir/RA-JAK-EXC-01.json"] = json.dumps(exc, indent=2).encode()
    files["tests/patients.ndjson"] = (
        b'{"resourceType":"Patient","id":"syn-1"}\r\n{"resourceType":"Patient","id":"syn-2"}\n'
    )
    return files


@pytest.fixture(scope="module")
def small() -> bytes:
    return sp.build(_small(), PRIV, DAY)


def _members(data: bytes) -> dict[str, bytes]:
    return sp.read_tar(data)


def _refused(data: bytes, keys: list[bytes] | None = None) -> sp.PackageRefused:
    with pytest.raises(sp.PackageRefused) as exc:
        sp.verify(data, keys if keys is not None else [PUB])
    sentence = str(exc.value)
    assert sentence.startswith("this study package") and "\n" not in sentence
    return exc.value


def _resigned(members: dict[str, bytes], private: bytes = PRIV, header: dict[str, Any] | None = None) -> bytes:
    """A package made by hand from ``members``: hash list and header made again and signed with ``private`` (a
    trusted key that signs a wrong package, so that the later checks are reached)."""
    body = {k: v for k, v in members.items() if k not in (sp.HASHES, sp.HEADER, sp.SIGNATURE)}
    hashes = sm.dumps({k: hashlib.sha256(v).hexdigest() for k, v in body.items()})
    head = dict(header if header is not None else json.loads(members[sp.HEADER]))
    if header is None or "package_id" not in header:
        head["package_id"] = sp.package_id(str(head.get("study_id")), str(head.get("version")), hashes)
    head_b = sm.dumps(head)
    sig = ed25519_sign(private, sp.signed_bytes(head_b, hashes))
    return sp.tar_bytes({**body, sp.HASHES: hashes, sp.HEADER: head_b, sp.SIGNATURE: sig})


# ---------------------------------------------------------------------------------------------- the proof
def test_every_changed_byte_fails_verification(small: bytes) -> None:
    """Every byte position, flipped (one bit, and all bits), is refused: nothing in a package is outside the
    signature, the hash list or the canonical framing."""
    assert sp.verify(small, [PUB]).header["study_id"] == "RA-JAK"
    for mask in (0x01, 0xFF):
        for i in range(len(small)):
            changed = bytearray(small)
            changed[i] ^= mask
            with pytest.raises(sp.PackageRefused):
                sp.verify(bytes(changed), [PUB])


def _offsets(data: bytes) -> dict[str, tuple[int, int]]:
    """Where each member's header block and bytes are: name -> (header offset, data offset)."""
    out = {}
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        for m in tf.getmembers():
            out[m.name] = (m.offset, m.offset_data)
    return out


def test_each_position_class_is_refused_at_its_check(small: bytes) -> None:
    at = _offsets(small)
    members = _members(small)

    def flip(i: int) -> bytes:
        changed = bytearray(small)
        changed[i] ^= 0x01
        return bytes(changed)

    # the signature's bytes: the signature check
    assert _refused(flip(at[sp.SIGNATURE][1] + 10)).step == "signature"
    # the header's and the hash list's bytes inside a JSON string: still canonical JSON, so the signature refuses
    head = members[sp.HEADER]
    assert _refused(flip(at[sp.HEADER][1] + head.index(b"RA-JAK") + 1)).step == "signature"
    hashes = members[sp.HASHES]
    assert _refused(flip(at[sp.HASHES][1] + hashes.index(b"files/") + 1)).step == "signature"
    # the protocol part's and a protocol file's bytes: the hash check
    assert _refused(flip(at[sp.PROTOCOL][1] + 40)).step == "hashes"
    assert _refused(flip(at["files/tests/patients.ndjson"][1] + 3)).step == "hashes"
    # a tar header's name, mode, mtime, owner name, checksum and unused bytes; the zero padding after a member's
    # bytes; the two end blocks: the archive check
    h = at["files/valuesets/VS_HBSAG.json"][0]
    for field in (5, 102, 140, 265, 150, 505):
        assert _refused(flip(h + field)).step == "tar", field
    pad = at[sp.SIGNATURE][1] + 64 + 3
    assert _refused(flip(pad)).step == "tar"
    assert _refused(flip(len(small) - 700)).step == "tar"
    assert _refused(flip(len(small) - 1)).step == "tar"
    # bytes appended after the archive (a whole block, a byte), and the archive cut short
    for tail in (bytes(512), b"\x00", b"x" * 512, bytes(10240 - len(small) % 10240)):
        assert _refused(small + tail).step == "tar"
    assert _refused(small[:-512]).step == "tar"
    assert _refused(small[:-1]).step == "tar"
    assert _refused(small[: at[sp.PROTOCOL][1] + 10]).step == "tar"


def test_same_study_twice_gives_the_same_bytes(small: bytes) -> None:
    assert sp.build(_small(), PRIV, DAY) == small
    assert (
        hashlib.sha256(sp.build_dir(SEED_RULESETS / "RA-JAK", PRIV, DAY)).digest()
        == hashlib.sha256(sp.build_dir(SEED_RULESETS / "RA-JAK", PRIV, DAY)).digest()
    )
    # the date and the key are the writer's: each changes the header, not the package id
    other_day = sp.build(_small(), PRIV, "2026-11-20")
    other_key = sp.build(_small(), OTHER_PRIV, DAY)
    assert len({small, other_day, other_key}) == 3
    ids = {sp.header_of(b)["package_id"] for b in (small, other_day, other_key)}
    assert len(ids) == 1


@pytest.mark.parametrize("ruleset", SHIPPED)
def test_every_shipped_study_packs_and_verifies(ruleset: str) -> None:
    data = sp.build_dir(SEED_RULESETS / ruleset, PRIV, DAY)
    got = sp.verify(data, [OTHER_PUB, PUB])
    parts = sm.split_dir(SEED_RULESETS / ruleset)
    assert got.header["criteria_sha256"] == parts.criteria_sha256 == got.protocol["criteria_sha256"]
    assert got.protocol == parts.protocol and set(got.files) == set(parts.protocol["files"])
    assert got.header["study_id"] == ruleset and got.header["pins"] == {} and got.header["key_id"] == sp.key_id(PUB)
    # an ordinary tar reader reads it: regular files, fixed fields, names in byte order, no extended header
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        infos = tf.getmembers()
    names = [i.name for i in infos]
    assert names == sorted(names, key=lambda n: n.encode()) and len(names) == len(got.files) + 4
    assert all(i.isreg() and i.mode == 0o644 and i.mtime == 0 and i.uid == i.gid == 0 for i in infos)
    assert all(i.uname == i.gname == "" and not i.pax_headers for i in infos)
    # no site part: no address, approver, IRB record, routing or equivalence run of the shipped folders
    assert not re.search(rb"[\w.+-]+@[\w-]+\.[\w.-]+", data)
    for planted in (b"approved_by", b"irb_", b"routing", b"equivalence", b"scopes", b"crc1"):
        assert planted not in data, planted


# ---------------------------------------------------------------------------------------------- the order
def test_an_untrusted_or_missing_key_is_refused(small: bytes) -> None:
    assert _refused(small, [OTHER_PUB]).step == "signature"
    assert "not a trusted coordinating-centre key" in str(_refused(small, []))
    assert _refused(sp.build(_small(), OTHER_PRIV, DAY)).step == "signature"
    with pytest.raises(sp.PackageRefused, match="not an Ed25519 public key"):
        sp.verify(small, [b"-----BEGIN PUBLIC KEY-----\nnot a key\n-----END PUBLIC KEY-----\n"])
    # a header naming a trusted key id but signed by another key
    members = _members(small)
    header = json.loads(members[sp.HEADER])
    forged = _resigned(members, OTHER_PRIV, header)
    assert "does not verify" in str(_refused(forged))


def test_the_key_id_is_the_update_bundles() -> None:
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    from tools.verify_update import key_id

    assert sp.key_id(PUB) == key_id(load_pem_public_key(PUB))


def _pax(members: dict[str, bytes], fmt: int = tarfile.PAX_FORMAT, **extra: Any) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=fmt) as tf:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            for k, v in extra.items():
                setattr(info, k, v)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_archive_rules_refused_before_the_signature(small: bytes, monkeypatch: pytest.MonkeyPatch) -> None:
    members = _members(small)

    def raw_tar(names: list[tuple[str, bytes, bytes]]) -> bytes:
        out = bytearray()
        for name, data, kind in names:
            block = bytearray(sp._block("x", len(data)))
            block[0:100] = name.encode().ljust(100, b"\x00")[:100]
            block[156:157] = kind
            block[148:156] = b" " * 8
            block[148:156] = b"%06o\x00 " % sum(block)
            out += block + data + bytes(-len(data) % 512)
        return bytes(out + bytes(1024))

    cases = {
        "../escape.json": raw_tar([("../escape.json", b"{}", b"0")]),
        "/abs.json": raw_tar([("/abs.json", b"{}", b"0")]),
        "a symbolic link": raw_tar([("files/labels.yaml", b"", b"2")]),
        "a hard link": raw_tar([("files/labels.yaml", b"", b"1")]),
        "a folder": raw_tar([("files", b"", b"5")]),
        "an extended header": _pax({"files/labels.yaml": b"x"}, pax_headers={"comment": "x"}),
        "a GNU archive": _pax({sp.HEADER: members[sp.HEADER]}, fmt=tarfile.GNU_FORMAT),
        "a duplicate": raw_tar([(sp.HEADER, members[sp.HEADER], b"0")] * 2),
        "a site file": sp.tar_bytes({**members, "files/tests/equivalence.json": b"{}"}),
        "a stray file": sp.tar_bytes({**members, "files/notes.txt": b"x"}),
        "no header": sp.tar_bytes({k: v for k, v in members.items() if k != sp.HEADER}),
        "a short signature": sp.tar_bytes({**members, sp.SIGNATURE: b"x" * 63}),
        "a header not canonical": sp.tar_bytes(
            {**members, sp.HEADER: json.dumps(json.loads(members[sp.HEADER]), indent=1).encode()}
        ),
        "mode 0755": _pax(dict(sorted(members.items())), fmt=tarfile.USTAR_FORMAT, mode=0o755),
        "a tarfile record": _pax(dict(sorted(members.items())), fmt=tarfile.USTAR_FORMAT, mode=0o644, mtime=0),
        "an empty file": b"",
        "not blocks": small[:-100],
    }
    for why, data in cases.items():
        assert _refused(data).step == "tar", why
    # an unknown header field (a v1 header is closed) and a pin v1 does not know (10D-26's) are refused
    header = json.loads(members[sp.HEADER])
    for bad, words in (
        ({**header, "central_approval": "IRB-1"}, "does not have"),
        ({k: v for k, v in header.items() if k != "created"}, "lacks the field created"),
        ({**header, "pins": {"verifier_prompt": "abc"}}, "newer release"),
        ({**header, "format": "tb-study-package/2"}, "format"),
        ({**header, "created": "19 Nov 2026"}, "YYYY-MM-DD"),
    ):
        assert words in str(_refused(_resigned(members, header=bad)))
    # the caps
    monkeypatch.setattr(sp, "STUDY_PACKAGE_MAX_MEMBERS", 5)
    assert "more than 5 members" in str(_refused(small))
    monkeypatch.setattr(sp, "STUDY_PACKAGE_MAX_MEMBERS", 2000)
    monkeypatch.setattr(sp, "STUDY_PACKAGE_MAX_MEMBER_BYTES", 300)
    assert "may be at most 300 bytes" in str(_refused(small))
    monkeypatch.setattr(sp, "STUDY_PACKAGE_MAX_BYTES", len(small) - 1)
    assert f"may be at most {len(small) - 1:,} bytes" in str(_refused(small))


def test_member_set_and_hashes_after_the_signature(small: bytes) -> None:
    members = _members(small)
    # a member the signed list does not name, one it names and the package lacks, one whose bytes changed
    extra = sp.tar_bytes({**members, "files/labels.yaml": b"labels: {}\n"})
    assert "which its signed hash list does not name" in str(_refused(extra))
    lacking = sp.tar_bytes({k: v for k, v in members.items() if k != "files/valuesets/VS_HBSAG.json"})
    assert "lacks files/valuesets/VS_HBSAG.json" in str(_refused(lacking))
    changed = sp.tar_bytes({**members, "files/tests/patients.ndjson": b'{"id":"syn-3"}\n'})
    assert _refused(changed).step == "hashes"


def test_criteria_hash_check_last(small: bytes) -> None:
    """A trusted key that signs a wrong package still meets the last check: the criteria hash computed again from
    the carried files by ``study_manifest``."""
    members = _members(small)
    # a carried file changed with its hash in the list, the protocol part not
    swapped = _resigned({**members, "files/tests/patients.ndjson": b'{"id":"syn-3"}\n'})
    assert "does not carry the protocol's file tests/patients.ndjson" in str(_refused(swapped))
    # the protocol part's threshold changed without its criteria hash
    protocol = json.loads(members[sp.PROTOCOL])
    protocol["manifest"]["thresholds"]["small_cell"] = 3
    edited = _resigned({**members, sp.PROTOCOL: sm.dumps(protocol)})
    assert "changed after its criteria hash was taken" in str(_refused(edited))
    # ... and with its criteria hash taken again: the header's hash is another
    protocol["criteria_sha256"] = sm.criteria_sha256(protocol)
    rehashed = _resigned({**members, sp.PROTOCOL: sm.dumps(protocol)})
    assert "criteria_sha256 is not its protocol part's" in str(_refused(rehashed))
    # a file carried with CR LF (not its canonical form), listed so in the protocol part and the header
    crlf = b'{"resourceType":"Patient","id":"syn-1"}\r\n'
    protocol = json.loads(members[sp.PROTOCOL])
    protocol["files"]["tests/patients.ndjson"] = hashlib.sha256(crlf).hexdigest()
    protocol["criteria_sha256"] = sm.criteria_sha256(protocol)
    header = {**json.loads(members[sp.HEADER]), "criteria_sha256": protocol["criteria_sha256"]}
    raw = _resigned({**members, sp.PROTOCOL: sm.dumps(protocol), "files/tests/patients.ndjson": crlf}, header=header)
    assert "not in the canonical form of its protocol file" in str(_refused(raw))
    # a site key smuggled into the protocol part
    protocol = json.loads(members[sp.PROTOCOL])
    protocol["manifest"]["routing"] = {"list_to": ["x@y.test"]}
    protocol["criteria_sha256"] = sm.criteria_sha256(protocol)
    header = {**json.loads(members[sp.HEADER]), "criteria_sha256": protocol["criteria_sha256"]}
    site = _resigned({**members, sp.PROTOCOL: sm.dumps(protocol)}, header=header)
    assert _refused(site).step == "protocol"


def test_verify_writes_nothing(small: bytes, monkeypatch: pytest.MonkeyPatch) -> None:
    def no(*_a: object, **_k: object) -> None:
        raise AssertionError("verify opened a file")

    real_open: Callable[..., Any] = builtins.open
    monkeypatch.setattr(builtins, "open", no)
    monkeypatch.setattr(os, "open", no)
    monkeypatch.setattr(Path, "write_bytes", no)
    try:
        bad = bytearray(small)
        bad[-2000] ^= 1
        for data in (small, bytes(bad)):
            with contextlib.suppress(sp.PackageRefused):
                sp.verify(data, [PUB])
    finally:
        monkeypatch.setattr(builtins, "open", real_open)


# ---------------------------------------------------------------------------------------------- no site data
PLANTED = (
    "Planted Okabe Rintaro",
    "planted.pi@site-x.test",
    "planted.crc@site-x.test",
    "IRB-PLANTED-0042",
    "PLANTPRAC77",
    "PLANTDEPT9",
    "planted review comment",
    "planted-judge-model",
    "planted equivalence",
    "planted-notes",
)


def test_planted_site_data_is_in_no_byte_of_the_package() -> None:
    files = _folder("RA-JAK")
    m = yaml.safe_load(files["manifest.yaml"])
    m["routing"] = {"list_to": ["planted.pi@site-x.test"], "aggregate_to": ["planted.crc@site-x.test"]}
    m["review"] = {"approved_by": "Planted Okabe Rintaro", "approved_via": "planted review comment", "rounds": 1}
    m["irb_reference"] = "IRB-PLANTED-0042"
    m["irb_approved_on"] = "2026-10-01"
    m["scopes"]["screen"]["practitioners"] = ["PLANTPRAC77"]
    m["scopes"]["screen"]["departments"] = ["PLANTDEPT9"]
    m["models"]["judge"] = "planted-judge-model"
    m["equivalence"]["failing"] = ["planted equivalence"]
    files["manifest.yaml"] = yaml.safe_dump(m, allow_unicode=True).encode()
    for i, path in enumerate(sorted(p for p in files if p.startswith("ir/"))):
        doc = json.loads(files[path])
        doc["review"] = {
            "status": "rejected" if i == 0 else "approved",
            "by": "planted.crc@site-x.test",
            "at": "2026-11-11T04:31:43+08:00",
            "comment": "planted review comment from Planted Okabe Rintaro",
        }
        files[path] = json.dumps(doc, ensure_ascii=False).encode()
    files["tests/equivalence.json"] = b'{"by": "planted.pi@site-x.test", "note": "planted equivalence"}'
    files["notes.txt"] = b"planted-notes Planted Okabe Rintaro IRB-PLANTED-0042"
    folder = "\n".join(f.decode("utf-8", "replace") for f in files.values())
    assert all(p in folder for p in PLANTED)  # each is in the folder
    data = sp.build(files, PRIV, DAY)
    got = sp.verify(data, [PUB])
    for planted in PLANTED:
        for enc in ("utf-8", "utf-16-le", "utf-16-be"):
            assert planted.encode(enc) not in data, planted
        assert planted.lower().encode() not in data.lower(), planted
    assert got.header["criteria_sha256"] == sm.split(files).criteria_sha256
    # a criterion's "rejected" stays (the protocol's), its reviewer and comment do not
    rejected = sorted(p for p in got.files if p.startswith("ir/"))[0]
    assert json.loads(got.files[rejected])["review"] == {"status": "rejected"}


def test_a_study_folder_holding_its_template_is_not_packed() -> None:
    files = _small()
    m = yaml.safe_load(files["manifest.yaml"])
    m["docx_template"] = "form.docx"
    files["manifest.yaml"] = yaml.safe_dump(m, allow_unicode=True).encode()
    files["form.docx"] = b"PK\x03\x04 docProps/core.xml dc:creator Planted Okabe Rintaro"
    with pytest.raises(ValueError, match="does not carry a template"):
        sp.build(files, PRIV, DAY)
    del files["form.docx"]  # named but not in the folder: not hashed (D-1366), packed
    assert sp.verify(sp.build(files, PRIV, DAY), [PUB]).protocol["manifest"]["docx_template"] == "form.docx"


def test_test_patients_name_only_placeholders() -> None:
    """The owner's yes to the export (2026-11-19): the test patients leave the box only with the synthetic practitioner
    and department placeholders; the department system is named site-local."""
    dept = "https://trialbox.local/fhir/CodeSystem/department"
    assert dept in sp.SITE_LOCAL_CODE_SYSTEMS
    good = {
        "resourceType": "Appointment",
        "id": "a1",
        "participant": [{"actor": {"reference": "Practitioner/P12345"}}, {"actor": {"reference": "Patient/syn-1"}}],
        "serviceType": [{"coding": [{"system": dept, "code": "RHEU"}]}],
    }
    files = _small()
    files["tests/patients.ndjson"] = json.dumps(good).encode() + b"\n"
    assert sp.verify(sp.build(files, PRIV, DAY), [PUB]).files["tests/patients.ndjson"]
    bad_cases = {
        "practitioner": ({**good, "participant": [{"actor": {"reference": "Practitioner/PLANTPRAC77"}}]}, "practitioner"),
        "role": ({**good, "participant": [{"actor": {"reference": "PractitionerRole/R9"}}]}, "practitioner"),
        "department": ({**good, "serviceType": [{"coding": [{"system": dept, "code": "PLANTDEPT9"}]}]}, "hospital's own"),
        "record": ({"resourceType": "Practitioner", "id": "P12345", "name": [{"text": "Planted"}]}, "record"),
    }
    for resource, says in bad_cases.values():
        files["tests/patients.ndjson"] = json.dumps(good).encode() + b"\n" + json.dumps(resource).encode() + b"\n"
        with pytest.raises(ValueError, match=f"line 2 of tests/patients.ndjson .*{re.escape(says)}"):
            sp.build(files, PRIV, DAY)
    files["tests/patients.ndjson"] = b'{"resourceType": "Patient"\n'
    with pytest.raises(ValueError, match="is not JSON"):
        sp.build(files, PRIV, DAY)
    files["tests/patients.ndjson"] = b"[" * 300 + b"]" * 300 + b"\n"
    with pytest.raises(ValueError, match="nests deeper"):
        sp.build(files, PRIV, DAY)


def test_the_writer_gives_the_date() -> None:
    for bad in ("2026-13-01", "20261119", ""):
        with pytest.raises(ValueError):
            sp.build(_small(), PRIV, bad)


def _nested(depth: int) -> bytes:
    return b"[" * depth + b"]" * depth


def test_deep_json_is_refused_before_it_is_parsed(small: bytes) -> None:
    """A JSON member nested past the limit is refused with a sentence, never a RecursionError: the header and the
    hash list before the signature (no key needed), the protocol part and a carried file with a trusted signer."""
    members = _members(small)
    deep_header = sp.tar_bytes({**members, sp.HEADER: _nested(200_000)})
    deep_hashes = sp.tar_bytes({**members, sp.HASHES: b'{"a":' * 100_000 + b"1" + b"}" * 100_000})
    for data in (deep_header, deep_hashes):
        got = _refused(data)
        assert got.step == "tar" and "nests deeper than 200" in str(got)
    deep_protocol = _resigned({**members, sp.PROTOCOL: _nested(100_000)})
    deep_file = _resigned({**members, "files/valuesets/VS_HBSAG.json": b'{"a":' * 50_000 + b"1" + b"}" * 50_000})
    for data in (deep_protocol, deep_file):
        got = _refused(data)
        assert got.step == "protocol" and "nests deeper than 200" in str(got)
    # at the limit a JSON value is read and written; one deeper is refused; brackets in strings do not count
    assert sm.dumps(sm.load_json(_nested(200))) == _nested(200)
    assert sp.json_depth(_nested(200)) == 200 and sp.json_depth(_nested(201)) == 201
    assert sp.json_depth(b'{"a":"[[[[\\\\\\"[[","b":[1]}') == 2
    # the writer refuses a folder with such a file
    files = {**_small(), "valuesets/VS_DEEP.json": _nested(201)}
    with pytest.raises(ValueError, match="nests deeper than 200"):
        sp.build(files, PRIV, DAY)


def test_the_package_id_is_checked(small: bytes) -> None:
    members = _members(small)
    header = {**json.loads(members[sp.HEADER]), "package_id": "OTHER-9-0000000000000000"}
    got = _refused(_resigned(members, header=header))
    assert got.step == "protocol" and "package_id" in str(got)
    assert sp.header_of(small)["package_id"] == sp.package_id("RA-JAK", "1.0.0", members[sp.HASHES])


def _locked(private_pem: bytes) -> bytes:
    from cryptography.hazmat.primitives import serialization

    key = serialization.load_pem_private_key(private_pem, password=None)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(b"synthetic-test-passphrase"),
    )


def test_versions_are_texts_and_the_key_unencrypted() -> None:
    # the manifest schema refuses a version or protocol_version that is not a text (an unquoted 1.0 in YAML); the
    # writer refuses an empty one
    for field, value, words in (("version", 1.0, "string"), ("protocol_version", 1.0, "string"),
                                ("protocol_version", "", "its protocol_version written as a text")):  # fmt: skip
        files = _small()
        m = yaml.safe_load(files["manifest.yaml"])
        m[field] = value
        files["manifest.yaml"] = yaml.safe_dump(m, allow_unicode=True).encode()
        with pytest.raises(ValueError, match=words):
            sp.build(files, PRIV, DAY)
    with pytest.raises(ValueError, match="not an unencrypted Ed25519 private key"):
        sp.build(_small(), _locked(PRIV), DAY)


def test_a_size_that_runs_into_the_next_header_says_so(small: bytes) -> None:
    head = bytearray(small[:512])
    size = int(head[124:135], 8)
    head[124:136] = b"%011o\x00" % (size + 600)
    head[148:156] = b" " * 8
    head[148:156] = b"%06o\x00 " % sum(head)
    got = _refused(bytes(head) + small[512:])
    assert "declares a size that does not match its bytes" in str(got)


# ---------------------------------------------------------------------------------------------- the tool
def _run(*args: str) -> subprocess.CompletedProcess[str]:
    # PYTHONUNBUFFERED out: a CI runner does not set it
    env = {k: v for k, v in os.environ.items() if k != "PYTHONUNBUFFERED"}
    env["PYTHONPATH"] = "libs:services:."
    return subprocess.run(
        [sys.executable, "-m", "tools.study_package", *args], check=False, cwd=ROOT, env=env, capture_output=True,
        text=True,
        timeout=300,
    )  # fmt: skip


def test_command_line(tmp_path: Path) -> None:
    keys = tmp_path / "keys"
    r = _run("keygen", "--out", str(keys))
    assert r.returncode == 0, r.stderr
    priv, pub = keys / "cc_ed25519.key", keys / "cc_ed25519.pub"
    assert priv.stat().st_mode & 0o777 == 0o600
    assert _run("keygen", "--out", str(keys)).returncode == 1  # a key is never replaced
    study = tmp_path / "RA-JAK"
    for path, data in _small().items():
        (study / path).parent.mkdir(parents=True, exist_ok=True)
        (study / path).write_bytes(data)
    out = tmp_path / "RA-JAK.tbstudy"
    w = _run("write", str(study), "--key", str(priv), "--out", str(out), "--created", DAY)
    assert w.returncode == 0, w.stderr
    assert "package RA-JAK-1.0.0-" in w.stdout and sp.key_id(pub.read_bytes()) in w.stdout
    v = _run("verify", str(out), "--trust", str(pub))
    assert v.returncode == 0 and v.stdout.startswith("verified "), v.stderr
    s = _run("show", str(out))
    assert s.returncode == 0 and json.loads(s.stdout.split("\n(")[0])["study_id"] == "RA-JAK"
    assert "not checked" in s.stdout
    # another key, and a changed byte: refused with one sentence, exit 1
    other = tmp_path / "other.pub"
    other.write_bytes(OTHER_PUB)
    bad = _run("verify", str(out), "--trust", str(other))
    assert bad.returncode == 1 and bad.stderr.count("\n") == 1 and "not a trusted" in bad.stderr
    flipped = bytearray(out.read_bytes())
    flipped[1000] ^= 1
    out.write_bytes(bytes(flipped))
    assert _run("verify", str(out), "--trust", str(pub)).returncode == 1
    # an existing --out is not replaced without --force
    again = _run("write", str(study), "--key", str(priv), "--out", str(out), "--created", DAY)
    assert again.returncode == 1 and "--force" in again.stderr and out.read_bytes() == bytes(flipped)
    forced = _run("write", str(study), "--key", str(priv), "--out", str(out), "--created", DAY, "--force")
    assert forced.returncode == 0 and _run("verify", str(out), "--trust", str(pub)).returncode == 0
    # an encrypted key: one sentence, exit 1, no traceback
    locked = tmp_path / "locked.key"
    locked.write_bytes(_locked(priv.read_bytes()))
    locked.chmod(0o600)
    enc = _run("write", str(study), "--key", str(locked), "--out", str(tmp_path / "y"), "--created", DAY)
    assert enc.returncode == 1 and enc.stderr.count("\n") == 1 and "Traceback" not in enc.stderr
    assert "unencrypted" in enc.stderr
    # a key file others may read is not used
    priv.chmod(0o644)
    loose = _run("write", str(study), "--key", str(priv), "--out", str(tmp_path / "x"), "--created", DAY)
    assert loose.returncode == 1 and "make it 600" in loose.stderr and not (tmp_path / "x").exists()
    # no key material is ever printed
    secret = priv.read_bytes()
    for result in (r, w, v, s, bad, loose, again, forced, enc):
        text = result.stdout + result.stderr
        assert "PRIVATE KEY" not in text and "PUBLIC KEY" not in text
        assert not any(line in text for line in secret.decode().splitlines()[1:-1])
