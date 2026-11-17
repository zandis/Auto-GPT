"""The nightly compose job's ``test_offlist_gate_on_hapi`` (80 % where 100 % is due): the fixture was PUT to HAPI in
file-name order, each Condition and MedicationRequest before the Patient it names. HAPI, deployed without
referential integrity on write, does not index a reference to a resource that is not there yet, so the CQL found no
record for any patient while the lake's SQL did. The fixture now loads as the adapter does (``LOAD_ORDER``)."""

from __future__ import annotations

from tests.offlist_fixture import resources


def test_every_reference_names_a_resource_already_loaded() -> None:
    seen: set[str] = set()
    for r in resources():
        ref = (r.get("subject") or r.get("patient") or {}).get("reference")
        assert ref is None or ref in seen, f"{r['resourceType']}/{r['id']} names {ref} before it is loaded"
        seen.add(f"{r['resourceType']}/{r['id']}")


def test_every_fixture_resource_is_still_loaded_once() -> None:
    ids = [f"{r['resourceType']}/{r['id']}" for r in resources()]
    assert len(ids) == len(set(ids)) and any(i.startswith("Patient/") for i in ids)
