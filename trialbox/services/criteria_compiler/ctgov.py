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

The study (``to_study``, D-1367) carries, beside the fields the trial simulation reads, the record's sites (facility,
city, country, recruitment status; never a contact person), its secondary ids with the registry of a jRCT, JapicCTI or
UMIN-CTR number (``registry_ids``), the arms, interventions, primary and secondary outcomes and the design.

With nothing set the client is ``offline`` (owner decision, 2026-11-09); the install question and the settings
wizard write the hospital's choice (a box installed before D-140 has ``live`` in its ``.env`` and keeps it).
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

import httpx
from tb_common.ctgov_record import is_person, registry_of
from tb_common.http import EgressRefused, guarded_client
from tb_contracts import (
    CtgovArm,
    CtgovDesign,
    CtgovIntervention,
    CtgovLocation,
    CtgovOutcome,
    CtgovSearchRequest,
    CtgovSearchResult,
    CtgovSecondaryId,
    CtgovStudy,
)

log = logging.getLogger(__name__)
CASSETTES = Path(__file__).resolve().parent / "cassettes" / "ctgov"
DEFAULT_BASE = "https://clinicaltrials.gov/api/v2"
MODES = ("live", "offline", "cassette")


class CtgovError(RuntimeError):
    pass


def slug(condition: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", condition.lower()).strip("-")


def _d(v: Any) -> dict[str, Any]:
    """A module or part of the record: a dict, else empty (a malformed record never stops a search, D-1367)."""
    return v if isinstance(v, dict) else {}


def _items(v: Any) -> list[dict[str, Any]]:
    """The dict items of a list (anything else in it, or a non-list, is left out)."""
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def _s(v: Any) -> str | None:
    return v if isinstance(v, str) and v else None


def _strs(v: Any) -> list[str]:
    """A list of strings; one string is a list of one (never split into characters); anything else is empty."""
    if isinstance(v, str):
        return [v] if v else []
    return [x for x in v if isinstance(x, str) and x] if isinstance(v, list) else []


def _design(design: dict[str, Any]) -> CtgovDesign | None:
    info = _d(design.get("designInfo"))
    mask = _d(info.get("maskingInfo"))
    out = CtgovDesign(
        study_type=_s(design.get("studyType")),
        allocation=_s(info.get("allocation")),
        model=_s(info.get("interventionModel")) or _s(info.get("observationalModel")),
        primary_purpose=_s(info.get("primaryPurpose")),
        masking=_s(mask.get("masking")),
        who_masked=_strs(mask.get("whoMasked")) or None,
        enrollment_type=_s(_d(design.get("enrollmentInfo")).get("type")),
    )
    return out if out.model_dump(exclude_none=True) else None


def _secondary_id(sid: str, x: dict[str, Any]) -> CtgovSecondaryId:
    found = registry_of(sid)
    return CtgovSecondaryId(
        id=sid,
        type=_s(x.get("type")),
        domain=_s(x.get("domain")),
        registry=cast(Any, found[0]) if found else None,
        registry_id=found[1] if found else None,
    )


def _widened(ps: dict[str, Any]) -> dict[str, Any]:
    """10D-15 (D-1367): sites, secondary ids, arms, interventions, outcomes and design. No contact person, official
    or investigator is read (``tb_common.ctgov_record`` lists what a stored record drops). A part that is not of the
    API's shape (a string where a list of objects belongs) is left out; it never fails the search."""
    arms = _d(ps.get("armsInterventionsModule"))
    outcomes = _d(ps.get("outcomesModule"))

    def outcome_list(key: str) -> list[CtgovOutcome]:
        return [
            CtgovOutcome(measure=m, description=_s(o.get("description")), time_frame=_s(o.get("timeFrame")))
            for o in _items(outcomes.get(key))
            if (m := _s(o.get("measure")))
        ]

    parts: dict[str, Any] = {
        "locations": [
            CtgovLocation(
                facility=f,
                city=_s(x.get("city")),
                state=_s(x.get("state")),
                country=_s(x.get("country")),
                status=_s(x.get("status")),
            )
            for x in _items(_d(ps.get("contactsLocationsModule")).get("locations"))
            if (f := _s(x.get("facility")))
        ],
        "secondary_ids": [
            _secondary_id(i, x)
            for x in _items(_d(ps.get("identificationModule")).get("secondaryIdInfos"))
            if (i := _s(x.get("id")))
        ],
        "arms": [
            CtgovArm(
                label=label,
                type=_s(a.get("type")),
                description=_s(a.get("description")),
                intervention_names=_strs(a.get("interventionNames")),
            )
            for a in _items(arms.get("armGroups"))
            if (label := _s(a.get("label")))
        ],
        "interventions": [
            CtgovIntervention(
                name=name,
                type=_s(i.get("type")),
                description=_s(i.get("description")),
                arm_labels=_strs(i.get("armGroupLabels")),
                other_names=_strs(i.get("otherNames")),
            )
            for i in _items(arms.get("interventions"))
            if (name := _s(i.get("name")))
        ],
        "primary_outcomes": outcome_list("primaryOutcomes"),
        "secondary_outcomes": outcome_list("secondaryOutcomes"),
        "design": _design(_d(ps.get("designModule"))),
    }
    return {k: v or None for k, v in parts.items()}  # a module the record lacks is absent, not empty


def registry_ids(study: CtgovStudy, registry: str) -> list[str]:
    """The ids of one other registry (``jRCT``, ``JapicCTI``, ``UMIN-CTR``) among the study's secondary ids."""
    return [x.registry_id for x in study.secondary_ids or [] if x.registry == registry and x.registry_id]


def _sponsor(ps: dict[str, Any]) -> str | None:
    """The lead sponsor's name; none when the sponsor is a person (class INDIV, D-1367)."""
    lead = _d(_d(ps.get("sponsorCollaboratorsModule")).get("leadSponsor"))
    return None if is_person(lead) else _s(lead.get("name"))


def to_study(raw: dict[str, Any]) -> CtgovStudy | None:
    ps = _d(_d(raw).get("protocolSection"))
    ident = _d(ps.get("identificationModule"))
    status = _d(ps.get("statusModule"))
    elig = _d(ps.get("eligibilityModule"))
    text = elig.get("eligibilityCriteria") or ""
    nct = ident.get("nctId") or ""
    last = str(_d(status.get("lastUpdatePostDateStruct")).get("date") or "")[:10]
    if not (nct and text and re.match(r"^\d{4}-\d{2}-\d{2}$", last)):
        return None  # no usable eligibility text (or a partial month-only date)
    design = _d(ps.get("designModule"))
    locs = _items(_d(ps.get("contactsLocationsModule")).get("locations"))
    return CtgovStudy(
        nct_id=nct,
        title=ident.get("briefTitle") or ident.get("officialTitle") or nct,
        phases=_strs(design.get("phases")),
        conditions=_strs(_d(ps.get("conditionsModule")).get("conditions")),
        overall_status=str(status.get("overallStatus") or ""),
        last_update=date.fromisoformat(last),
        enrollment=_d(design.get("enrollmentInfo")).get("count"),
        sponsor=_sponsor(ps),
        countries=sorted({c for x in locs if (c := _s(x.get("country")))}),
        eligibility_text=text,
        minimum_age=elig.get("minimumAge"),
        maximum_age=elig.get("maximumAge"),
        sex=elig.get("sex"),
        **_widened(ps),
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
        # T-212d (D-450): TB_CTGOV_BASE_URL is a setting; the guard holds the call to the declared registry
        client = self.http or guarded_client("criteria-compiler", timeout=60)
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
        except EgressRefused as exc:
            raise CtgovError(f"the ClinicalTrials.gov address is not allowed ({exc.reason}): {exc.host}") from exc
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
            try:
                s = to_study(r)
            except ValueError:  # pydantic's ValidationError, a bad date: one record the contract refuses (D-1367)
                nct = _nct(r) if isinstance(r, dict) else ""
                log.warning("ctgov: record %s left out: not of the registry's shape",
                            nct if re.fullmatch(r"NCT\d{8}", nct) else "(no NCT id)")  # fmt: skip
                continue
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
