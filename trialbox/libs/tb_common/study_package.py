"""The study package, format v1 (10D-3, D-1372; review 14 M14-2; the owner's decisions 47 and 50).

A study travels from its coordinating centre to every hospital as **one file** on media or by internal mail: a
canonical POSIX ustar archive that holds the study's protocol part (``tb_common.study_manifest``, D-1366) and its
protocol files, a header, a hash list and a detached Ed25519 signature by a coordinating-centre key. It carries no
site part: no scopes, routing, review or IRB record, no criterion review record, no equivalence run and no patient
data (the synthetic test patients are a protocol file).

* :func:`build` / :func:`build_dir` write a package; the same study, date and key give the same bytes.
* :func:`verify` / :func:`verify_file` check one against the trusted public keys the caller passes, in a fixed order,
  and raise :class:`PackageRefused` with one sentence at the first check that fails. They write nothing anywhere.

The format is written in D-1372 precisely enough for a second implementation: the member order, the tar block's
fixed fields, the header's fields, the signed byte string and the caps. **Nothing on the live path reads a package
yet**: import, the register of coordinating-centre keys and the audit are 10D-4's.
"""

from __future__ import annotations

import hashlib
import re
import struct
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from itertools import accumulate
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from tb_common import study_manifest as sm
from tb_common.crypto import ed25519_public_of, ed25519_sign, ed25519_verify

FORMAT = "tb-study-package/1"
#: the members every package holds besides its protocol files, in the archive's byte order of names
HASHES = "hashes.json"
HEADER = "header.json"
PROTOCOL = "protocol.json"
SIGNATURE = "signature.ed25519"
#: where the protocol files sit in the archive: ``files/`` + their path in the study folder
FILES = "files/"
#: what the signature is taken over: this prefix, the header's length (8 bytes, big-endian), the header, the hash list
SIGNED_PREFIX = b"tb-study-package/1 signature\x00"
#: the header's fields, all required; any other field is refused (a v1 box cannot know what it would ask)
HEADER_FIELDS = (
    "created",
    "criteria_sha256",
    "format",
    "key_id",
    "package_id",
    "pins",
    "protocol_version",
    "study_id",
    "version",
)
#: the pins a v1 reader knows (``pins`` in the header): none; 10D-26 adds the screen-only items
KNOWN_PINS: frozenset[str] = frozenset()

#: caps, checked from the file's size and the tar headers before a member's bytes are used (the rule-set zip's
#: member and size caps, D-1102)
STUDY_PACKAGE_MAX_BYTES = 200_000_000
STUDY_PACKAGE_MAX_MEMBERS = 2000
STUDY_PACKAGE_MAX_MEMBER_BYTES = 100_000_000
STUDY_PACKAGE_MAX_META_BYTES = 4 << 20
#: a member's name: ASCII letters, digits, ``.``, ``_`` and ``-`` in parts joined by ``/``; at most 100 bytes
#: (the ustar name field, no prefix field)
NAME_MAX_BYTES = 100
#: how deeply a JSON member may nest arrays and objects, checked on its bytes before it is parsed (the deepest shipped
#: file, RA-JAK's ELM, nests 87)
STUDY_PACKAGE_MAX_JSON_DEPTH = 200
_PART = re.compile(r"^[A-Za-z0-9._-]+$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_KEY_ID = re.compile(r"^ed25519:[0-9a-f]{16}$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_BLOCK = 512
_ZERO = bytes(_BLOCK)
_MAGIC = b"ustar\x0000"
_META = frozenset({HASHES, HEADER, SIGNATURE})
_JSON_STRING = re.compile(rb'"(?:[^"\\]++|\\.)*+"', re.DOTALL)
_NOT_BRACKET = bytes(c for c in range(256) if c not in b"[]{}")


class PackageRefused(ValueError):
    """A study package refused; the message is its one sentence, ``step`` the check that refused it (``tar``,
    ``signature``, ``hashes``, ``members``, ``protocol``)."""

    def __init__(self, step: str, sentence: str) -> None:
        super().__init__(sentence)
        self.step = step


@dataclass(frozen=True)
class Package:
    """A verified package: its header, its protocol part and its protocol files as carried (path in the study
    folder -> bytes)."""

    header: dict[str, Any]
    protocol: dict[str, Any]
    files: dict[str, bytes]


# ---------------------------------------------------------------------------------------------- keys
def key_id(public_pem: bytes) -> str:
    """``ed25519:`` + the first 16 hex of the sha256 of the raw 32-byte public key: the update bundle's ``key_id``
    (``tools.verify_update.key_id``), so one key has one name on both channels."""
    key = serialization.load_pem_public_key(public_pem)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("not an Ed25519 public key")
    raw = key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return "ed25519:" + hashlib.sha256(raw).hexdigest()[:16]


def package_id(study_id: str, version: str, hashes: bytes) -> str:
    """``<study id>-<version>-`` and the first 16 hex of the sha256 of ``hashes.json``: it names the content."""
    return f"{study_id}-{version}-{hashlib.sha256(hashes).hexdigest()[:16]}"


def signed_bytes(header: bytes, hashes: bytes) -> bytes:
    """The byte string the signature is over (D-1372): the prefix, the header's length, the header, the hash list."""
    return SIGNED_PREFIX + struct.pack(">Q", len(header)) + header + hashes


# ---------------------------------------------------------------------------------------------- the tar
def _name_refusal(name: str) -> str | None:
    if len(name.encode("utf-8")) > NAME_MAX_BYTES:
        return f"the member name {name!r} is longer than {NAME_MAX_BYTES} bytes"
    parts = name.split("/")
    if not all(_PART.match(p) and p not in (".", "..") for p in parts):
        return (
            f"the member name {name!r} is not a relative path of letters, digits, '.', '_' and '-' "
            "(no absolute path, no '..', no empty part)"
        )
    return None


def _block(name: str, size: int) -> bytes:
    """The one tar header a v1 member has: ustar, a regular file, mode 0644, uid and gid 0, no owner names, mtime 0."""
    head = bytearray(_BLOCK)
    raw = name.encode("ascii")
    head[0 : len(raw)] = raw
    head[100:108] = b"0000644\x00"
    head[108:116] = b"0000000\x00"
    head[116:124] = b"0000000\x00"
    head[124:136] = b"%011o\x00" % size
    head[136:148] = b"00000000000\x00"
    head[148:156] = b" " * 8
    head[156:157] = b"0"
    head[257:265] = _MAGIC
    head[329:337] = b"0000000\x00"
    head[337:345] = b"0000000\x00"
    head[148:156] = b"%06o\x00 " % sum(head)
    return bytes(head)


def tar_bytes(members: Mapping[str, bytes]) -> bytes:
    """The canonical archive of ``members``: names in the order of their UTF-8 bytes, each a header block and its
    bytes padded with zeros to a whole block, then two zero blocks and nothing after."""
    out = bytearray()
    for name in sorted(members, key=lambda n: n.encode("utf-8")):
        why = _name_refusal(name)
        if why:
            raise ValueError(why)
        data = members[name]
        out += _block(name, len(data)) + data + bytes(-len(data) % _BLOCK)
    return bytes(out + _ZERO + _ZERO)


def _octal(field: bytes) -> int:
    text = field.rstrip(b"\x00 ").lstrip(b" ")
    if not text or not all(48 <= c <= 55 for c in text):
        raise ValueError
    return int(text, 8)


def _refuse(sentence: str, step: str = "tar") -> PackageRefused:
    return PackageRefused(step, f"this study package {sentence}")


def read_tar(data: bytes) -> dict[str, bytes]:
    """The members of a package archive, checked: whole blocks, intact headers, ustar regular files only, safe and
    unique names, within the caps, two zero blocks at the end and nothing after, and byte for byte the canonical
    archive of its members (so no field, padding or order may vary)."""
    if len(data) > STUDY_PACKAGE_MAX_BYTES:
        raise _refuse(f"is {len(data):,} bytes; a study package may be at most {STUDY_PACKAGE_MAX_BYTES:,} bytes")
    if len(data) % _BLOCK or len(data) < 2 * _BLOCK:
        raise _refuse("is not a tar archive of whole 512-byte blocks")
    members: dict[str, bytes] = {}
    total = 0
    at = 0
    while True:
        if at + _BLOCK > len(data):
            raise _refuse("ends before the archive's end (it was cut short)")
        head = data[at : at + _BLOCK]
        if head == _ZERO:
            if data[at:] != _ZERO + _ZERO:
                raise _refuse("has bytes after the end of its archive, or does not end with exactly two empty blocks")
            break
        try:
            stored = _octal(head[148:156])
            size = _octal(head[124:136])
        except ValueError:
            raise _refuse(
                "has a damaged tar header: a number field is not plain octal (a base-256 size is not v1), or the "
                "member before it declares a size that does not match its bytes"
            ) from None
        if stored != sum(head[:148]) + 8 * 32 + sum(head[156:]):
            raise _refuse("has a damaged tar header (its checksum does not match)")
        if head[257:265] != _MAGIC:
            raise _refuse("is not a POSIX ustar archive")
        if head[156:157] != b"0":
            raise _refuse("holds a member that is not a plain file (a link, a folder, a device or an extended header)")
        if any(head[345:500]):
            raise _refuse("holds a member whose name uses the ustar prefix field")
        raw = head[0:100].split(b"\x00", 1)[0]
        try:
            name = raw.decode("ascii")
        except UnicodeDecodeError:
            raise _refuse("holds a member whose name is not ASCII") from None
        why = _name_refusal(name)
        if why:
            raise _refuse(f"is refused: {why}")
        if name in members:
            raise _refuse(f"holds the member {name} twice")
        if len(members) + 1 > STUDY_PACKAGE_MAX_MEMBERS:
            raise _refuse(f"holds more than {STUDY_PACKAGE_MAX_MEMBERS:,} members")
        cap = STUDY_PACKAGE_MAX_META_BYTES if name in _META | {PROTOCOL} else STUDY_PACKAGE_MAX_MEMBER_BYTES
        if size > cap:
            raise _refuse(f"holds {name} of {size:,} bytes; that member may be at most {cap:,} bytes")
        total += size
        if total > STUDY_PACKAGE_MAX_BYTES:
            raise _refuse(f"holds more than {STUDY_PACKAGE_MAX_BYTES:,} bytes")
        start = at + _BLOCK
        end = start + size
        if end + (-size % _BLOCK) > len(data):
            raise _refuse("ends before the archive's end (it was cut short)")
        if (
            head != _block(name, size)
            or any(data[end : end + (-size % _BLOCK)])
            or (members and name.encode() <= list(members)[-1].encode())
        ):
            raise _refuse(
                "is not in the canonical form of a v1 package (a tar field, the padding or the order of its members "
                "differs from the one way v1 writes it)"
            )
        members[name] = data[start:end]
        at = end + (-size % _BLOCK)
    return members


# ---------------------------------------------------------------------------------------------- members
def _allowed(name: str, docx: str | None) -> bool:
    """A name a v1 package may hold: its four fixed members, or ``files/`` + a path of the protocol's files
    (``study_manifest.PROTOCOL_FILES``; never a site file or the docx template)."""
    if name in _META or name == PROTOCOL:
        return True
    if not name.startswith(FILES):
        return False
    path = name[len(FILES) :]
    if path in sm.SITE_FILES or path == docx:
        return False
    return any(
        path == prefix if suffix is None else path.startswith(prefix) and path.endswith(suffix)
        for prefix, suffix, _kind in sm.PROTOCOL_FILES
    )


def json_depth(data: bytes) -> int:
    """How deeply a JSON text nests arrays and objects, counted on its bytes without parsing it (brackets inside
    strings do not count; an unterminated string's brackets do, which only over-counts)."""
    brackets = _JSON_STRING.sub(b"", data).translate(None, _NOT_BRACKET)
    return max(accumulate(1 if c in b"[{" else -1 for c in brackets), default=0)


def _depth_refusal(name: str, data: bytes) -> str | None:
    if json_depth(data) > STUDY_PACKAGE_MAX_JSON_DEPTH:
        return f"{name} nests deeper than {STUDY_PACKAGE_MAX_JSON_DEPTH} arrays and objects"
    return None


def _canonical_json(name: str, data: bytes, step: str = "tar") -> Any:
    why = _depth_refusal(name, data)
    if why:
        raise _refuse(f"is refused: {why}", step)
    try:
        value = sm.load_json(data)
        same = sm.dumps(value) == data
    except (ValueError, UnicodeDecodeError):
        raise _refuse(f"holds {name}, which is not JSON a v1 package can carry", step) from None
    if not same:
        raise _refuse(f"holds {name} not in its canonical JSON form (RFC 8785)", step)
    return value


def _header_refusal(header: Any) -> str | None:
    if not isinstance(header, dict):
        return "its header is not a JSON object"
    unknown = sorted(set(header) - set(HEADER_FIELDS))
    if unknown:
        return f"its header has the field {unknown[0]}, which a v1 package does not have"
    missing = [k for k in HEADER_FIELDS if k not in header]
    if missing:
        return f"its header lacks the field {missing[0]}"
    if header["format"] != FORMAT:
        return f"its header names the format {header['format']!r}, not {FORMAT}"
    for k in HEADER_FIELDS:
        if k != "pins" and not (isinstance(header[k], str) and header[k]):
            return f"its header's {k} is not a text"
    if not isinstance(header["pins"], dict):
        return "its header's pins is not a JSON object"
    unknown_pins = sorted(set(header["pins"]) - KNOWN_PINS)
    if unknown_pins:
        return (
            f"asks for the pin {unknown_pins[0]}, which a v1 reader cannot check; it needs a newer release of the box"
        )
    if not _HEX64.match(header["criteria_sha256"]):
        return "its header's criteria hash is not 64 lowercase hex"
    if not _KEY_ID.match(header["key_id"]):
        return "its header's key_id is not an Ed25519 key id"
    if not _DAY.match(header["created"]):
        return "its header's created date is not YYYY-MM-DD"
    try:
        date.fromisoformat(header["created"])
    except ValueError:
        return "its header's created date is not a date"
    return None


def _hashes_refusal(hashes: Any) -> str | None:
    if not isinstance(hashes, dict) or not hashes:
        return "its hash list is not a JSON object of member names"
    for name, digest in hashes.items():
        if name in _META:
            return f"its hash list names {name}, which is not hashed"
        if not (isinstance(digest, str) and _HEX64.match(digest)):
            return f"its hash list's entry for {name} is not 64 lowercase hex"
    return None


def _structure(data: bytes) -> tuple[dict[str, bytes], dict[str, Any], dict[str, Any]]:
    """Check 1: a well-formed canonical archive within the caps, only the allowed members, a v1 header and a hash
    list in canonical JSON."""
    members = read_tar(data)
    for need in (HEADER, HASHES, SIGNATURE, PROTOCOL):
        if need not in members:
            raise _refuse(f"lacks its {need}")
    for name in members:
        if not _allowed(name, None):
            raise _refuse(f"holds {name}, which is not a member a v1 package may hold")
    if len(members[SIGNATURE]) != 64:
        raise _refuse("has a signature that is not 64 bytes (Ed25519)")
    header = _canonical_json(HEADER, members[HEADER])
    why = _header_refusal(header)
    if why:
        raise _refuse(f"is refused: {why}")
    hashes = _canonical_json(HASHES, members[HASHES])
    why = _hashes_refusal(hashes)
    if why:
        raise _refuse(f"is refused: {why}")
    return members, header, hashes


def header_of(data: bytes) -> dict[str, Any]:
    """The header of a well-formed package (check 1 only: the signature is NOT checked; :func:`verify` checks it)."""
    return _structure(data)[1]


# ---------------------------------------------------------------------------------------------- verify
def _trusted(keys: Iterable[bytes]) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for pem in keys:
        try:
            out[key_id(pem)] = pem
        except ValueError:
            raise PackageRefused("signature", "a trusted key given is not an Ed25519 public key (PEM)") from None
    return out


def verify(data: bytes, trusted_keys: Iterable[bytes]) -> Package:
    """A package checked against ``trusted_keys`` (Ed25519 public keys, PEM), in this order, each refusal one
    sentence (:class:`PackageRefused`): (1) a well-formed canonical archive within the caps, only allowed names; (2)
    the signature valid for a trusted key, the one the header names; (3) every member's sha256 the one in the hash
    list; (4) no member outside the list and none missing; (5) the protocol part holds its criteria hash, the carried
    files are the protocol's files in their canonical form, the criteria hash computed again from them by
    ``tb_common.study_manifest`` is the header's, and the header's package id is the one its content gives. Every
    JSON member is refused before it is parsed when it nests deeper than :data:`STUDY_PACKAGE_MAX_JSON_DEPTH`.
    Writes nothing anywhere; it holds about twice the package's bytes in memory (the input and its members)."""
    trusted = _trusted(trusted_keys)
    members, header, hashes = _structure(data)
    # (2) the signature
    kid = header["key_id"]
    if kid not in trusted:
        raise PackageRefused(
            "signature",
            f"this study package is signed by the key {kid}, which is not a trusted coordinating-centre key",
        )
    if not ed25519_verify(trusted[kid], signed_bytes(members[HEADER], members[HASHES]), members[SIGNATURE]):
        raise PackageRefused(
            "signature",
            f"this study package's signature does not verify with the key {kid}: its header or hash list was changed "
            "after it was signed, or another key signed it",
        )
    # (3) each member against the hash list
    for name in sorted(hashes):
        if name in members and hashlib.sha256(members[name]).hexdigest() != hashes[name]:
            raise PackageRefused("hashes", f"this study package's member {name} does not match its signed hash")
    # (4) the member set against the hash list
    carried = set(members) - _META
    extra = sorted(carried - set(hashes))
    if extra:
        raise PackageRefused(
            "members", f"this study package holds {extra[0]}, which its signed hash list does not name"
        )
    missing = sorted(set(hashes) - carried)
    if missing:
        raise PackageRefused("members", f"this study package lacks {missing[0]}, which its signed hash list names")
    # (5) the protocol part and the criteria hash
    return _protocol(members, header)


def _protocol(members: Mapping[str, bytes], header: Mapping[str, Any]) -> Package:
    def refuse(sentence: str) -> PackageRefused:
        return PackageRefused("protocol", f"this study package {sentence}")

    protocol = _canonical_json(PROTOCOL, members[PROTOCOL], "protocol")
    why = sm.protocol_refusal(protocol) if isinstance(protocol, dict) else "this is not a study's protocol part"
    if why:
        raise refuse(f"is refused: {why}")
    manifest = protocol["manifest"]
    for field, value in (
        ("study_id", manifest.get("id")),
        ("version", manifest.get("version")),
        ("protocol_version", manifest.get("protocol_version")),
        ("criteria_sha256", protocol["criteria_sha256"]),
    ):
        if header[field] != value:
            raise refuse(f"has a header whose {field} is not its protocol part's")
    docx = manifest.get("docx_template")
    files: dict[str, bytes] = {}
    for name in sorted(members):
        if not name.startswith(FILES):
            continue
        path = name[len(FILES) :]
        if path == docx:
            raise refuse(f"carries the template {path}, which a v1 package does not carry")
        why = _depth_refusal(path, members[name]) if path.endswith(".json") else None
        if why:
            raise refuse(f"is refused: {why}")
        if sm.carried(path, members[name], docx) != members[name]:
            raise refuse(f"carries {path} not in the canonical form of its protocol file")
        files[path] = members[name]
    recomputed = {p: hashlib.sha256(b).hexdigest() for p, b in files.items()}
    if recomputed != protocol["files"]:
        diff = sorted(set(recomputed) ^ set(protocol["files"])) or sorted(
            p for p in recomputed if recomputed[p] != protocol["files"][p]
        )
        raise refuse(f"does not carry the protocol's file {diff[0]} as its protocol part lists it")
    again = sm.criteria_sha256({"schema": protocol["schema"], "manifest": manifest, "files": recomputed})
    if again != header["criteria_sha256"]:
        raise refuse("has files whose criteria hash is not the one its header states")
    if header["package_id"] != package_id(header["study_id"], header["version"], members[HASHES]):
        raise refuse("has a header whose package_id is not the one its study, version and hash list give")
    return Package(dict(header), dict(protocol), files)


def read_file(path: Path) -> bytes:
    """A package file's bytes, its size checked before it is read."""
    size = path.stat().st_size
    if size > STUDY_PACKAGE_MAX_BYTES:
        raise _refuse(f"is {size:,} bytes; a study package may be at most {STUDY_PACKAGE_MAX_BYTES:,} bytes")
    return path.read_bytes()


def verify_file(path: Path, trusted_keys: Iterable[bytes]) -> Package:
    """:func:`verify` of a file, its size checked before it is read."""
    return verify(read_file(path), trusted_keys)


# ---------------------------------------------------------------------------------------------- write
def build(files: Mapping[str, bytes], private_pem: bytes, created: str) -> bytes:
    """The package of one study folder given as ``{relative path: bytes}``, signed with the coordinating centre's
    Ed25519 private key (PEM); ``created`` is the writer's date, YYYY-MM-DD (the library reads no clock). Refused
    (``ValueError``, one sentence) for a study whose folder holds its docx template, has no ``protocol_version``,
    or a protocol file whose path a v1 package cannot carry. The result is verified before it is returned."""
    try:
        public_pem = ed25519_public_of(private_pem)
    except (TypeError, ValueError):
        raise ValueError(
            "the private key is not an unencrypted Ed25519 private key (PEM, PKCS8); a v1 writer takes no passphrase"
        ) from None
    for path in sorted(files):
        why = _depth_refusal(path, files[path]) if path.endswith(".json") and _allowed(FILES + path, None) else None
        if why:
            raise ValueError(f"the study folder cannot be packaged: {why}")
    parts = sm.split(files)
    protocol = parts.protocol
    manifest = protocol["manifest"]
    docx = manifest.get("docx_template")
    if docx and docx in files:
        raise ValueError(
            f"the study folder holds its template {docx}: a v1 package does not carry a template (its bytes would "
            "travel as they are, with whatever names its document properties hold)"
        )
    for field in ("id", "version", "protocol_version"):
        if not (isinstance(manifest.get(field), str) and manifest[field]):
            raise ValueError(
                f"a study is packaged with its {field} written as a text (quoted in manifest.yaml, as '1.0'), and "
                "this manifest's is not"
            )
    carried: dict[str, bytes] = {}
    for path in sorted(protocol["files"]):
        body = sm.carried(path, files[path], docx)
        assert body is not None
        if hashlib.sha256(body).hexdigest() != protocol["files"][path]:  # pragma: no cover - split computed it so
            raise ValueError(f"the protocol file {path} does not hash as the protocol part lists it")
        why = _name_refusal(FILES + path)
        if why:
            raise ValueError(f"a v1 package cannot carry this study: {why}")
        carried[FILES + path] = body
    carried[PROTOCOL] = sm.dumps(protocol)
    hashes = {name: hashlib.sha256(body).hexdigest() for name, body in carried.items()}
    hashes_bytes = sm.dumps(hashes)
    if not _DAY.match(created):
        raise ValueError("the created date is written YYYY-MM-DD")
    date.fromisoformat(created)
    header = {
        "created": created,
        "criteria_sha256": protocol["criteria_sha256"],
        "format": FORMAT,
        "key_id": key_id(public_pem),
        "package_id": package_id(manifest["id"], manifest["version"], hashes_bytes),
        "pins": {},
        "protocol_version": manifest["protocol_version"],
        "study_id": manifest["id"],
        "version": manifest["version"],
    }
    header_bytes = sm.dumps(header)
    members = {
        **carried,
        HASHES: hashes_bytes,
        HEADER: header_bytes,
        SIGNATURE: ed25519_sign(private_pem, signed_bytes(header_bytes, hashes_bytes)),
    }
    data = tar_bytes(members)
    verify(data, [public_pem])
    return data


def build_dir(folder: Path, private_pem: bytes, created: str) -> bytes:
    """:func:`build` of a study folder on disk (``rulesets/<ID>/``), read as ``Ruleset.load`` reads it."""
    files = {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}
    return build(files, private_pem, created)
