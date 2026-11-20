"""The MEDIS disease-name master, loaded at installation by the hospital's own staff (card 10B-22, D-1261).

MEDIS-DC's "ICD10対応標準病名マスター" (the disease-name, modifier and index tables) is free for a medical institution
to download and use, and may not be passed on without MEDIS's permission, so TrialBox never ships it (D-137, D-1261).
A person of the hospital opens MEDIS's download page from the site set-up step (``console.medis_page``), downloads
the release, hands the zip to the box, reads what the box found in it, approves, and the box loads it.

This module is the box's side of that hand-over, under the site set-up row of the orchestrator's API:

* :func:`unpack` opens the zip the person sent, within hard caps (:data:`MAX_ZIP` bytes, :data:`MAX_MEMBERS`
  members, :data:`MAX_MEMBER` bytes unpacked per member), and writes only the members the loader reads, matched by
  their base name (:data:`WANTED`; a member's folder is never trusted and never used), into a temporary folder this
  module made. Nothing in the zip is run; the specification's PDF and Word files are never unpacked.
* :func:`check` reads the release without loading it (the loader's own dry run): version, release date, rows of
  each table, what would be skipped and why. :func:`load` loads it (``adapter.licensed.load_release``, card 10B-2c)
  in one transaction. Both remove the temporary folder before they return; the zip's bytes are never kept, only
  its SHA-256, the version and the counts.
* :func:`applies`: the step exists only for a site whose country layer says it uses this master (``P7``
  ``medis_master``, D-1250); every other site's pages are as before.
* :func:`reminder`: a loaded release older than :data:`REMIND_MONTHS` months is shown with a reminder (MEDIS
  publishes twice a year, in June and December).

A refusal is a :class:`adapter.licensed.LicensedError` with its code and reason, which the page shows as they are.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import zipfile
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

#: MEDIS's own pages, opened by the person (the box never fetches them)
DOWNLOAD_URL = "https://www2.medis.or.jp/stdcd/byomei/download2019.html"
TERMS_URL = "https://www.medis.or.jp/4_hyojyun/medis-master/riyou/index.html"
#: the hard caps of the hand-over: the zip as sent, its members, and each member the loader reads, once unpacked
MAX_ZIP = 48 * 1024 * 1024
MAX_MEMBERS = 64
MAX_MEMBER = 64 * 1024 * 1024
#: the members the loader reads, by base name (any folder in the zip; the name decides, the folder never does)
WANTED = re.compile(
    r"^(?:readme\.txt|nmain\d{3}\.txt|mdfy\d{3}\.txt|index\d{3}\.txt|ttl_(?:main|mdfy|idx)\.txt)$", re.I
)
REMIND_MONTHS = 7
#: the approval the person ticks, as the audit records it (the page shows it in the person's language)
APPROVAL = "our institution downloaded this release from MEDIS and may use it under MEDIS's terms"
#: what the box keeps of a load (the page's result and the audit event): never a row of the release
SETTING = "medis_release"  # the set-up store's setting that records the last load (:func:`record`)
KEPT = ("version", "released", "disease_rows", "disease_current", "modifier_rows", "index_rows", "sha256")


def _err(code: str, message: str) -> Exception:
    from adapter.licensed import LicensedError

    return LicensedError(code, message)


def applies(country: str | None) -> bool:
    """Does a site of ``country`` load the MEDIS master at installation? Its country layer says so (``P7``,
    ``medis_master``); a country without a layer does not. A broken layer offers no step (nothing of it is read,
    D-1250); the box's health says the layer is broken."""
    from tb_common import country_layer

    try:
        return country_layer.value(country, "P7", "medis_master") is True
    except country_layer.LayerBroken:
        return False


def site_country(environ: Mapping[str, str] | None = None) -> str:
    """The box's country as the committees part reads it (``TB_TZ``): ``JP``, ``TW`` or ""."""
    from tb_common.derived import country_of

    env = os.environ if environ is None else environ
    return country_of(str(env.get("TB_TZ") or "").strip()) or ""


def here(environ: Mapping[str, str] | None = None) -> bool:
    """:func:`applies` for this box."""
    return applies(site_country(environ))


def unpack(data: bytes, into: Path) -> Path:
    """The members of the zip ``data`` the loader reads, written under ``into/release`` by their base name; the
    folder written. Refused (``LicensedError``) when the zip is larger than :data:`MAX_ZIP`, is not a zip, has more
    than :data:`MAX_MEMBERS` members, is encrypted, holds one wanted name twice, or a wanted member unpacks to more
    than :data:`MAX_MEMBER` bytes (zipfile reads no more than the header claims, and a header that understates the
    size fails the zip's CRC: refused as a damaged zip)."""
    if len(data) > MAX_ZIP:
        raise _err("LIC-UPLOAD-SIZE", f"the file is larger than {MAX_ZIP // (1024 * 1024)} MB: not a MEDIS release")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        members = zf.infolist()
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise _err("LIC-UPLOAD-ZIP", "the file is not a zip archive: send the zip as downloaded from MEDIS") from exc
    with zf:
        if len(members) > MAX_MEMBERS:
            raise _err("LIC-UPLOAD-MEMBERS", f"the zip holds more than {MAX_MEMBERS} files: not a MEDIS release")
        out = into / "release"
        out.mkdir(mode=0o700)
        seen: set[str] = set()
        for m in members:
            if m.is_dir():
                continue
            base = m.filename.replace("\\", "/").rsplit("/", 1)[-1]
            if not WANTED.match(base):
                continue  # the specification's PDF and Word files, anything else: never unpacked
            if m.flag_bits & 0x1:
                raise _err("LIC-UPLOAD-ENCRYPTED", f"{base} is encrypted in the zip: send the release as downloaded")
            key = base.lower()
            if key in seen:
                raise _err("LIC-UPLOAD-TWICE", f"the zip holds {base} twice: send one release")
            seen.add(key)
            if m.file_size > MAX_MEMBER:
                raise _err("LIC-UPLOAD-MEMBER-SIZE", f"{base} is larger than {MAX_MEMBER // (1024 * 1024)} MB")
            try:
                # zipfile never reads more than the member's declared size (and then checks its CRC), so a header
                # that understates the size is refused as a damaged zip, never read past the cap
                with zf.open(m) as src, (out / key).open("wb") as dst:
                    while chunk := src.read(1024 * 1024):
                        dst.write(chunk)
            except (zipfile.BadZipFile, OSError, EOFError, NotImplementedError, RuntimeError) as exc:
                raise _err("LIC-UPLOAD-ZIP", f"{base} cannot be read from the zip ({type(exc).__name__})") from exc
    return out


def _kept(out: Mapping[str, Any], sha: str) -> dict[str, Any]:
    """What a check or a load says: the counts, version and date, the zip's SHA-256, and the skipped lines by table,
    line and reason (the loader's own words; never a row's content)."""
    got: dict[str, Any] = {k: out.get(k) for k in KEPT}
    got["sha256"] = sha
    got["skipped"] = [
        {"table": str(t), "line": int(n), "reason": str(why)[:300]} for t, n, why in (out.get("skipped") or ())
    ]
    return got


def _with_release(data: bytes, use: Any) -> dict[str, Any]:
    tmp = Path(tempfile.mkdtemp(prefix="tb-medis-"))
    try:
        return _kept(use(unpack(data, tmp)), hashlib.sha256(data).hexdigest())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check(data: bytes) -> dict[str, Any]:
    """What loading the zip would do, writing nothing: the loader's dry run on the unpacked release."""
    from adapter import licensed

    return _with_release(data, licensed.check_release)


def load(data: bytes, store: Any, *, by: str) -> dict[str, Any]:
    """Load the zip into ``store`` (an ``adapter.licensed.TermStore``) in one transaction, as ``by``."""
    from adapter import licensed

    return _with_release(data, lambda folder: licensed.load_release(store, folder, by=by))


def _months_after(day: date, months: int) -> date:
    y, m = divmod(day.month - 1 + months, 12)
    year, month = day.year + y, m + 1
    for d in (day.day, 30, 29, 28):
        try:
            return date(year, month, d)
        except ValueError:
            continue
    return date(year, month, 28)


def reminder(released: str, today: date) -> bool:
    """Is a release of ``released`` (ISO date) older than :data:`REMIND_MONTHS` months on ``today``? A date that
    cannot be read is not a reminder (the page shows the release as the loader gave it)."""
    try:
        day = date.fromisoformat(str(released)[:10])
    except ValueError:
        return False
    return today >= _months_after(day, REMIND_MONTHS)


def record(out: Mapping[str, Any], by: str) -> str:
    """What the set-up store keeps of a load (:data:`SETTING`): the version, release date, fingerprint and counts,
    and who approved it. Never a row of the release."""
    return json.dumps({**{k: out.get(k) for k in KEPT}, "skipped": len(out.get("skipped") or ()), "by": by},
                      ensure_ascii=False, sort_keys=True)  # fmt: skip


def read_record(raw: str) -> dict[str, Any]:
    try:
        got = json.loads(raw) if raw else {}
    except ValueError:
        return {}
    return got if isinstance(got, dict) else {}


def loaded(status: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The disease-name table's row of ``adapter.licensed.status``, when it is loaded."""
    for s in status:
        if s.get("kind") == "medis" and s.get("state") == "loaded":
            return s
    return None
