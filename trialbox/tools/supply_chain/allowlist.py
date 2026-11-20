"""The supply-chain allow-list (D-186): ``deploy/supply-chain-allowlist.yaml``.

A finding is accepted only by a written entry: which package, why, and until when. Two lists:

    vulnerabilities:
      - id: GHSA-xxxx-xxxx-xxxx          # or CVE-..., PYSEC-...; matches the finding id or any alias
        package: pillow                  # required: the entry covers this package only
        reason: Not reachable: ...       # required, a sentence a reviewer can check
        review_by: 2027-01-31            # required ISO date, at most 180 days ahead; after it the gate fails
        owner: security owner            # optional here (tools/vex.py requires one, D-1339)
        date: 2026-11-10                 # optional here: the day it was accepted (tools/vex.py requires it, D-1339)
        image: hapiproject/hapi          # optional (T-110b): accepts the finding in this image repository only
      - id: "*"                          # D-622: every finding of ONE package in ONE third-party image of
        package: linux-libc-dev          # images.lock, named in full; never an image of ours, never without
        image: vllm/vllm-openai          # package and image; dated and reasoned like every entry
        reason: ...
        review_by: 2026-12-10
    licences:
      - package: psycopg
        class: lgpl                      # lgpl, gpl, agpl, unknown or dual, as the licence report flags it
        reason: Used unmodified as an installed package; licence text in the notices
        review_by: 2027-05-01
      - package: dulwich
        class: dual
        chosen: Apache-2.0               # dual: the permissive branch taken; it must be one the package offers
        reason: ...
        review_by: 2027-05-01
      - package: matplotlib
        class: unknown
        licence: PSF-based matplotlib licence (classifier Python Software Foundation License; LICENSE read)
        reason: ...                      # unknown: ``licence`` records what a person verified
        review_by: 2027-05-01

    budgets:                             # open licence flags counted per image and ecosystem (licences.evaluate)
      - image: trialbox-jvm              # an image repository, or requirements.lock
        ecosystem: maven                 # a purl type; "*" (all) for a third-party image only
        max: 68                          # more fails; never pypi or npm (or "*") for our own images
        reason: ...
        review_by: 2027-02-01

    os_packages_unreadable:              # D-574: a third-party image whose OS package list the scanner cannot read
      - image: authelia/authelia         # one image repository; never one of ours, never a pattern
        reason: ...                      # the report is then read without OS packages; its other packages are
        review_by: 2026-12-10            # gated as always; an entry for an image that is readable is refused

The checker rejects an entry with no reason, a reason shorter than 20 characters, no or a bad ``review_by``, a date
in the past or more than 180 days ahead, an unknown or duplicate key, a duplicate entry, a vulnerability entry without
a package, a dual entry without ``chosen``, and an unknown entry without ``licence``. An entry for every id (D-622,
``id: "*"``) is rejected without a package or an image, for an image of ours, for an image that is not a third-party
image of ``deploy/images.lock`` by its full name, and beside an entry for one id that it covers; it accepts findings
only in the image at the digest the lock pins. "Today" is the build machine's
date (``today()``); there is no override on the command line.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST = ROOT / "deploy" / "supply-chain-allowlist.yaml"
MIN_REASON = 20
MAX_AHEAD_DAYS = 180
LICENCE_CLASSES = ("lgpl", "gpl", "agpl", "unknown", "dual")

_VULN_KEYS = {"id", "package", "reason", "review_by", "owner", "image", "date"}
_LIC_KEYS = {"package", "class", "chosen", "licence", "reason", "review_by", "owner"}
_BUDGET_KEYS = {"image", "ecosystem", "max", "reason", "review_by", "owner"}
_OS_KEYS = {"image", "reason", "review_by", "owner", "date"}
_REPO_PART = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")  # one path component of an image repository, ASCII only
EVERY_ID = "*"  # D-622: a vulnerability entry for every finding of one package in one third-party image
IMAGES_LOCK = ROOT / "deploy" / "images.lock"
# in our own images and the lock, an unknown licence in these ecosystems is never budgeted: each needs an entry
STRICT_ECOSYSTEMS = ("pypi", "npm")
LOCK_SUBJECT = "requirements.lock"


def is_own(subject: str) -> bool:
    """Our images (trialbox-*, in any registry) and the Python lock: the strict licence rules apply."""
    return subject == LOCK_SUBJECT or subject.rsplit("/", 1)[-1].startswith("trialbox-")


def today() -> dt.date:
    """The date entries are judged against (tests replace this function)."""
    return dt.date.today()


@dataclass(frozen=True)
class VulnEntry:
    id: str
    package: str
    reason: str
    review_by: dt.date
    image: str | None = None  # an image repository: the entry accepts the finding in that image only (T-110b)


@dataclass(frozen=True)
class LicenceEntry:
    package: str
    cls: str
    reason: str
    review_by: dt.date
    chosen: str | None = None
    licence: str | None = None


@dataclass(frozen=True)
class BudgetEntry:
    image: str  # the SBOM subject: an image repository ("trialbox-jvm", "vllm/vllm-openai") or "requirements.lock"
    ecosystem: str  # a purl type ("maven", "golang", "cargo", "generic"...) or "*" (a third-party image only)
    max: int
    reason: str
    review_by: dt.date


@dataclass(frozen=True)
class OsUnreadableEntry:
    image: str  # a third-party image repository whose OS package list the scanner cannot read (D-574)
    reason: str
    review_by: dt.date


@dataclass
class Allowlist:
    vulnerabilities: list[VulnEntry]
    licences: list[LicenceEntry]
    budgets: list[BudgetEntry] = field(default_factory=list)
    os_packages_unreadable: list[OsUnreadableEntry] = field(default_factory=list)

    def os_unreadable(self, subject: str) -> OsUnreadableEntry | None:
        """The entry that lets the report of ``subject`` (a scanned image reference) show no OS packages."""
        for e in self.os_packages_unreadable:
            if same_repository(e.image, subject):
                return e
        return None

    def vuln(self, ids: set[str], package: str, subject: str | None = None) -> VulnEntry | None:
        """The entry accepting a finding known by any of ``ids`` in ``package``, if one does. An entry scoped to an
        image accepts it only when ``subject`` (the scanned image reference) is that image."""
        wanted = {i.upper() for i in ids}
        for e in self.vulnerabilities:
            if e.package != norm(package):
                continue
            if e.id == EVERY_ID:  # D-622: the pinned image: that repository exactly, at the lock's digest
                if e.image and subject and same_repository(e.image, subject):
                    digest = third_party_digests().get(e.image)
                    if digest and "@" in subject and subject.rsplit("@", 1)[1] == digest:
                        return e
            elif e.id.upper() in wanted and image_matches(e.image, subject):
                return e
        return None

    def licence(self, package: str, cls: str) -> LicenceEntry | None:
        for e in self.licences:
            if e.package == norm(package) and e.cls == cls:
                return e
        return None

    def budget(self, subject: str, ecosystem: str) -> BudgetEntry | None:
        """The budget for open licence flags of ``ecosystem`` in the SBOM of ``subject``, if one is written."""
        for e in self.budgets:
            if (subject == e.image or subject.endswith("/" + e.image)) and e.ecosystem in (ecosystem, "*"):
                return e
        return None


def image_repository(ref: str) -> str:
    """``hapiproject/hapi:v8@sha256:..`` -> ``hapiproject/hapi``; ``localhost:5000/x:1`` -> ``localhost:5000/x``."""
    ref = ref.split("@", 1)[0]
    head, _, last = ref.rpartition("/")
    name = last.split(":", 1)[0]
    return f"{head}/{name}" if head else name


def image_matches(scope: str | None, subject: str | None) -> bool:
    """An unscoped entry matches everywhere; a scoped one only the scanned image of that repository (any registry)."""
    if scope is None:
        return True
    if not subject:
        return False
    repo = image_repository(subject)
    return repo == scope or repo.endswith("/" + scope)


def same_repository(scope: str, subject: str) -> bool:
    """Stricter than :func:`image_matches`: ``subject`` is exactly the repository ``scope``, in any registry (a first
    component with a dot or a port, or ``localhost``; Docker Hub's ``library/`` for a one-word name). A longer path
    that only ends the same way (``someone/authelia/authelia``) is another repository."""
    repo = image_repository(subject)
    head, _, rest = repo.partition("/")
    if rest and ("." in head or ":" in head or head == "localhost"):
        repo = rest
    if "/" not in scope and repo.startswith("library/"):
        repo = repo[len("library/") :]
    return repo == scope


def third_party_digests() -> dict[str, str]:
    """Repository -> pinned digest of the third-party images of ``deploy/images.lock``; empty when it cannot be read."""
    try:
        doc = json.loads(IMAGES_LOCK.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entries = doc.get("third_party") if isinstance(doc, dict) else None
    if not isinstance(entries, dict):
        return {}
    return {
        image_repository(str(e.get("image", ""))): str(e.get("digest") or "")
        for e in entries.values()
        if isinstance(e, dict) and e.get("image")
    }


def third_party_repositories() -> frozenset[str]:
    """The repositories of the third-party images the project pins (``deploy/images.lock``)."""
    return frozenset(third_party_digests())


def norm(name: str) -> str:
    """PEP 503 name form, so ``Pillow`` and ``pillow`` match."""
    return name.strip().lower().replace("_", "-").replace(".", "-")


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that refuses a mapping with the same key twice (the second would silently win)."""


def _no_duplicates(loader: _StrictLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    keys: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in keys:
            raise yaml.constructor.ConstructorError(None, None, f"duplicate key {key!r}", key_node.start_mark)
        keys.add(key)
    return dict(loader.construct_pairs(node, deep=deep))


_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicates)


def _date(value: Any) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def _text(raw: dict[str, Any], key: str) -> str | None:
    value = raw.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _common(where: str, raw: dict[str, Any], keys: set[str], on: dt.date | None) -> tuple[list[str], dt.date | None]:
    errors = [f"{where}: unknown key {k!r}" for k in sorted(set(raw) - keys, key=str)]
    reason = raw.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        errors.append(f"{where}: no reason; every entry must say why it is accepted")
    elif len(reason.strip()) < MIN_REASON:
        errors.append(f"{where}: reason {reason.strip()!r} is too short (at least {MIN_REASON} characters)")
    when = _date(raw.get("review_by"))
    if when is None:
        errors.append(f"{where}: review_by must be an ISO date (YYYY-MM-DD), got {raw.get('review_by')!r}")
    elif on is not None:
        if when < on:
            errors.append(f"{where}: review_by {when} has passed; review the entry or remove it")
        elif (when - on).days > MAX_AHEAD_DAYS:
            errors.append(f"{where}: review_by {when} is more than {MAX_AHEAD_DAYS} days ahead")
    return errors, when


def parse(data: Any, *, today: dt.date | None) -> tuple[Allowlist, list[str]]:
    """Validate an allow-list document. ``today=None`` checks structure only (no dates), for tests of the file."""
    errors: list[str] = []
    out = Allowlist(vulnerabilities=[], licences=[])
    if data is None:
        return out, errors
    if not isinstance(data, dict):
        return out, ["the allow-list must be a mapping with 'vulnerabilities' and 'licences'"]
    errors += [
        f"unknown top-level key {k!r}"
        for k in sorted(set(data) - {"vulnerabilities", "licences", "budgets", "os_packages_unreadable"}, key=str)
    ]
    lists: dict[str, list[Any]] = {}
    for list_key in ("vulnerabilities", "licences", "budgets", "os_packages_unreadable"):
        value = data.get(list_key)
        if value is None:
            lists[list_key] = []
        elif isinstance(value, list):
            lists[list_key] = value
        else:
            errors.append(f"'{list_key}' must be a list, got {type(value).__name__}")
            lists[list_key] = []
    seen: set[tuple[str, str, str | None]] = set()
    for i, raw in enumerate(lists["vulnerabilities"]):
        if not isinstance(raw, dict):
            errors.append(f"vulnerabilities[{i}]: must be a mapping")
            continue
        vid, pkg, img = _text(raw, "id"), _text(raw, "package"), _text(raw, "image")
        where = f"vulnerabilities[{i}] ({vid})" if vid else f"vulnerabilities[{i}]"
        errs, when = _common(where, raw, _VULN_KEYS, today)
        if "image" in raw and (img is None or img != image_repository(img)):
            errs.append(f"{where}: image must be an image repository without tag or digest, got {raw.get('image')!r}")
        if not vid:
            errs.append(f"{where}: no id")
        if not pkg:
            errs.append(f"{where}: no package; an entry covers one package")
        if vid == EVERY_ID:  # D-622: every id of ONE package in ONE third-party image, by its full name
            if pkg and not pkg.replace("-", "").replace("_", "").replace(".", "").replace("+", "").isalnum():
                errs.append(f"{where}: an entry for every id names one package, got {pkg!r}")
            if img is None:
                errs.append(f"{where}: an entry for every id needs an image (it never holds for every image)")
            elif img == image_repository(img) and is_own(img):
                errs.append(f"{where}: an entry for every id is never for our own images")
            elif img == image_repository(img) and img not in third_party_repositories():
                errs.append(f"{where}: {img!r} is not a third-party image of deploy/images.lock, by its full name")
        if vid and pkg:
            key = (vid.upper(), norm(pkg), img)
            if key in seen:
                errs.append(f"{where}: duplicate entry")
            seen.add(key)
        errors += errs
        if not errs and when is not None and vid and pkg:
            out.vulnerabilities.append(VulnEntry(vid, norm(pkg), str(raw["reason"]).strip(), when, img))
    wide = {(e.package, e.image) for e in out.vulnerabilities if e.id == EVERY_ID}
    for e in out.vulnerabilities:
        if e.id != EVERY_ID and (e.package, e.image) in wide:
            errors.append(
                f"vulnerabilities ({e.id}): {e.package} in {e.image} is covered by the entry for every id; remove it"
            )
    seen_l: set[tuple[str, str]] = set()
    for i, raw in enumerate(lists["licences"]):
        if not isinstance(raw, dict):
            errors.append(f"licences[{i}]: must be a mapping")
            continue
        pkg, cls = _text(raw, "package"), raw.get("class")
        where = f"licences[{i}] ({pkg})"
        errs, when = _common(where, raw, _LIC_KEYS, today)
        if not pkg:
            errs.append(f"{where}: no package")
        if cls not in LICENCE_CLASSES:
            errs.append(f"{where}: class must be one of {', '.join(LICENCE_CLASSES)}, got {cls!r}")
        chosen, licence = _text(raw, "chosen"), _text(raw, "licence")
        if cls == "dual" and not chosen:
            errs.append(f"{where}: a dual entry must name the chosen permissive branch in 'chosen'")
        if cls != "dual" and "chosen" in raw:
            errs.append(f"{where}: 'chosen' belongs to dual entries only")
        if cls == "unknown" and not licence:
            errs.append(f"{where}: an unknown entry must record the verified licence in 'licence'")
        if pkg and isinstance(cls, str):
            key_l = (norm(pkg), cls)
            if key_l in seen_l:
                errs.append(f"{where}: duplicate entry")
            seen_l.add(key_l)
        errors += errs
        if not errs and when is not None and pkg and isinstance(cls, str):
            out.licences.append(LicenceEntry(norm(pkg), cls, str(raw["reason"]).strip(), when, chosen, licence))
    seen_b: set[tuple[str, str]] = set()
    for i, raw in enumerate(lists["budgets"]):
        if not isinstance(raw, dict):
            errors.append(f"budgets[{i}]: must be a mapping")
            continue
        image, eco, top = _text(raw, "image"), _text(raw, "ecosystem"), raw.get("max")
        where = f"budgets[{i}] ({image} {eco})"
        errs, when = _common(where, raw, _BUDGET_KEYS, today)
        if not image or not eco:
            errs.append(f"{where}: needs image and ecosystem")
        if not isinstance(top, int) or isinstance(top, bool) or top < 0:
            errs.append(f"{where}: max must be a whole number of components, 0 or more")
        if image and eco and is_own(image) and (eco in STRICT_ECOSYSTEMS or eco == "*"):
            errs.append(f"{where}: unknown {eco} licences in our own images are not budgeted; write an entry each")
        if image and eco:
            if (image, eco) in seen_b:
                errs.append(f"{where}: duplicate entry")
            seen_b.add((image, eco))
        errors += errs
        if not errs and when is not None and image and eco and isinstance(top, int):
            out.budgets.append(BudgetEntry(image, eco, top, str(raw["reason"]).strip(), when))
    seen_o: set[str] = set()
    for i, raw in enumerate(lists["os_packages_unreadable"]):
        if not isinstance(raw, dict):
            errors.append(f"os_packages_unreadable[{i}]: must be a mapping")
            continue
        image = _text(raw, "image")
        where = f"os_packages_unreadable[{i}] ({image})"
        errs, when = _common(where, raw, _OS_KEYS, today)
        if not image:
            errs.append(f"{where}: needs an image")
        elif image != image_repository(image):
            errs.append(f"{where}: image must be an image repository without tag or digest, got {image!r}")
        elif not all(_REPO_PART.fullmatch(part) for part in image.split("/")):
            errs.append(f"{where}: image must name one image repository, not a pattern, got {image!r}")
        elif is_own(image):
            errs.append(f"{where}: our own images always show their OS packages; no entry for them")
        elif image not in third_party_repositories():
            errs.append(f"{where}: {image!r} is not a third-party image of deploy/images.lock, by its full name")
        if image:
            if image in seen_o:
                errs.append(f"{where}: duplicate entry")
            seen_o.add(image)
        errors += errs
        if not errs and when is not None and image:
            out.os_packages_unreadable.append(OsUnreadableEntry(image, str(raw["reason"]).strip(), when))
    return out, errors


def load(path: Path = ALLOWLIST, *, today: dt.date | None) -> tuple[Allowlist, list[str]]:
    if not path.is_file():
        return Allowlist([], []), [f"{path} is missing"]
    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=_StrictLoader)
    except yaml.YAMLError as exc:
        return Allowlist([], []), [f"{path} is not valid YAML: {exc}"]
    return parse(data, today=today)
