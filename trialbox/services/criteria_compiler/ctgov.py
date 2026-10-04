"""ClinicalTrials.gov API v2 client for COHORT trial simulation (SPEC §8.3).

Public registry data only (no PHI is sent): ``GET /api/v2/studies`` with ``query.cond``, ``query.locn`` and
``filter.overallStatus``. ``TB_CTGOV_MODE=cassette`` (CI, demo box without egress) replays
``cassettes/ctgov/<condition-slug>.json`` written by ``tools/make_ctgov_cassettes.py``; ``live`` (default) calls
``TB_CTGOV_BASE_URL`` (default ``https://clinicaltrials.gov/api/v2``) through the compiler's egress.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
from tb_contracts import CtgovSearchRequest, CtgovSearchResult, CtgovStudy

CASSETTES = Path(__file__).resolve().parent / "cassettes" / "ctgov"
DEFAULT_BASE = "https://clinicaltrials.gov/api/v2"


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


class CtGov:
    def __init__(
        self,
        mode: str | None = None,
        base_url: str | None = None,
        cassette_dir: Path = CASSETTES,
        http: httpx.Client | None = None,
    ) -> None:
        self.mode = (mode or os.environ.get("TB_CTGOV_MODE", "live")).lower()
        self.base = (base_url or os.environ.get("TB_CTGOV_BASE_URL") or DEFAULT_BASE).rstrip("/")
        self.cassette_dir = cassette_dir
        self.http = http

    def _cassette(self, req: CtgovSearchRequest) -> list[dict[str, Any]]:
        path = self.cassette_dir / f"{slug(req.condition)}.json"
        if not path.exists():
            return []
        studies: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8")).get("studies", [])
        return studies

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

    def search(self, req: CtgovSearchRequest) -> CtgovSearchResult:
        raw = self._cassette(req) if self.mode == "cassette" else self._live(req)
        wanted = {c.lower() for c in req.locations or []}
        studies = []
        for r in raw:
            s = to_study(r)
            if s is None or s.overall_status.upper() != (req.status or "RECRUITING").upper():
                continue
            if wanted and not wanted & {c.lower() for c in s.countries or []}:
                continue
            studies.append(s)
        return CtgovSearchResult(
            condition=req.condition,
            source="cassette" if self.mode == "cassette" else "api",
            fetched_at=datetime.now(UTC),
            studies=studies,
        )
