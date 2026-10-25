"""Bake-off task definitions (spec v4 §8.10, §17.1; S1-14). One YAML file per task; :func:`load_tasks` reads them."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Task:
    id: str
    gateway_role: str
    purpose: str
    context_of_use: str
    prompt: str
    dataset: str
    data_class: str
    langs: tuple[str, ...]
    n: int
    out_tokens: int
    metrics: tuple[str, ...]

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> Task:
        return cls(
            id=str(doc["id"]),
            gateway_role=str(doc["gateway_role"]),
            purpose=str(doc["purpose"]),
            context_of_use=str(doc["context_of_use"]),
            prompt=str(doc["prompt"]),
            dataset=str(doc["dataset"]),
            data_class=str(doc["data_class"]),
            langs=tuple(doc.get("langs") or ()),
            n=int(doc.get("n", 0)),
            out_tokens=int(doc.get("out_tokens", 64)),
            metrics=tuple(doc.get("metrics") or ()),
        )


def load_tasks(directory: Path = HERE) -> dict[str, Task]:
    out: dict[str, Task] = {}
    for p in sorted(directory.glob("*.yaml")):
        t = Task.from_doc(yaml.safe_load(p.read_text(encoding="utf-8")) or {})
        out[t.id] = t
    return out
