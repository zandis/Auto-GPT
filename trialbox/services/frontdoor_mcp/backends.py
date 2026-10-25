"""Read sides the front-door tools use (spec v4 §9.3). None of them returns patient-level data (HER-9, ENG-01).

The front-door package may not import the data platform, the lake or patient-level contracts (ENG-01). Each source
is therefore a narrow protocol that the deployment wires to the orchestrator's read models; this module also ships
the simple implementations used in the test box and the Test Bench:

* :class:`LocalRegistryIndex`: the local ClinicalTrials.gov index (cached public records, D0);
* :class:`GatewayProtocolAnswerer`: ``answer_protocol`` through ``tb-gateway`` (``libs/tb_llm`` only);
* :class:`StaticAtlas`, :class:`StaticAggregates`, :class:`StaticOps`, :class:`ReleaseIndex`: in-memory read models.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from tb_common.llm import load_prompt, render
from tb_contracts.frontdoor import AskProtocolOut, AtlasRow, OpsPanel, OpsRow, RegistryRecord
from tb_llm import CallLabels, GatewayClient, json_schema_format


class ProtocolAnswerer(Protocol):
    def answer(self, study: str, question: str) -> AskProtocolOut: ...


class RegistryIndex(Protocol):
    def search(self, query: str, limit: int) -> list[RegistryRecord]: ...


class AtlasSource(Protocol):
    def describe(self, domain: str | None) -> tuple[str | None, list[AtlasRow]]: ...


class AggregateSource(Protocol):
    def counts(self, metric: str, breakdown: str | None, study: str | None) -> tuple[str, dict[str, int]]:
        """``(data_cut, {key: exact count})``; the server rounds and suppresses."""
        ...


class OpsSource(Protocol):
    def read(self, panel: OpsPanel) -> list[OpsRow]: ...


@dataclass(frozen=True)
class Release:
    release_id: str
    job_id: str
    recipients: tuple[str, ...]  # directory principals the release went to at G2/G3
    payload_ref: str  # object-store key of the released file; never returned by a tool


@dataclass
class ReleaseIndex:
    releases: dict[str, Release] = field(default_factory=dict)

    def get(self, release_id: str) -> Release | None:
        return self.releases.get(release_id)


# ------------------------------------------------------------------------------------------------ registry (D0)
def _record(study: Mapping[str, Any]) -> RegistryRecord | None:
    ps = study.get("protocolSection") or {}
    ident = ps.get("identificationModule") or {}
    nct = str(ident.get("nctId") or study.get("nct_id") or "")
    if not nct:
        return None
    return RegistryRecord(
        nct_id=nct,
        title=str(ident.get("briefTitle") or ""),
        status=str((ps.get("statusModule") or {}).get("overallStatus") or "UNKNOWN"),
        phases=[str(p) for p in (ps.get("designModule") or {}).get("phases") or []],
        conditions=[str(c) for c in (ps.get("conditionsModule") or {}).get("conditions") or []],
    )


class LocalRegistryIndex:
    """Keyword search over cached registry records; no network call (FR-M5-9: no live search with patient text)."""

    def __init__(self, records: Iterable[RegistryRecord]) -> None:
        self.records = sorted(records, key=lambda r: r.nct_id)

    @classmethod
    def from_ctgov_dir(cls, directory: Path) -> LocalRegistryIndex:
        out: list[RegistryRecord] = []
        for p in sorted(directory.glob("ctgov_*.json")):
            doc = json.loads(p.read_text(encoding="utf-8"))
            study = dict(doc.get("study") or doc)
            study.setdefault("nct_id", doc.get("nct_id"))
            rec = _record(study)
            if rec is not None:
                out.append(rec)
        return cls(out)

    def search(self, query: str, limit: int) -> list[RegistryRecord]:
        terms = [t for t in re.split(r"\W+", query.lower()) if t]
        if not terms:
            return []
        hits = []
        for r in self.records:
            hay = " ".join([r.nct_id, r.title, *r.conditions]).lower()
            if all(t in hay for t in terms):
                hits.append(r)
        return hits[:limit]


# ------------------------------------------------------------------------------------------------ protocol answers
ProtocolSections = Callable[[str], tuple[str, Sequence[tuple[str, str]]]]  # study -> (data class, [(section, text)])


class GatewayProtocolAnswerer:
    """``answer_protocol`` (role table §8.15) through the gateway as caller ``frontdoor-mcp``. The protocol text is
    D1 for a site protocol and D0 for a public one; the label comes from the section source, never inferred."""

    def __init__(self, client: GatewayClient, sections: ProtocolSections, prompt_id: str = "answer_protocol") -> None:
        self.client = client
        self.sections = sections
        self.prompt = load_prompt(prompt_id)

    def answer(self, study: str, question: str) -> AskProtocolOut:
        data_class, secs = self.sections(study)
        if not secs:
            return AskProtocolOut(answer=None, citations=[], not_stated=True)
        schema = AskProtocolOut.model_json_schema()
        msgs = render(self.prompt, {"study": study, "question": question, "sections": [list(s) for s in secs]})
        labels = CallLabels(
            data_class=data_class,
            purpose="intake",
            study_id=study,
            context_of_use="protocol_qa",
            role="answer_protocol",
            prompt=f"{self.prompt.meta.id}@{self.prompt.meta.version}",
        )
        res = self.client.chat(msgs, labels, response_format=json_schema_format("answer_protocol", schema))
        out = AskProtocolOut.model_validate(res.data)
        known = {s for s, _ in secs}
        citations = [c for c in out.citations if c in known]  # a citation must name a real section
        if out.answer is None or not citations:
            return AskProtocolOut(answer=None, citations=[], not_stated=True)
        return AskProtocolOut(answer=out.answer, citations=citations, not_stated=False)


# ------------------------------------------------------------------------------------------------ static read models
@dataclass
class StaticAtlas:
    snapshot: str | None
    rows: list[AtlasRow]

    def describe(self, domain: str | None) -> tuple[str | None, list[AtlasRow]]:
        return self.snapshot, [r for r in self.rows if domain is None or r.domain == domain]


@dataclass
class StaticAggregates:
    data_cut: str
    table: dict[tuple[str, str | None, str | None], dict[str, int]]

    def counts(self, metric: str, breakdown: str | None, study: str | None) -> tuple[str, dict[str, int]]:
        return self.data_cut, dict(self.table.get((metric, breakdown, study), {}))


@dataclass
class StaticOps:
    panels: dict[str, list[OpsRow]]

    def read(self, panel: OpsPanel) -> list[OpsRow]:
        return list(self.panels.get(panel, []))
