"""A ClinicalTrials.gov API v2 study record as TrialBox keeps it (10D-15, D-1367): no personal names, and the ids of
other registries recognised among its secondary ids.

**No personal names.** A registry record is public, but its contact persons, officials and investigators must not
become a contact list on the box (review 14, M14-14; jRCT's terms say the same of its own records). :func:`strip_names`
returns a copy of the record without:

* ``contactsLocationsModule.centralContacts`` and ``overallOfficials`` (name, role, phone, e-mail, affiliation);
* ``contacts`` of every location (the site's contact persons); the location's facility, city, state, country and
  recruitment status stay;
* ``sponsorCollaboratorsModule.responsibleParty`` ``investigatorFullName``, ``investigatorTitle`` and
  ``oldNameTitle`` (the responsible party's type and affiliation stay);
* ``resultsSection.moreInfoModule.pointOfContact`` (a person's name, phone and e-mail for the results);
* ``citation`` of every reference (the authors' names); the PMID and the reference type stay.

Every other field is kept as the registry gave it. The reference data pack is built from stripped records
(``tools/refdata_fetch.py``), the store strips again when it loads a pack (an older pack) and its schema version 4
strips the rows stored before (``tb_common.refdata``); the criteria compiler's study (``CtgovStudy``) reads none of
these fields.

**Other registries' ids.** :func:`registry_of` names the registry of a secondary id that is a jRCT, JapicCTI or UMIN-CTR
number, and gives the number in its registry's own spelling; the jRCT intake (10D-16) joins on it.
"""

from __future__ import annotations

import copy
import re
from typing import Any

#: paths (from the record's root) dropped whole
DROPPED_PATHS: tuple[tuple[str, ...], ...] = (
    ("protocolSection", "contactsLocationsModule", "centralContacts"),
    ("protocolSection", "contactsLocationsModule", "overallOfficials"),
    ("protocolSection", "sponsorCollaboratorsModule", "responsibleParty", "investigatorFullName"),
    ("protocolSection", "sponsorCollaboratorsModule", "responsibleParty", "investigatorTitle"),
    ("protocolSection", "sponsorCollaboratorsModule", "responsibleParty", "oldNameTitle"),
    ("resultsSection", "moreInfoModule", "pointOfContact"),
)
#: (path to a list, key dropped from each of its items)
DROPPED_IN_LISTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("protocolSection", "contactsLocationsModule", "locations"), "contacts"),
    (("protocolSection", "referencesModule", "references"), "citation"),
)

# jRCT: "jRCT" + 10 digits, or a category letter + 9 or 10 digits ("jRCTs031180001", "jRCT1031230456"); JapicCTI:
# "JapicCTI-" + 6 digits; UMIN-CTR: "UMIN" + 9 digits. Matched anywhere in the id text, any case, spaces ignored.
_REGISTRIES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("jRCT", re.compile(r"jRCT([a-z]?)(\d{9,10})(?!\d)", re.IGNORECASE), "jRCT{0}{1}"),
    ("JapicCTI", re.compile(r"JapicCTI-?(\d{6})(?!\d)", re.IGNORECASE), "JapicCTI-{0}"),
    ("UMIN-CTR", re.compile(r"UMIN(?:-CTR)?(\d{9})(?!\d)", re.IGNORECASE), "UMIN{0}"),
)


def _get(node: Any, path: tuple[str, ...]) -> Any:
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def strip_names(study: dict[str, Any]) -> dict[str, Any]:
    """A copy of the API v2 record without the personal names listed in the module's text; the record passed is not
    changed."""
    out = copy.deepcopy(study)
    for path in DROPPED_PATHS:
        parent = _get(out, path[:-1])
        if isinstance(parent, dict):
            parent.pop(path[-1], None)
    for path, key in DROPPED_IN_LISTS:
        items = _get(out, path)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    item.pop(key, None)
    return out


def registry_of(secondary_id: str) -> tuple[str, str] | None:
    """``(registry, id)`` when the text is a jRCT, JapicCTI or UMIN-CTR number (``("jRCT", "jRCT2031210123")``),
    else None."""
    text = re.sub(r"\s+", "", secondary_id or "")
    for name, pattern, form in _REGISTRIES:
        m = pattern.search(text)
        if m:
            groups = [g.lower() if i == 0 and name == "jRCT" else g for i, g in enumerate(m.groups())]
            return name, form.format(*groups)
    return None
