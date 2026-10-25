"""Metric catalogue, controlled rounding and the privacy accountant for ``tb.aggregate_query`` (§9.3, §7; HER-10).

The catalogue (``metrics.yaml``) is the only source of metric ids and breakdowns. Every count passes the small-cell
rule and controlled rounding (``tb_common.smallcell.round_count``: 1–4 → ``"<5"``, larger counts to the nearest
multiple of 5) before it leaves the server, and every answer is recorded by the accountant, which returns the entry
id the output carries. A question the accountant refuses gets the refusal reason, never a partial number
(FR-CONV-13).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from tb_common.smallcell import is_suppressed, round_count
from tb_common.ulid import new_ulid
from tb_contracts.frontdoor import AggregateRow

DEFAULT_PATH = Path(__file__).resolve().parent / "metrics.yaml"


class MetricRefused(PermissionError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class Metric:
    id: str
    unit: str
    breakdowns: tuple[str, ...]


@dataclass(frozen=True)
class Catalogue:
    version: str
    threshold: int
    metrics: dict[str, Metric]

    @classmethod
    def load(cls, path: Path = DEFAULT_PATH) -> Catalogue:
        doc: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        metrics = {
            str(k): Metric(str(k), str(v.get("unit", "")), tuple(v.get("breakdowns") or ()))
            for k, v in (doc.get("metrics") or {}).items()
        }
        return cls(str(doc["version"]), int(doc.get("threshold", 5)), metrics)

    def check(self, metric: str, breakdown: str | None) -> Metric:
        m = self.metrics.get(metric)
        if m is None:
            raise MetricRefused("metric_unknown", f"{metric!r} is not in the metric catalogue {self.version}")
        if breakdown is not None and breakdown not in m.breakdowns:
            raise MetricRefused("breakdown_unknown", f"{metric} has no breakdown {breakdown!r}")
        return m


def rounded_rows(counts: Mapping[str, int], threshold: int) -> list[AggregateRow]:
    rows = []
    for key in sorted(counts):
        v = round_count(int(counts[key]), threshold)
        rows.append(AggregateRow(key=key, value=v, suppressed=is_suppressed(v)))
    return rows


@dataclass
class PrivacyAccountant:
    """Per-user query budget with an entry per answered query (stand-in for the §7 accountant until MS2)."""

    budget_per_user: int = 200
    id_factory: Callable[[], str] = new_ulid
    entries: list[dict[str, Any]] = field(default_factory=list)

    def record(self, user: str, metric: str, breakdown: str | None, study: str | None, cells: int) -> str:
        used = sum(1 for e in self.entries if e["user"] == user)
        if used >= self.budget_per_user:
            raise MetricRefused("budget_exhausted", "the privacy budget for aggregate questions is used up")
        entry_id = self.id_factory()
        self.entries.append(
            {
                "entry_id": entry_id,
                "user": user,
                "metric": metric,
                "breakdown": breakdown,
                "study": study,
                "cells": cells,
            }
        )
        return entry_id
