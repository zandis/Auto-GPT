"""The study package, format v1 (10D-3, D-1372; review 14 M14-2; the owner's decisions 47 and 50).

A study travels from its coordinating centre to every hospital as **one file** on media or by internal mail: a
canonical POSIX ustar archive that holds the study's protocol part (``tb_common.study_manifest``, D-1366) and its
protocol files, a header, a hash list and a detached Ed25519 signature by a coordinating-centre key. It carries no
site part: no scopes, routing, review or IRB record, no criterion review record, no equivalence run and no patient
data (the synthetic test patients are a protocol file).

* :func:`build` / :func:`build_dir` write a package; the same study, date and key give the same bytes.
* :func:`verify` / :func:`verify_file` check one against the trusted keys the caller passes (:class:`TrustedKey`: each
  for the studies its entry names, :func:`load_trust`), in a fixed order, and raise :class:`PackageRefused` with one
  sentence at the first check that fails. They write nothing anywhere.

The format is written in D-1372 precisely enough for a second implementation: the member order, the tar block's
fixed fields, the header's fields, the signed byte string and the caps. **Nothing on the live path reads a package
yet**: import, the register of coordinating-centre keys and the audit of an import are 10D-4's (the operator's
command ``tools.study_package`` audits each package it writes).
"""

from __future__ import annotations

import functools
import hashlib
import hmac
import math
import os
import re
import stat
import struct
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import date
from itertools import accumulate
from pathlib import Path
from typing import Any, Literal

import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, field_validator
from tb_contracts import CriterionIR

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
#: the protocol file of synthetic test patients (D-1366 rule 4), the one carried file that names practitioners and
#: departments
TEST_PATIENTS = "tests/patients.ndjson"
#: code systems whose codes are a hospital's own, not a protocol's: a criterion that uses one names codes each site
#: maps to its own (10D-4); in the test patients only the placeholder codes below may appear
SITE_LOCAL_CODE_SYSTEMS = frozenset({"https://trialbox.local/fhir/CodeSystem/department"})
#: the synthetic placeholders the test patients may name (``tools.synth.catalog`` and ``tools.synth.ad``): the
#: practitioners a ``Practitioner/`` reference may point at and the department codes of the site-local system
PLACEHOLDER_PRACTITIONERS = frozenset(
    {"P12345", "P23456", "P34567", "P45678", "P56789", "P67890", "P78901", "P89012", "P90001", "P90002", "P90003"}
)
PLACEHOLDER_DEPARTMENTS = frozenset({"RHEU", "META", "NEPH", "CARD", "FM", "ONC", "ORTH", "NEUR", "PSY"})
#: the organisations a test patient's ``Organization/`` reference may point at (the shipped studies' placeholders)
PLACEHOLDER_ORGANIZATIONS = frozenset({"hospital", "nhi"})
#: the synthetic site's pseudonym key: the test stack's ``site_hmac.key`` (Makefile ``.cache/test-secrets``,
#: ``tests/conftest.py``), public and in the repository, so it is no secret and no box's key. The shipped test patients
#: are the synthetic hospital's records ingested under it (``tools/build_rulesets.py``): each ``Patient.id`` is
#: ``hex(HMAC-SHA256(this key, chart number))[:32]`` (``tb_common.crypto.pid_for_mrn``) of a synthetic chart number.
#: A box's ingest of its own patients uses its own secret key, so its pseudonyms are not these (D-1372, H1).
SYNTHETIC_SITE_KEY = b"trialbox-test-site-key-0123456789abcdef"
#: the synthetic generators' chart numbers: one digit, the site's prefix (``tools/make_fixtures.py`` site-a ``1``,
#: site-b ``2``; ``tools.synth_hospital`` ``2`` onwards), then the patient's number in seven digits, from 1 to
#: :data:`SYNTHETIC_MAX_PATIENTS` (the CI profiles' largest site, 2,500; site-a holds 600)
SYNTHETIC_MRN = re.compile(r"[1-9][0-9]{7}")
SYNTHETIC_MAX_PATIENTS = 2500
#: the identifier system of a synthetic test patient's pseudonym (site ``DEMO-A``, ``tools/build_rulesets.py``)
SYNTHETIC_PID_SYSTEM = "https://trialbox.local/fhir/sid/pid/DEMO-A"
#: ``tests/expected.json`` (the synthetic verdicts, H2): its fields, those it must have, and the closed sets its two
#: label fields take (measured from the eight shipped studies; the tools that write the file name the engine and the
#: synthetic source, nothing else). A new engine or generator run is a new release of this list, not free text.
EXPECTED = "tests/expected.json"
EXPECTED_FIELDS = frozenset({"agreement", "engine", "index_date", "patients", "ruleset", "source", "version"})
EXPECTED_REQUIRED = EXPECTED_FIELDS - {"agreement"}
EXPECTED_ENGINES = frozenset(
    {
        "hapi-cr 8.12 $evaluate",
        "cqf-fhir-cql 4.13.0 LibraryEngine in process (CQL engine 5.4.0, as HAPI 8.12 CR $evaluate)",
        "duckdb sql, equal to the generator's planted gold on every coded criterion; CQL (HAPI) not run",
    }
)
EXPECTED_SOURCES = frozenset(
    {
        "tests/fixtures/synthetic_patients/site-a (tools/make_fixtures.py defaults)",
        "tools.synth_hospital --profile jp-ad --ref-date 2026-11-01 (site jp-ad; its Alzheimer's patients)",
        "tools.synth_hospital --profile jp-ad --ref-date 2026-11-01 (site jp-ad; every patient)",
        "tools.synth_hospital --profile tw-ra --ref-date 2026-11-01 (site tw-ra; its rajak patients and the gate's "
        "stratified sample)",
    }
)
#: ``agreement`` (``tools/build_scenario_ruleset.record``): exactly these fields; ``known_differences`` empty
#: (its ``KNOWN`` table is empty, and its values would be words)
EXPECTED_AGREEMENT_FIELDS = frozenset({"all_equal", "known_differences", "patients", "per_criterion"})
#: the test patients' allow-list (D-1372), measured from the shipped studies' ``tests/patients.ndjson`` (GOUT-COH,
#: GZQO, ONC-OSI, RA-BIO, RA-COH; a test measures them again): each resource type they hold and, for each, every
#: element they carry, as a path of keys from the resource (an array's items take the array's path). Any other
#: resource type, element or depth is refused.
TEST_PATIENT_ELEMENTS: dict[str, frozenset[str]] = {
    kind: frozenset(paths.split())
    for kind, paths in {
        "Appointment": "end id participant.actor.reference participant.status serviceType.coding.code "
        "serviceType.coding.system start status",
        "Claim": "created id insurance.coverage.reference insurance.focal insurance.sequence "
        "item.productOrService.coding.code item.productOrService.coding.system item.sequence patient.reference "
        "priority.coding.code priority.coding.system provider.reference status subType.coding.code "
        "subType.coding.system type.coding.code type.coding.system use",
        "ClaimResponse": "created disposition id insurer.reference outcome patient.reference preAuthPeriod.end "
        "preAuthPeriod.start request.reference status type.coding.code type.coding.system use",
        "Condition": "category.coding.code category.coding.system clinicalStatus.coding.code "
        "clinicalStatus.coding.system code.coding.code code.coding.system encounter.reference id meta.profile "
        "onsetDateTime recordedDate subject.reference",
        "Consent": "category.coding.code category.coding.system dateTime id patient.reference policyRule.coding.code "
        "policyRule.coding.system provision.type scope.coding.code scope.coding.system status",
        "Coverage": "beneficiary.reference id payor.reference status",
        "DiagnosticReport": "category.coding.code category.coding.system code.coding.code code.coding.display "
        "code.coding.system conclusion effectiveDateTime id meta.profile status subject.reference",
        "Encounter": "class.code class.system id identifier.system identifier.value meta.profile "
        "participant.individual.reference period.start serviceType.coding.code serviceType.coding.system status "
        "subject.reference",
        "MedicationRequest": "authoredOn dispenseRequest.validityPeriod.end dispenseRequest.validityPeriod.start "
        "dosageInstruction.text id intent medicationCodeableConcept.coding.code "
        "medicationCodeableConcept.coding.display medicationCodeableConcept.coding.system "
        "medicationCodeableConcept.text meta.profile status subject.reference",
        "Observation": "category.coding.code category.coding.system code.coding.code code.coding.display "
        "code.coding.system component.code.coding.code component.code.coding.display component.code.coding.system "
        "component.valueQuantity.code component.valueQuantity.system component.valueQuantity.unit "
        "component.valueQuantity.value effectiveDateTime id meta.profile status subject.reference "
        "valueCodeableConcept.coding.code valueCodeableConcept.coding.display valueCodeableConcept.coding.system "
        "valueCodeableConcept.text valueQuantity.code valueQuantity.system valueQuantity.unit valueQuantity.value",
        "Patient": "birthDate gender id identifier.system identifier.value meta.profile",
        "Procedure": "code.coding.code code.coding.display code.coding.system id meta.profile performedDateTime status "
        "subject.reference",
    }.items()
}
#: the types a test patient's ``reference`` may name, written exactly ``<type>/<id>`` (no address, no ``#``)
TEST_PATIENT_REFERENCE_TYPES = frozenset({"Claim", "Coverage", "Encounter", "Organization", "Patient", "Practitioner"})
#: every ``system`` a test patient may name, exactly (measured): standard terminologies and the named placeholder
#: systems (``trialbox.local`` and the reserved ``.test`` domain)
TEST_PATIENT_SYSTEMS = frozenset(
    {
        "http://hl7.org/fhir/sid/icd-10-cm",
        "http://loinc.org",
        "http://terminology.hl7.org/CodeSystem/claim-type",
        "http://terminology.hl7.org/CodeSystem/condition-category",
        "http://terminology.hl7.org/CodeSystem/condition-clinical",
        "http://terminology.hl7.org/CodeSystem/consentscope",
        "http://terminology.hl7.org/CodeSystem/observation-category",
        "http://terminology.hl7.org/CodeSystem/processpriority",
        "http://terminology.hl7.org/CodeSystem/v2-0074",
        "http://terminology.hl7.org/CodeSystem/v3-ActCode",
        "http://unitsofmeasure.org",
        "http://www.whocc.no/atc",
        "https://hospa.test/fhir/CodeSystem/exam-local",
        "https://hospa.test/fhir/CodeSystem/lab-local",
        "https://trialbox.local/fhir/CodeSystem/clinical-score",
        "https://trialbox.local/fhir/CodeSystem/department",
        "https://trialbox.local/fhir/CodeSystem/nhi-apply-type",
        "https://trialbox.local/fhir/CodeSystem/nhi-drug",
        "https://trialbox.local/fhir/CodeSystem/nhi-order",
        "https://trialbox.local/fhir/sid/encounter",
        "https://trialbox.local/fhir/sid/pid/DEMO-A",
    }
)
#: every ``meta.profile`` a test patient may name, exactly (measured: the TW Core profiles)
TEST_PATIENT_PROFILES = frozenset(
    "https://twcore.mohw.gov.tw/ig/twcore/StructureDefinition/" + name
    for name in (
        "Condition-twcore",
        "DiagnosticReport-twcore",
        "Encounter-twcore",
        "MedicationRequest-twcore",
        "Observation-bloodPressure-twcore",
        "Observation-body-height-twcore",
        "Observation-body-weight-twcore",
        "Observation-laboratoryResult-twcore",
        "Patient-twcore",
        "Procedure-twcore",
    )
)
#: the inner elements of each allowed resource type: the paths that lead to an allowed element
_TEST_PATIENT_INNER: dict[str, frozenset[str]] = {
    kind: frozenset(p.rsplit(".", i)[0] for p in paths for i in range(1, p.count(".") + 1))
    for kind, paths in TEST_PATIENT_ELEMENTS.items()
}
#: the test patients' leaves that are not texts (measured): each one's JSON type; every other leaf is a text
TEST_PATIENT_NON_TEXT: dict[tuple[str, str], Literal["boolean", "integer", "number"]] = {
    ("Claim", "insurance.focal"): "boolean",
    ("Claim", "insurance.sequence"): "integer",
    ("Claim", "item.sequence"): "integer",
    ("Observation", "component.valueQuantity.value"): "number",
    ("Observation", "valueQuantity.value"): "number",
}
#: the elements the test patients hold as a JSON array (measured); an array anywhere else, an array inside an array, an
#: empty array and a single value where these hold an array are refused
TEST_PATIENT_LISTS: dict[str, frozenset[str]] = {
    kind: frozenset(paths.split())
    for kind, paths in {
        "Appointment": "participant serviceType serviceType.coding",
        "Claim": "insurance item item.productOrService.coding priority.coding subType.coding type.coding",
        "ClaimResponse": "type.coding",
        "Condition": "category category.coding clinicalStatus.coding code.coding meta.profile",
        "Consent": "category category.coding policyRule.coding scope.coding",
        "Coverage": "payor",
        "DiagnosticReport": "category category.coding code.coding meta.profile",
        "Encounter": "identifier meta.profile participant serviceType.coding",
        "MedicationRequest": "dosageInstruction medicationCodeableConcept.coding meta.profile",
        "Observation": "category category.coding code.coding component component.code.coding meta.profile "
        "valueCodeableConcept.coding",
        "Patient": "identifier meta.profile",
        "Procedure": "code.coding meta.profile",
    }.items()
}
#: the longest text a test patient's leaf may hold, in characters: the longest in the shipped files is 92 (an
#: ``Observation.meta.profile``), so 200 leaves room for a longer display or profile and none for a narrative
TEST_PATIENT_MAX_TEXT = 200
#: the largest magnitude a test patient's number may have (the shipped files' largest is 416.21); an integer
#: (``sequence``) is also at least 1
TEST_PATIENT_MAX_NUMBER = 1_000_000_000
#: a key of a test patient, at every depth: a FHIR element name (ASCII letters and digits, a letter first), so no
#: ``.``, no ``_``, no space and no look-alike letter can make a key read as a path
_KEY = re.compile(r"[A-Za-z][A-Za-z0-9]*")
#: a FHIR id (``Resource.id`` and the id of a reference), matched whole
_ID = re.compile(r"[A-Za-z0-9.\-]{1,64}")
_REFERENCE = re.compile(r"([A-Za-z]+)/([A-Za-z0-9.\-]{1,64})")
#: characters no test patient text holds: controls, the line and paragraph separators and the byte-order mark
_NOT_TEXT = re.compile("[\x00-\x1f\x7f-\x9f\u2028\u2029\ufeff]")
_BOM = b"\xef\xbb\xbf"
#: the protocol files a package may carry (``files/<path>``): ``study_manifest.PROTOCOL_FILES`` narrowed to one
#: file directly in its folder, not hidden, with that folder's one extension (``cql/elm/`` only ``.json``). The
#: criteria hash still covers every file the engine reads (D-1366); a folder whose hash covers any other file is not
#: packaged.
PACKAGE_FILES: tuple[tuple[str, str | None], ...] = (
    ("ir/", ".json"),
    ("valuesets/", ".json"),
    ("cql/elm/", ".json"),
    ("cql/", ".cql"),
    ("sql/", ".sql"),
    ("labels.yaml", None),
    ("tests/patients.ndjson", None),
    ("tests/expected.json", None),
)
_FILE_NAME = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]*$")
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


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _Concept(_Strict):
    code: str
    display: str


class _Include(_Strict):
    system: str
    concept: list[_Concept]


class _Compose(_Strict):
    include: list[_Include]


#: the one extension a compiled value set carries and the one tag (``criteria_compiler.terminology.mapper``
#: ``FAMILY_EXT`` and ``REVIEW_TAG_SYSTEM``; a test holds them equal, the library does not import the compiler)
FAMILY_EXT = "https://trialbox.local/fhir/StructureDefinition/code-family"
REVIEW_TAG_SYSTEM = "https://trialbox.local/fhir/CodeSystem/review-flag"
#: a code family as the mapper writes it: ``<system>|<code prefix>``
_FAMILY = re.compile(r"https?://[A-Za-z0-9._~/:-]{1,200}\|[A-Za-z0-9.\-]{1,32}")


class _Extension(_Strict):
    url: Literal["https://trialbox.local/fhir/StructureDefinition/code-family"]
    valueString: str

    @field_validator("valueString")
    @classmethod
    def _family(cls, value: str) -> str:
        if not _FAMILY.fullmatch(value):
            raise ValueError("not a code family")
        return value


class _Coding(_Strict):
    system: Literal["https://trialbox.local/fhir/CodeSystem/review-flag"]
    code: Literal["needs_review"]


class _Meta(_Strict):
    tag: list[_Coding]


class ValueSetFile(_Strict):
    """A study's ``valuesets/<name>.json`` as the compiler writes it (``criteria_compiler.terminology.mapper.valueset``)
    and nothing more: the writer loads each one through this model before it packs it (no product model of the file
    existed; ``Ruleset`` reads it as a plain dict)."""

    resourceType: Literal["ValueSet"]
    id: str
    url: str
    version: str
    name: str
    title: str
    status: str
    compose: _Compose
    extension: list[_Extension] | None = None
    meta: _Meta | None = None


class PackageRefused(ValueError):
    """A study package refused; the message is its one sentence, ``step`` the check that refused it (``tar``,
    ``signature``, ``hashes``, ``members``, ``protocol``)."""

    def __init__(self, step: str, sentence: str) -> None:
        super().__init__(sentence)
        self.step = step


#: what a trusted key is for (H5): a coordinating centre's key signs study packages; a key marked ``update`` (the
#: vendor's update key, whose ``sign-file`` signs raw bytes with no prefix) is refused for them, so one key does not
#: serve both channels
STUDY_PURPOSE = "study-package"
TRUST_PURPOSES = frozenset({STUDY_PURPOSE, "update"})
TRUST_FORMAT = "tb-study-trust/1"
#: a study id as a manifest writes it (``RA-JAK``, ``GOUT-COH``): what a trust entry's ``studies`` names
_STUDY_ID = re.compile(r"[A-Z0-9]+(?:-[A-Z0-9]+)*")
#: at most this many entries in a trust file (a site trusts a few coordinating centres)
TRUST_MAX_KEYS = 64


@dataclass(frozen=True)
class TrustedKey:
    """One key the verifier trusts (H5): its public key (PEM), the studies it may sign for, and what it is for. A key
    is trusted only for the studies its entry names; an entry naming none is refused (default deny)."""

    public_pem: bytes
    studies: frozenset[str]
    purpose: str = STUDY_PURPOSE


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
def carriable(path: str) -> bool:
    """Whether a package may carry the protocol file at ``path`` of the study folder (:data:`PACKAGE_FILES`)."""
    for prefix, suffix in PACKAGE_FILES:
        if suffix is None:
            if path == prefix:
                return True
        elif path.startswith(prefix) and path.endswith(suffix) and _FILE_NAME.match(path[len(prefix) :]):
            return True
    return False


def _allowed(name: str, docx: str | None) -> bool:
    """A name a v1 package may hold: its four fixed members, or ``files/`` + a path a package carries
    (:func:`carriable`; never a site file or the docx template)."""
    if name in _META or name == PROTOCOL:
        return True
    if not name.startswith(FILES):
        return False
    path = name[len(FILES) :]
    if path in sm.SITE_FILES or path == docx:
        return False
    return carriable(path)


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
def _trusted(keys: Iterable[TrustedKey]) -> dict[str, TrustedKey]:
    """``{key id: entry}``; refused (step ``signature``) for a key that is not an Ed25519 public key, a bare key with
    no entry (it names no study: default deny), an entry naming no study or a purpose not known, and a key given
    twice (one key, one entry: it cannot be trusted for updates and for studies at once)."""
    out: dict[str, TrustedKey] = {}
    for entry in keys:
        if not isinstance(entry, TrustedKey):
            raise PackageRefused(
                "signature",
                "a trusted key was given without the studies it may sign for; a coordinating-centre key is trusted "
                "only for the studies its entry names",
            )
        if entry.purpose not in TRUST_PURPOSES or not entry.studies:
            raise PackageRefused(
                "signature", "a trusted key's entry names no study it may sign for, or a purpose that is not known"
            )
        try:
            kid = key_id(entry.public_pem)
        except ValueError:
            raise PackageRefused("signature", "a trusted key given is not an Ed25519 public key (PEM)") from None
        if kid in out:
            raise PackageRefused("signature", f"the key {kid} is given twice; a key has one trust entry")
        out[kid] = entry
    return out


def load_trust(data: bytes) -> list[TrustedKey]:
    """The keys of a study-package trust file (H5; the minimal form 10D-4's register of coordinating-centre keys is to
    carry): RFC 8259 JSON ``{"format": "tb-study-trust/1", "keys": [{"key_id", "public_key", "purpose", "studies"}]}``,
    exactly these fields; ``public_key`` the PEM text, ``key_id`` its :func:`key_id`, ``purpose`` one of
    :data:`TRUST_PURPOSES`, ``studies`` a non-empty list of study ids. Raises ``ValueError`` with one sentence."""
    try:
        doc = sm.load_json(data)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("the trust file is not JSON") from None
    if not isinstance(doc, dict) or set(doc) != {"format", "keys"} or doc["format"] != TRUST_FORMAT:
        raise ValueError(f"the trust file is not a {TRUST_FORMAT} file (format and keys, nothing else)")
    keys = doc["keys"]
    if not isinstance(keys, list) or not 0 < len(keys) <= TRUST_MAX_KEYS:
        raise ValueError(f"the trust file's keys are a list of 1 to {TRUST_MAX_KEYS} entries")
    out: list[TrustedKey] = []
    for n, entry in enumerate(keys, 1):
        if not isinstance(entry, dict) or set(entry) != {"key_id", "public_key", "purpose", "studies"}:
            raise ValueError(f"trust entry {n} does not have exactly key_id, public_key, purpose and studies")
        studies = entry["studies"]
        if (
            not isinstance(studies, list)
            or not studies
            or not all(isinstance(s, str) and _STUDY_ID.fullmatch(s) for s in studies)
            or len(set(studies)) != len(studies)
        ):
            raise ValueError(f"trust entry {n} names its studies as a list of distinct study ids (at least one)")
        if entry["purpose"] not in TRUST_PURPOSES:
            raise ValueError(f"trust entry {n} has a purpose that is not one of {', '.join(sorted(TRUST_PURPOSES))}")
        pem = entry["public_key"].encode("ascii", "replace") if isinstance(entry["public_key"], str) else b""
        try:
            kid = key_id(pem)
        except ValueError:
            raise ValueError(f"trust entry {n}'s public_key is not an Ed25519 public key (PEM)") from None
        if entry["key_id"] != kid:
            raise ValueError(f"trust entry {n}'s key_id is not the id of its public key")
        out.append(TrustedKey(pem, frozenset(studies), entry["purpose"]))
    if len({key_id(t.public_pem) for t in out}) != len(out):
        raise ValueError("the trust file names a key twice; a key has one trust entry")
    return out


def verify(data: bytes, trusted_keys: Iterable[TrustedKey]) -> Package:
    """A package checked against ``trusted_keys`` (:class:`TrustedKey`: an Ed25519 public key, PEM, the studies it may
    sign for and its purpose), in this order, each refusal one sentence (:class:`PackageRefused`): (1) a well-formed
    canonical archive within the caps, only allowed names; (2) the header's key one of the trusted keys, trusted for
    study packages (not a key marked for updates), the signature valid with it, and the header's study one its entry
    names; (3) every member's sha256 the one in the hash list; (4) no member outside the list and none missing; (5)
    the protocol part holds its criteria hash, the carried files are the protocol's files in their canonical form,
    the criteria hash computed again from them by ``tb_common.study_manifest`` is the header's, the header's package
    id is the one its content gives, and the criteria the protocol part names are exactly the ``ir/`` files carried
    (and its CQL library's files are carried). Every JSON member is refused before it is parsed when it nests deeper
    than :data:`STUDY_PACKAGE_MAX_JSON_DEPTH`. Writes nothing anywhere; it holds about twice the package's bytes in
    memory (the input and its members)."""
    trusted = _trusted(trusted_keys)
    members, header, hashes = _structure(data)
    # (2) the signature, by a key trusted for study packages and for this study
    kid = header["key_id"]
    if kid not in trusted:
        raise PackageRefused(
            "signature",
            f"this study package is signed by the key {kid}, which is not a trusted coordinating-centre key",
        )
    entry = trusted[kid]
    if entry.purpose != STUDY_PURPOSE:
        raise PackageRefused(
            "signature",
            f"this study package is signed by the key {kid}, which is trusted for {entry.purpose}, not for study "
            "packages; one key does not serve both",
        )
    if not ed25519_verify(entry.public_pem, signed_bytes(members[HEADER], members[HASHES]), members[SIGNATURE]):
        raise PackageRefused(
            "signature",
            f"this study package's signature does not verify with the key {kid}: its header or hash list was changed "
            "after it was signed, or another key signed it",
        )
    if header["study_id"] not in entry.studies:
        raise PackageRefused(
            "signature",
            f"this study package is for the study {header['study_id']}, which the key {kid} is not trusted to sign "
            "for (its trust entry names the studies it coordinates)",
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
    why = criteria_refusal(manifest, files)
    if why:
        raise refuse(why)
    return Package(dict(header), dict(protocol), files)


def criteria_refusal(manifest: Mapping[str, Any], files: Mapping[str, bytes]) -> str | None:
    """Why a study's files do not hold exactly the criteria its manifest names, or None (H3): each id in ``criteria``
    once, each with its ``ir/<id>.json`` whose ``id`` is that id, no ``ir/*.json`` the manifest does not name, and,
    when the manifest names a CQL ``library``, its ``cql/<library>.cql`` and ``cql/elm/<library>.json``. The screening
    engine loads every ``ir/*.json`` and the library by name (``Ruleset.from_files``), so a criterion named without
    its file would screen without it, and a file not named would screen unlisted. ``files``: path -> bytes."""
    named = manifest.get("criteria")
    if not isinstance(named, list) or not all(isinstance(c, str) for c in named) or len(set(named)) != len(named):
        return "names its criteria not as a list of distinct criterion ids"
    ir = {p[len("ir/") : -len(".json")]: b for p, b in files.items() if p.startswith("ir/") and p.endswith(".json")}
    missing = sorted(set(named) - set(ir))
    if missing:
        return f"names the criterion {missing[0]} but carries no ir/{missing[0]}.json"
    unnamed = sorted(set(ir) - set(named))
    if unnamed:
        return f"carries ir/{unnamed[0]}.json, a criterion its manifest does not name"
    for cid in sorted(ir):
        try:
            doc = sm.load_json(ir[cid])
        except (ValueError, UnicodeDecodeError):
            return f"carries ir/{cid}.json, which is not JSON"
        if not isinstance(doc, dict) or doc.get("id") != cid:
            return f"carries ir/{cid}.json, which does not hold the criterion {cid}"
    library = manifest.get("library")
    if library is not None:
        for path in (f"cql/{library}.cql", f"cql/elm/{library}.json"):
            if not isinstance(library, str) or path not in files:
                return f"names the CQL library {library} but carries no {path}"
    return None


def read_file(path: Path) -> bytes:
    """A package file's bytes, its size checked before it is read."""
    size = path.stat().st_size
    if size > STUDY_PACKAGE_MAX_BYTES:
        raise _refuse(f"is {size:,} bytes; a study package may be at most {STUDY_PACKAGE_MAX_BYTES:,} bytes")
    return path.read_bytes()


def verify_file(path: Path, trusted_keys: Iterable[TrustedKey]) -> Package:
    """:func:`verify` of a file, its size checked before it is read."""
    return verify(read_file(path), trusted_keys)


# ---------------------------------------------------------------------------------------------- write
def _reference_refusal(ref: str) -> str | None:
    match = _REFERENCE.fullmatch(ref)
    if match is None or match[1] not in TEST_PATIENT_REFERENCE_TYPES:
        return (
            "has a reference that is not written <type>/<id> with a type the shipped test patients refer to ("
            + ", ".join(sorted(TEST_PATIENT_REFERENCE_TYPES))
            + "; exact case, an id of letters, digits, '.' and '-', no address, no '#', no space)"
        )
    if match[1] == "Practitioner" and match[2] not in PLACEHOLDER_PRACTITIONERS:
        return "names a practitioner that is not one of the synthetic placeholders (P12345 and the like)"
    if match[1] == "Organization" and match[2] not in PLACEHOLDER_ORGANIZATIONS:
        return "names an organisation that is not one of the synthetic placeholders (hospital, nhi)"
    return None


def _keys_refusal(resource: dict[str, Any]) -> str | None:
    """Every key of a test patient, at every depth, is a FHIR element name (:data:`_KEY`), checked before any path is
    looked up, so a key holding ``.`` cannot read as a path."""
    stack: list[Any] = [resource]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if not all(_KEY.fullmatch(key) for key in node):
                return (
                    "has a key that is not an element name (ASCII letters and digits, a letter first: no '.', '_', "
                    "space or other letter)"
                )
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return None


def _leaf_refusal(kind: str, path: str, node: Any) -> str | None:
    """Why one leaf of a test patient may not leave the box, or None: its type (:data:`TEST_PATIENT_NON_TEXT`, else
    a text), its size, and for an id, a reference, a system and a profile, its form."""
    where = f"{kind}.{path}"
    want = TEST_PATIENT_NON_TEXT.get((kind, path), "text")
    if node is None:
        return f"holds null at {where}, where the shipped synthetic test patients hold a {want}"
    if want == "boolean":
        return None if isinstance(node, bool) else f"holds a value at {where} that is not a boolean"
    if want in ("integer", "number"):
        if (
            isinstance(node, bool)
            or not isinstance(node, int | float)
            or (want == "integer" and isinstance(node, float))
        ):
            return f"holds a value at {where} that is not a{'n' if want == 'integer' else ''} {want}"
        if not math.isfinite(node) or abs(node) > TEST_PATIENT_MAX_NUMBER or (want == "integer" and node < 1):
            return (
                f"holds a number at {where} that is not finite or is out of range (at most "
                f"{TEST_PATIENT_MAX_NUMBER:,} in magnitude; a sequence at least 1)"
            )
        return None
    if not isinstance(node, str):
        return f"holds a value at {where} that is not a text"
    if not node or len(node) > TEST_PATIENT_MAX_TEXT or _NOT_TEXT.search(node):
        return (
            f"holds a text at {where} that is empty, longer than {TEST_PATIENT_MAX_TEXT} characters, or holds a "
            "control character, a line separator or a byte-order mark"
        )
    last = path.rsplit(".", 1)[-1]
    if path == "id" and not _ID.fullmatch(node):
        return f"has an id at {where} that is not a FHIR id (letters, digits, '.' and '-', at most 64)"
    if last == "reference":
        return _reference_refusal(node)
    if last == "system" and node not in TEST_PATIENT_SYSTEMS:
        return (
            f"names a system at {where} that is not one of the test patients' systems (the standard terminologies "
            "and the named placeholder systems, written exactly)"
        )
    if path == "meta.profile" and node not in TEST_PATIENT_PROFILES:
        return f"names a profile at {where} that is not one of the test patients' profiles"
    return None


def _resource_refusal(resource: dict[str, Any]) -> str | None:
    """Why one test patient resource may not leave the box, or None: the allow-list of D-1372 over its whole tree.
    A refusal names the last element the allow-list knows, never a key or a type it does not know."""
    why = _keys_refusal(resource)
    if why:
        return why
    kind = resource.get("resourceType")
    if not isinstance(kind, str) or kind not in TEST_PATIENT_ELEMENTS:
        return (
            "is a record of a resource type a package does not carry (the test patients hold only the resource types "
            "of the shipped studies, exact case)"
        )
    leaves, inner, lists = TEST_PATIENT_ELEMENTS[kind], _TEST_PATIENT_INNER[kind], TEST_PATIENT_LISTS[kind]
    stack: list[tuple[str, Any, bool]] = [("", resource, False)]
    while stack:
        path, node, in_list = stack.pop()
        where = f"{kind}.{path}" if path else kind
        if isinstance(node, list):
            if in_list or path not in lists:
                return f"holds an array at {where}, where the shipped synthetic test patients hold no array there"
            if not node:
                return f"holds an empty array at {where}"
            stack.extend((path, item, True) for item in node)
            continue
        if path in lists and not in_list:
            return f"holds a single value at {where}, where the shipped synthetic test patients hold an array"
        if isinstance(node, dict):
            if path and path not in inner:
                return f"holds an object at {where}, which the shipped synthetic test patients never carry there"
            if not node:
                return f"holds an empty object at {where}"
            for key in node:
                child = f"{path}.{key}" if path else key
                if child != "resourceType" and child not in leaves and child not in inner:
                    return f"holds an element under {where} that the shipped synthetic test patients never carry"
            if "reference" in node and ("display" in node or "identifier" in node):
                return f"has a reference at {where} with a display or an identifier, which a package does not carry"
            system, code = node.get("system"), node.get("code")
            system = system if isinstance(system, str) else None
            if system in SITE_LOCAL_CODE_SYSTEMS and not (isinstance(code, str) and code in PLACEHOLDER_DEPARTMENTS):
                return (
                    f"holds a code of the hospital's own system {system} that is not one of the synthetic placeholders"
                )
            stack.extend(
                (f"{path}.{key}" if path else key, value, False)
                for key, value in node.items()
                if key != "resourceType" or path
            )
            continue
        if path not in leaves:
            return f"holds a value at {where} where the shipped synthetic test patients hold an object"
        why = _leaf_refusal(kind, path, node)
        if why:
            return why
    return None


def _test_patients_refusal(data: bytes) -> str | None:
    """Why the test patients may not leave the box, or None: no byte-order mark, each line a JSON object that passes
    the allow-list of D-1372 (:func:`_resource_refusal`). The file travels as its text form (D-1366), not
    re-serialised: the criteria hash covers that form, and 828 of the shipped files' 30,551 lines are not RFC 8785."""
    why = _depth_refusal(TEST_PATIENTS, data)
    if why:
        return why
    if _BOM in data:
        return f"{TEST_PATIENTS} holds a byte-order mark; it is written as UTF-8 without one"
    resources: list[tuple[int, dict[str, Any]]] = []
    for number, line in enumerate(data.splitlines(), 1):
        if not line.strip():
            continue
        try:
            resource = sm.load_json(line)
        except (ValueError, UnicodeDecodeError):
            return f"line {number} of {TEST_PATIENTS} is not JSON, so its codes cannot be checked"
        if not isinstance(resource, dict):
            return f"line {number} of {TEST_PATIENTS} is not a FHIR resource"
        why = _resource_refusal(resource)
        if why:
            return f"line {number} of {TEST_PATIENTS} {why}"
        resources.append((number, resource))
    return _synthetic_refusal(resources)


@functools.cache
def synthetic_pseudonyms() -> dict[str, str]:
    """``{pseudonym: chart number}`` of every synthetic chart number (:data:`SYNTHETIC_MRN`, patients 1 to
    :data:`SYNTHETIC_MAX_PATIENTS` of each one-digit prefix) under :data:`SYNTHETIC_SITE_KEY`: the HMAC of
    ``pid_for_mrn`` taken on the chart number as written (a synthetic one is plain digits, which every chart-number
    rule leaves as it is), so no setting of the box changes it. 22,500 HMACs, taken once."""
    return {
        hmac.new(SYNTHETIC_SITE_KEY, mrn.encode("ascii"), hashlib.sha256).hexdigest()[:32]: mrn
        for mrn in (f"{p}{i:07d}" for p in "123456789" for i in range(1, SYNTHETIC_MAX_PATIENTS + 1))
    }


def _patient_references(node: Any) -> Iterator[str]:
    stack = [node]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            ref = item.get("reference")
            if isinstance(ref, str) and ref.startswith("Patient/"):
                yield ref[len("Patient/") :]
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


def _synthetic_refusal(resources: list[tuple[int, dict[str, Any]]]) -> str | None:
    """Why the test patients are not the synthetic site's, or None (H1): each ``Patient`` once, its ``id`` the
    pseudonym of a synthetic chart number under the synthetic site's public key (:func:`synthetic_pseudonyms`), its
    ``identifier`` exactly that pseudonym under :data:`SYNTHETIC_PID_SYSTEM`; every ``Patient/`` reference of every
    line one of those patients. It shows where the records were pseudonymised, not what they say (D-1372)."""
    pseudonyms = synthetic_pseudonyms()
    patients: set[str] = set()
    for number, resource in resources:
        if resource["resourceType"] != "Patient":
            continue
        pid = resource.get("id")
        if pid not in pseudonyms:
            return (
                f"line {number} of {TEST_PATIENTS} is a patient whose id is not the pseudonym of a synthetic chart "
                "number under the synthetic site's public key; only the synthetic hospital's test patients travel"
            )
        idents = resource.get("identifier")
        if (
            not isinstance(idents, list)
            or not idents
            or any(i != {"system": SYNTHETIC_PID_SYSTEM, "value": pid} for i in idents)
        ):
            return (
                f"line {number} of {TEST_PATIENTS} is a patient whose identifier is not its own pseudonym under the "
                f"synthetic site's system {SYNTHETIC_PID_SYSTEM}"
            )
        if pid in patients:
            return f"line {number} of {TEST_PATIENTS} is a patient the file already holds"
        patients.add(pid)
    for number, resource in resources:
        if any(ref not in patients for ref in _patient_references(resource)):
            return f"line {number} of {TEST_PATIENTS} refers to a patient that is not one of the file's test patients"
    return None


def test_patient_chart_numbers(data: bytes) -> set[str]:
    """The synthetic chart numbers of the ``Patient`` lines of test patients that passed :func:`_test_patients_refusal`
    (what ``tests/expected.json`` is keyed by)."""
    pseudonyms = synthetic_pseudonyms()
    out: set[str] = set()
    for line in data.splitlines():
        if line.strip():
            resource = sm.load_json(line)
            if resource.get("resourceType") == "Patient":
                out.add(pseudonyms[resource["id"]])
    return out


def _expected_refusal(data: bytes, manifest: Mapping[str, Any], chart_numbers: set[str] | None) -> str | None:
    """Why ``tests/expected.json`` may not leave the box, or None (H2): an object of :data:`EXPECTED_FIELDS` (those of
    :data:`EXPECTED_REQUIRED` present); ``ruleset`` and ``version`` the manifest's; ``index_date`` a date; ``engine``
    and ``source`` one of the closed sets; ``patients`` 1 to 10,000 entries, each key a synthetic chart number
    (:data:`SYNTHETIC_MRN`, at most :data:`SYNTHETIC_MAX_PATIENTS` per prefix) and, when the study carries test
    patients, exactly the chart numbers of its ``Patient`` lines (``chart_numbers``); each value an object of
    criterion ids the manifest names to ``true``, ``false`` or ``null``; ``agreement`` (optional) exactly its four
    fields: ``all_equal`` a boolean, ``known_differences`` empty, ``patients`` the number of patients,
    ``per_criterion`` criterion ids to a number from 0 to 100. No other text travels in it."""
    head = f"{EXPECTED} "
    try:
        doc = sm.load_json(data)
    except (ValueError, UnicodeDecodeError):
        return head + "is not JSON"
    if not isinstance(doc, dict) or not set(doc) <= EXPECTED_FIELDS or not set(doc) >= EXPECTED_REQUIRED:
        return head + (
            "is not the synthetic verdicts' file: an object of " + ", ".join(sorted(EXPECTED_FIELDS)) + " (all but "
            "agreement required), nothing else"
        )
    if doc["ruleset"] != manifest.get("id") or doc["version"] != manifest.get("version"):
        return head + "names another study or version than its manifest"
    day = doc["index_date"]
    try:
        if not (isinstance(day, str) and _DAY.match(day)):
            raise ValueError
        date.fromisoformat(day)
    except ValueError:
        return head + "has an index_date that is not a date written YYYY-MM-DD"
    if doc["engine"] not in EXPECTED_ENGINES or doc["source"] not in EXPECTED_SOURCES:
        return head + "names an engine or a source that is not one of the product's (the synthetic generators' runs)"
    criteria = set(manifest.get("criteria") or ())
    patients = doc["patients"]
    if not isinstance(patients, dict) or not 0 < len(patients) <= 10_000:
        return head + "holds its patients not as an object of 1 to 10,000 synthetic chart numbers"
    for mrn, verdicts in patients.items():
        if not SYNTHETIC_MRN.fullmatch(mrn) or not 0 < int(mrn[1:]) <= SYNTHETIC_MAX_PATIENTS:
            return head + (
                "holds a patient key that is not a synthetic chart number (a site digit and seven digits, at most "
                f"{SYNTHETIC_MAX_PATIENTS:,} patients a site)"
            )
        if not isinstance(verdicts, dict) or not all(
            c in criteria and (v is None or isinstance(v, bool)) for c, v in verdicts.items()
        ):
            return head + "holds a verdict that is not true, false or null for a criterion its manifest names"
    if chart_numbers is not None and set(patients) != chart_numbers:
        return head + "holds patients that are not exactly the chart numbers of the study's synthetic test patients"
    agreement = doc.get("agreement")
    if agreement is not None:
        per = agreement.get("per_criterion") if isinstance(agreement, dict) else None
        if (
            not isinstance(agreement, dict)
            or set(agreement) != EXPECTED_AGREEMENT_FIELDS
            or not isinstance(agreement["all_equal"], bool)
            or agreement["known_differences"] != {}
            or type(agreement["patients"]) is not int
            or agreement["patients"] != len(patients)
            or not isinstance(per, dict)
            or not all(
                c in criteria and not isinstance(v, bool) and isinstance(v, int | float) and 0 <= v <= 100
                for c, v in per.items()
            )
        ):
            return head + (
                "has an agreement that is not all_equal (a boolean), known_differences (empty), patients (their "
                "number) and per_criterion (criterion ids to a number from 0 to 100)"
            )
    return None


#: the keys of a compiled ELM library (``cql/elm/*.json``): the file is ``{"library": {...}}`` with only these (the
#: ELM standard's library keys and ``localId``, which the shipped files carry); the keys inside them are not checked
#: here (the ELM node allow-list is 10D-28's, ``ruleset_part``)
ELM_LIBRARY_KEYS = frozenset(
    {
        "annotation",
        "codeSystems",
        "codes",
        "concepts",
        "contexts",
        "identifier",
        "includes",
        "localId",
        "parameters",
        "schemaIdentifier",
        "statements",
        "usings",
        "valueSets",
    }
)


def _elm_refusal(path: str, doc: Any) -> str | None:
    library = doc.get("library") if isinstance(doc, dict) and set(doc) == {"library"} else None
    if not isinstance(library, dict) or not set(library) <= ELM_LIBRARY_KEYS:
        return (
            f"{path} is not a compiled ELM library: an object whose one key is library, holding only the ELM "
            "library's keys"
        )
    return None


_FLAG = re.compile(r"[a-z][a-z0-9_]{0,63}")


def _ir_refusal(path: str, doc: Any) -> str | None:
    """An IR's ``flags`` are words of the compiler's (``needs_review``, ``compile_error``: as the rule-set export of
    10D-28 takes them), and its ``provenance`` holds only ``calls`` (D-989; nothing writes its other fields), each a
    call id."""
    if not isinstance(doc, dict):
        return None
    flags = doc.get("flags")
    if flags is not None and not (
        isinstance(flags, list) and all(isinstance(f, str) and _FLAG.fullmatch(f) for f in flags)
    ):
        return f"{path} holds a flag that is not one word of the compiler's (lower-case letters, digits and '_')"
    prov = doc.get("provenance")
    if prov is None:
        return None
    calls = prov.get("calls") if isinstance(prov, dict) and set(prov) <= {"calls"} else None
    if not isinstance(calls, list) or not all(isinstance(c, str) and _ID.fullmatch(c) for c in calls):
        return (
            f"{path} holds a provenance that is not a list of call ids (calls only; letters, digits, '.' and '-', at "
            "most 64 each)"
        )
    return None


#: the folders whose files the engine reads as the study's (``Ruleset.from_files``)
_ENGINE_DIRS = ("ir/", "valuesets/", "cql/", "sql/")


def _not_carried(path: str) -> str:
    return (
        f"it holds {path}, which a package does not carry (a hidden file, a file in a subfolder, or an "
        "extension that folder does not take: cql/elm/ takes only .json); remove it from the folder"
    )


def _hashed(path: str, docx: str | None) -> bool:
    """Whether the criteria hash covers ``path`` (``study_manifest.PROTOCOL_FILES``, the template, not a site file)."""
    if path in sm.SITE_FILES:
        return False
    return path == docx or any(
        path == prefix if suffix is None else path.startswith(prefix) and path.endswith(suffix)
        for prefix, suffix, _ in sm.PROTOCOL_FILES
    )


def _folder_refusal(files: Mapping[str, bytes]) -> str | None:
    """Why the protocol files of a study folder may not be packed, or None: each file the criteria hash covers is one
    a package carries (:data:`PACKAGE_FILES`); each JSON file is JSON; each ``ir/*.json`` loads as a ``CriterionIR``
    and each ``valuesets/*.json`` as a :class:`ValueSetFile` (both refuse a field they do not have; the IR strictly,
    as JSON, by its field names: no lax type, no Python name for an aliased field); each ``cql/elm/*.json`` is a
    library of :data:`ELM_LIBRARY_KEYS`; an IR's flags are compiler words and its ``provenance`` only call ids."""
    if sm.MANIFEST not in files:
        return None  # split says so
    try:
        docx = (yaml.safe_load(files[sm.MANIFEST].decode("utf-8")) or {}).get("docx_template")
    except (ValueError, yaml.YAMLError, AttributeError):
        return "its manifest.yaml is not a YAML mapping"
    hashed = sm.hashed_paths(files)
    for path in sorted(files):
        if path == docx:
            continue
        if (path in hashed or path.startswith(_ENGINE_DIRS)) and not carriable(path):
            return _not_carried(path)
        if path not in hashed or not path.endswith(".json"):
            continue
        try:
            doc = sm.load_json(files[path])
        except (ValueError, UnicodeDecodeError):
            return f"{path} is not JSON"
        why = _elm_refusal(path, doc) if path.startswith("cql/elm/") else None
        why = why or (_ir_refusal(path, doc) if path.startswith("ir/") else None)
        if why:
            return why
        try:
            if path.startswith("ir/"):
                for body in (sm.dumps(doc), sm.carried(path, files[path]) or b""):
                    CriterionIR.model_validate_json(body, strict=True, by_alias=True, by_name=False)
            elif path.startswith("valuesets/"):
                ValueSetFile.model_validate(doc)
        except ValueError:  # a ValidationError, or a number RFC 8785 cannot write
            model = "a criterion (CriterionIR)" if path.startswith("ir/") else "a value set"
            return (
                f"{path} does not load as {model}: it holds a field the model does not have, or a value it does "
                "not take"
            )
    return None


def build(files: Mapping[str, bytes], private_pem: bytes, created: str) -> bytes:
    """The package of one study folder given as ``{relative path: bytes}``, signed with the coordinating centre's
    Ed25519 private key (PEM); ``created`` is the writer's date, YYYY-MM-DD (the library reads no clock). Refused
    (``ValueError``, one sentence) for a study whose folder holds its docx template, has no ``protocol_version``,
    holds a file the criteria hash covers or the engine reads that a package does not carry (:data:`PACKAGE_FILES`),
    a JSON file that is not JSON, an IR or value set file that does not load through its model, test patients
    outside the allow-list of D-1372 (:func:`_resource_refusal`) or not the synthetic site's
    (:func:`_synthetic_refusal`), a ``tests/expected.json`` outside its allow-list (:func:`_expected_refusal`), or
    criteria that are not exactly its ``ir/`` files (:func:`criteria_refusal`). The result is verified, with its key
    trusted for this study only, before it is returned."""
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
    why = _folder_refusal(files)
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
    chart_numbers: set[str] | None = None
    if TEST_PATIENTS in protocol["files"]:
        why = _test_patients_refusal(files[TEST_PATIENTS])
        if why:
            raise ValueError(f"the study folder cannot be packaged: {why}")
        chart_numbers = test_patient_chart_numbers(files[TEST_PATIENTS])
    if EXPECTED in protocol["files"]:
        why = _expected_refusal(files[EXPECTED], manifest, chart_numbers)
        if why:
            raise ValueError(f"the study folder cannot be packaged: {why}")
    why = criteria_refusal(manifest, {p: files[p] for p in protocol["files"]})
    if why:
        raise ValueError(f"the study folder cannot be packaged: it {why}")
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
    verify(data, [TrustedKey(public_pem, frozenset({manifest["id"]}))])
    return data


_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)


def _read_fd(dir_fd: int, name: str, rel: str, cap: int, seen: os.stat_result) -> bytes:
    """One file opened by name in its folder's descriptor without following a link, checked on the open descriptor
    (the file listed, a regular file, one link) and against ``cap`` before a byte is read."""
    fd = os.open(name, _FILE_FLAGS, dir_fd=dir_fd)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or (st.st_dev, st.st_ino) != (seen.st_dev, seen.st_ino):
            raise ValueError(f"the study folder cannot be packaged: {rel} is not a regular file, or changed while read")
        if st.st_nlink > 1:
            raise ValueError(
                f"the study folder cannot be packaged: {rel} has another name on this disk (a hard link); a package "
                "is written from the folder's own files only"
            )
        if st.st_size > cap:
            raise ValueError(
                f"the study folder cannot be packaged: {rel} is {st.st_size:,} bytes; a carried file may be at most "
                f"{cap:,} bytes"
            )
        chunks: list[bytes] = []
        left = cap + 1
        while left > 0:
            chunk = os.read(fd, min(left, 1 << 20))
            if not chunk:
                break
            chunks.append(chunk)
            left -= len(chunk)
        data = b"".join(chunks)
        if len(data) > cap:
            raise ValueError(f"the study folder cannot be packaged: {rel} grew past {cap:,} bytes while read")
        return data
    finally:
        os.close(fd)


def read_folder(folder: Path) -> dict[str, bytes]:
    """The files of a study folder on disk that a package needs, as ``{relative path: bytes}``: ``manifest.yaml``
    and each file a package carries (:func:`carriable`), nothing else is read. The folder is opened once, as a
    directory descriptor that is not a symbolic link, and walked by descriptor (``dir_fd``, ``O_NOFOLLOW`` on every
    component), so a folder or file swapped for a link while it is read is refused, not followed. Refused
    (``ValueError``, one sentence): the folder itself a link; anything inside it a symbolic link (a file or a folder)
    or not a regular file or folder; a file it would read with another name on the disk (a hard link) or over its
    size cap (checked before it is read: 4 MiB for the manifest, 100,000,000 bytes for a protocol file, 200,000,000
    together); the docx template; a file the criteria hash covers or under ``ir/``, ``valuesets/``, ``cql/``, ``sql/``
    that a package does not carry. The path to the folder itself is resolved as usual."""
    try:
        root = os.open(folder, _DIR_FLAGS)
    except OSError as error:
        if os.path.islink(folder):
            raise ValueError(
                "the study folder cannot be packaged: the folder is a symbolic link; give the folder itself"
            ) from None
        raise ValueError(
            f"the study folder cannot be packaged: it cannot be opened as a folder ({error.strerror})"
        ) from None
    files: dict[str, bytes] = {}
    total = 0
    try:
        try:
            seen = os.stat(sm.MANIFEST, dir_fd=root, follow_symlinks=False)
        except FileNotFoundError:
            seen = None
        docx = None
        if seen is not None and stat.S_ISREG(seen.st_mode):
            files[sm.MANIFEST] = _read_fd(root, sm.MANIFEST, sm.MANIFEST, STUDY_PACKAGE_MAX_META_BYTES, seen)
            total = len(files[sm.MANIFEST])
            try:
                loaded = yaml.safe_load(files[sm.MANIFEST].decode("utf-8")) or {}
            except (ValueError, yaml.YAMLError):
                raise ValueError(
                    "the study folder cannot be packaged: its manifest.yaml is not a YAML mapping"
                ) from None
            docx = loaded.get("docx_template") if isinstance(loaded, dict) else None
        stack: list[tuple[int, str]] = [(root, "")]
        opened: list[int] = []
        try:
            while stack:
                dfd, prefix = stack.pop()
                with os.scandir(dfd) as listing:
                    names = sorted(entry.name for entry in listing)
                for name in names:
                    rel = prefix + name
                    st = os.stat(name, dir_fd=dfd, follow_symlinks=False)
                    if stat.S_ISLNK(st.st_mode):
                        raise ValueError(
                            f"the study folder cannot be packaged: {rel} is a symbolic link; a package is written "
                            "from the folder's own files only"
                        )
                    if stat.S_ISDIR(st.st_mode):
                        try:
                            child = os.open(name, _DIR_FLAGS, dir_fd=dfd)
                        except OSError:
                            raise ValueError(
                                f"the study folder cannot be packaged: {rel} is a symbolic link or changed while read"
                            ) from None
                        opened.append(child)
                        cst = os.fstat(child)
                        if (cst.st_dev, cst.st_ino) != (st.st_dev, st.st_ino):
                            raise ValueError(f"the study folder cannot be packaged: {rel} changed while read")
                        stack.append((child, rel + "/"))
                        continue
                    if not stat.S_ISREG(st.st_mode):
                        raise ValueError(f"the study folder cannot be packaged: {rel} is not a regular file")
                    if rel == sm.MANIFEST:
                        continue
                    if docx and rel == docx:
                        raise ValueError(
                            f"the study folder holds its template {docx}: a v1 package does not carry a template "
                            "(its bytes would travel as they are, with whatever names its document properties hold)"
                        )
                    if rel in sm.SITE_FILES or not carriable(rel):
                        if _hashed(rel, docx) or rel.startswith(_ENGINE_DIRS):
                            raise ValueError(f"the study folder cannot be packaged: {_not_carried(rel)}")
                        continue  # not carried and not hashed: not read
                    try:
                        files[rel] = _read_fd(dfd, name, rel, STUDY_PACKAGE_MAX_MEMBER_BYTES, st)
                    except OSError:
                        raise ValueError(
                            f"the study folder cannot be packaged: {rel} is a symbolic link or changed while read"
                        ) from None
                    total += len(files[rel])
                    if total > STUDY_PACKAGE_MAX_BYTES:
                        raise ValueError(
                            f"the study folder cannot be packaged: its files are more than {STUDY_PACKAGE_MAX_BYTES:,} "
                            "bytes together"
                        )
        finally:
            for fd in opened:
                os.close(fd)
    finally:
        os.close(root)
    return files


def build_dir(folder: Path, private_pem: bytes, created: str) -> bytes:
    """:func:`build` of a study folder on disk (``rulesets/<ID>/``), read by :func:`read_folder` (by descriptor, no
    symbolic link, no hard link, no file that is not a regular file, caps before reading, only what is carried)."""
    return build(read_folder(folder), private_pem, created)
