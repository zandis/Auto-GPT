"""The MEDIS disease-name master, loaded at installation by the hospital's own staff (card 10B-22, D-1261).

MEDIS-DC's "ICD10対応標準病名マスター" (the disease-name, modifier and index tables) is free for a medical institution
to download and use, and may not be passed on without MEDIS's permission, so TrialBox never ships it (D-137, D-1261).
A person of the hospital opens MEDIS's download page from the site set-up step (``console.medis_page``), downloads
the release, hands the zip to the box, reads what the box found in it, approves, and the box loads it.

This module is the box's side of that hand-over, under the site set-up row of the orchestrator's API:

* :func:`vet` reads the zip the person sent within hard caps (:data:`MAX_ZIP` bytes, :data:`MAX_MEMBERS` members,
  :data:`MAX_MEMBER` bytes for a file and :data:`MAX_TOTAL` for all the release's files together, one file of each
  kind), the files the loader reads only, matched by their base name, and writes nothing. Nothing in the zip is run;
  the specification's PDF and Word files are never read.
* :func:`check` reads the release without loading it (the loader's own dry run): version, release date, rows of
  each table, what would be skipped and why. :func:`load` loads it (``adapter.licensed.load_release``, card 10B-2c)
  in one transaction. Both hand the loader the zip itself, so the store's fingerprint is the zip's SHA-256, the one
  the page and the audit show; :func:`already` tells that this very release is the one loaded. Both remove the
  temporary folder before they return; the zip's bytes are never kept, only its SHA-256, the version and the counts.
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
#: the hard caps of the hand-over: the zip as sent, its members, and each member the loader reads
MAX_ZIP = 32 * 1024 * 1024  # the loader's own bound (adapter.licensed RELEASE_MAX_ZIP, card 10B-2c)
MAX_MEMBERS = 64
MAX_MEMBER = 16 * 1024 * 1024  # the loader's bound for one file of the release
MAX_TOTAL = 40 * 1024 * 1024  # every file of the release together (the real tables: about 11 MB)
SKIPPED_KEPT = 50  # the skipped lines a check or a load answers with, beside their count (review A, M1)
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


def _kind(base: str) -> str:
    """Which file of a release a base name is (``readme``, ``nmain``, ``mdfy``, ``index``, ``ttl_main``, ...), or ""."""
    m = WANTED.match(base)
    if not m:
        return ""
    low = base.lower()
    return low.split(".", 1)[0] if low.startswith(("readme", "ttl_")) else re.sub(r"\d+\.txt$", "", low)


def vet(data: bytes) -> dict[str, str]:
    """The zip ``data`` read within the caps, nothing written anywhere (D-1261; review A, M2): each file the loader
    reads, by its kind, and its base name. Refused (``LicensedError``) when the zip is larger than :data:`MAX_ZIP`,
    is not a zip, has more than :data:`MAX_MEMBERS` members, is encrypted, holds a second file of one kind (a second
    ``nmain*.txt``: refused before it is read), a file is larger than :data:`MAX_MEMBER`, or the files together are
    larger than :data:`MAX_TOTAL` (each is read in pieces and counted; zipfile reads no more than a header claims, and
    a header that understates a size fails the zip's CRC: a damaged zip). A member's folder is never used; the
    specification's PDF and Word files are never read."""
    if len(data) > MAX_ZIP:
        raise _err("LIC-UPLOAD-SIZE", f"the file is larger than {MAX_ZIP // (1024 * 1024)} MB: not a MEDIS release")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        members = zf.infolist()
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise _err("LIC-UPLOAD-ZIP", "the file is not a zip archive: send the zip as downloaded from MEDIS") from exc
    found: dict[str, str] = {}
    total = 0
    with zf:
        if len(members) > MAX_MEMBERS:
            raise _err("LIC-UPLOAD-MEMBERS", f"the zip holds more than {MAX_MEMBERS} files: not a MEDIS release")
        for m in members:
            if m.is_dir():
                continue
            base = m.filename.replace("\\", "/").rsplit("/", 1)[-1]
            kind = _kind(base)
            if not kind:
                continue  # the specification's PDF and Word files, anything else: never read
            if m.flag_bits & 0x1:
                raise _err("LIC-UPLOAD-ENCRYPTED", f"{base} is encrypted in the zip: send the release as downloaded")
            if kind in found:
                raise _err("LIC-UPLOAD-TWICE", f"the zip holds {found[kind]} and {base}: send one release")
            found[kind] = base
            if m.file_size > MAX_MEMBER:
                raise _err("LIC-UPLOAD-MEMBER-SIZE", f"{base} is larger than {MAX_MEMBER // (1024 * 1024)} MB")
            try:
                with zf.open(m) as src:
                    while chunk := src.read(1024 * 1024):
                        total += len(chunk)
                        if total > MAX_TOTAL:
                            raise _err("LIC-UPLOAD-TOTAL", f"the release's files are larger than "
                                       f"{MAX_TOTAL // (1024 * 1024)} MB together: not a MEDIS release")  # fmt: skip
            except (zipfile.BadZipFile, OSError, EOFError, NotImplementedError, RuntimeError) as exc:
                raise _err("LIC-UPLOAD-ZIP", f"{base} cannot be read from the zip ({type(exc).__name__})") from exc
    return found


def _kept(out: Mapping[str, Any], sha: str) -> dict[str, Any]:
    """What a check or a load says: the counts, version and date, the zip's SHA-256, and the skipped lines by table,
    line and reason. The reason is the loader's own words and may quote the cell it could not read: it is shown to
    the person who sent the file only, never written to the audit (which keeps the count)."""
    got: dict[str, Any] = {k: out.get(k) for k in KEPT}
    got["sha256"] = sha
    skipped = list(out.get("skipped") or ())
    # the first lines and the count (review A, M1); the loader closes a long list with one summary line (line 0)
    got["skipped"] = [
        {"table": str(t), "line": int(n), "reason": str(why)[:300]} for t, n, why in skipped[:SKIPPED_KEPT]
    ]
    got["skipped_count"] = len(skipped)
    return got


def _with_release(data: bytes, use: Any) -> dict[str, Any]:
    """The zip checked within this module's caps (:func:`vet`), written to a temporary folder and given to the loader
    AS THE ZIP, so the fingerprint the store keeps is the zip's: the one the page and the audit show (D-1261)."""
    vet(data)
    tmp = Path(tempfile.mkdtemp(prefix="tb-medis-"))
    try:
        archive = tmp / "release.zip"
        archive.write_bytes(data)
        return _kept(use(archive), hashlib.sha256(data).hexdigest())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def already(status: list[dict[str, Any]], sha256: str) -> dict[str, Any] | None:
    """The loaded disease table's row when it came from this very release (the same zip's SHA-256), else None."""
    row = loaded(status)
    return row if row is not None and sha256 and str(row.get("sha256") or "") == sha256 else None


def check(data: bytes, store: Any = None) -> dict[str, Any]:
    """What loading the zip would do, writing nothing: the loader's dry run on the zip. With ``store`` the dry run
    also refuses a release older than the loaded one, as the load would."""
    from adapter import licensed

    return _with_release(data, lambda archive: licensed.check_release(archive, store))


def load(data: bytes, store: Any, *, by: str, again: bool = False) -> dict[str, Any]:
    """Load the zip into ``store`` (an ``adapter.licensed.TermStore``) in one transaction, as ``by``; ``again``: the
    person asked to load the release in use a second time (the loader refuses it otherwise)."""
    from adapter import licensed

    return _with_release(data, lambda archive: licensed.load_release(store, archive, by=by, allow_reload=again))


def load_running(store: Any) -> bool:
    """Is a load of the terminology store under way (its advisory lock held by another session)? Asked without
    waiting, and released at once (review A, M4: the page says so plainly instead of a second load waiting)."""
    with store.db.transaction() as tx:
        got = tx.fetchval(
            "SELECT pg_try_advisory_xact_lock(hashtext('terminology.load'), hashtext(current_schema()))", ()
        )
    return not bool(got)


#: how long a read of a zip stands for its load by the same person (review A, L1)
CHECK_VALID_MINUTES = 30


def check_key(sha256: str) -> str:
    """The set-up store's setting that records who read a zip, and when (the load asks for it)."""
    return f"{SETTING}.checked.{sha256}"


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
    return today > _months_after(day, REMIND_MONTHS)  # "more than seven months" (lane J, L1)


def record(out: Mapping[str, Any], by: str) -> str:
    """What the set-up store keeps of a load (:data:`SETTING`): the version, release date, fingerprint and counts,
    and who approved it. Never a row of the release."""
    skipped = out.get("skipped_count", len(out.get("skipped") or ()))
    return json.dumps({**{k: out.get(k) for k in KEPT}, "skipped": skipped, "by": by},
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
