"""A REDCap data dictionary, as the API returns it, read into TrialBox's forms.

The dictionary becomes one FHIR Questionnaire per instrument (:func:`datacore.forms.questionnaires`). Identifier
fields are not put on those questionnaires. Events are visits, the form-event mapping is the schedule, and a
repeating instrument stays a repeating CRF. Nothing here writes a protocol criterion: eligibility rules stay in
the ruleset, and the study link reads consent and enrolment on its own.
"""

from __future__ import annotations

from typing import Any

from datacore.forms import field_of, questionnaires

CROSSWALK = {
    "eligibility": "A REDCap field is a CRF item. Inclusion and exclusion rules stay in the ruleset. The study "
    "link reads consent, enrolment, screen-fail and withdrawal as the eligibility outcome, not as criteria.",
    "fhir": "Each instrument becomes a FHIR R4 Questionnaire. QuestionnaireResponse is the data core's export. "
    "Values stay REDCap's raw codes so a row can go back unchanged.",
    "omop": "The OMOP store is the hospital record, read one way. This mapping does not write CRF rows into it.",
    "cdisc": "The data core exports ODM 1.3, with CDASH tags on TrialBox's built-in forms. REDCap can also export "
    "records as ODM (format=odm). This connector's record calls use JSON flat, the same fields.",
    "cdis": "REDCap's Clinical Data Interoperability Services pull EHR data into mapped fields inside REDCap. "
    "That module is not this API, and TrialBox does not call it.",
}


def identifier_names(metadata: list[dict[str, Any]]) -> set[str]:
    """Fields tagged identifier, except the record id (the first field), which a row cannot spare."""
    if not metadata:
        return set()
    record_id = str(metadata[0].get("field_name") or "")
    names: set[str] = set()
    for row in metadata:
        if str(row.get("identifier") or "").strip().lower() != "y":
            continue
        name = str(row.get("field_name") or "")
        if name and name != record_id:
            names.add(name)
    return names


def blank_identifiers(rows: list[dict[str, Any]], metadata: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copies of ``rows`` with identifier fields, and their checkbox columns, set to blank."""
    names = identifier_names(metadata)
    if not names:
        return [dict(row) for row in rows]
    out: list[dict[str, Any]] = []
    for row in rows:
        copied = dict(row)
        for key in copied:
            base = key.split("___", 1)[0]
            if key in names or base in names:
                copied[key] = ""
        out.append(copied)
    return out


def map_project(
    study: str,
    metadata: list[dict[str, Any]],
    *,
    project: dict[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
    arms: list[dict[str, Any]] | None = None,
    form_event_mapping: list[dict[str, Any]] | None = None,
    repeating: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The dictionary and the schedule as TrialBox holds a study's forms. ``study`` is the ruleset id."""
    fields = [field_of(row) for row in metadata]
    forms = questionnaires(study, fields)
    by_form: dict[str, list[str]] = {}
    for field in fields:
        if field.identifier:
            continue
        by_form.setdefault(field.form, []).append(field.name)
    info = project or {}
    return {
        "study": study,
        "project_id": info.get("project_id"),
        "project_title": info.get("project_title") or "",
        "longitudinal": bool(int(info.get("is_longitudinal") or 0)) if info else bool(events),
        "instruments": [{"name": name, "fields": names} for name, names in by_form.items()],
        "questionnaires": forms,
        "identifiers_not_stored": sorted(identifier_names(metadata)),
        "file_fields": [field.name for field in fields if field.kind == "file" and not field.identifier],
        "calculated_fields": [field.name for field in fields if field.kind == "calc"],
        "arms": [dict(row) for row in arms or []],
        "visits": [dict(row) for row in events or []],
        "schedule": [dict(row) for row in form_event_mapping or []],
        "repeating": [dict(row) for row in repeating or []],
        "crosswalk": dict(CROSSWALK),
    }
