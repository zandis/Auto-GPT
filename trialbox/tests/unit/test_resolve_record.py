from __future__ import annotations

import pytest
from tb_common.crypto import pid_for_mrn
from tb_common.identity import HeldOwner, Identifier, IdentityState, MissingIdentity, ResolvedRecord, resolve_record

KEY = bytes(range(32))
PATIENT = Identifier("001")


def resolve(
    *parts: str,
    patient: Identifier = PATIENT,
    source: str = "source-A",
    occurrence: str = "",
    version: str = "1",
    previous: ResolvedRecord | None = None,
) -> ResolvedRecord:
    return resolve_record(
        KEY,
        source,
        (patient,),
        "Observation",
        tuple(Identifier(v) for v in parts),
        table="lab",
        occurrence=occurrence,
        rule_version=version,
        previous=previous,
        state=IdentityState(),
    )


def test_opaque_identifiers_are_scoped_and_lossless(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_CHARTNO_RULE", "digits:4")
    variants = ("001", "1", "００１", " 001", "a", "A")
    assert len({resolve("r", patient=Identifier(p)).owner for p in variants}) == len(variants)
    assert len({resolve(p).record_key for p in variants}) == len(variants)
    got = resolve("r")
    other = resolve("r", source="source-B")
    assert other.owner != got.owner and other.record_key != got.record_key


def test_declared_chart_preserves_existing_patient_and_optout_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_CHARTNO_RULE", "digits:4")
    owners = (Identifier("００１", "chart"), Identifier("1", "chart"))
    patient = resolve_record(KEY, "site", owners, "Patient", owners[:1], state=IdentityState())
    assert patient.owner == patient.record_key == pid_for_mrn(KEY, "0001")
    assert patient.owner != resolve("r", patient=Identifier("0001")).owner
    assert resolve("r", patient=owners[0]) == resolve("r", patient=owners[1])
    assert resolve_record(KEY, "site", owners, "Coverage", owners[:1], state=IdentityState()) == resolve_record(
        KEY, "site", owners, "Coverage", owners[1:], state=IdentityState()
    )


def test_components_and_occurrence_have_boundaries() -> None:
    keys = {
        resolve("a|b", "c").record_key,
        resolve("a", "b|c").record_key,
        resolve("a", occurrence="b|c").record_key,
        resolve("ab|c").record_key,
    }
    assert len(keys) == 4


def test_correction_names_the_key_actually_published() -> None:
    old = resolve("old", version="1")
    update = resolve("new", version="2", previous=old)
    assert old.previous_key is None
    assert update.previous_key == old.record_key
    assert update.record_key == resolve("new", version="2").record_key != old.record_key
    with pytest.raises(HeldOwner):
        resolve("new", patient=Identifier("different"), previous=old)
    with pytest.raises(MissingIdentity):
        resolve("new", source="other", previous=old)


def test_disagreement_stays_held_across_types_and_tables() -> None:
    state = IdentityState()
    a, b = Identifier("a"), Identifier("b")
    with pytest.raises(HeldOwner):
        resolve_record(KEY, "s", (a, b), "Patient", (a,), state=state)
    for owner in (a, b):
        with pytest.raises(HeldOwner):
            resolve_record(KEY, "s", (owner,), "Observation", (Identifier("o"),), table="lab", state=state)
    assert resolve_record(KEY, "s", (Identifier("c"),), "Condition", (Identifier("d"),), state=state).owner


@pytest.mark.parametrize(("owners", "records"), [((), ("x",)), (("",), ("x",)), (("a",), ()), (("a",), ("x", " "))])
def test_no_partial_identity(owners: tuple[str, ...], records: tuple[str, ...]) -> None:
    with pytest.raises(MissingIdentity):
        resolve_record(
            KEY,
            "s",
            tuple(map(Identifier, owners)),
            "Observation",
            tuple(map(Identifier, records)),
            state=IdentityState(),
        )
