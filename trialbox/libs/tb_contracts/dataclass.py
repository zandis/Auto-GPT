"""Data classes D0–D4 (spec v4 §7.1, S1-01).

The data class, not the network location, decides what may happen to data. Every payload that crosses a boundary
carries a :class:`ClassLabel`. A derived object takes the highest class of its inputs (:func:`highest`); only the
registered transforms in ``tb_common.policy.classes`` may lower a class, and each leaves a certificate id.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DataClass(StrEnum):
    """D0 public · D1 confidential, no PHI · D2 de-identified · D3 pseudonymised · D4 identified (§7.1)."""

    D0 = "D0"
    D1 = "D1"
    D2 = "D2"
    D3 = "D3"
    D4 = "D4"

    @property
    def rank(self) -> int:
        return int(self.value[1])

    @property
    def is_patient_level(self) -> bool:
        return self.rank >= 2


class D2Variant(StrEnum):
    """D2-K keeps project-scoped pseudonyms (re-linkable through the vault); D2-L is de-linked (§7.1)."""

    KEYED = "K"
    DELINKED = "L"


class ClassLabel(BaseModel):
    """The label every boundary-crossing payload carries. Unknown classes and missing labels fail validation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    data_class: DataClass
    d2_variant: D2Variant | None = None
    special_category: bool = Field(default=False, description="`sc` flag: genetic, psychiatric, HIV/STI, minors …")
    certificate: str | None = Field(default=None, description="id of the transform certificate that lowered the class")

    @field_validator("d2_variant")
    @classmethod
    def _variant_only_for_d2(cls, v: D2Variant | None, info: Any) -> D2Variant | None:
        dc = info.data.get("data_class")
        if v is not None and dc != DataClass.D2:
            raise ValueError("d2_variant is only valid for D2")
        return v

    @property
    def tag(self) -> str:
        """Short form used in manifests and audit lines: ``D3``, ``D2-K``, ``D1+sc``."""
        t = self.data_class.value
        if self.d2_variant is not None:
            t += f"-{self.d2_variant.value}"
        if self.special_category:
            t += "+sc"
        return t


def parse_class(value: object) -> DataClass:
    """Strict parse: ``None``, ``""`` and anything outside D0–D4 raise ``ValueError`` (fail closed)."""
    if isinstance(value, DataClass):
        return value
    if not isinstance(value, str) or value not in DataClass.__members__:
        raise ValueError(f"unknown or missing data class: {value!r}")
    return DataClass(value)


def highest(*labels: ClassLabel) -> ClassLabel:
    """Propagation rule (§7.1): the result takes the highest class of its inputs; ``sc`` is sticky.

    D2-K outranks D2-L (the key exists, so the combination is still re-linkable). The certificate is dropped:
    a derived object has not itself been through a lowering transform.
    """
    if not labels:
        raise ValueError("highest() needs at least one label")
    top = max(labels, key=lambda lb: (lb.data_class.rank, lb.d2_variant == D2Variant.KEYED))
    variant = top.d2_variant
    if top.data_class == DataClass.D2 and any(lb.d2_variant == D2Variant.KEYED for lb in labels):
        variant = D2Variant.KEYED
    return ClassLabel(
        data_class=top.data_class,
        d2_variant=variant,
        special_category=any(lb.special_category for lb in labels),
    )


__all__ = ["ClassLabel", "D2Variant", "DataClass", "highest", "parse_class"]
