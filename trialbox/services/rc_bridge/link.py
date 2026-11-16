"""Project link and field map per study (ICD-04 §4.1a, FR-RC-16), and the status read-back through it.

A link names, per study, the REDCap fields that carry the TrialBox screening number, the consent date, the
enrolment code, the screen-fail reason (with a choice map to TrialBox reason categories), the withdrawal code and
the sponsor subject number. ``validate`` checks every named field against the data dictionary (RC-LINK-FIELD);
``read_back`` joins the exported records to pseudonyms by screening number and derives one status per record.
Only the default link mode ``tb_screening_no`` is built; ``mrn`` is a hospital-stage mode (H) and is refused.

Write-back (D-123): ``write_mode`` ``existing`` fills TrialBox's own instrument (``write_form``, default
``trialbox_screening``) in records the coordinator created; ``create`` also creates a record for a screening number
REDCap does not have yet (a screening-log project). ``validate`` refuses a write form that holds any field the link
reads, so TrialBox can never overwrite a REDCap-owned field.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

LINK_MODES = ("tb_screening_no",)  # `mrn` is H (TB-DS-08 §4.1a)
WRITE_MODES = ("off", "existing", "create")
WRITE_FIELDS = ("tb_screen_date", "tb_status", "tb_status_date")  # TrialBox's instrument (fixture projects A and B)
REASON_CATEGORIES = ("inclusion", "exclusion", "consent_withdrawn", "lost_contact", "other")
_FIELD = re.compile(r"^[a-z][a-z0-9_]{0,99}$")


class LinkError(ValueError):
    def __init__(self, code: str, message: str, fields: list[str] | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.fields = fields or []


@dataclass
class ProjectLink:
    ruleset: str
    project_id: int
    token_ref: str
    link_field: str = "tb_screening_no"
    link_mode: str = "tb_screening_no"
    dag: str = ""
    consent_field: str = ""
    consent_event: str = ""
    enrol_field: str = ""
    enrol_value: str = "1"
    screenfail_field: str = ""
    screenfail_choice_map: dict[str, str] = field(default_factory=dict)
    withdraw_field: str = ""
    withdraw_value: str = "1"
    subject_no_field: str = ""
    write_mode: str = "off"
    write_form: str = "trialbox_screening"
    write_event: str = ""

    @classmethod
    def from_dict(cls, body: dict[str, Any]) -> ProjectLink:
        known = {f for f in cls.__dataclass_fields__}
        data = {k: v for k, v in body.items() if k in known}
        data["project_id"] = int(data.get("project_id") or 0)
        data["screenfail_choice_map"] = {str(k): str(v) for k, v in (data.get("screenfail_choice_map") or {}).items()}
        data.setdefault("write_mode", "off")
        for k in known - {"project_id", "screenfail_choice_map"}:
            if k in data and data[k] is None:
                data[k] = ""
            if k in data:
                data[k] = str(data[k]).strip()
        data["write_mode"] = data["write_mode"] or "off"
        data["write_form"] = data.get("write_form") or "trialbox_screening"
        return cls(**data)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def fields(self) -> list[str]:
        """Every REDCap field the link reads, in a fixed order."""
        names = [
            self.link_field,
            self.consent_field,
            self.enrol_field,
            self.screenfail_field,
            self.withdraw_field,
            self.subject_no_field,
        ]
        return [n for n in names if n]

    def check_shape(self) -> None:
        if self.link_mode not in LINK_MODES:
            raise LinkError("RC-LINK-MODE", "only the tb_screening_no link mode is available in this build")
        if self.project_id <= 0:
            raise LinkError("RC-LINK-FIELD", "the REDCap project id is missing")
        if not self.token_ref:
            raise LinkError("RC-LINK-FIELD", "no REDCap token is chosen for this link")
        if not self.link_field or not self.enrol_field:
            raise LinkError("RC-LINK-FIELD", "the link field and the enrolment field are required")
        bad = [f for f in self.fields() if not _FIELD.match(f)]
        if bad:
            raise LinkError("RC-LINK-FIELD", "REDCap field names are lower-case letters, digits and _", bad)
        if self.write_mode not in WRITE_MODES:
            raise LinkError("RC-LINK-FIELD", f"write-back is one of {', '.join(WRITE_MODES)}")
        if self.write_mode != "off" and not _FIELD.match(self.write_form or ""):
            raise LinkError("RC-LINK-FIELD", "name TrialBox's REDCap instrument", [self.write_form])
        cats = [c for c in self.screenfail_choice_map.values() if c not in REASON_CATEGORIES]
        if cats:
            raise LinkError("RC-LINK-FIELD", f"reason categories are {', '.join(REASON_CATEGORIES)}", cats)


def choices(meta_row: dict[str, Any]) -> dict[str, str]:
    """``"1, Yes | 0, No"`` -> ``{"1": "Yes", "0": "No"}``; yes/no and true/false fields have fixed codes."""
    kind = str(meta_row.get("field_type") or "")
    if kind == "yesno":
        return {"1": "Yes", "0": "No"}
    if kind == "truefalse":
        return {"1": "True", "0": "False"}
    if kind not in ("radio", "dropdown", "checkbox"):
        return {}
    out: dict[str, str] = {}
    for part in str(meta_row.get("select_choices_or_calculations") or "").split("|"):
        code, _, label = part.strip().partition(",")
        if code.strip():
            out[code.strip()] = label.strip()
    return out


def validate(link: ProjectLink, metadata: list[dict[str, Any]], project: dict[str, Any] | None = None) -> None:
    """RC-LINK-FIELD when a named field (or a mapped code) is not in the project's data dictionary."""
    link.check_shape()
    if project is not None and int(project.get("project_id") or 0) != link.project_id:
        raise LinkError(
            "RC-LINK-FIELD",
            f"the token reads project {project.get('project_id')}, not project {link.project_id}",
        )
    by_name = {str(m.get("field_name")): m for m in metadata}
    missing = [f for f in link.fields() if f not in by_name]
    if missing:
        raise LinkError("RC-LINK-FIELD", "these fields are not in the REDCap data dictionary", missing)
    for fname, code in ((link.enrol_field, link.enrol_value), (link.withdraw_field, link.withdraw_value)):
        ch = choices(by_name[fname]) if fname else {}
        if ch and code not in ch:
            raise LinkError("RC-LINK-FIELD", f"{fname} has no choice {code!r}", [fname])
    if link.screenfail_field:
        ch = choices(by_name[link.screenfail_field])
        bad = [c for c in link.screenfail_choice_map if ch and c not in ch]
        if bad:
            raise LinkError("RC-LINK-FIELD", f"{link.screenfail_field} has no choice {', '.join(bad)}", bad)
    if link.write_mode != "off":
        validate_write(link, by_name, project)


def validate_write(link: ProjectLink, by_name: dict[str, dict[str, Any]], project: dict[str, Any] | None) -> None:
    """TrialBox's instrument holds the three write fields and none of the fields the link reads (D-123)."""
    from rc_bridge.writeback import STATUS_CODES

    missing = [f for f in WRITE_FIELDS if f not in by_name]
    if missing:
        raise LinkError("RC-LINK-FIELD", "TrialBox's REDCap instrument lacks these fields", missing)
    elsewhere = [f for f in WRITE_FIELDS if by_name[f].get("form_name") != link.write_form]
    if elsewhere:
        raise LinkError("RC-LINK-FIELD", f"these fields are not on the instrument {link.write_form}", elsewhere)
    owned = [f for f in link.fields() if by_name[f].get("form_name") == link.write_form]
    if owned:
        raise LinkError("RC-LINK-WRITE", "fields TrialBox reads may not be on TrialBox's own instrument", owned)
    ch = choices(by_name["tb_status"])
    lacking = [c for c in STATUS_CODES.values() if c not in ch]
    if lacking:
        raise LinkError("RC-LINK-FIELD", "tb_status lacks the TrialBox status codes", lacking)
    if project is not None and int(project.get("is_longitudinal") or 0) and not link.write_event:
        raise LinkError(
            "RC-LINK-FIELD", "a longitudinal project needs the event of TrialBox's instrument", ["write_event"]
        )


@dataclass
class Joined:
    record_id: str
    link_value: str
    pid: str | None
    status: str | None
    reason: str | None = None
    consent_date: str = ""
    subject_no: str = ""
    dag: str = ""


@dataclass
class ReadBack:
    joined: list[Joined] = field(default_factory=list)
    duplicates: list[dict[str, Any]] = field(default_factory=list)  # RC-LINK-DUP, never resolved automatically
    unmatched: list[dict[str, str]] = field(default_factory=list)  # in REDCap, not in TrialBox (not an error)
    no_link_value: int = 0
    outside_dag: int = 0


def derive_status(link: ProjectLink, vals: dict[str, str]) -> tuple[str | None, str | None]:
    """REDCap's word on one record: withdrawn > enrolled > screen-failed > consented (TB-DS-07 outcome table)."""
    if link.withdraw_field and vals.get(link.withdraw_field) == link.withdraw_value:
        return "withdrawn", "REDCap: withdrawn"
    if vals.get(link.enrol_field) == link.enrol_value:
        return "enrolled", None
    sf = vals.get(link.screenfail_field, "") if link.screenfail_field else ""
    if sf:
        return "screen_fail", f"REDCap: {link.screenfail_choice_map.get(sf, 'other')}"
    if link.consent_field and vals.get(link.consent_field):
        return "consented", None
    return None, None


GROUP_COLUMN = "redcap_data_access_group"


def in_group(rows: list[dict[str, Any]], dag: str) -> tuple[list[dict[str, Any]], bool]:
    """RC13-D (D-849): the rows of the link's data access group, and whether the token is a group user's. Such a
    token's export holds its own group's records only and never the group column, even when asked for (REDCap 13.7);
    its group is taken to be the link's, which the API cannot confirm to a group user. With the column, the rows of
    other groups are left out as before."""
    if not dag:
        return rows, False
    if rows and not any(GROUP_COLUMN in r for r in rows):
        return rows, True
    return [r for r in rows if str(r.get(GROUP_COLUMN) or "") == dag], False


def read_back(link: ProjectLink, rows: list[dict[str, Any]], screening: dict[str, str], id_field: str) -> ReadBack:
    """Join exported rows (one per record and event) to pids through ``screening`` (screening number -> pid)."""
    screening = {k.strip().upper(): v for k, v in screening.items()}
    merged: dict[str, dict[str, str]] = {}
    dag_of: dict[str, str] = {}
    bound = in_group(rows, link.dag)[1]  # RC13-D (D-849): a group user's export has no group column
    for row in rows:
        rid = str(row.get(id_field) or "")
        if not rid:
            continue
        dag = str(row.get(GROUP_COLUMN) or "") or (link.dag if bound else "")
        if dag:
            dag_of[rid] = dag
        vals = merged.setdefault(rid, {})
        event = str(row.get("redcap_event_name") or "")
        for f in link.fields():
            v = str(row.get(f) or "").strip()
            if not v:
                continue
            if f == link.consent_field and link.consent_event and event and event != link.consent_event:
                continue
            vals.setdefault(f, v)
    out = ReadBack()
    by_value: dict[str, list[str]] = {}
    for rid, vals in merged.items():
        if link.dag and dag_of.get(rid, "") != link.dag:
            out.outside_dag += 1
            continue
        value = vals.get(link.link_field, "").upper()
        if not value:
            out.no_link_value += 1
            continue
        by_value.setdefault(value, []).append(rid)
    for value, rids in sorted(by_value.items()):
        if len(rids) > 1:
            out.duplicates.append({"code": "RC-LINK-DUP", "link_value": value, "record_ids": sorted(rids)})
            continue
        rid = rids[0]
        vals = merged[rid]
        pid = screening.get(value)
        if pid is None:
            out.unmatched.append({"record_id": rid, "link_value": value})
            continue
        status, reason = derive_status(link, vals)
        out.joined.append(
            Joined(
                record_id=rid,
                link_value=value,
                pid=pid,
                status=status,
                reason=reason,
                consent_date=vals.get(link.consent_field, "") if link.consent_field else "",
                subject_no=vals.get(link.subject_no_field, "") if link.subject_no_field else "",
                dag=dag_of.get(rid, ""),
            )
        )
    return out
