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
        "id": "a1",
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


def test_h4_a_package_is_released_only_after_its_audit_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """H4: the host command writes the box's audit event (who, the study, version, package id, sha256, key id; no
    content) before the package takes its name, gives the event's files to the audit folder's owner (injected here:
    the test runs as any user), and leaves no package when there is no audit folder, the event cannot be written, or
    the study is not approved."""
    from tools import study_package as tool

    study = tmp_path / "RA-JAK"
    _write_folder(study, _small())
    key = tmp_path / "cc.key"
    key.write_bytes(PRIV)
    key.chmod(0o600)
    audit = tmp_path / "audit"
    audit.mkdir()
    out = tmp_path / "out" / "RA-JAK.tbstudy"
    out.parent.mkdir()
    owned: list[tuple[Path, bool]] = []

    def own(folder: Path) -> None:  # called after the event, before the package is renamed
        owned.append((folder, out.exists()))

    with pytest.raises(ValueError, match="no audit directory"):
        tool.write(study, key, out, DAY, audit_dir=None, own=own)
    with pytest.raises(ValueError, match="is not a folder"):
        tool.write(study, key, out, DAY, audit_dir=tmp_path / "missing", own=own)
    assert not out.exists() and not (tmp_path / "missing").exists()
    h = tool.write(study, key, out, DAY, audit_dir=audit, tz="Asia/Taipei", by="host:crc-test", own=own)
    assert owned == [(audit, False)]  # the event was written, and the folder given back, before the package's name
    assert out.read_bytes() and out.stat().st_mode & 0o777 == 0o600
    assert not list(out.parent.glob(".*")), "no hidden part file left"
    events = [json.loads(x) for f in sorted(audit.glob("*.jsonl")) for x in f.read_text().splitlines() if x]
    exported = [e for e in events if e["event"] == tool.EVENT]
    assert len(exported) == 1
    ev = exported[0]
    assert ev["actor"] == "host:crc-test" and ev["ruleset"] == "RA-JAK" and ev["ruleset_version"] == "1.0.0"
    assert ev["output_sha"] == hashlib.sha256(out.read_bytes()).hexdigest() == h["sha256"]
    assert ev["detail"] == {"package_id": h["package_id"], "key_id": sp.key_id(PUB), "created": DAY,
                            "protocol_version": h["protocol_version"], "criteria_sha256": h["criteria_sha256"]}  # fmt: skip
    assert PID1 not in json.dumps(events)  # no content of the package in the audit

    # the event cannot be written: no package, no part file
    def full(*_a: Any, **_k: Any) -> None:
        raise OSError("disk full")

    from tb_common import audit as audit_mod

    monkeypatch.setattr(audit_mod.AuditLog, "append", full)
    second = tmp_path / "out" / "second.tbstudy"
    with pytest.raises(ValueError, match="audit event could not be written"):
        tool.write(study, key, second, DAY, audit_dir=audit, own=own)
    assert not second.exists() and not list(out.parent.glob(".*"))
    monkeypatch.undo()
    # a draft is not packed
    m = yaml.safe_load((study / "manifest.yaml").read_bytes())
    m["status"] = "draft"
    (study / "manifest.yaml").write_text(yaml.safe_dump(m, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match="status: approved"):
        tool.write(study, key, tmp_path / "out" / "draft.tbstudy", DAY, audit_dir=audit, own=own)
    assert not (tmp_path / "out" / "draft.tbstudy").exists()
    # the default gives the folder back only as root (backup._own_writes, D-724): a no-op for another user
    if os.geteuid() != 0:
        tool._own_writes(audit)


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
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUNBUFFERED", "TB_AUDIT_DIR")}
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
    study = tmp_path / "RA-JAK"
    for path, data in _small().items():
        (study / path).parent.mkdir(parents=True, exist_ok=True)
        (study / path).write_bytes(data)
    out = tmp_path / "RA-JAK.tbstudy"
    audit = tmp_path / "audit"
    audit.mkdir()
    # no audit folder: no package (H4)
    none = _run("write", str(study), "--key", str(priv), "--out", str(out), "--created", DAY)
    assert none.returncode == 1 and "no audit directory" in none.stderr and not out.exists()
    w = _run("write", str(study), "--key", str(priv), "--out", str(out), "--created", DAY, "--audit-dir", str(audit))
    assert w.returncode == 0, w.stderr
    assert "package RA-JAK-1.0.0-" in w.stdout and sp.key_id(pub.read_bytes()) in w.stdout
    assert out.stat().st_mode & 0o777 == 0o600 and not list(tmp_path.glob(".*.part"))
    events = [json.loads(x) for f in sorted(audit.glob("*.jsonl")) for x in f.read_text().splitlines() if x]
    assert [e["event"] for e in events if e["event"].startswith("approve.")] == ["approve.study_package_exported"]
    trust = _trust_file(tmp_path / "trust.json", [(pub.read_bytes(), ["RA-JAK"], sp.STUDY_PURPOSE)])
    v = _run("verify", str(out), "--trust-file", str(trust))
    assert v.returncode == 0 and v.stdout.startswith("verified "), v.stderr
    s = _run("show", str(out))
    assert s.returncode == 0 and json.loads(s.stdout.split("\n(")[0])["study_id"] == "RA-JAK"
    assert "not checked" in s.stdout
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
