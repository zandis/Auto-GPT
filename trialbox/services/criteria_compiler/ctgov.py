"""ClinicalTrials.gov API v2 client: COHORT trial simulation (SPEC §8.3) and criteria drafting from a registry record.

Public registry data only (no PHI is sent). Three modes (``TB_CTGOV_MODE``; the hospital chooses live or offline at
install, D-140):

* ``live``: ``GET /api/v2/studies`` with ``query.cond``, ``query.locn`` and ``filter.overallStatus`` (or
  ``GET /api/v2/studies/<NCT id>``) on ``TB_CTGOV_BASE_URL`` (default ``https://clinicaltrials.gov/api/v2``) through
  the compiler's egress: the box may reach clinicaltrials.gov:443.
* ``offline``: no outbound access; the studies come from the reference data pack in the trial database
  (``tb_common.refdata``, schema ``refdata``), refreshed by the signed update bundle. Same questions, same records.
* ``cassette``: CI and the demo box; replays ``cassettes/ctgov/<condition-slug>.json`` written by
  ``tools/make_ctgov_cassettes.py``.

With nothing set the client is ``offline`` (owner decision, 2026-11-09); the install question and the settings
wizard write the hospital's choice (a box installed before D-140 has ``live`` in its ``.env`` and keeps it).
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

import httpx
from tb_contracts import CtgovSearchRequest, CtgovSearchResult, CtgovStudy

CASSETTES = Path(__file__).resolve().parent / "cassettes" / "ctgov"
DEFAULT_BASE = "https://clinicaltrials.gov/api/v2"
MODES = ("live", "offline", "cassette")


class CtgovError(RuntimeError):
    pass


def slug(condition: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", condition.lower()).strip("-")


def to_study(raw: dict[str, Any]) -> CtgovStudy | None:
    ps = raw.get("protocolSection") or {}
    ident = ps.get("identificationModule") or {}
    status = ps.get("statusModule") or {}
    elig = ps.get("eligibilityModule") or {}
    text = elig.get("eligibilityCriteria") or ""
    nct = ident.get("nctId") or ""
    last = ((status.get("lastUpdatePostDateStruct") or {}).get("date") or "")[:10]
    if not (nct and text and re.match(r"^\d{4}-\d{2}-\d{2}$", last)):
        return None  # no usable eligibility text (or a partial month-only date)
    design = ps.get("designModule") or {}
    locs = (ps.get("contactsLocationsModule") or {}).get("locations") or []
    return CtgovStudy(
        nct_id=nct,
        title=ident.get("briefTitle") or ident.get("officialTitle") or nct,
        phases=list(design.get("phases") or []),
        conditions=list((ps.get("conditionsModule") or {}).get("conditions") or []),
        overall_status=str(status.get("overallStatus") or ""),
        last_update=date.fromisoformat(last),
        enrollment=(design.get("enrollmentInfo") or {}).get("count"),
        sponsor=((ps.get("sponsorCollaboratorsModule") or {}).get("leadSponsor") or {}).get("name"),
        countries=sorted({str(x.get("country")) for x in locs if x.get("country")}),
        eligibility_text=text,
        minimum_age=elig.get("minimumAge"),
        maximum_age=elig.get("maximumAge"),
        sex=elig.get("sex"),
    )


def _nct(raw: dict[str, Any]) -> str:
    return str(((raw.get("protocolSection") or {}).get("identificationModule") or {}).get("nctId") or "")


class CtGov:
    def __init__(
        self,
        mode: str | None = None,
        base_url: str | None = None,
        cassette_dir: Path = CASSETTES,
        http: httpx.Client | None = None,
        db_url: str | None = None,
    ) -> None:
        self.mode = (mode or os.environ.get("TB_CTGOV_MODE") or "offline").lower()
        if self.mode not in MODES:
            raise CtgovError(f"TB_CTGOV_MODE={self.mode} is not one of {', '.join(MODES)}")
        self.base = (base_url or os.environ.get("TB_CTGOV_BASE_URL") or DEFAULT_BASE).rstrip("/")
        self.cassette_dir = cassette_dir
        self.http = http
        self.db_url = db_url  # offline mode: the trial database (default TB_DB_URL)

    @property
    def origin(self) -> str:
        """The result's ``source``: api (live), refdata (offline) or cassette."""
        return {"live": "api", "offline": "refdata", "cassette": "cassette"}[self.mode]

    def _cassette(self, req: CtgovSearchRequest) -> list[dict[str, Any]]:
        files = (
            sorted(self.cassette_dir.glob("*.json"))
            if req.nct_id
            else [self.cassette_dir / f"{slug(req.condition)}.json"]
        )
        studies: list[dict[str, Any]] = []
        for path in files:
            if path.exists():
                studies += json.loads(path.read_text(encoding="utf-8")).get("studies", [])
        return [s for s in studies if _nct(s) == req.nct_id] if req.nct_id else studies

    def _offline(self, req: CtgovSearchRequest) -> list[dict[str, Any]]:
        from tb_common.refdata import RefStore

        try:
            with RefStore(self.db_url) as st:
                if st.status() is None:
                    raise CtgovError(
                        "offline mode: no reference data pack is loaded (tools/apply_update.sh <refdata bundle>)"
                    )
                if req.nct_id:
                    one = st.ctgov_study(req.nct_id)
                    return [one] if one else []
                return st.ctgov_search(req.condition, req.locations or [], req.status or "RECRUITING",
                                       req.max_studies or 50)  # fmt: skip
        except CtgovError:
            raise
        except Exception as exc:  # the trial database is not reachable
            raise CtgovError(f"offline mode: the reference data could not be read ({type(exc).__name__})") from exc

    def _live_one(self, client: httpx.Client, nct_id: str) -> list[dict[str, Any]]:
        resp = client.get(f"{self.base}/studies/{nct_id}", params={"format": "json"})
        if resp.status_code == 404:
            return []
        if resp.status_code >= 400:
            raise CtgovError(f"ClinicalTrials.gov answered HTTP {resp.status_code}")
        return [resp.json()]

    def _live(self, req: CtgovSearchRequest) -> list[dict[str, Any]]:
        client = self.http or httpx.Client(timeout=60)
        params: dict[str, Any] = {
            "query.cond": req.condition,
            "filter.overallStatus": req.status or "RECRUITING",
            "pageSize": min(req.max_studies or 50, 100),
            "format": "json",
        }
        if req.locations:
            params["query.locn"] = " OR ".join(req.locations)
        out: list[dict[str, Any]] = []
        token: str | None = None
        try:
            if req.nct_id:
                return self._live_one(client, req.nct_id)
            while len(out) < (req.max_studies or 50):
                if token:
                    params["pageToken"] = token
                resp = client.get(f"{self.base}/studies", params=params)
                if resp.status_code >= 400:
                    raise CtgovError(f"ClinicalTrials.gov answered HTTP {resp.status_code}")
                body = resp.json()
                out.extend(body.get("studies") or [])
                token = body.get("nextPageToken")
                if not token:
                    break
        except httpx.HTTPError as exc:
            raise CtgovError(f"ClinicalTrials.gov unreachable ({type(exc).__name__})") from exc
        finally:
            if self.http is None:
                client.close()
        return out[: req.max_studies or 50]

    def raw(self, req: CtgovSearchRequest) -> list[dict[str, Any]]:
        """The full API v2 records (criteria drafting reads their eligibility module)."""
        if not (req.nct_id or req.condition.strip()):
            raise CtgovError("a ClinicalTrials.gov search needs a condition or an NCT id")
        if self.mode == "cassette":
            return self._cassette(req)
        return self._offline(req) if self.mode == "offline" else self._live(req)

    def search(self, req: CtgovSearchRequest) -> CtgovSearchResult:
        wanted = {c.lower() for c in req.locations or []}
        studies = []
        for r in self.raw(req):
            s = to_study(r)
            if s is None:
                continue
            if not req.nct_id:  # one study asked for by its id comes back whatever its status and sites
                if s.overall_status.upper() != (req.status or "RECRUITING").upper():
                    continue
                if wanted and not wanted & {c.lower() for c in s.countries or []}:
                    continue
            studies.append(s)
        return CtgovSearchResult(
            condition=req.condition or (req.nct_id or ""),
            source=cast(Any, self.origin),
            fetched_at=datetime.now(UTC),
            studies=studies,
        )
