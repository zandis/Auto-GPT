"""The routes of the orchestrator that return a patient's row (NEW-SEC-1, D-717).

Each takes a verified v3 claim (``tb_common.actor_v3``) for the action named here on the route's own study: the
orchestrator's ``require_actor`` on the route, and the console's signing of the call (``console.actor``). A route
of a set-up workspace (``/setup/{ws}/...``) is the whole site's, not a study's: its claim names no study.

Every other GET route of the orchestrator says why it returns no patient's row
(``services/orchestrator/route_actors.yaml``, ``reads_without_patient``); a GET route in neither list stops the
orchestrator at import. "A patient's row": a record of one patient's data, by pseudonym or record key (values,
facts, events, a status, an uploaded row), and a list of such records. Counts, settings and a study's definition
are not."""

from __future__ import annotations

import re

#: the right a patient read asks of the matrix: who may see patient-level data
PHI = "phi.view"
#: D-389: a monitor (a sponsor's CRA, under a monitor grant) reads the enrolled subjects and their cited values
#: (``console.sdv_page``): the routes that page reads take its row too (NEW-JRN-8, D-772: and one enrolled subject's
#: record, for its values in the built-in forms; the console signs it only for a subject the monitor may open)
MONITOR = (PHI, "monitor.read")

#: "GET <template>" -> the action its claim must be for (or one of several: the claim names which, and the matrix
#: is asked for that one)
PATIENT_READS: dict[str, str | tuple[str, ...]] = {
    # the data core (D-123): values, records, their history, conflicts between sources, every record as a file
    "GET /studies/{rs}/data": PHI,
    "GET /studies/{rs}/records": PHI,
    "GET /studies/{rs}/records/{record}": MONITOR,  # NEW-JRN-8 (D-772): the monitor's sheet
    "GET /studies/{rs}/conflicts": PHI,
    "GET /studies/{rs}/export/{fmt}": PHI,
    "GET /studies/{rs}/fhir": PHI,
    # the lifecycle (D-134): participants, their visits, AEs, possible deviations, the enrolment report
    "GET /studies/{rs}/subjects": MONITOR,
    "GET /studies/{rs}/subjects/{record}": MONITOR,
    "GET /studies/{rs}/visits": PHI,
    "GET /studies/{rs}/aes": PHI,
    "GET /studies/{rs}/deviations/possible": PHI,
    "GET /studies/{rs}/report": PHI,
    "GET /studies/{rs}/report/{fmt}": PHI,
    # the REDCap read-back (D-109): record id and sponsor subject number per pseudonym
    "GET /studies/{rs}/redcap-records": PHI,
    "GET /studies/{rs}/redcap-link": PHI,  # the review: its last reads name patients by screening number
    # the EDC prefill (D-160): drafted values, their signatures, and a record's trail
    "GET /studies/{rs}/edc": MONITOR,  # the review: its status lists each subject's visit and drafts
    "GET /studies/{rs}/edc/drafts": MONITOR,
    "GET /studies/{rs}/edc/trail/{record}": MONITOR,
    "GET /studies/{rs}/edc/copy": PHI,
    "GET /studies/{rs}/edc/export/odm": PHI,
    # the screening registry (D-273): a status per pseudonym and its events
    "GET /registry/{ruleset}": PHI,
    "GET /registry/{ruleset}/events": PHI,
    # the site set-up of the whole site (D-131): uploaded files and charts, facts, checks with raw values, fixes with
    # example values, patients by pseudonym, the patient check
    "GET /setup/{ws}/inputs": PHI,
    "GET /setup/{ws}/facts": PHI,
    "GET /setup/{ws}/checks": PHI,
    "GET /setup/{ws}/fixes": PHI,
    "GET /setup/{ws}/people": PHI,
    "GET /setup/{ws}/patients": PHI,
}

_ROUTES = [
    (re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", key.split(" ", 1)[1]) + "$"), key, action)
    for key, action in PATIENT_READS.items()
]  # fmt: skip


def actions(key: str) -> tuple[str, ...]:
    """The actions a patient read takes a claim for, as a tuple."""
    got = PATIENT_READS[key]
    return (got,) if isinstance(got, str) else tuple(got)


def match(method: str, path: str) -> tuple[str, tuple[str, ...], str] | None:
    """For a call of the orchestrator: ``(template, actions, study)`` when it is a patient read, else None. The
    study is the path's ``{rs}`` or ``{ruleset}`` upper-cased, "" for a set-up route of the whole site. ``path``
    may carry a query."""
    if method.upper() != "GET":
        return None
    bare = path.split("?", 1)[0]
    for rx, key, _ in _ROUTES:
        if rx.match(bare):
            parts, tpl = bare.split("/"), key.split(" ", 1)[1].split("/")
            study = next((parts[i] for i, t in enumerate(tpl) if t in ("{rs}", "{ruleset}")), "")
            return key, actions(key), study.strip().upper()
    return None
