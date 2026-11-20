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
import inspect
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
#: each key trusted for every shipped study (H5: a key is trusted only for the studies its entry names)
TRUST = sp.TrustedKey(PUB, frozenset(SHIPPED))
OTHER_TRUST = sp.TrustedKey(OTHER_PUB, frozenset(SHIPPED))


def _patient_lines(n: int, ruleset: str = "GZQO") -> list[bytes]:
    """The first ``n`` Patient lines of a shipped study's synthetic test patients (the synthetic site's pseudonyms)."""
    lines = (SEED_RULESETS / ruleset / "tests" / "patients.ndjson").read_bytes().splitlines()
    return [line for line in lines if b'"resourceType":"Patient"' in line][:n]


SYN1, SYN2 = _patient_lines(2)
PID1 = json.loads(SYN1)["id"]


def _folder(ruleset: str) -> dict[str, bytes]:
    d = SEED_RULESETS / ruleset
    return {p.relative_to(d).as_posix(): p.read_bytes() for p in d.rglob("*") if p.is_file()}


def _small() -> dict[str, bytes]:
    """A small study: RA-JAK's manifest naming two criteria (one rejected) and no CQL library, their two IR files, a
    value set and two synthetic test patients (the synthetic site's, the first line written with CR LF)."""
    full = _folder("RA-JAK")
    files = {p: full[p] for p in ("ir/RA-JAK-INC-01.json", "valuesets/VS_HBSAG.json")}
    m = yaml.safe_load(full["manifest.yaml"])
    m["criteria"] = ["RA-JAK-EXC-01", "RA-JAK-INC-01"]
    del m["library"]
    files["manifest.yaml"] = yaml.safe_dump(m, allow_unicode=True).encode()
    exc = json.loads(full["ir/RA-JAK-EXC-01.json"])
    exc["review"] = {"status": "rejected", "by": "crc1@hospa.test", "at": "2026-11-11T04:31:43+08:00"}
    files["ir/RA-JAK-EXC-01.json"] = json.dumps(exc, indent=2).encode()
    files["tests/patients.ndjson"] = SYN1 + b"\r\n" + SYN2 + b"\n"
    return files


@pytest.fixture(scope="module")
def small() -> bytes:
    return sp.build(_small(), PRIV, DAY)


def _members(data: bytes) -> dict[str, bytes]:
    return sp.read_tar(data)


def _refused(data: bytes, keys: list[sp.TrustedKey] | None = None) -> sp.PackageRefused:
    with pytest.raises(sp.PackageRefused) as exc:
        sp.verify(data, keys if keys is not None else [TRUST])
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
    assert sp.verify(small, [TRUST]).header["study_id"] == "RA-JAK"
    for mask in (0x01, 0xFF):
        for i in range(len(small)):
            changed = bytearray(small)
            changed[i] ^= mask
            with pytest.raises(sp.PackageRefused):
                sp.verify(bytes(changed), [TRUST])


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
    got = sp.verify(data, [OTHER_TRUST, TRUST])
    parts = sm.split_dir(SEED_RULESETS / ruleset)
    assert got.header["criteria_sha256"] == parts.criteria_sha256 == got.protocol["criteria_sha256"]
    assert got.protocol == parts.protocol and set(got.files) == set(parts.protocol["files"])
    assert got.header["study_id"] == ruleset and got.header["pins"] == {} and got.header["key_id"] == sp.key_id(PUB)
    # the two members read before the signature, measured (review of 02b55d8a, item 1): their caps are far above
    meta = sp.read_tar(data)
    assert len(meta[sp.HEADER]) <= 296 and len(meta[sp.HASHES]) <= 5390
    assert len(meta[sp.HEADER]) * 200 <= sp.STUDY_PACKAGE_MAX_HEADER_BYTES
    assert len(meta[sp.HASHES]) * 150 <= sp.STUDY_PACKAGE_MAX_HASHES_BYTES
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
    assert _refused(small, [OTHER_TRUST]).step == "signature"
    assert "not a trusted coordinating-centre key" in str(_refused(small, []))
    assert _refused(sp.build(_small(), OTHER_PRIV, DAY)).step == "signature"
    with pytest.raises(sp.PackageRefused, match="not an Ed25519 public key"):
        sp.verify(small, [sp.TrustedKey(b"-----BEGIN PUBLIC KEY-----\nnot a key\n-----END PUBLIC KEY-----\n",
                                        frozenset({"RA-JAK"}))])  # fmt: skip
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
        ({**header, "central_approval": "IRB-1"}, "is not a field a v1 package has"),
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
                sp.verify(data, [TRUST])
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
    got = sp.verify(data, [TRUST])
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
    assert sp.verify(sp.build(files, PRIV, DAY), [TRUST]).protocol["manifest"]["docx_template"] == "form.docx"


def test_test_patients_name_only_placeholders() -> None:
    """The owner's yes to the export (2026-11-19): the test patients leave the box only with the synthetic practitioner
    and department placeholders; the department system is named site-local."""
    dept = "https://trialbox.local/fhir/CodeSystem/department"
    assert dept in sp.SITE_LOCAL_CODE_SYSTEMS
    good = {
        "resourceType": "Appointment",
        "id": "a1" + "0" * 30,
        "participant": [{"actor": {"reference": "Practitioner/P12345"}}, {"actor": {"reference": f"Patient/{PID1}"}}],
        "serviceType": [{"coding": [{"system": dept, "code": "RHEU"}]}],
    }
    files = _small()
    files["tests/patients.ndjson"] = SYN1 + b"\n" + json.dumps(good).encode() + b"\n"
    assert sp.verify(sp.build(files, PRIV, DAY), [TRUST]).files["tests/patients.ndjson"]
    bad_cases = {
        "practitioner": (
            {**good, "participant": [{"actor": {"reference": "Practitioner/PLANTPRAC77"}}]},
            "practitioner",
        ),
        "role": ({**good, "participant": [{"actor": {"reference": "PractitionerRole/R9"}}]}, "<type>/<id>"),
        "department": (
            {**good, "serviceType": [{"coding": [{"system": dept, "code": "PLANTDEPT9"}]}]},
            "hospital's own",
        ),
        "record": ({"resourceType": "Practitioner", "id": "P12345", "name": [{"text": "Planted"}]}, "record"),
    }
    for resource, says in bad_cases.values():
        files["tests/patients.ndjson"] = SYN1 + b"\n" + json.dumps(resource).encode() + b"\n"
        with pytest.raises(ValueError, match=f"line 2 of tests/patients.ndjson .*{re.escape(says)}"):
            sp.build(files, PRIV, DAY)
    files["tests/patients.ndjson"] = b'{"resourceType": "Patient"\n'
    with pytest.raises(ValueError, match="is not JSON"):
        sp.build(files, PRIV, DAY)
    files["tests/patients.ndjson"] = b"[" * 300 + b"]" * 300 + b"\n"
    with pytest.raises(ValueError, match="nests deeper"):
        sp.build(files, PRIV, DAY)


_DEPT = "https://trialbox.local/fhir/CodeSystem/department"
#: the review of 50a07a81 (PR 1183): each line the deny-list let through; all synthetic, each carries PROBE
_BYPASSES: dict[str, dict[str, Any]] = {
    "contained practitioner": {
        "resourceType": "Appointment",
        "contained": [{"resourceType": "Practitioner", "id": "c1", "name": [{"text": "PROBE Dr Example"}]}],
        "participant": [{"actor": {"reference": "#c1"}}],
    },
    "absolute URL reference": {
        "resourceType": "Appointment",
        "participant": [{"actor": {"reference": "https://hosp.example/fhir/Practitioner/PROBEDR1"}}],
    },
    "lower-case reference": {
        "resourceType": "Appointment",
        "participant": [{"actor": {"reference": "practitioner/PROBEDR2"}}],
    },
    "leading space reference": {
        "resourceType": "Appointment",
        "participant": [{"actor": {"reference": " Practitioner/PROBEDR3"}}],
    },
    "placeholder with a display": {
        "resourceType": "Appointment",
        "participant": [{"actor": {"reference": "Practitioner/P12345", "display": "PROBE Dr Example"}}],
    },
    "logical identifier reference": {
        "resourceType": "Appointment",
        "participant": [{"actor": {"type": "Practitioner", "identifier": {"value": "PROBESTAFF9"}}}],
    },
    "department system with a slash": {
        "resourceType": "Encounter",
        "serviceType": [{"coding": [{"system": _DEPT + "/", "code": "PROBEDEPT1"}]}],
    },
    "department system in upper case": {
        "resourceType": "Encounter",
        "serviceType": [{"coding": [{"system": _DEPT.upper(), "code": "PROBEDEPT2"}]}],
    },
    "department code with a space": {
        "resourceType": "Encounter",
        "serviceType": [{"coding": [{"system": _DEPT, "code": "RHEU "}]}],
    },
    "another hospital-local system": {
        "resourceType": "Encounter",
        "serviceType": [{"coding": [{"system": "https://hosp.example/codes/ward", "code": "PROBEWARD7"}]}],
    },
    "organisation with a display": {
        "resourceType": "Encounter",
        "serviceProvider": {"reference": "Organization/PROBEHOSP", "display": "PROBE Example Hospital"},
    },
    "organisation not a placeholder": {
        "resourceType": "Coverage",
        "payor": [{"reference": "Organization/PROBEHOSP"}],
    },
    "patient with a name": {
        "resourceType": "Patient",
        "id": "x",
        "name": [{"family": "PROBEFAMILY", "given": ["Example"]}],
        "birthDate": "1950-01-01",
    },
    "practitioner record, lower case": {"resourceType": "practitioner", "id": "z", "name": [{"text": "PROBE"}]},
    "_reference extension": {
        "resourceType": "Appointment",
        "participant": [{"actor": {"_reference": {"extension": [{"valueString": "Practitioner/PROBEEXT"}]}}}],
    },
    "patient telecom": {"resourceType": "Patient", "id": "x", "telecom": [{"value": "PROBE-000"}]},
    "patient address": {"resourceType": "Patient", "id": "x", "address": [{"text": "PROBE street"}]},
    "a note": {"resourceType": "Condition", "id": "x", "note": [{"text": "PROBE note"}]},
    "a resource inside an element": {
        "resourceType": "Encounter",
        "subject": {"reference": "Patient/syn-1", "resourceType": "Practitioner"},
    },
    "a profile not measured": {
        "resourceType": "Patient",
        "id": "x",
        "meta": {"profile": ["https://example.org/PROBE"]},
    },
    "an object where a value is": {"resourceType": "Patient", "id": "x", "gender": {"text": "PROBE"}},
    "a value where an object is": {"resourceType": "Encounter", "subject": "PROBE Example"},
}


@pytest.mark.parametrize("case", sorted(_BYPASSES))
def test_test_patients_outside_the_allow_list_are_refused(case: str) -> None:
    files = _small()
    line = json.dumps(_BYPASSES[case]).encode()
    files["tests/patients.ndjson"] = b'{"resourceType":"Patient","id":"syn-1"}\n' + line + b"\n"
    with pytest.raises(
        ValueError, match=r"^the study folder cannot be packaged: line 2 of tests/patients\.ndjson "
    ) as e:
        sp.build(files, PRIV, DAY)
    assert "PROBE" not in str(e.value) and "\n" not in str(e.value)  # the refusal does not repeat the data


def test_the_allow_list_is_what_the_shipped_test_patients_hold() -> None:
    """The allow-list is measured: exactly the resource types, elements, systems, profiles and reference types of the
    shipped studies' test patients."""
    elements: dict[str, set[str]] = {}
    systems: set[str] = set()
    profiles: set[str] = set()
    types: set[str] = set()

    def walk(node: Any, path: str, kind: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}" if path else key, kind)
        elif isinstance(node, list):
            for item in node:
                walk(item, path, kind)
        elif path != "resourceType":
            elements.setdefault(kind, set()).add(path)
            if path.endswith("system"):
                systems.add(node)
            elif path == "meta.profile":
                profiles.add(node)
            elif path.endswith("reference"):
                types.add(node.split("/")[0])

    shipped = sorted(SEED_RULESETS.glob("*/tests/patients.ndjson"))
    assert len(shipped) == 5
    for path in shipped:
        for line in path.read_bytes().splitlines():
            if line.strip():
                resource = json.loads(line)
                walk(resource, "", resource["resourceType"])
    assert {k: frozenset(v) for k, v in elements.items()} == sp.TEST_PATIENT_ELEMENTS
    assert systems == sp.TEST_PATIENT_SYSTEMS and len(systems) == 21
    assert profiles == sp.TEST_PATIENT_PROFILES
    assert types == sp.TEST_PATIENT_REFERENCE_TYPES
    assert len(sp.TEST_PATIENT_ELEMENTS) == 12


def _ir_with(**extra: Any) -> dict[str, bytes]:
    files = _small()
    doc = json.loads(files["ir/RA-JAK-INC-01.json"])
    files["ir/RA-JAK-INC-01.json"] = json.dumps({**doc, **extra}).encode()
    return files


@pytest.mark.parametrize(
    ("change", "says"),
    [
        (lambda f: _ir_with(reviewer_note="PROBE-IRNOTE"), "does not load as a criterion"),
        (lambda f: _ir_with(review_history=[{"by": "PROBE-HIST"}]), "does not load as a criterion"),
        (lambda f: _ir_with(review={"status": "approved", "note": "PROBE"}), "does not load as a criterion"),
        (lambda f: {**f, "ir/RA-JAK-INC-09.json": b"{not json"}, "is not JSON"),
        (
            lambda f: {**f, "valuesets/VS_X.json": json.dumps({"id": "x", "publisher": "PROBE-VS"}).encode()},
            "value set",
        ),
        (
            lambda f: {
                **f,
                "valuesets/VS_HBSAG.json": json.dumps(
                    {**json.loads(f["valuesets/VS_HBSAG.json"]), "publisher": "PROBE-VS"}
                ).encode(),
            },
            "does not load as a value set",
        ),
    ],
    ids=["ir extra key", "ir review history", "ir review extra key", "ir not json", "valueset", "valueset extra"],
)
def test_ir_and_value_sets_load_through_their_models(
    change: Callable[[dict[str, bytes]], dict[str, bytes]], says: str
) -> None:
    with pytest.raises(ValueError, match=f"cannot be packaged: .*{says}"):
        sp.build(change(_small()), PRIV, DAY)
    # every shipped value set loads through the model
    for path in SEED_RULESETS.glob("*/valuesets/*.json"):
        sp.ValueSetFile.model_validate(json.loads(path.read_bytes()))


@pytest.mark.parametrize(
    "path",
    [
        "cql/elm/NOTES",
        "cql/elm/.reviewer-notes.txt",
        "cql/elm/cc_ed25519.key",
        "cql/elm/TB_RA_JAK_v1_0.xml",
        "cql/elm/.hidden.json",
        "cql/elm/sub/Other.json",
        "cql/elm/Other.cql",
        "cql/.Hidden.cql",
        "cql/sub/Other.cql",
        "ir/.hidden.json",
        "ir/sub/deep.json",
        "ir/notes.txt",
        "valuesets/.VS_X.json",
        "valuesets/sub/VS_X.json",
        "sql/.x.sql",
        "sql/sub/x.sql",
        "sql/notes.txt",
    ],
)
def test_only_the_protocol_files_a_package_takes_are_packed(path: str) -> None:
    """A file the criteria hash covers or the engine reads but a package does not carry refuses the folder: under
    cql/elm/ only .json, no hidden file, no subfolder, each folder its one extension."""
    files = {**_small(), path: b'{"x": "PROBE"}'}
    with pytest.raises(ValueError, match=f"it holds {re.escape(path)}, which a package does not carry"):
        sp.build(files, PRIV, DAY)
    assert not sp.carriable(path)


def test_cql_elm_json_must_be_json_and_the_verifier_takes_only_carriable_names(small: bytes) -> None:
    files = {**_small(), "cql/elm/TB_X.json": b"PROBE not json"}
    with pytest.raises(ValueError, match="cql/elm/TB_X.json is not JSON"):
        sp.build(files, PRIV, DAY)
    files = {**_small(), "cql/elm/TB_X.json": b'{"library": {"identifier": {"id": "TB_X"}}}'}
    assert "cql/elm/TB_X.json" in sp.verify(sp.build(files, PRIV, DAY), [TRUST]).files
    members = _members(small)
    for name in ("files/cql/elm/NOTES", "files/cql/elm/.x.json", "files/ir/sub/deep.json"):
        got = _refused(_resigned({**members, name: b"{}"}))
        assert got.step == "tar" and "not a member a v1 package may hold" in str(got)


def _write_folder(root: Path, files: dict[str, bytes]) -> None:
    for path, data in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(data)


@pytest.mark.parametrize("kind", ["file link", "folder link", "link inside", "fifo"])
def test_build_dir_refuses_links_and_files_that_are_not_regular(tmp_path: Path, kind: str) -> None:
    study = tmp_path / "RA-JAK"
    _write_folder(study, _small())
    assert sp.verify(sp.build_dir(study, PRIV, DAY), [TRUST])
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.json").write_bytes(b'{"PROBE": 1}')
    if kind == "file link":
        (study / "cql" / "elm").mkdir(parents=True)
        (study / "cql" / "elm" / "TB_X.json").symlink_to(outside / "x.json")
        says = "cql/elm/TB_X.json is a symbolic link"
    elif kind == "folder link":
        (study / "cql").mkdir()
        (study / "cql" / "elm").symlink_to(outside, target_is_directory=True)
        says = "cql/elm is a symbolic link"
    elif kind == "link inside":
        (study / "notes.txt").symlink_to(study / "manifest.yaml")
        says = "notes.txt is a symbolic link"
    else:
        os.mkfifo(study / "tests" / "expected.json")
        says = "tests/expected.json is not a regular file"
    with pytest.raises(ValueError, match=f"cannot be packaged: {re.escape(says)}"):
        sp.build_dir(study, PRIV, DAY)


#: the second review of 0a0f65b5 (PR 1183): lines the allow-list let through or answered with a TypeError, or whose
#: refusal repeated a key or a type; all synthetic, each carries PROBE (or a name-like word) the refusal must not repeat
_APPT = "Appointment"
_LOINC = "http://loinc.org"
_SHAPES: dict[str, bytes] = {
    "dotted keys under serviceType": json.dumps(
        {"resourceType": _APPT, "serviceType": [{"coding.system": _DEPT, "coding.code": "PROBEWARD"}]}
    ).encode(),
    "dotted keys at the top": json.dumps(
        {"resourceType": _APPT, "serviceType.coding.system": _DEPT, "serviceType.coding.code": "PROBEWARD7"}
    ).encode(),
    "dotted reference key": json.dumps({"resourceType": "Observation", "subject.reference": "Patient/a"}).encode(),
    "system a list": json.dumps(
        {"resourceType": "Observation", "code": {"coding": [{"system": [_LOINC], "code": "PROBE"}]}}
    ).encode(),
    "department system a list": json.dumps(
        {"resourceType": _APPT, "serviceType": [{"coding": [{"system": [_DEPT], "code": "PROBEWARD"}]}]}
    ).encode(),
    "department code a list": json.dumps(
        {"resourceType": _APPT, "serviceType": [{"coding": [{"system": _DEPT, "code": ["RHEU", "PROBEWARD"]}]}]}
    ).encode(),
    "code an object": json.dumps(
        {"resourceType": "Observation", "code": {"coding": [{"system": _LOINC, "code": {"x": "PROBE"}}]}}
    ).encode(),
    "code a number": json.dumps(
        {"resourceType": "Observation", "code": {"coding": [{"system": _LOINC, "code": 4548}]}}
    ).encode(),
    "code null": json.dumps(
        {"resourceType": "Observation", "code": {"coding": [{"system": _LOINC, "code": None}]}, "id": "PROBE"}
    ).encode(),
    "array of arrays": json.dumps(
        {"resourceType": "Observation", "code": {"coding": [[{"system": _LOINC, "code": "PROBE-AA"}]]}}
    ).encode(),
    "array at a leaf": json.dumps({"resourceType": "Patient", "id": ["PROBE-LIST", "b"]}).encode(),
    "single value where an array is": json.dumps(
        {"resourceType": "Observation", "code": {"coding": {"system": _LOINC, "code": "PROBE"}}}
    ).encode(),
    "empty array": json.dumps({"resourceType": "Patient", "id": "a", "identifier": []}).encode(),
    "null leaf": json.dumps({"resourceType": "Patient", "id": None, "birthDate": "PROBE"}).encode(),
    "number id": b'{"resourceType":"Patient","id":12345678901234567890}',
    "boolean where a number is": b'{"resourceType":"Observation","valueQuantity":{"value":true,"unit":"PROBE"}}',
    "text where a number is": b'{"resourceType":"Observation","valueQuantity":{"value":"PROBE"}}',
    "a sequence not an integer": b'{"resourceType":"Claim","item":[{"sequence":1.5}],"use":"PROBE"}',
    "a number where a boolean is": b'{"resourceType":"Claim","insurance":[{"focal":1,"sequence":1}],"use":"PROBE"}',
    "infinite number": b'{"resourceType":"Observation","valueQuantity":{"value":1e999999,"unit":"PROBE"}}',
    "absurd number": b'{"resourceType":"Observation","valueQuantity":{"value":1e300,"unit":"PROBE"}}',
    "byte-order mark inside": b'\xef\xbb\xbf{"resourceType":"Patient","id":"PROBE"}',
    "escaped byte-order mark in a text": b'{"resourceType":"DiagnosticReport","conclusion":"\\ufeffPROBE"}',
    "a long text": json.dumps({"resourceType": "DiagnosticReport", "conclusion": "PROBE " + "x" * 5000}).encode(),
    "a line separator in an id": '{"resourceType":"Patient","id":"a PROBE"}'.encode(),
    "an id with a space": json.dumps({"resourceType": "Patient", "id": "PROBE Chen"}).encode(),
    "an id over 64": json.dumps({"resourceType": "Patient", "id": "PROBE" + "x" * 64}).encode(),
    "a reference with a trailing newline": json.dumps(
        {"resourceType": "Observation", "subject": {"reference": "Patient/a\n"}}
    ).encode(),
    "a key with a look-alike letter": json.dumps({"resourceType": "Patient", "іd": "PROBE"}).encode(),
    "an empty key": json.dumps({"resourceType": "Patient", "": "PROBE"}).encode(),
    "an unknown key that reads as a name": json.dumps({"resourceType": "Patient", "PROBEChenMeiLing": "a"}).encode(),
    "an unknown deep key that reads as a name": json.dumps(
        {"resourceType": "Observation", "code": {"coding": [{"system": _LOINC, "PROBEChenMeiLing": "y"}]}}
    ).encode(),
    "an unknown type that reads as a name": json.dumps({"resourceType": "PROBEChenMeiLing", "id": "a"}).encode(),
}


@pytest.mark.parametrize("case", sorted(_SHAPES))
def test_test_patients_of_a_wrong_shape_are_refused_in_one_sentence(case: str) -> None:
    files = _small()
    files["tests/patients.ndjson"] = b'{"resourceType":"Patient","id":"syn-1"}\n' + _SHAPES[case] + b"\n"
    with pytest.raises(
        ValueError, match=r"^the study folder cannot be packaged: (line 2 of )?tests/patients\.ndjson "
    ) as e:
        sp.build(files, PRIV, DAY)
    message = str(e.value)
    assert type(e.value) is ValueError and "\n" not in message
    assert "PROBE" not in message and "Chen" not in message  # never a value, an unknown key or an unknown type


def test_the_test_patients_shapes_are_measured() -> None:
    """The leaf types, the arrays and the caps are measured from the shipped test patients: each non-text leaf has the
    type the allow-list states, each array is where it states, every key is an element name, no file holds a
    byte-order mark, and the longest text and the largest number are within the caps."""
    types: dict[tuple[str, str], set[str]] = {}
    lists: dict[str, set[str]] = {}
    longest, largest = 0, 0.0

    def walk(node: Any, path: str, kind: str) -> None:
        nonlocal longest, largest
        if isinstance(node, dict):
            for key, value in node.items():
                assert re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", key)
                walk(value, f"{path}.{key}" if path else key, kind)
        elif isinstance(node, list):
            lists.setdefault(kind, set()).add(path)
            for item in node:
                assert not isinstance(item, list)
                walk(item, path, kind)
        elif path != "resourceType":
            name = {bool: "boolean", int: "integer", float: "number", str: "text"}[type(node)]
            types.setdefault((kind, path), set()).add(name)
            if isinstance(node, str):
                longest = max(longest, len(node))
            else:
                largest = max(largest, abs(float(node)))

    for path in sorted(SEED_RULESETS.glob("*/tests/patients.ndjson")):
        data = path.read_bytes()
        assert b"\xef\xbb\xbf" not in data
        for line in data.splitlines():
            if line.strip():
                resource = json.loads(line)
                walk(resource, "", resource["resourceType"])
    non_text = {k: v for k, v in types.items() if v != {"text"}}
    stated = {k: {"number": {"integer", "number"}}.get(v, {v}) for k, v in sp.TEST_PATIENT_NON_TEXT.items()}
    assert set(non_text) == set(stated) and all(non_text[k] <= stated[k] for k in stated)
    assert {k: frozenset(v) for k, v in lists.items()} == sp.TEST_PATIENT_LISTS
    assert longest == 92 and longest * 2 <= sp.TEST_PATIENT_MAX_TEXT
    assert largest < 1000 < sp.TEST_PATIENT_MAX_NUMBER


def _vs_with(**extra: Any) -> dict[str, bytes]:
    files = _small()
    doc = json.loads(files["valuesets/VS_HBSAG.json"])
    files["valuesets/VS_HBSAG.json"] = json.dumps({**doc, **extra}).encode()
    return files


@pytest.mark.parametrize(
    "extra",
    [
        {"extension": [{"url": "https://example.org/PROBE/reviewer", "valueString": "PROBE Dr Example"}]},
        {"extension": [{"url": sp.FAMILY_EXT, "valueString": "PROBE reviewed by Dr Example"}]},
        {"extension": [{"url": sp.FAMILY_EXT, "valueString": "http://hl7.org/fhir/sid/icd-10-cm|M05 PROBE"}]},
        {"extension": [{"url": sp.FAMILY_EXT, "valueInteger": 3}]},
        {"meta": {"tag": [{"system": "https://example.org/PROBE/site", "code": "needs_review"}]}},
        {"meta": {"tag": [{"system": sp.REVIEW_TAG_SYSTEM, "code": "PROBE-reviewer"}]}},
    ],
    ids=["extension url", "family free text", "family with a space", "family value type", "tag system", "tag code"],
)
def test_a_value_sets_extension_and_tag_are_the_compilers(extra: dict[str, Any]) -> None:
    from criteria_compiler.terminology import mapper

    assert (sp.FAMILY_EXT, sp.REVIEW_TAG_SYSTEM) == (mapper.FAMILY_EXT, mapper.REVIEW_TAG_SYSTEM)
    with pytest.raises(ValueError, match="does not load as a value set") as e:
        sp.build(_vs_with(**extra), PRIV, DAY)
    assert "PROBE" not in str(e.value)
    good = _vs_with(
        extension=[{"url": sp.FAMILY_EXT, "valueString": "http://hl7.org/fhir/sid/icd-10-cm|M05"}],
        meta={"tag": [{"system": sp.REVIEW_TAG_SYSTEM, "code": "needs_review"}]},
    )
    assert sp.verify(sp.build(good, PRIV, DAY), [TRUST])


@pytest.mark.parametrize(
    ("body", "says"),
    [
        ({"site_notes": "PROBE reviewer"}, "is not a compiled ELM library"),
        ({"library": {"identifier": {"id": "TB_X"}}, "notes": "PROBE"}, "is not a compiled ELM library"),
        ({"library": {"identifier": {"id": "TB_X"}, "reviewer": "PROBE"}}, "is not a compiled ELM library"),
        ({"library": ["PROBE"]}, "is not a compiled ELM library"),
        ([{"library": {}}], "is not a compiled ELM library"),
    ],
    ids=["other key", "second top key", "library extra key", "library a list", "a list"],
)
def test_cql_elm_is_a_library_of_the_standard_keys(body: Any, says: str) -> None:
    """The top-level shape of ``cql/elm/*.json`` only; the ELM node allow-list is 10D-28's (``ruleset_part``)."""
    files = {**_small(), "cql/elm/TB_X.json": json.dumps(body).encode()}
    with pytest.raises(ValueError, match=f"cql/elm/TB_X.json {says}") as e:
        sp.build(files, PRIV, DAY)
    assert "PROBE" not in str(e.value)
    for path in SEED_RULESETS.glob("*/cql/elm/*.json"):
        doc = json.loads(path.read_bytes())
        assert set(doc) == {"library"} and set(doc["library"]) <= sp.ELM_LIBRARY_KEYS


@pytest.mark.parametrize(
    ("extra", "says"),
    [
        ({"provenance": {"calls": ["01JPROBE"], "model_route": "PROBE-route"}}, "provenance"),
        ({"provenance": {"calls": ["PROBE call Dr Example"]}}, "provenance"),
        ({"provenance": {"calls": "01JPROBE"}}, "provenance"),
        ({"flags": ["PROBE reviewed by Dr Example"]}, "flag"),
        ({"flags": "needs_review"}, "flag"),
        ({"time_sensitive": "yes"}, "does not load as a criterion"),
    ],
    ids=["provenance other field", "call id with spaces", "calls a text", "flag free text", "flags a text", "lax"],
)
def test_an_irs_flags_provenance_and_types_are_strict(extra: dict[str, Any], says: str) -> None:
    with pytest.raises(ValueError, match=f"ir/RA-JAK-INC-01.json .*{says}") as e:
        sp.build(_ir_with(**extra), PRIV, DAY)
    assert "PROBE" not in str(e.value)


def test_an_ir_field_by_its_python_name_is_refused() -> None:
    files = _small()
    doc = json.loads(files["ir/RA-JAK-INC-01.json"])
    doc["class_"] = doc.pop("class")
    files["ir/RA-JAK-INC-01.json"] = json.dumps(doc).encode()
    with pytest.raises(ValueError, match="does not load as a criterion"):
        sp.build(files, PRIV, DAY)
    carried = sp.verify(
        sp.build(_ir_with(flags=["needs_review"], provenance={"calls": ["01JABCDEF"]}), PRIV, DAY), [TRUST]
    )
    assert b"01JABCDEF" in carried.files["ir/RA-JAK-INC-01.json"]  # call ids travel (D-1372, for the owner)


def _swap_on_open(monkeypatch: pytest.MonkeyPatch, study: Path, name: str, evil: Path) -> None:
    """Simulate a race: the first time ``name`` is opened in a folder descriptor, ``study/ir`` is moved away and a
    symbolic link to ``evil`` takes its place (as the reviewer's probe does)."""
    real_open = os.open
    done: list[bool] = []

    def racing(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        if path == name and kwargs.get("dir_fd") is not None and not done:
            done.append(True)
            os.rename(study / "ir", study.parent / "ir-moved")
            os.symlink(evil, study / "ir")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", racing)


@pytest.mark.parametrize("when", ["before ir/ is opened", "after ir/ is opened"])
def test_build_dir_does_not_follow_a_folder_swapped_for_a_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, when: str
) -> None:
    study = tmp_path / "RA-JAK"
    _write_folder(study, _small())
    evil = tmp_path / "evil"
    evil.mkdir()
    doc = json.loads((study / "ir" / "RA-JAK-INC-01.json").read_bytes())
    for name in ("RA-JAK-INC-01.json", "RA-JAK-EXC-01.json"):
        (evil / name).write_text(json.dumps({**doc, "label": "PROBE-RACE"}))
    _swap_on_open(monkeypatch, study, "ir" if when.startswith("before") else "RA-JAK-EXC-01.json", evil)
    if when.startswith("before"):
        with pytest.raises(ValueError, match="cannot be packaged: ir is a symbolic link or changed while read"):
            sp.build_dir(study, PRIV, DAY)
    else:  # the folder's descriptor is held: the file read is the one listed, not the link's
        assert b"PROBE-RACE" not in sp.build_dir(study, PRIV, DAY)


@pytest.mark.parametrize("kind", ["root link", "hard link", "over the cap", "unread"])
def test_build_dir_reads_by_descriptor_only_what_it_carries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    study = tmp_path / "RA-JAK"
    _write_folder(study, _small())
    read: list[int] = []
    real_read = os.read

    def counted(fd: int, n: int) -> bytes:
        data = real_read(fd, n)
        read.append(len(data))
        return data

    monkeypatch.setattr(os, "read", counted)
    if kind == "root link":
        (tmp_path / "link").symlink_to(study, target_is_directory=True)
        with pytest.raises(ValueError, match="cannot be packaged: the folder is a symbolic link"):
            sp.build_dir(tmp_path / "link", PRIV, DAY)
    elif kind == "hard link":
        (tmp_path / "outside.yaml").write_bytes(b"x: PROBE-HARDLINK\n")
        os.link(tmp_path / "outside.yaml", study / "labels.yaml")
        with pytest.raises(ValueError, match=r"cannot be packaged: labels\.yaml has another name on this disk"):
            sp.build_dir(study, PRIV, DAY)
    elif kind == "over the cap":
        monkeypatch.setattr(sp, "STUDY_PACKAGE_MAX_MEMBER_BYTES", 10)
        (study / "labels.yaml").write_bytes(b"x: " + b"y" * 100 + b"\n")
        with pytest.raises(
            ValueError, match=r"cannot be packaged: labels\.yaml is 104 bytes; a carried file may be at most"
        ):
            sp.read_folder(study)
        assert sum(read) == len((study / "manifest.yaml").read_bytes())  # labels.yaml was not read
    else:
        (study / "notes.bin").write_bytes(b"\0" * 5_000_000)
        (study / "tests" / "equivalence.json").write_bytes(b'{"by": "PROBE"}')
        got = sp.read_folder(study)
        assert "notes.bin" not in got and "tests/equivalence.json" not in got
        assert sum(read) == sum(len(b) for b in got.values())  # nothing else was read
        assert set(got) == set(_small())


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
    deep_header = sp.tar_bytes({**members, sp.HEADER: _nested(20_000)})  # within the header's 64 KiB cap
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


# ---------------------------------------------------------------------------------------------- review of f1d1fe3c
#: the review of f1d1fe3c (PR 1183), H1 to H5: each test is the reviewer's probe at the real call, refused now


def test_h1_test_patients_not_of_the_synthetic_site_are_refused() -> None:
    """H1: the reviewer's probe (a patient with a chart number, a birth date and a report's narrative) and each way a
    record can be other than the synthetic site's: a patient whose id is not the pseudonym of a synthetic chart number
    under the public synthetic key, an identifier other than its own pseudonym, a patient twice, a reference to a
    patient the file does not hold. The refusal repeats no value. Every shipped study still packs (below)."""
    base = SYN1 + b"\n"
    probe = [
        {"resourceType": "Patient", "id": "probe42", "birthDate": "1950-01-01", "gender": "male",
         "identifier": [{"system": sp.SYNTHETIC_PID_SYSTEM, "value": "DEMO-MRN-42"}]},
        {"resourceType": "DiagnosticReport", "id": "dr42", "status": "final",
         "conclusion": "Example patient has lymphoma", "subject": {"reference": "Patient/probe42"}},
    ]  # fmt: skip
    real_looking = json.loads(SYN1)
    hospital_pid = hashlib.sha256(b"a hospital's own key|10000001").hexdigest()[:32]  # a pseudonym under another key
    cases = {
        "the reviewer's probe": (b"".join(json.dumps(r).encode() + b"\n" for r in probe), "line 2", "pseudonym"),
        "another key's pseudonym": (
            json.dumps(
                {
                    **real_looking,
                    "id": hospital_pid,
                    "identifier": [{"system": sp.SYNTHETIC_PID_SYSTEM, "value": hospital_pid}],
                }
            ).encode(),
            "line 2",
            "pseudonym",
        ),
        "an identifier that is a chart number": (
            json.dumps(
                {**real_looking, "identifier": [{"system": sp.SYNTHETIC_PID_SYSTEM, "value": "10000001"}]}
            ).encode(),
            "line 1",
            "identifier",
        ),
        "no identifier": (
            json.dumps({k: v for k, v in real_looking.items() if k != "identifier"}).encode(),
            "line 1",
            "identifier",
        ),
        "a patient twice": (SYN1, "line 2", "already holds"),
        "a record of a patient not in the file": (
            json.dumps({"resourceType": "Condition", "id": "c1", "subject": {"reference": "Patient/probe42"}}).encode(),
            "line 2",
            "not one of the file's test patients",
        ),
    }
    for why, (lines, where, says) in cases.items():
        files = _small()
        body = lines if where == "line 1" else base + lines
        files["tests/patients.ndjson"] = body if body.endswith(b"\n") else body + b"\n"
        with pytest.raises(ValueError, match=f"cannot be packaged: {where} of tests/patients.ndjson .*{says}") as e:
            sp.build(files, PRIV, DAY)
        message = str(e.value)
        assert not any(v in message for v in ("probe42", "DEMO-MRN", "lymphoma", "1950", hospital_pid)), why
    # the shipped test patients: every Patient the synthetic site's, every chart number one the generators write
    pseudonyms = sp.synthetic_pseudonyms()
    assert len(pseudonyms) == 9 * sp.SYNTHETIC_MAX_PATIENTS
    for path in sorted(SEED_RULESETS.glob("*/tests/patients.ndjson")):
        mrns = sp.test_patient_chart_numbers(path.read_bytes())
        assert len(mrns) == 200 and all(m.startswith("1") for m in mrns)  # site-a of tools/make_fixtures.py
    # the key is the test stack's, as the conftest and the Makefile write it
    assert sp.SYNTHETIC_SITE_KEY in (ROOT / "Makefile").read_bytes()


def _expected(files: dict[str, bytes], **change: Any) -> dict[str, bytes]:
    doc = json.loads(files["tests/expected.json"])
    doc.update(change)
    return {**files, "tests/expected.json": json.dumps(doc).encode()}


def test_h2_expected_verdicts_carry_no_identifier_and_no_free_text() -> None:
    """H2: ``tests/expected.json`` holds only synthetic chart numbers (those of the study's test patients when it
    carries them), the protocol's criteria, verdicts true, false or null, and labels from a closed set."""
    jak = _folder("RA-JAK")  # expected.json, no test patients
    gzqo = _folder("GZQO")  # expected.json and test patients
    one = next(iter(json.loads(gzqo["tests/expected.json"])["patients"]))
    cases = {
        "the reviewer's probe": {**jak, "tests/expected.json": b'{"patients":{"DEMO-MRN-42":{"RA-JAK-EXC-01":true}}}'},
        "a chart number outside the generators'": _expected(jak, patients={"20009999": {"RA-JAK-EXC-01": True}}),
        "a text verdict": _expected(jak, patients={"20000002": {"RA-JAK-EXC-01": "PROBE has lymphoma"}}),
        "a criterion the protocol does not name": _expected(jak, patients={"20000002": {"PROBE-NOTE": True}}),
        "a free-text source": _expected(jak, source="PROBE chart review at the hospital, Dr Example"),
        "a free-text engine": _expected(jak, engine="PROBE"),
        "a field more": _expected(jak, note="PROBE"),
        "another study": _expected(jak, ruleset="GZQO"),
        "a known difference in words": _expected(
            jak,
            agreement={
                **json.loads(jak["tests/expected.json"])["agreement"],
                "known_differences": {"RA-JAK-EXC-01": "PROBE patient 20000002 differs"},
            },
        ),
        "not the test patients' chart numbers": _expected(
            gzqo, patients={**json.loads(gzqo["tests/expected.json"])["patients"], "10000002": {}}
        ),
        "a test patient left out": _expected(
            gzqo, patients={k: v for k, v in json.loads(gzqo["tests/expected.json"])["patients"].items() if k != one}
        ),
    }
    for why, files in cases.items():
        with pytest.raises(ValueError, match="cannot be packaged: tests/expected.json ") as e:
            sp.build(files, PRIV, DAY)
        assert "PROBE" not in str(e.value) and "DEMO-MRN" not in str(e.value), why
    # the shipped files: each label in its closed set, each key a synthetic chart number
    for path in sorted(SEED_RULESETS.glob("*/tests/expected.json")):
        doc = json.loads(path.read_bytes())
        assert doc["engine"] in sp.EXPECTED_ENGINES and doc["source"] in sp.EXPECTED_SOURCES, path
        assert set(doc) <= sp.EXPECTED_FIELDS
    assert {json.loads(p.read_bytes())["source"] for p in SEED_RULESETS.glob("*/tests/expected.json")} == (
        sp.EXPECTED_SOURCES
    )
    assert {json.loads(p.read_bytes())["engine"] for p in SEED_RULESETS.glob("*/tests/expected.json")} == (
        sp.EXPECTED_ENGINES
    )


def _without_member(members: dict[str, bytes], path: str, add: dict[str, bytes] | None = None) -> bytes:
    """A package signed by a trusted key whose protocol part, hash list and header are made again without the carried
    file ``path`` (and with ``add``): every check before the criteria set holds."""
    body = {k: v for k, v in members.items() if k != FILES_PREFIX + path}
    body.update({FILES_PREFIX + k: v for k, v in (add or {}).items()})
    protocol = json.loads(members[sp.PROTOCOL])
    protocol["files"] = {k[len(FILES_PREFIX) :]: hashlib.sha256(v).hexdigest() for k, v in body.items()
                         if k.startswith(FILES_PREFIX)}  # fmt: skip
    protocol["criteria_sha256"] = sm.criteria_sha256(protocol)
    body[sp.PROTOCOL] = sm.dumps(protocol)
    header = {**json.loads(members[sp.HEADER]), "criteria_sha256": protocol["criteria_sha256"]}
    del header["package_id"]
    return _resigned(body, header=header)


FILES_PREFIX = sp.FILES


def test_h3_the_criteria_named_are_exactly_the_ir_files() -> None:
    """H3: the writer and the verifier refuse a study whose manifest names a criterion without its ``ir/`` file, an
    ``ir/`` file it does not name, an IR holding another criterion, and a named CQL library without its files. The
    verifier's check is the last of step 5 (protocol), after the signature, the hashes, the member set and the
    criteria hash: a trusted key that signed such a package still meets it."""
    jak = _folder("RA-JAK")
    lacking = {k: v for k, v in jak.items() if k != "ir/RA-JAK-EXC-01.json"}
    with pytest.raises(ValueError, match="names the criterion RA-JAK-EXC-01 but carries no ir/RA-JAK-EXC-01.json"):
        sp.build(lacking, PRIV, DAY)
    extra_ir = json.loads(jak["ir/RA-JAK-EXC-01.json"])
    unnamed = {**jak, "ir/RA-JAK-EXC-99.json": json.dumps({**extra_ir, "id": "RA-JAK-EXC-99"}).encode()}
    with pytest.raises(ValueError, match="carries ir/RA-JAK-EXC-99.json, a criterion its manifest does not name"):
        sp.build(unnamed, PRIV, DAY)
    other_id = {**jak, "ir/RA-JAK-EXC-01.json": json.dumps({**extra_ir, "id": "RA-JAK-EXC-02"}).encode()}
    with pytest.raises(ValueError, match="does not hold the criterion RA-JAK-EXC-01"):
        sp.build(other_id, PRIV, DAY)
    no_elm = {k: v for k, v in jak.items() if k != "cql/elm/TB_RA_JAK_v1_0.json"}
    with pytest.raises(ValueError, match="names the CQL library TB_RA_JAK_v1_0 but carries no cql/elm/"):
        sp.build(no_elm, PRIV, DAY)
    # the verifier: a trusted key signs a package without a criterion's file, or with one more
    unnamed_carried = sm.carried("ir/RA-JAK-EXC-99.json", unnamed["ir/RA-JAK-EXC-99.json"]) or b""
    members = _members(sp.build(jak, PRIV, DAY))
    got = _refused(_without_member(members, "ir/RA-JAK-EXC-01.json"))
    assert got.step == "protocol" and "names the criterion RA-JAK-EXC-01 but carries no" in str(got)
    got = _refused(_without_member(members, "", {"ir/RA-JAK-EXC-99.json": unnamed_carried}))
    assert got.step == "protocol" and "a criterion its manifest does not name" in str(got)
    got = _refused(_without_member(members, "cql/TB_RA_JAK_v1_0.cql"))
    assert got.step == "protocol" and "carries no cql/TB_RA_JAK_v1_0.cql" in str(got)
    # every shipped study names exactly its IR files
    for ruleset in SHIPPED:
        files = _folder(ruleset)
        assert sp.criteria_refusal(yaml.safe_load(files["manifest.yaml"]), files) is None, ruleset


#: ``write`` refuses root (review of ec90c1b4, item 1): a test that runs as root gives the writer another uid
NOT_ROOT = 65534


def _not_root() -> int:
    return NOT_ROOT


@pytest.fixture(autouse=True)
def _rulesets_dir() -> Any:
    """``TB_RULESETS_DIR`` as each test leaves it is put back (``_store`` names the store it makes)."""
    before = os.environ.get("TB_RULESETS_DIR")
    yield
    if before is None:
        os.environ.pop("TB_RULESETS_DIR", None)
    else:
        os.environ["TB_RULESETS_DIR"] = before


def _store(
    root: Path,
    files: dict[str, bytes],
    sid: str = "RA-JAK",
    message: str | None = None,
    tagger: str | None = None,
    configure: bool = True,
) -> Path:
    """A rule-set store as the criteria compiler keeps it (``criteria_compiler.repo``), the study committed, tagged
    ``<ID>/v<version>`` as the compiler's approval writes it (message ``<ID> v<version> approved by <who>``, tagger
    ``<who>``, the manifest's ``review.approved_by`` that person), and materialised: the folder ``write`` packs. With
    ``configure`` it is the box's configured store (``TB_RULESETS_DIR``)."""
    from criteria_compiler.repo import RulesetRepo

    repo = RulesetRepo(root / "rulesets")
    manifest = yaml.safe_load(files["manifest.yaml"])
    version = str(manifest["version"])
    by = str((manifest.get("review") or {}).get("approved_by") or "crc-test")
    repo.write_dir("main", "main", f"{sid}/", files, f"approve {sid} v{version} by {by}", by)
    repo.tag(f"{sid}/v{version}", "main", message or f"{sid} v{version} approved by {by}", tagger or by)
    repo.materialize(sid)
    if configure:
        os.environ["TB_RULESETS_DIR"] = str(root / "rulesets")
    return root / "rulesets" / sid


def _key_file(path: Path, pem: bytes = PRIV) -> Path:
    path.write_bytes(pem)
    path.chmod(0o600)
    return path


def _events(audit: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for f in sorted(audit.glob("*.jsonl")) for x in f.read_text().splitlines() if x]


def test_h4_a_package_is_released_only_after_its_audit_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """H4: the command writes the audit event through the writer it is given (who, the study, version, approval tag,
    package id, sha256, key id; no content) before the package takes its name, and leaves no package when there is no
    writer, the event cannot be written, or the study is not approved."""
    from tb_common.audit import AuditLog

    from tools import study_package as tool

    study = _store(tmp_path, _small())
    key = _key_file(tmp_path / "cc.key")
    audit = tmp_path / "audit"
    audit.mkdir()
    out = tmp_path / "out" / "RA-JAK.tbstudy"
    out.parent.mkdir()
    seen: list[bool] = []

    class Spy(AuditLog):
        def append(self, *a: Any, **k: Any) -> dict[str, Any]:
            seen.append(out.exists())
            return super().append(*a, **k)

    with pytest.raises(ValueError, match="no audit writer"):
        tool.write(study, key, out, DAY, audit=None, euid=_not_root)
    assert not out.exists()
    h = tool.write(study, key, out, DAY, audit=Spy(audit, "Asia/Taipei"), by="host:crc-test", euid=_not_root)
    assert seen == [False]  # the event was written before the package's name
    assert out.read_bytes() and out.stat().st_mode & 0o777 == 0o600
    assert not list(out.parent.glob(".*")), "no hidden part file left"
    exported = [e for e in _events(audit) if e["event"] == tool.EVENT]
    assert len(exported) == 1
    ev = exported[0]
    assert ev["actor"] == "host:crc-test" and ev["ruleset"] == "RA-JAK" and ev["ruleset_version"] == "1.0.0"
    assert ev["output_sha"] == hashlib.sha256(out.read_bytes()).hexdigest() == h["sha256"]
    a = h["approval"]
    assert ev["detail"] == {"package_id": h["package_id"], "key_id": sp.key_id(PUB), "created": DAY,
                            "protocol_version": h["protocol_version"], "criteria_sha256": h["criteria_sha256"],
                            "approval_tag": "RA-JAK/v1.0.0", "approval_tag_sha": a.tag_sha,
                            "approval_commit": a.commit, "approved_by": a.by}  # fmt: skip
    assert re.fullmatch("[0-9a-f]{40}", a.tag_sha) and re.fullmatch("[0-9a-f]{40}", a.commit) and a.by
    assert PID1 not in json.dumps(_events(audit))  # no content of the package in the audit

    # the event cannot be written: no package, no part file
    class Full:
        def append(self, *_a: Any, **_k: Any) -> None:
            raise OSError("disk full")

    second = tmp_path / "out" / "second.tbstudy"
    with pytest.raises(ValueError, match="audit event could not be written"):
        tool.write(study, key, second, DAY, audit=Full(), euid=_not_root)
    assert not second.exists() and not list(out.parent.glob(".*"))
    # a draft is not packed
    m = yaml.safe_load((study / "manifest.yaml").read_bytes())
    m["status"] = "draft"
    (study / "manifest.yaml").write_text(yaml.safe_dump(m, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match="status: approved"):
        tool.write(study, key, tmp_path / "out" / "draft.tbstudy", DAY, audit=AuditLog(audit), euid=_not_root)
    assert not (tmp_path / "out" / "draft.tbstudy").exists()


def test_h5_a_key_signs_only_the_studies_its_entry_names() -> None:
    """H5: a site that trusts centre A for RA-JAK and centre B for GZQO refuses a RA-JAK package signed by B; a key
    marked for updates is refused for study packages; a key given with no studies, or twice, is refused (default
    deny); the trust file has exactly its fields."""
    jak = _small()
    by_b = sp.build(jak, OTHER_PRIV, DAY)
    a_for_jak = sp.TrustedKey(PUB, frozenset({"RA-JAK"}))
    b_for_gzqo = sp.TrustedKey(OTHER_PUB, frozenset({"GZQO"}))
    got = _refused(by_b, [a_for_jak, b_for_gzqo])
    assert got.step == "signature" and "not trusted to sign for" in str(got)
    assert sp.verify(sp.build(jak, PRIV, DAY), [a_for_jak, b_for_gzqo]).header["study_id"] == "RA-JAK"
    update = sp.TrustedKey(OTHER_PUB, frozenset({"RA-JAK"}), "update")
    got = _refused(by_b, [update])
    assert got.step == "signature" and "trusted for update, not for study packages" in str(got)
    for keys, says in (
        ([OTHER_PUB], "without the studies"),
        ([sp.TrustedKey(OTHER_PUB, frozenset())], "names no study"),
        ([sp.TrustedKey(OTHER_PUB, frozenset({"RA-JAK"}), "anything")], "purpose that is not known"),
        ([OTHER_TRUST, sp.TrustedKey(OTHER_PUB, frozenset({"RA-JAK"}), "update")], "given twice"),
    ):
        with pytest.raises(sp.PackageRefused, match=says):
            sp.verify(by_b, keys)  # type: ignore[arg-type]
    entry = {"key_id": sp.key_id(PUB), "public_key": PUB.decode(), "purpose": "study-package", "studies": ["RA-JAK"]}
    assert sp.load_trust(json.dumps({"format": sp.TRUST_FORMAT, "keys": [entry]}).encode()) == [a_for_jak]
    for bad in (
        {"format": sp.TRUST_FORMAT, "keys": [{**entry, "studies": []}]},
        {"format": sp.TRUST_FORMAT, "keys": [{**entry, "studies": ["ra jak"]}]},
        {"format": sp.TRUST_FORMAT, "keys": [{**entry, "key_id": sp.key_id(OTHER_PUB)}]},
        {"format": sp.TRUST_FORMAT, "keys": [{**entry, "note": "x"}]},
        {"format": sp.TRUST_FORMAT, "keys": [entry, {**entry, "purpose": "update"}]},
        {"format": "tb-study-trust/2", "keys": [entry]},
        {"format": sp.TRUST_FORMAT, "keys": []},
    ):
        with pytest.raises(ValueError):
            sp.load_trust(json.dumps(bad).encode())


# ---------------------------------------------------------------------------------------------- the tool
def _run(*args: str) -> subprocess.CompletedProcess[str]:
    # PYTHONUNBUFFERED out: a CI runner does not set it; no audit folder from the environment
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUNBUFFERED", "TB_AUDIT_DIR", "TB_AUDIT_WRITER")}
    env["PYTHONPATH"] = "libs:services:."
    return subprocess.run(
        [sys.executable, "-m", "tools.study_package", *args], check=False, cwd=ROOT, env=env, capture_output=True,
        text=True,
        timeout=300,
    )  # fmt: skip


def _trust_file(path: Path, entries: list[tuple[bytes, list[str], str]]) -> Path:
    """A tb-study-trust/1 file of ``(public PEM, studies, purpose)``."""
    keys = [{"key_id": sp.key_id(pem), "public_key": pem.decode(), "purpose": purpose, "studies": studies}
            for pem, studies, purpose in entries]  # fmt: skip
    path.write_text(json.dumps({"format": sp.TRUST_FORMAT, "keys": keys}), encoding="utf-8")
    return path


def test_command_line(tmp_path: Path) -> None:
    keys = tmp_path / "keys"
    r = _run("keygen", "--out", str(keys))
    assert r.returncode == 0, r.stderr
    priv, pub = keys / "cc_ed25519.key", keys / "cc_ed25519.pub"
    assert priv.stat().st_mode & 0o777 == 0o600
    assert _run("keygen", "--out", str(keys)).returncode == 1  # a key is never replaced
    study = _store(tmp_path, _small())
    out = tmp_path / "RA-JAK.tbstudy"
    audit = tmp_path / "audit"
    audit.mkdir()
    if os.geteuid() == 0:  # write refuses root (item 1); the rest of this test runs as any other account
        refused = _run("write", str(study), "--key", str(priv), "--out", str(out), "--created", DAY,
                       "--audit-dir", str(audit))  # fmt: skip
        assert refused.returncode == 1 and refused.stderr.count("\n") == 1, refused.stderr
        assert "never written as root" in refused.stderr and "docker compose run --rm" in refused.stderr
        assert not out.exists() and not list(audit.iterdir())
        return
    # no audit folder: no package (H4)
    none = _run("write", str(study), "--key", str(priv), "--out", str(out), "--created", DAY)
    assert none.returncode == 1 and "no audit directory" in none.stderr and not out.exists()
    w = _run("write", str(study), "--key", str(priv), "--out", str(out), "--created", DAY, "--audit-dir", str(audit))
    assert w.returncode == 0, w.stderr
    assert "package RA-JAK-1.0.0-" in w.stdout and sp.key_id(pub.read_bytes()) in w.stdout
    assert "approval tag RA-JAK/v1.0.0" in w.stdout
    from tools import study_package as tool

    assert tool.text("h1_limit", "en") in w.stdout  # H1's limit, said to the person who packs
    assert out.stat().st_mode & 0o777 == 0o600 and not list(tmp_path.glob(".*.part"))
    events = [json.loads(x) for f in sorted(audit.glob("*.jsonl")) for x in f.read_text().splitlines() if x]
    assert [e["event"] for e in events if e["event"].startswith("approve.")] == ["approve.study_package_exported"]
    trust = _trust_file(tmp_path / "trust.json", [(pub.read_bytes(), ["RA-JAK"], sp.STUDY_PURPOSE)])
    v = _run("verify", str(out), "--trust-file", str(trust))
    assert v.returncode == 0 and v.stdout.startswith("verified "), v.stderr
    s = _run("show", str(out))  # shown, NOT verified: exit 3, that line first on stdout and on stderr (item 2)
    first, shown = s.stdout.split("\n", 1)
    assert s.returncode == 3 and json.loads(shown)["study_id"] == "RA-JAK", s.stderr
    assert "NOT checked" in first and s.stderr.startswith(first)
    # another key, a key for another study, and a changed byte: refused with one sentence, exit 1
    other = _trust_file(tmp_path / "other.json", [(OTHER_PUB, ["RA-JAK"], sp.STUDY_PURPOSE)])
    bad = _run("verify", str(out), "--trust-file", str(other))
    assert bad.returncode == 1 and bad.stderr.count("\n") == 1 and "not a trusted" in bad.stderr
    scoped = _trust_file(tmp_path / "scoped.json", [(pub.read_bytes(), ["GZQO"], sp.STUDY_PURPOSE)])
    wrong = _run("verify", str(out), "--trust-file", str(scoped))
    assert wrong.returncode == 1 and "not trusted to sign for" in wrong.stderr
    flipped = bytearray(out.read_bytes())
    flipped[1000] ^= 1
    out.write_bytes(bytes(flipped))
    assert _run("verify", str(out), "--trust-file", str(trust)).returncode == 1
    # an existing --out is not replaced without --force
    again = _run(
        "write", str(study), "--key", str(priv), "--out", str(out), "--created", DAY, "--audit-dir", str(audit)
    )
    assert again.returncode == 1 and "--force" in again.stderr and out.read_bytes() == bytes(flipped)
    forced = _run("write", str(study), "--key", str(priv), "--out", str(out), "--created", DAY, "--force",
                  "--audit-dir", str(audit))  # fmt: skip
    assert forced.returncode == 0 and _run("verify", str(out), "--trust-file", str(trust)).returncode == 0
    # an encrypted key: one sentence, exit 1, no traceback
    locked = tmp_path / "locked.key"
    locked.write_bytes(_locked(priv.read_bytes()))
    locked.chmod(0o600)
    enc = _run("write", str(study), "--key", str(locked), "--out", str(tmp_path / "y"), "--created", DAY,
               "--audit-dir", str(audit))  # fmt: skip
    assert enc.returncode == 1 and enc.stderr.count("\n") == 1 and "Traceback" not in enc.stderr
    assert "unencrypted" in enc.stderr
    # a key file others may read is not used
    priv.chmod(0o644)
    loose = _run("write", str(study), "--key", str(priv), "--out", str(tmp_path / "x"), "--created", DAY,
                 "--audit-dir", str(audit))  # fmt: skip
    assert loose.returncode == 1 and "make it 600" in loose.stderr and not (tmp_path / "x").exists()
    # no key material is ever printed
    secret = priv.read_bytes()
    for result in (r, w, v, s, bad, wrong, loose, again, forced, enc, none):
        text = result.stdout + result.stderr
        assert "PRIVATE KEY" not in text and "PUBLIC KEY" not in text
        assert not any(line in text for line in secret.decode().splitlines()[1:-1])


# ---------------------------------------------------------------------------------------------- review items 6 to 12
def _expected_json(chart_numbers: list[str]) -> bytes:
    """A ``tests/expected.json`` for the small study, keyed by ``chart_numbers``."""
    return json.dumps({
        "engine": sorted(sp.EXPECTED_ENGINES)[0], "index_date": DAY, "ruleset": "RA-JAK", "version": "1.0.0",
        "source": sorted(sp.EXPECTED_SOURCES)[0],
        "patients": {mrn: {"RA-JAK-INC-01": True} for mrn in chart_numbers},
    }).encode()  # fmt: skip


def test_item6_the_verifier_runs_the_writers_content_guards() -> None:
    """Item 6 of the review of f1d1fe3c: a package signed by a trusted key but written by another writer, carrying
    what the local writer refuses (a ``Patient.name``, a patient not of the synthetic site, an ``expected.json`` keyed
    by a chart number of another form, an IR field the model does not have, a value set of a hospital's own codes),
    is refused at the last check of step 5, after the signature, the hashes, the member set and the criteria set; the
    sentence repeats no value."""
    chart = sorted(sp.test_patient_chart_numbers(SYN1 + b"\n" + SYN2 + b"\n"))
    files = {**_small(), "tests/expected.json": _expected_json(chart)}
    members = _members(sp.build(files, PRIV, DAY))
    named = json.loads(SYN1)
    named["name"] = [{"text": "PROBE Example Person"}]
    other = json.loads(SYN1)
    other["id"] = other["identifier"][0]["value"] = "0" * 32
    ir = json.loads(members[FILES_PREFIX + "ir/RA-JAK-INC-01.json"])
    vs = json.loads(members[FILES_PREFIX + "valuesets/VS_HBSAG.json"])
    vs["compose"]["include"].append(
        {"system": sorted(sp.SITE_LOCAL_CODE_SYSTEMS)[0], "concept": [{"code": "PROBE-17", "display": "PROBE ward"}]}
    )
    for path, body, says in (
        ("tests/patients.ndjson", json.dumps(named).encode() + b"\n" + SYN2 + b"\n", "line 1 of tests/patients"),
        ("tests/patients.ndjson", json.dumps(other).encode() + b"\n" + SYN2 + b"\n", "synthetic site's public key"),
        ("tests/expected.json", _expected_json(["DEMO-MRN-42"]).replace(b"DEMO", b"PROBE"), "tests/expected.json"),
        ("ir/RA-JAK-INC-01.json", sm.dumps({**ir, "site_notes": "PROBE"}), "does not load as a criterion"),
        ("valuesets/VS_HBSAG.json", sm.dumps(vs), "valuesets/VS_HBSAG.json"),
    ):
        got = _refused(_without_member(members, "", {path: body}))
        assert got.step == "protocol" and says in str(got), (path, str(got))
        assert "PROBE" not in str(got)
    # the package as the local writer wrote it still verifies
    assert sp.verify(sp.tar_bytes(members), [TRUST]).files["tests/expected.json"]


def test_item9_value_sets_carry_no_hospital_codes() -> None:
    """Item 9: a value set names only the standard and placeholder code systems of the test patients and WHO ICD-10; a code of
    the site-local department system only as a placeholder department code with its display (measured from the
    shipped value sets); no code family of that system. Writer and verifier."""
    department = sorted(sp.SITE_LOCAL_CODE_SYSTEMS)[0]
    pairs: dict[str, str] = {}
    used: set[str] = set()
    for path in SEED_RULESETS.glob("*/valuesets/*.json"):
        doc = json.loads(path.read_bytes())
        used |= {e["valueString"].split("|")[0] for e in doc.get("extension") or ()}
        for inc in doc["compose"]["include"]:
            used.add(inc["system"])
            if inc["system"] == department:
                pairs.update({c["code"]: c["display"] for c in inc["concept"]})
    assert used <= sp.VALUESET_SYSTEMS and used >= sp.VALUESET_SYSTEMS - sp.TEST_PATIENT_SYSTEMS
    assert pairs == sp.PLACEHOLDER_DEPARTMENT_DISPLAYS
    assert set(pairs) <= sp.PLACEHOLDER_DEPARTMENTS
    loinc = {"system": "http://loinc.org", "concept": [{"code": "5196-1", "display": "HBsAg"}]}
    for include, extension in (
        ({"system": department, "concept": [{"code": "PROBE-17", "display": "PROBE ward"}]}, None),
        ({"system": department, "concept": [{"code": "RHEU", "display": "PROBE ward"}]}, None),
        (
            {
                "system": "https://probe-hospital.example/fhir/CodeSystem/ward",
                "concept": [{"code": "W1", "display": "w"}],
            },
            None,
        ),
        (loinc, [{"url": sp.FAMILY_EXT, "valueString": f"{department}|PROBE"}]),
        (loinc, [{"url": sp.FAMILY_EXT, "valueString": "https://probe-hospital.example/cs|W1"}]),
    ):
        extra: dict[str, Any] = {"compose": {"include": [include]}}
        if extension:
            extra["extension"] = extension
        with pytest.raises(ValueError, match="valuesets/VS_HBSAG.json") as e:
            sp.build(_vs_with(**extra), PRIV, DAY)
        assert "PROBE" not in str(e.value) and "probe" not in str(e.value)
    ok = _vs_with(
        compose={"include": [{"system": department, "concept": [{"code": "RHEU", "display": "Rheumatology"}]}]}
    )
    assert sp.verify(sp.build(ok, PRIV, DAY), [TRUST])


def test_item12_a_site_field_in_the_protocol_part_is_refused_for_itself(small: bytes) -> None:
    """Item 12: the site field smuggled into the protocol part, with the package id made again, so that the only
    thing wrong is the site field; the refusal names it."""
    members = _members(small)
    protocol = json.loads(members[sp.PROTOCOL])
    protocol["manifest"]["routing"] = {"list_to": ["x@y.test"]}
    protocol["criteria_sha256"] = sm.criteria_sha256(protocol)
    header = {**json.loads(members[sp.HEADER]), "criteria_sha256": protocol["criteria_sha256"]}
    del header["package_id"]
    got = _refused(_resigned({**members, sp.PROTOCOL: sm.dumps(protocol)}, header=header))
    assert got.step == "protocol" and "routing" in str(got) and "package_id" not in str(got), str(got)


def test_a_the_package_is_written_by_descriptor_and_a_failed_link_says_the_event_was_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(a) The part file is made in the destination folder's descriptor (``O_EXCL | O_NOFOLLOW``, mode 600 under any
    umask); ``--force`` replaces only a regular file; when the event is written and the name cannot be taken, the
    sentence says an event names a package that does not exist and that the command may be run again, and a rerun
    works."""
    from tb_common.audit import AuditLog

    from tools import study_package as tool

    study = _store(tmp_path, _small())
    key = _key_file(tmp_path / "cc.key")
    audit = tmp_path / "audit"
    audit.mkdir()
    outdir = tmp_path / "out"
    outdir.mkdir()
    out = outdir / "RA-JAK.tbstudy"
    log = AuditLog(audit)

    opened: list[tuple[str, int, int | None]] = []
    real_open = os.open

    def spy(path: Any, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
        opened.append((os.fspath(path), flags, dir_fd))
        return real_open(path, flags, mode, dir_fd=dir_fd)

    def no_link(*_a: Any, **_k: Any) -> None:
        raise OSError(1, "Operation not permitted")

    old = os.umask(0)
    try:
        monkeypatch.setattr(os, "open", spy)
        monkeypatch.setattr(os, "link", no_link)
        with pytest.raises(ValueError) as e:
            tool.write(study, key, out, DAY, audit=log, by="host:crc-test", euid=_not_root)
        monkeypatch.undo()
        said = str(e.value)
        assert "was written" in said and "does not exist" in said and "run the command again" in said, said
        assert not out.exists() and not list(outdir.iterdir()), "no package and no part file"
        assert [ev["event"] for ev in _events(audit)].count(tool.EVENT) == 1
        part = [o for o in opened if o[0].endswith(".part")]
        assert len(part) == 1 and part[0][2] is not None and "/" not in part[0][0]
        need = os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        assert part[0][1] & need == need
        # the operator runs it again: a package and a second event
        h = tool.write(study, key, out, DAY, audit=log, by="host:crc-test", euid=_not_root)
        assert out.stat().st_mode & 0o7777 == 0o600 and h["sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()
        assert [ev["event"] for ev in _events(audit)].count(tool.EVENT) == 2
    finally:
        os.umask(old)
    # --force replaces a regular file only, and refuses before any event otherwise
    target = tmp_path / "elsewhere"
    target.write_bytes(b"keep")
    link = outdir / "link.tbstudy"
    link.symlink_to(target)
    folder = outdir / "folder.tbstudy"
    folder.mkdir()
    before = len(_events(audit))
    for where in (link, folder):
        with pytest.raises(ValueError, match="not a regular file"):
            tool.write(study, key, where, DAY, audit=log, force=True, euid=_not_root)
    assert len(_events(audit)) == before and target.read_bytes() == b"keep" and link.is_symlink()
    tool.write(study, key, out, DAY, audit=log, force=True, euid=_not_root)
    assert sp.verify_file(out, [TRUST]) and not [p for p in outdir.iterdir() if p.name.startswith(".")]


def stat_mode(st: os.stat_result) -> int:
    return st.st_mode & 0o7777


def test_b_the_trust_file_is_strict_and_read_safely(tmp_path: Path) -> None:
    """(b) ``tb-study-trust/1``: unknown fields, a key twice in an object, a public key with bytes around its PEM, a
    study id of another case and an empty studies list are refused; the file is read without following a link, as a
    regular file nobody else may write, within its cap; ``verify`` without a trust file is a usage error."""
    from tools import study_package as tool

    entry = {"key_id": sp.key_id(PUB), "public_key": PUB.decode(), "purpose": "study-package", "studies": ["RA-JAK"]}
    good = json.dumps({"format": sp.TRUST_FORMAT, "keys": [entry]}).encode()
    assert sp.load_trust(good) == [sp.TrustedKey(PUB, frozenset({"RA-JAK"}))]
    dup = good.replace(b'"purpose": "study-package"', b'"purpose": "update", "purpose": "study-package"')
    for bad in (
        dup,
        json.dumps({"format": sp.TRUST_FORMAT, "keys": [{**entry, "public_key": "junk\n" + PUB.decode()}]}).encode(),
        json.dumps({"format": sp.TRUST_FORMAT, "keys": [{**entry, "public_key": PUB.decode() + "junk\n"}]}).encode(),
        json.dumps({"format": sp.TRUST_FORMAT, "keys": [{**entry, "studies": []}]}).encode(),
        json.dumps({"format": sp.TRUST_FORMAT, "keys": [entry], "note": "x"}).encode(),
    ):
        with pytest.raises(ValueError):
            sp.load_trust(bad)
    lower = sp.load_trust(json.dumps({"format": sp.TRUST_FORMAT, "keys": [{**entry, "studies": ["RA-JAKX"]}]}).encode())
    assert "not trusted to sign for" in str(_refused(sp.build(_small(), PRIV, DAY), lower))
    # the file
    trust = tmp_path / "trust.json"
    trust.write_bytes(good)
    trust.chmod(0o644)
    assert tool.read_trust_file(trust) == [sp.TrustedKey(PUB, frozenset({"RA-JAK"}))]
    link = tmp_path / "link.json"
    link.symlink_to(trust)
    loose = tmp_path / "loose.json"
    loose.write_bytes(good)
    loose.chmod(0o666)
    big = tmp_path / "big.json"
    big.write_bytes(good + b" " * tool.TRUST_FILE_MAX_BYTES)
    big.chmod(0o644)
    fifo = tmp_path / "fifo.json"
    os.mkfifo(fifo)
    for path, says in ((link, "link"), (loose, "others may write"), (big, "bytes"), (fifo, "regular file")):
        with pytest.raises(ValueError, match=says):
            tool.read_trust_file(path)
    if os.geteuid() == 0:  # a file another account owns is not a trust root of this one
        other = tmp_path / "other.json"
        other.write_bytes(good)
        other.chmod(0o644)
        os.chown(other, 65534, 65534)
        with pytest.raises(ValueError, match="owned by"):
            tool.read_trust_file(other)
    usage = _run("verify", str(trust))
    assert usage.returncode == 2 and "verified" not in usage.stdout


# ------------------------------------------------------------------------- review of ec90c1b4 (writer and export)
def _written(tmp_path: Path, files: dict[str, bytes] | None = None) -> tuple[Path, Path, Path, Path]:
    """``(study in a store, key, audit folder, output folder)`` for a ``write``."""
    study = _store(tmp_path, files or _small())
    key = _key_file(tmp_path / "cc.key")
    audit = tmp_path / "audit"
    audit.mkdir()
    outdir = tmp_path / "out"
    outdir.mkdir()
    return study, key, audit, outdir


def test_item1_write_never_runs_as_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """Item 1: run as root, ``write`` refuses before it reads a file or touches the audit, with one sentence that
    names the supported way (the criteria compiler's container, its service account); the command does too, in the
    operator's language. The audit goes through the product's writer (``open_audit``), as 10D-28's export."""
    from tb_common.audit import AuditLog

    from tools import study_package as tool

    study, key, audit, outdir = _written(tmp_path)
    calls: list[Any] = []

    class Spy(AuditLog):
        def append(self, *a: Any, **k: Any) -> dict[str, Any]:
            calls.append(a)
            return super().append(*a, **k)

    with pytest.raises(tool.RootRefused) as e:
        tool.write(study, key, outdir / "x.tbstudy", DAY, audit=Spy(audit), euid=lambda: 0)
    said = str(e.value)
    assert "never written as root" in said and tool.SUPPORTED_RUN in said and said.count(". ") == 0
    assert "criteria-compiler" in tool.SUPPORTED_RUN and "/data/rulesets/<ID>" in tool.SUPPORTED_RUN
    assert calls == [] and not list(outdir.iterdir()) and not list(audit.iterdir())
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    rc = tool.main(["write", str(study), "--key", str(key), "--out", str(outdir / "y"), "--audit-dir", str(audit),
                    "--lang", "ja"])  # fmt: skip
    monkeypatch.undo()
    err = capsys.readouterr().err
    assert rc == 1 and err.count("\n") == 1 and "root" in err and tool.SUPPORTED_RUN in err
    assert tool.TEXTS["root"]["ja"].split("{")[0] in err and not list(outdir.iterdir())
    assert all(set(t) == {"en", "ja", "zh-TW"} for t in tool.TEXTS.values())
    src = inspect.getsource(tool.open_writer)
    assert "open_audit" in src and "AuditLog(" not in inspect.getsource(tool)


def test_item1_the_file_writer_writes_only_into_its_own_folder(tmp_path: Path) -> None:
    """Item 1: without the journal the event goes to a folder of the running account's only: a link, a folder others
    may write, or another account's folder is refused before anything is written."""
    from tools import study_package as tool

    loose = tmp_path / "loose"
    loose.mkdir()
    loose.chmod(0o777)
    link = tmp_path / "link"
    link.symlink_to(tmp_path)
    for bad in (loose, link, tmp_path / "missing"):
        with pytest.raises(ValueError, match="audit directory"):
            tool._file_audit_dir(bad)
    theirs = tmp_path / "theirs"
    theirs.mkdir()
    if os.geteuid() == 0:
        os.chown(theirs, NOT_ROOT, NOT_ROOT)
    else:
        theirs = Path("/")
    with pytest.raises(ValueError, match="not this account's alone"):
        tool._file_audit_dir(theirs)


def test_item2_the_export_changes_no_owner_and_no_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Item 2: nothing is handed to another account: ``write`` calls no chown, fchown, lchown, chmod, fchmod or
    lchmod (the root-only hand-back of ec90c1b4 is gone with root)."""
    import shutil

    from tb_common.audit import AuditLog

    from tools import study_package as tool

    study, key, audit, outdir = _written(tmp_path)
    secret = audit / "moved-in.key"
    secret.write_bytes(b"SYNTHETIC-SECRET\n")
    secret.chmod(0o600)
    before = os.lstat(secret)
    calls: list[str] = []
    for mod, names in ((os, ("chown", "fchown", "lchown", "chmod", "fchmod", "lchmod")), (shutil, ("chown",))):
        for name in names:
            if hasattr(mod, name):
                monkeypatch.setattr(mod, name, lambda *_a, _n=name, **_k: calls.append(_n))
    tool.write(study, key, outdir / "RA-JAK.tbstudy", DAY, audit=AuditLog(audit), euid=_not_root)
    monkeypatch.undo()
    assert calls == [] and not hasattr(tool, "_give_back")
    after = os.lstat(secret)
    assert (after.st_uid, after.st_gid, after.st_mode) == (before.st_uid, before.st_gid, before.st_mode)


def test_item3_the_destination_is_checked_and_the_name_is_the_audited_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 3: the destination folder is opened without following a link and must be this account's alone; the name
    is linked from the descriptor whose bytes were hashed for the event, so a file swapped in under the hidden name
    between the event and the link is not what takes the name; without ``/proc`` the name is checked against the
    descriptor, removed on a mismatch, and the sentence says so."""
    from tb_common.audit import AuditLog

    from tools import study_package as tool

    study, key, audit, outdir = _written(tmp_path)
    linked = tmp_path / "linked"
    linked.symlink_to(outdir)
    loose = tmp_path / "loose"
    loose.mkdir()
    loose.chmod(0o777)
    log = AuditLog(audit)
    for where, says in ((linked, "symbolic link"), (loose, "not this account's alone")):
        with pytest.raises(ValueError, match=says):
            tool.write(study, key, where / "x.tbstudy", DAY, audit=log, euid=_not_root)
    assert not [e for e in _events(audit) if e["event"] == tool.EVENT]
    other = tmp_path / "other.bin"

    class Swap(AuditLog):  # the hidden file is replaced by another one right after the event
        def append(self, *a: Any, **k: Any) -> dict[str, Any]:
            got = super().append(*a, **k)
            other.write_bytes(b"NOT-THE-PACKAGE")
            part = next(n for n in os.listdir(outdir) if n.endswith(".part"))
            os.rename(other, outdir / part)
            return got

    # the name is linked from the descriptor: the swapped-in file never takes it (the written file, no longer named,
    # cannot be linked either, and the sentence says the event names a package that does not exist)
    out = outdir / "RA-JAK.tbstudy"
    with pytest.raises(ValueError, match="could not take the name") as e:
        tool.write(study, key, out, DAY, audit=Swap(audit), euid=_not_root)
    assert "names a package that does not exist" in str(e.value)
    assert not out.exists() and not [p for p in outdir.iterdir() if p.name.startswith(".")]
    h = tool.write(study, key, out, DAY, audit=log, euid=_not_root)  # untouched: the audited bytes are the file's
    ev = [e for e in _events(audit) if e["event"] == tool.EVENT][-1]
    assert ev["output_sha"] == h["sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()
    assert sp.verify_file(out, [TRUST])
    # no /proc: the hidden name is linked, and the swapped file is caught, removed and said
    real_exists = os.path.exists
    monkeypatch.setattr(os.path, "exists", lambda p: False if str(p).startswith("/proc/self/fd/") else real_exists(p))
    second = outdir / "second.tbstudy"
    with pytest.raises(ValueError, match="is not that package") as e:
        tool.write(study, key, second, DAY, audit=Swap(audit), euid=_not_root)
    monkeypatch.undo()
    assert "names a package that does not exist" in str(e.value)
    assert not second.exists() and not [p for p in outdir.iterdir() if p.name.startswith(".")]


def test_item4_only_the_bytes_of_the_approval_tag_are_packed(tmp_path: Path) -> None:
    """Item 4: ``status: approved`` is bound to the approval: the folder must be its approval tag's in the box's
    rule-set store; a plain folder, a file edited after approval, a version with no tag, a tag that names nobody (a
    shipped example) and an approval that arrived in an update are refused before any event."""
    from tb_common.audit import AuditLog
    from tb_common.ruleset import SEEDED_TAG

    from tools import study_package as tool

    key = _key_file(tmp_path / "cc.key")
    audit = tmp_path / "audit"
    audit.mkdir()
    log = AuditLog(audit)

    def refused(study: Path, says: str) -> None:
        out = tmp_path / "out" / f"{study.parent.parent.name}.tbstudy"
        out.parent.mkdir(exist_ok=True)
        with pytest.raises(ValueError, match=says):
            tool.write(study, key, out, DAY, audit=log, euid=_not_root)
        assert not out.exists()

    plain = tmp_path / "plain" / "RA-JAK"
    _write_folder(plain, _small())
    refused(plain, "not in the box's rule-set store")
    edited = _store(tmp_path / "edited", _small())
    (edited / "ir" / "RA-JAK-INC-01.json").write_bytes((edited / "ir" / "RA-JAK-INC-01.json").read_bytes() + b" ")
    refused(edited, "differs from its approval tag RA-JAK/v1.0.0")
    added = _store(tmp_path / "added", _small())
    (added / "valuesets" / "VS_EXTRA.json").write_bytes((added / "valuesets" / "VS_HBSAG.json").read_bytes())
    refused(added, "differs from its approval tag")
    refused(_store(tmp_path / "seeded", _small(), message=f"RA-JAK v1.0.0 {SEEDED_TAG}"), "names nobody")
    refused(_store(tmp_path / "arrived", _small(), message="RA-JAK v1.0.0 (offline update, vendor)"), "arrived")
    untagged = _store(tmp_path / "untagged", _small())
    m = yaml.safe_load((untagged / "manifest.yaml").read_bytes())
    m["version"] = "1.0.1"
    (untagged / "manifest.yaml").write_text(yaml.safe_dump(m, allow_unicode=True), encoding="utf-8")
    refused(untagged, "no approval tag")
    assert not [e for e in _events(audit) if e["event"] == tool.EVENT]


def test_item4_every_shipped_study_packs_from_its_approval_tag(tmp_path: Path) -> None:
    """Item 4 and the card: each of the 8 shipped studies, approved in a store, packs through ``write`` and verifies."""
    from tb_common.audit import AuditLog

    from tools import study_package as tool

    key = _key_file(tmp_path / "cc.key")
    audit = tmp_path / "audit"
    audit.mkdir()
    (tmp_path / "out").mkdir()
    for ruleset in SHIPPED:
        study = _store(tmp_path / ruleset, _folder(ruleset), sid=ruleset)
        out = tmp_path / "out" / f"{ruleset}.tbstudy"
        h = tool.write(study, key, out, DAY, audit=AuditLog(audit), euid=_not_root)
        assert sp.verify_file(out, [TRUST]).header["criteria_sha256"] == h["criteria_sha256"]
    assert len(SHIPPED) == 8 and len([e for e in _events(audit) if e["event"] == tool.EVENT]) == 8


def _gzqo_with(change: Callable[[list[dict[str, Any]]], None]) -> dict[str, bytes]:
    files = _folder("GZQO")
    lines = [json.loads(x) for x in files[sp.TEST_PATIENTS].splitlines() if x.strip()]
    change(lines)
    files[sp.TEST_PATIENTS] = b"".join(json.dumps(r, separators=(",", ":")).encode() + b"\n" for r in lines)
    return files


def _first(lines: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    return next(r for r in lines if r["resourceType"] == kind)


@pytest.mark.parametrize(
    "case",
    ["no subject", "subject an encounter not here", "coverage reference typed", "record id typed",
     "claim patient not here", "appointment without patient", "encounter reference not here"],
)  # fmt: skip
def test_item5_every_record_names_a_patient_of_the_file_and_every_reference_resolves(case: str) -> None:
    """Item 5: every record other than a Patient names one of the file's patients in its own element (measured per
    type), has an id of the shipped shape (32 lowercase hex), and every reference names a record of the file, the
    placeholder practitioners and organisations aside."""

    def change(lines: list[dict[str, Any]]) -> None:
        if case == "no subject":
            del _first(lines, "Observation")["subject"]
        elif case == "subject an encounter not here":
            _first(lines, "Observation")["subject"] = {"reference": "Encounter/zz-not-here"}
        elif case == "coverage reference typed":
            claim = _first(lines, "Claim")
            claim["insurance"][0]["coverage"] = {"reference": "Coverage/JohnDoe-A123456789"}
        elif case == "record id typed":
            _first(lines, "Condition")["id"] = "JohnDoe-A123456789"
        elif case == "claim patient not here":
            _first(lines, "Claim")["patient"] = {"reference": "Patient/" + "0" * 32}
        elif case == "appointment without patient":
            appt = _first(lines, "Appointment")
            appt["participant"] = [p for p in appt["participant"] if not p["actor"]["reference"].startswith("Patient/")]
        else:
            enc = next(r for r in lines if r["resourceType"] == "Condition" and "encounter" in r)
            enc["encounter"] = {"reference": "Encounter/" + "f" * 32}

    with pytest.raises(ValueError, match="cannot be packaged"):
        sp.build(_gzqo_with(change), PRIV, DAY)


def test_item5_the_patient_elements_and_record_ids_are_measured() -> None:
    """Item 5: :data:`TEST_PATIENT_SUBJECT` is what the shipped test patients use, for every type but Patient, and
    every shipped record's id has :data:`TEST_PATIENT_RECORD_ID`'s shape."""
    used: dict[str, set[str]] = {}
    for ruleset in SHIPPED:
        data = _folder(ruleset).get(sp.TEST_PATIENTS)
        for line in (data or b"").splitlines():
            r = json.loads(line)
            if r["resourceType"] == "Patient":
                continue
            assert sp.TEST_PATIENT_RECORD_ID.fullmatch(r["id"])
            fields = {f for f in ("subject", "patient", "beneficiary") if f in r}
            if r["resourceType"] == "Appointment":
                fields = {"participant.actor"}
            used.setdefault(r["resourceType"], set()).update(fields)
    assert {k: {v} for k, v in sp.TEST_PATIENT_SUBJECT.items()} == used
    assert set(sp.TEST_PATIENT_SUBJECT) == set(sp.TEST_PATIENT_ELEMENTS) - {"Patient"}


def test_item6_the_actor_is_the_account_and_sudo_user_only_a_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 6: who is taken from the account database by uid, not from LOGNAME or USER; SUDO_USER is recorded as
    ``sudo_user_claimed``."""
    import pwd

    from tb_common.audit import AuditLog

    from tools import study_package as tool

    monkeypatch.setenv("LOGNAME", "spoofed-name")
    monkeypatch.setenv("USER", "spoofed-name")
    monkeypatch.setenv("SUDO_USER", "claimed-name")
    try:
        name = pwd.getpwuid(os.getuid()).pw_name
    except KeyError:
        name = f"uid:{os.getuid()}"
    assert tool.actor() == (f"host:{name}", "claimed-name")
    study, key, audit, outdir = _written(tmp_path)
    tool.write(study, key, outdir / "RA-JAK.tbstudy", DAY, audit=AuditLog(audit), euid=_not_root)
    ev = [e for e in _events(audit) if e["event"] == tool.EVENT][-1]
    assert ev["actor"] == f"host:{name}" and ev["detail"]["sudo_user_claimed"] == "claimed-name"
    monkeypatch.setattr(pwd, "getpwuid", lambda _uid: (_ for _ in ()).throw(KeyError(_uid)))
    monkeypatch.delenv("SUDO_USER")
    assert tool.actor() == (f"host:uid:{os.getuid()}", None)


def test_item7_the_key_file_is_read_once_and_strictly(tmp_path: Path) -> None:
    """Item 7: the private key is opened once without following a link and read from that descriptor: a regular file
    of the running account's with no group or other bit; a key the trust file trusts for updates is refused."""
    from tools import study_package as tool

    key = _key_file(tmp_path / "cc.key")
    assert tool._private_key(key) == PRIV
    link = tmp_path / "link.key"
    link.symlink_to(key)
    fifo = tmp_path / "fifo.key"
    os.mkfifo(fifo)
    with pytest.raises(ValueError, match="symbolic link"):
        tool._private_key(link)
    with pytest.raises(ValueError, match="not a regular file"):
        tool._private_key(fifo)
    theirs = _key_file(tmp_path / "theirs.key")
    if os.geteuid() == 0:
        os.chown(theirs, NOT_ROOT, NOT_ROOT)
    else:
        theirs = Path("/etc/passwd")
    with pytest.raises(ValueError, match="owned by another account"):
        tool._private_key(theirs)
    update = [sp.TrustedKey(PUB, frozenset({"RA-JAK"}), "update")]
    with pytest.raises(ValueError, match="trusted for updates"):
        tool._private_key(key, update)
    assert tool._private_key(key, [sp.TrustedKey(PUB, frozenset({"RA-JAK"}))]) == PRIV


@pytest.mark.parametrize(("value", "ok"), [(33.3, True), (100, True), (0, True), (33.33, False), (100.1, False),
                                           (-0.1, False), (True, False), (12.000001, False)])  # fmt: skip
def test_item7_per_criterion_carries_the_shipped_precision(value: Any, ok: bool) -> None:
    """Item 7: ``agreement.per_criterion`` is a number from 0 to 100 with at most one decimal, as every shipped value
    is (no numeric side channel), at the writer's real call."""
    with_agreement = [r for r in SHIPPED if (json.loads(_folder(r).get("tests/expected.json", b"{}")).get("agreement"))]
    assert with_agreement
    for r in with_agreement:
        per = json.loads(_folder(r)["tests/expected.json"])["agreement"]["per_criterion"]
        assert all(type(v) in (int, float) and float(f"{v:.1f}") == v for v in per.values())
    files = _folder(with_agreement[0])
    doc = json.loads(files["tests/expected.json"])
    first = sorted(doc["agreement"]["per_criterion"])[0]
    doc["agreement"]["per_criterion"][first] = value
    files["tests/expected.json"] = json.dumps(doc).encode()
    if ok:
        assert sp.build(files, PRIV, DAY)
    else:
        with pytest.raises(ValueError, match="at most 1 decimal"):
            sp.build(files, PRIV, DAY)


def test_item7_a_manifest_refusal_names_the_field_not_its_value() -> None:
    """Item 7: a manifest the model refuses is said by its field's path; the value is not echoed."""
    files = _folder("GZQO")
    files["manifest.yaml"] += b"\npopulation: SYNTH-NAME-ZZZ\n"
    with pytest.raises(ValueError) as e:
        sp.build(files, PRIV, DAY)
    assert "population" in str(e.value) and "SYNTH-NAME-ZZZ" not in str(e.value) and "\n" not in str(e.value)


# ---------------------------------------------------------------------------------------------- review of 02b55d8a
def _timed(call: Callable[[], Any]) -> float:
    import time

    start = time.monotonic()
    with contextlib.suppress(sp.PackageRefused):
        call()
    return time.monotonic() - start


def test_r1_the_depth_scan_is_linear_and_the_meta_members_are_capped_before_any_parse(
    small: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 1: the reviewer's header (a quote, then an escaped quote repeated) took 38 s at 80 KB in the regex scan,
    before the signature; the scan is one linear pass, and the header and hash list are capped (64 KiB, 1 MiB) from
    the tar header, before a byte of them is scanned or parsed. Bounds generous for a loaded machine."""
    _, pub = ed25519_generate()
    anyone = [sp.TrustedKey(pub, frozenset({"RA-JAK"}))]
    for n in (40_000, 2 << 20):  # 80 KB, and 4 MiB (the old cap)
        evil = b'"' + b'\\"' * n

        def scan(e: bytes = evil) -> int:
            return sp.json_depth(e)

        assert _timed(scan) < 2.0
    at_cap = b'"' + b'\\"' * ((sp.STUDY_PACKAGE_MAX_HEADER_BYTES - 1) // 2)
    assert len(at_cap) <= sp.STUDY_PACKAGE_MAX_HEADER_BYTES
    data = sp.tar_bytes({"hashes.json": b"{}", "header.json": at_cap, "protocol.json": b"{}",
                         "signature.ed25519": bytes(64)})  # fmt: skip
    assert _timed(lambda: sp.verify(data, anyone)) < 2.0
    assert _refused(data, anyone).step == "tar"

    # over the cap: refused from the tar header, nothing scanned or parsed
    def never(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("scanned or parsed before the cap")

    monkeypatch.setattr(sp, "json_depth", never)
    monkeypatch.setattr(sm, "load_json", never)
    members = _members(small)
    for name, cap in ((sp.HEADER, sp.STUDY_PACKAGE_MAX_HEADER_BYTES), (sp.HASHES, sp.STUDY_PACKAGE_MAX_HASHES_BYTES)):
        got = _refused(sp.tar_bytes({**members, name: b"{" + b" " * cap + b"}"}))
        assert got.step == "tar" and f"may be at most {cap:,} bytes" in str(got), str(got)
    assert sp.STUDY_PACKAGE_MAX_HEADER_BYTES == 64 << 10 and sp.STUDY_PACKAGE_MAX_HASHES_BYTES == 1 << 20
    assert sp.json_depth is never  # (the patch held: no path above reached a scan)


_EVIL = "\x1b[31mEVIL\x07\u009b\u202e"


def _plain(text: str) -> bool:
    return all(c == "\n" or 0x20 <= ord(c) < 0x7F for c in text)


def test_r2_no_text_of_the_sender_is_echoed_before_the_signature_and_what_is_shown_is_escaped(
    small: bytes, tmp_path: Path, capsys: Any
) -> None:
    """Item 2: an unknown header field, a pin and a hash-list entry name, all before the signature, are named by
    place and length only; a field shown after the signature, and ``show``'s header, are printable ASCII; ``show``
    says NOT checked first, on stdout and stderr, and exits 3."""
    from tools import study_package as tool

    members = _members(small)
    header = json.loads(members[sp.HEADER])
    hashes = json.loads(members[sp.HASHES])
    for bad in (
        {**members, sp.HEADER: sm.dumps({**header, _EVIL: "x"})},
        {**members, sp.HEADER: sm.dumps({**header, "pins": {_EVIL: 1}})},
        {**members, sp.HASHES: sm.dumps({**hashes, _EVIL: "zz"})},
    ):
        got = _refused(sp.tar_bytes(bad))
        assert got.step == "tar" and "EVIL" not in str(got) and _plain(str(got)), str(got)
        assert "characters" in str(got)
    # after the signature: the study id a trusted key signed, shown escaped
    renamed = _resigned(members, header={**header, "study_id": "RA-JAK\u202e"})
    got = _refused(renamed, [sp.TrustedKey(PUB, frozenset({"RA-JAK"}))])
    assert got.step == "signature" and "\u202e" not in str(got) and "\\u202e" in str(got) and _plain(str(got))
    # show on a forged package (no valid signature) with a C1 control and a bidi mark in its study id
    forged = {**members, sp.HEADER: sm.dumps({**header, "study_id": "RA-JAK\u009b31m\u202e"}), sp.SIGNATURE: bytes(64)}
    path = tmp_path / "forged.tbstudy"
    path.write_bytes(sp.tar_bytes(forged))
    assert tool.main(["show", str(path)]) == tool.SHOWN == 3
    out, err = capsys.readouterr()
    assert out.startswith(tool.SHOWN_NOT_VERIFIED + "\n") and err.startswith(tool.SHOWN_NOT_VERIFIED)
    assert _plain(out) and "\\u009b" in out and "\\u202e" in out
    assert sp.printable("a\x1b\x7f\u202e\U0001f600") == "a\\x1b\\x7f\\u202e\\U0001f600"


@pytest.mark.parametrize(
    ("member", "junk"),
    [
        *[("files/ir/RA-JAK-INC-01.json", b) for b in (b"[]", b"null", b"1", b'"x"', b"{bad", b"\xff\xfe", b"")],
        *[("files/valuesets/VS_HBSAG.json", b) for b in (b"1e400", b"{bad", b"\xff\xfe")],
    ],
)
def test_r3_a_signed_member_of_the_wrong_type_is_refused_in_one_sentence(
    small: bytes, member: str, junk: bytes
) -> None:
    """Item 3: with a package signed by a trusted key, an IR member that is not an object, not JSON, not UTF-8, or a
    value set of ``1e400`` raised TypeError, AttributeError or a bare ValueError in ``study_manifest``: now a
    PackageRefused of one sentence."""
    got = _refused(_resigned({**_members(small), member: junk}))
    assert type(got) is sp.PackageRefused and got.step == "protocol", str(got)


def test_r3_a_seeded_fuzz_lets_nothing_but_a_refusal_out(small: bytes, tmp_path: Path, monkeypatch: Any) -> None:
    """Item 3: a small deterministic fuzz (truncations, a byte changed in each member, members of the wrong JSON
    type, the unsigned and the re-signed); only a PackageRefused leaves ``verify``; the command says one sentence and
    exits 1, and an internal error is one sentence and exit 2, never a traceback."""
    import random

    from tools import study_package as tool

    rng = random.Random(1183)
    members = _members(small)
    cases: list[bytes] = [small[:i] for i in range(0, len(small), 97)]
    files = [*sorted(n for n in members if n.startswith(sp.FILES)), sp.PROTOCOL]
    for name in sorted(members):
        for _ in range(12):
            data = bytearray(members[name] or b"\x00")
            data[rng.randrange(len(data))] = rng.randrange(256)
            cases.append(sp.tar_bytes({**members, name: bytes(data)}))
            if name in files:
                cases.append(_resigned({**members, name: bytes(data)}))
    for name in files:
        for junk in (b"", b"null", b"[]", b"{}", b'"x"', b"1", b"1e400", b"\xff\xfe", b'{"id": 1}', b'{"review": []}'):
            cases.append(_resigned({**members, name: junk}))
    assert len(cases) > 300
    for case in cases:
        if case == small:
            continue
        with pytest.raises(sp.PackageRefused):
            sp.verify(case, [TRUST])
    # the command: a refusal is one line and exit 1; anything else one sentence and exit 2
    trust = _trust_file(tmp_path / "trust.json", [(PUB, ["RA-JAK"], sp.STUDY_PURPOSE)])
    bad = tmp_path / "bad.tbstudy"
    bad.write_bytes(_resigned({**members, "files/ir/RA-JAK-INC-01.json": b"[]"}))
    assert tool.main(["verify", str(bad), "--trust-file", str(trust)]) == 1

    def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("secret detail")

    monkeypatch.setattr(sp, "verify_file", boom)
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        assert tool.main(["verify", str(bad), "--trust-file", str(trust)]) == 2
    assert err.getvalue() == "study package: the package could not be read (internal)\n"
    monkeypatch.undo()
    monkeypatch.setattr(sp, "_structure", boom)
    got = _refused(small)
    assert got.step == "internal" and "RuntimeError" in str(got) and "secret" not in str(got)


def _key_refused(data: bytes, keys: list[sp.TrustedKey]) -> sp.PackageRefused:
    """A refusal of the trusted keys given (one sentence, not about the package)."""
    with pytest.raises(sp.PackageRefused) as exc:
        sp.verify(data, keys)
    assert "\n" not in str(exc.value)
    return exc.value


def _other_algorithm_pem() -> bytes:
    import base64

    der = bytes.fromhex("3011300506032a0304" + "0308" + "00" + "41" * 7)
    return b"-----BEGIN PUBLIC KEY-----\n" + base64.encodebytes(der) + b"-----END PUBLIC KEY-----\n"


def test_r4_a_trust_file_of_another_algorithm_or_nested_deep_is_refused_in_one_sentence(small: bytes) -> None:
    """Item 4: a SubjectPublicKeyInfo with another OID raised cryptography's UnsupportedAlgorithm; a trust file nested
    very deep raised RecursionError. Both are refused with one sentence."""
    pem = _other_algorithm_pem()
    doc = {"format": sp.TRUST_FORMAT, "keys": [{"key_id": "ed25519:0000000000000000", "public_key": pem.decode(),
                                                "purpose": sp.STUDY_PURPOSE, "studies": ["RA-JAK"]}]}  # fmt: skip
    with pytest.raises(ValueError, match="is not an Ed25519 public key") as exc:
        sp.load_trust(json.dumps(doc).encode())
    assert type(exc.value) is ValueError
    got = _key_refused(small, [sp.TrustedKey(pem, frozenset({"RA-JAK"}))])
    assert got.step == "signature" and "not an Ed25519 public key" in str(got)
    for deep in (b"[" * 200_000, b'{"format": "tb-study-trust/1", "keys": ' + b"[" * 9 + b"]" * 9 + b"}"):
        with pytest.raises(ValueError, match="nests deeper than 8") as exc:
            sp.load_trust(deep)
        assert type(exc.value) is ValueError


def test_r5_a_fifo_a_device_or_a_link_is_never_read_as_a_package_or_a_trust_file(tmp_path: Path, small: bytes) -> None:
    """Item 5: the size was taken by stat() and the file read by path: a FIFO stats 0 and was read for 1 MiB, and
    /dev/zero would never end. Now each is opened once (O_NOFOLLOW | O_NONBLOCK), checked on the descriptor (a
    regular file) and read at most to its cap from it."""
    from tools import study_package as tool

    fifo = tmp_path / "pipe.tbstudy"
    os.mkfifo(fifo)
    link = tmp_path / "link.tbstudy"
    real = tmp_path / "real.tbstudy"
    real.write_bytes(small)
    link.symlink_to(real)
    for path in (fifo, Path("/dev/zero"), link, tmp_path):
        with pytest.raises(sp.PackageRefused) as exc:
            sp.verify_file(path, [TRUST])
        assert exc.value.step == "tar"
    assert "not a regular file" in str(_raises(lambda: sp.read_file(fifo)))
    assert sp.verify_file(real, [TRUST]).header["study_id"] == "RA-JAK"
    with pytest.raises(ValueError, match="is over 10 bytes|may be at most 10 bytes"):
        sp.read_capped(real, 10, "the file")
    trust_fifo = tmp_path / "trust.fifo"
    os.mkfifo(trust_fifo)
    with pytest.raises(ValueError, match="not a regular file"):
        tool.read_trust_file(trust_fifo)
    with pytest.raises(ValueError, match="not a regular file"):
        tool.read_trust_file(Path("/dev/zero"))


def _raises(call: Callable[[], Any]) -> BaseException:
    with pytest.raises(Exception) as exc:  # the caller checks the type and the sentence
        call()
    return exc.value


def test_r6_a_key_is_trusted_only_for_exact_study_ids_and_patterns_match_whole(small: bytes) -> None:
    """Item 6: ``studies`` given as a text matched by substring ("JAK" in "RA-JAK"); now only a tuple or frozenset
    of exact study ids is taken. The name and field patterns match whole (a final newline no longer passes)."""
    members = _members(small)
    header = json.loads(members[sp.HEADER])
    jak = _resigned(members, header={**header, "study_id": "JAK"})
    got = _key_refused(jak, [sp.TrustedKey(PUB, "RA-JAK")])  # type: ignore[arg-type]
    assert got.step == "signature" and "tuple or frozenset" in str(got)
    assert _refused(jak, [sp.TrustedKey(PUB, frozenset({"RA-JAK"}))]).step == "signature"
    assert _key_refused(small, [sp.TrustedKey(PUB, ["RA-JAK"])]).step == "signature"  # type: ignore[arg-type]
    assert _key_refused(small, [sp.TrustedKey(PUB, ("RA-JAK ",))]).step == "signature"
    assert sp.verify(small, [sp.TrustedKey(PUB, ("RA-JAK",))]).header["study_id"] == "RA-JAK"
    assert sp._name_refusal("files/ir/x.json\n") is not None
    for field, value in (("key_id", header["key_id"] + "\n"), ("criteria_sha256", header["criteria_sha256"] + "\n"),
                         ("created", header["created"] + "\n")):  # fmt: skip
        assert sp._header_refusal({**header, field: value}) is not None, field


def test_r7_only_the_configured_store_and_the_compilers_own_approval_tag_are_packed(tmp_path: Path) -> None:
    """Item 7 (blocker): a forged store (a repository made anywhere, tagged ``RA-JAK/v1.0.0 -m anything``) packed
    with an ``approve.`` event. Now the store must be the box's configured one (TB_RULESETS_DIR, the same folder),
    and the tag the compiler's approval (message, tagger, the tagged manifest's approver); the event records the tag
    object, the commit and the approver."""
    from dulwich.repo import Repo
    from tb_common.audit import AuditLog

    from tools import study_package as tool

    key = _key_file(tmp_path / "cc.key")
    audit = tmp_path / "audit"
    audit.mkdir()
    log = AuditLog(audit)
    (tmp_path / "out").mkdir()

    def refused(study: Path, says: str) -> None:
        out = tmp_path / "out" / f"{study.parent.parent.name}.tbstudy"
        with pytest.raises(ValueError, match=says):
            tool.write(study, key, out, DAY, audit=log, euid=_not_root)
        assert not out.exists()

    real = _store(tmp_path / "real", _small())  # the configured store
    forged = _store(tmp_path / "forged", _small(), message="anything at all", tagger="x", configure=False)
    refused(forged, "not in the box's rule-set store")
    os.environ["TB_RULESETS_DIR"] = str(forged.parent)  # even configured, the tag is not an approval
    refused(forged, "not the criteria compiler's approval")
    refused(_store(tmp_path / "tagger", _small(), tagger="someone-else"), "its tagger is not the approver")
    refused(
        _store(tmp_path / "who", _small(), message="RA-JAK v1.0.0 approved by mallory", tagger="mallory"),
        "review.approved_by is not the approver",
    )
    refused(_store(tmp_path / "suffix", _small(), message="RA-JAK v1.0.0 approved by crc1@hospa.test\n"), "not the")
    bare = _store(tmp_path / "bare", _small())
    repo = Repo(str(bare.parent))
    refs: Any = repo.refs
    try:
        commit = refs[b"refs/heads/main"]
        del refs[b"refs/tags/RA-JAK/v1.0.0"]
        refs[b"refs/tags/RA-JAK/v1.0.0"] = commit  # a lightweight tag names nobody
    finally:
        repo.close()
    refused(bare, "names nobody")
    assert not [e for e in _events(audit) if e["event"] == tool.EVENT]
    # the real store packs, and the event names the tag object, the commit and the approver
    os.environ["TB_RULESETS_DIR"] = str(real.parent)
    h = tool.write(real, key, tmp_path / "out" / "ok.tbstudy", DAY, audit=log, euid=_not_root)
    a = h["approval"]
    repo = Repo(str(real.parent))
    refs = repo.refs
    try:
        tag_obj: Any = repo[refs[b"refs/tags/RA-JAK/v1.0.0"]]
        assert a.tag_sha == refs[b"refs/tags/RA-JAK/v1.0.0"].decode()
        assert a.commit == tag_obj.object[1].decode()
    finally:
        repo.close()
    assert a.by == "crc1@hospa.test"
    (ev,) = [e for e in _events(audit) if e["event"] == tool.EVENT]
    assert ev["detail"]["approval_tag_sha"] == a.tag_sha and ev["detail"]["approval_commit"] == a.commit
    assert ev["detail"]["approved_by"] == a.by


def test_r8_keygen_writes_both_files_by_descriptor_and_never_through_a_link(tmp_path: Path) -> None:
    """Item 8: ``keygen`` (which may run as root) wrote the public key by path, following a link. Now both files are
    created O_EXCL | O_NOFOLLOW in the folder's descriptor; an existing name, a link among them, is refused and
    nothing is written."""
    from tools import study_package as tool

    keys = tmp_path / "keys"
    priv, pub, kid = tool.keygen(keys)
    assert stat_mode(priv.stat()) == 0o600 and stat_mode(pub.stat()) == 0o644 and kid == sp.key_id(pub.read_bytes())
    victim = tmp_path / "victim"
    victim.write_bytes(b"untouched")
    trap = tmp_path / "trap"
    trap.mkdir()
    (trap / tool.PUBLIC).symlink_to(victim)
    with pytest.raises(ValueError, match="exists"):
        tool.keygen(trap)
    assert victim.read_bytes() == b"untouched" and sorted(p.name for p in trap.iterdir()) == [tool.PUBLIC]
    with pytest.raises(ValueError, match="never replaced"):
        tool.keygen(keys)


def test_r9_a_test_patient_refers_only_to_records_of_the_same_patient_once() -> None:
    """Item 9: a Claim could name another patient's Coverage, a coverage could be written ``Patient/<pid>``, and a
    record could be held twice; now a reference names a record of the same patient, of the type its element takes
    (measured), and each type and id is held once."""
    lines = [json.loads(x) for x in _folder("RA-BIO")[sp.TEST_PATIENTS].splitlines() if x.strip()]

    def refusal(change: Callable[[list[dict[str, Any]]], None]) -> str | None:
        import copy

        mine = copy.deepcopy(lines)
        change(mine)
        return sp._test_patients_refusal(b"".join(json.dumps(r).encode() + b"\n" for r in mine))

    assert refusal(lambda _l: None) is None
    claim = _first(lines, "Claim")
    pid = claim["patient"]["reference"]
    other = next(c for c in lines if c["resourceType"] == "Coverage" and c["beneficiary"]["reference"] != pid)

    def coverage_of_another(rows: list[dict[str, Any]]) -> None:
        _first(rows, "Claim")["insurance"][0]["coverage"]["reference"] = "Coverage/" + other["id"]

    def coverage_as_patient(rows: list[dict[str, Any]]) -> None:
        _first(rows, "Claim")["insurance"][0]["coverage"]["reference"] = pid

    def twice(rows: list[dict[str, Any]]) -> None:
        rows.append(dict(_first(rows, "Observation")))

    assert "of another test patient" in (refusal(coverage_of_another) or "")
    assert "a type that element does not take" in (refusal(coverage_as_patient) or "")
    assert "already holds" in (refusal(twice) or "")


def test_r9_the_reference_types_are_measured() -> None:
    """Item 9: the type each reference element takes is what the shipped test patients hold, exactly."""
    measured: dict[tuple[str, str], set[str]] = {}
    for ruleset in SHIPPED:
        data = _folder(ruleset).get(sp.TEST_PATIENTS)
        for line in (data or b"").splitlines():
            if line.strip():
                record = json.loads(line)
                for path, ref in sp._reference_paths(record):
                    measured.setdefault((record["resourceType"], path), set()).add(ref.split("/")[0])
    assert {k: frozenset(v) for k, v in measured.items()} == sp.TEST_PATIENT_REFERENCE_FIELDS


def test_r9_stale_part_files_of_this_command_are_removed_and_named(tmp_path: Path) -> None:
    """Item 9: a SIGKILL between the event and the link left a hidden ``.<name>.<pid>.part`` (0600). The next run
    removes, in the destination only, regular files of the command's own pattern owned by the running account whose
    writer is gone, and says which; anything else is kept."""
    from tb_common.audit import AuditLog

    from tools import study_package as tool

    study, key, audit, outdir = _written(tmp_path)
    gone_pid = 4_194_305  # above the kernel's largest pid: no such process
    stale = outdir / f".RA-JAK.tbstudy.{gone_pid}.part"
    stale.write_bytes(b"x")
    stale.chmod(0o600)
    final = outdir / f".old.tbstudy.{gone_pid}.part.final"
    final.write_bytes(b"x")
    live = outdir / f".RA-JAK.tbstudy.{os.getppid()}.part"  # a run that is still going keeps its file
    live.write_bytes(b"x")
    other = outdir / ".notes.part"
    other.write_bytes(b"x")
    linked = outdir / f".link.tbstudy.{gone_pid}.part"
    linked.symlink_to(other)
    h = tool.write(study, key, outdir / "RA-JAK.tbstudy", DAY, audit=AuditLog(audit), euid=_not_root)
    assert h["removed_parts"] == sorted([stale.name, final.name])
    assert not stale.exists() and not final.exists()
    assert live.exists() and other.exists() and linked.is_symlink()
