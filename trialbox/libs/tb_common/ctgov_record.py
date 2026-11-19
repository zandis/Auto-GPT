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
* the ``name`` of the lead sponsor and of each collaborator whose ``class`` is ``INDIV`` (a person as sponsor);
  an organisation's name stays;
* ``resultsSection.moreInfoModule.pointOfContact`` (a person's name, phone and e-mail for the results);
* ``citation`` of every reference (the authors' names); the PMID and the reference type stay.

Every other field is kept as the registry gave it. **Not cleaned** (D-1367): free text (summaries, descriptions,
eligibility text), ``seeAlsoLinks`` labels and a facility named after a person may still hold a name; old pack
tarballs already on a box keep the records they were built with until a new pack replaces them.

Where it applies: the reference data pack is built from stripped records (``tools/refdata_fetch.py``), the store
strips again when it loads a pack (an older pack), and its schema version 4 (``refdata.DDL_V4``, which names every
path and key below; a test holds it to them) strips the rows stored before; the criteria compiler's study
(``CtgovStudy``) reads none of these fields, and gives no sponsor name when the lead sponsor is a person.

**Other registries' ids.** :func:`registry_of` names the registry of a secondary id that is one jRCT, JapicCTI or
UMIN-CTR number, and gives the number in its registry's own spelling; the jRCT intake (10D-16) joins on it.
"""

from __future__ import annotations

import copy
import re
from typing import Any

Path_ = tuple[str, ...]

#: paths (from the record's root) dropped whole
DROPPED_PATHS: tuple[Path_, ...] = (
    ("protocolSection", "contactsLocationsModule", "centralContacts"),
    ("protocolSection", "contactsLocationsModule", "overallOfficials"),
    ("protocolSection", "sponsorCollaboratorsModule", "responsibleParty", "investigatorFullName"),
    ("protocolSection", "sponsorCollaboratorsModule", "responsibleParty", "investigatorTitle"),
    ("protocolSection", "sponsorCollaboratorsModule", "responsibleParty", "oldNameTitle"),
    ("resultsSection", "moreInfoModule", "pointOfContact"),
)
#: (path to a list, key dropped from each of its items)
DROPPED_IN_LISTS: tuple[tuple[Path_, str], ...] = (
    (("protocolSection", "contactsLocationsModule", "locations"), "contacts"),
    (("protocolSection", "referencesModule", "references"), "citation"),
)
#: a party whose ``class`` is ``INDIV`` is a person: its ``name`` is dropped (an object, and each item of a list)
INDIV = "INDIV"
PERSON_OBJECTS: tuple[Path_, ...] = (("protocolSection", "sponsorCollaboratorsModule", "leadSponsor"),)
PERSON_LISTS: tuple[Path_, ...] = (("protocolSection", "sponsorCollaboratorsModule", "collaborators"),)

# The jRCT forms in the repository's own Japan data and its registry check (services/console/sitestore.py):
# "jRCT" + 10 digits (jRCT1031230456, jRCT2031210123) or "jRCTs" + 9 digits (jRCTs031180001). The letter "s" is the
# only category letter those data show; another letter is assumed not to exist and is not recognised. JapicCTI:
# "JapicCTI-" + 6 digits; UMIN-CTR: "UMIN" + 9 digits. Any case, one optional space or hyphen after the prefix; the
# number must stand on its own (no letter or digit before or after it).
_B = r"(?<![A-Za-z0-9])"
_E = r"(?![A-Za-z0-9])"
_REGISTRIES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("jRCT", re.compile(_B + r"jRCT[ -]?(?:(s)(\d{9})|(\d{10}))" + _E, re.IGNORECASE)),
    ("JapicCTI", re.compile(_B + r"JapicCTI[ -]?(\d{6})" + _E, re.IGNORECASE)),
    ("UMIN-CTR", re.compile(_B + r"UMIN(?:-CTR)?[ -]?(\d{9})" + _E, re.IGNORECASE)),
)


def _get(node: Any, path: Path_) -> Any:
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def is_person(party: Any) -> bool:
    """A sponsor or collaborator whose ``class`` is ``INDIV`` in any case, spaces around it ignored (as version 4's
    ``upper(btrim(...))``). A party without a class is kept as an organisation (the API's default is a body)."""
    cls = party.get("class") if isinstance(party, dict) else None
    return isinstance(cls, str) and cls.strip(" ").upper() == INDIV


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
    parties = [_get(out, p) for p in PERSON_OBJECTS]
    for p in PERSON_LISTS:
        items = _get(out, p)
        parties += items if isinstance(items, list) else []
    for party in parties:
        if is_person(party):
            party.pop("name", None)
    return out


def _forms(m: re.Match[str], name: str) -> str:
    if name == "jRCT":
        return f"jRCTs{m.group(2)}" if m.group(1) else f"jRCT{m.group(3)}"
    return {"JapicCTI": "JapicCTI-{}", "UMIN-CTR": "UMIN{}"}[name].format(m.group(1))


def registry_of(secondary_id: str) -> tuple[str, str] | None:
    """``(registry, id)`` when the text holds exactly one jRCT, JapicCTI or UMIN-CTR number
    (``("jRCT", "jRCT2031210123")``), else None. A field naming two different numbers (``"UMIN000012345 and
    jRCT2031260123"``) is not recognised: which one the field stands for is not known; its text stays in ``id``."""
    found = {(name, _forms(m, name)) for name, pat in _REGISTRIES for m in pat.finditer(secondary_id or "")}
    return found.pop() if len(found) == 1 else None
