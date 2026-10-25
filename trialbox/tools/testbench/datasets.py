"""Datasets the Test Bench may load: each one names its entry in ``eval/DATASETS.yaml`` and is refused unless that
entry is D0 and ``open`` or ``synthetic`` (ENG-16). Nothing else reaches a page."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from tb_common.policy.classes import Environment, PolicyError
from tb_contracts.dataclass import ClassLabel

from tools.testbench.safety import check_label

ROOT = Path(__file__).resolve().parents[2]
DATASETS_YAML = ROOT / "eval" / "DATASETS.yaml"
ALLOWED_KINDS = ("open", "synthetic")


@dataclass(frozen=True)
class BenchDataset:
    id: str
    title: str
    registry_key: str  # key under ``datasets:`` in eval/DATASETS.yaml
    path: Path
    kind: str = ""
    licence: str = ""
    data_class: str = ""

    @property
    def available(self) -> bool:
        return self.path.exists()


BENCH_DATASETS: dict[str, tuple[str, str, Path]] = {
    "synthea_site_a": (
        "Synthetic site A (stands in for Synthea)",
        "synthetic_hospitals",
        ROOT / "tests" / "fixtures" / "synthetic_patients" / "site-a",
    ),
    "mimic_demo": (
        "MIMIC-IV Clinical Database Demo on FHIR v2.1.0",
        "mimic_iv_fhir_demo",
        ROOT / ".cache" / "open_data" / "mimic-iv-fhir-demo",
    ),
    "ctgov_records": (
        "ClinicalTrials.gov records (cached)",
        "ctgov_records",
        ROOT / "tests" / "fixtures" / "open_data",
    ),
    "recall_cert": ("recall_cert simulation (seeded)", "recall_cert", ROOT / "eval" / "suites" / "recall_cert"),
    "deid_synthetic": (
        "Planted-identifier text (seeded)",
        "deid_synthetic",
        ROOT / "eval" / "suites" / "deid_synthetic",
    ),
}


def load_registry(path: Path = DATASETS_YAML) -> dict[str, dict[str, Any]]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(k): dict(v or {}) for k, v in (doc.get("datasets") or {}).items()}


def require(dataset_id: str, env: Environment, registry: dict[str, dict[str, Any]] | None = None) -> BenchDataset:
    """The dataset if the bench may load it in ``env``; :class:`PolicyError` otherwise (fail closed)."""
    if dataset_id not in BENCH_DATASETS:
        raise PolicyError(f"unknown Test Bench dataset {dataset_id!r}")
    title, key, path = BENCH_DATASETS[dataset_id]
    reg = load_registry() if registry is None else registry
    entry = reg.get(key)
    if entry is None:
        raise PolicyError(f"dataset {key!r} has no entry in eval/DATASETS.yaml")
    label: ClassLabel = check_label(str(entry.get("data_class") or ""), env)
    kind = str(entry.get("kind") or "")
    if kind not in ALLOWED_KINDS:
        raise PolicyError(f"dataset {key!r} is {kind or 'unclassified'!r}; the Test Bench loads open or synthetic data")
    return BenchDataset(dataset_id, title, key, path, kind, str(entry.get("licence") or ""), label.tag)


def all_datasets(env: Environment, registry: dict[str, dict[str, Any]] | None = None) -> list[BenchDataset]:
    reg = load_registry() if registry is None else registry
    return [require(d, env, reg) for d in BENCH_DATASETS]


__all__ = ["BENCH_DATASETS", "BenchDataset", "all_datasets", "load_registry", "require"]
