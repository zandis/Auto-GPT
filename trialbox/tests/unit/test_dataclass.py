from __future__ import annotations

import inspect
from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel, ValidationError
from tb_common.policy.classes import (
    CONTRACT_CLASSES,
    Destination,
    Environment,
    PolicyError,
    Topology,
    check_env,
    contract_class,
    lower,
    may_reach,
)
from tb_contracts.dataclass import ClassLabel, D2Variant, DataClass, highest, parse_class
from tb_testkit.req import spec_requirement_ids, unknown_ids

ROOT = Path(__file__).resolve().parents[2]


def lb(dc: str, **kw: object) -> ClassLabel:
    return ClassLabel(data_class=DataClass(dc), **kw)  # type: ignore[arg-type]


@pytest.mark.req("PRIV-13")
def test_missing_or_unknown_class_fails_validation() -> None:
    with pytest.raises(ValidationError):
        ClassLabel.model_validate({})
    with pytest.raises(ValidationError):
        ClassLabel.model_validate({"data_class": "D5"})
    with pytest.raises(ValidationError):
        ClassLabel.model_validate({"data_class": "D3", "extra": 1})
    for bad in (None, "", "d3", "D9", 3):
        with pytest.raises(ValueError):
            parse_class(bad)
    assert parse_class("D2") is DataClass.D2


def test_d2_variant_only_on_d2() -> None:
    with pytest.raises(ValidationError):
        lb("D3", d2_variant=D2Variant.KEYED)
    assert lb("D2", d2_variant=D2Variant.KEYED, special_category=True).tag == "D2-K+sc"


def test_propagation_takes_highest_and_sc_is_sticky() -> None:
    out = highest(lb("D0"), lb("D1", special_category=True), lb("D3"))
    assert out.data_class == DataClass.D3 and out.special_category
    assert highest(lb("D2", d2_variant=D2Variant.DELINKED), lb("D2", d2_variant=D2Variant.KEYED)).d2_variant == "K"
    assert highest(lb("D1", certificate="pl_1")).certificate is None


@pytest.mark.req("PRIV-13")
def test_every_v1_contract_has_a_class() -> None:
    import tb_contracts.generated.models as m

    names = {
        n for n, o in vars(m).items() if inspect.isclass(o) and issubclass(o, BaseModel) and o.__module__ == m.__name__
    }
    assert names == set(CONTRACT_CLASSES)
    assert contract_class("CandidateRow") == DataClass.D3
    with pytest.raises(PolicyError):
        contract_class("NotAContract")


@pytest.mark.parametrize("topology", list(Topology))
@pytest.mark.parametrize("dc", ["D3", "D4"])
@pytest.mark.parametrize("opt_in", [False, True])
@pytest.mark.parametrize("sc", [False, True])
def test_d3_d4_never_reach_an_external_model(topology: Topology, dc: str, opt_in: bool, sc: bool) -> None:
    label = lb(dc, special_category=sc)
    assert not may_reach(label, Destination.EXTERNAL_MODEL, topology, cloud_opt_in=opt_in)
    assert not may_reach(label, Destination.DEV_PUBLIC, topology, cloud_opt_in=opt_in)


def test_boundary_table() -> None:
    assert may_reach(lb("D0"), Destination.DEV_PUBLIC, Topology.A)
    assert not may_reach(lb("D1"), Destination.DEV_PUBLIC, Topology.C, cloud_opt_in=True)
    assert not may_reach(lb("D1"), Destination.EXTERNAL_MODEL, Topology.A, cloud_opt_in=True)
    assert not may_reach(lb("D1"), Destination.EXTERNAL_MODEL, Topology.C)
    assert may_reach(lb("D1"), Destination.EXTERNAL_MODEL, Topology.C, cloud_opt_in=True)
    keyed = lb("D2", d2_variant=D2Variant.KEYED, certificate="rc_1")
    delinked = lb("D2", d2_variant=D2Variant.DELINKED, certificate="rc_2")
    assert not may_reach(keyed, Destination.EXTERNAL_MODEL, Topology.C, cloud_opt_in=True)
    assert not may_reach(keyed, Destination.PERIMETER, Topology.A)
    assert may_reach(keyed, Destination.TRE, Topology.A)
    assert may_reach(delinked, Destination.EXTERNAL_MODEL, Topology.C, cloud_opt_in=True)
    assert not may_reach(
        lb("D2", d2_variant=D2Variant.DELINKED), Destination.EXTERNAL_MODEL, Topology.C, cloud_opt_in=True
    )
    assert may_reach(lb("D4"), Destination.PERIMETER, Topology.A)
    assert not may_reach(lb("D3"), Destination.TRE, Topology.A)


def test_lowering_needs_a_registered_transform_and_certificate() -> None:
    out = lower(lb("D3", special_category=True), "privacy_accountant", "pl_01")
    assert out.data_class == DataClass.D1 and out.certificate == "pl_01" and out.special_category
    with pytest.raises(PolicyError):
        lower(lb("D3"), "model_says_so", "x")
    with pytest.raises(PolicyError):
        lower(lb("D4"), "privacy_accountant", "x")
    with pytest.raises(PolicyError):
        lower(lb("D3"), "deid_pipeline_delinked", "")


def test_environment_ceiling() -> None:
    check_env(lb("D0"), Environment.DEV)
    with pytest.raises(PolicyError):
        check_env(lb("D1"), Environment.TEST)
    check_env(lb("D2"), Environment.VALIDATION)
    with pytest.raises(PolicyError):
        check_env(lb("D3"), Environment.VALIDATION)


@pytest.mark.req("ENG-16")
def test_every_eval_dataset_is_d0_in_dev_and_test() -> None:
    data = yaml.safe_load((ROOT / "eval" / "DATASETS.yaml").read_text())["datasets"]
    containers = {"suites", "bakeoff", "redteam", "studies"}  # hold suite configs; their datasets are listed by name
    on_disk = {p.name for p in (ROOT / "eval").iterdir() if p.is_dir() and p.name not in containers}
    on_disk |= {p.name for p in (ROOT / "eval" / "suites").glob("*") if p.is_dir()}
    assert on_disk <= set(data), f"eval/ datasets without a class: {sorted(on_disk - set(data))}"
    for d in data.values():
        check_env(lb(d["data_class"]), Environment.TEST)


@pytest.mark.req("ENG-05")
def test_req_marker_ids_come_from_the_spec() -> None:
    ids = spec_requirement_ids()
    assert {"ENG-05", "LLM-1", "S1-06", "C-2′"} <= ids
    assert unknown_ids(["ENG-05", "NOPE-1"]) == ["NOPE-1"]
