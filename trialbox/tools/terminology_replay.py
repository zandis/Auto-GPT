"""Mapping calls and unmapped criteria, counted offline from a run's stored model calls (card 9h-2, D-1350).

    python -m tools.terminology_coverage <raw-traces.json> --model-calls [--synonyms] [--set NAME] [--json]
    python -m tools.terminology_coverage <raw-traces.json> --replay [--answers answers.json] [--set NAME] [--json]

No model, no network: the file is read as JSON and never run. Imported by ``tools.terminology_coverage``, which puts
``libs`` and ``services`` on the path. ``--set`` picks one set of a replay slice
(``{"sets": {name: {"traces": [...]}}}``, ``tests/fixtures/public_accuracy_p1b/replay_slice.json``).

**Study isolation.** Every record is keyed by its study (``tb.study_id``). A record with a missing or empty study id
is never pooled with a study's records and never answers anything: it is counted in its own bucket
(``no_study_id``). A study's ``concept_map`` replies answer only that study's calls.

**What is counted.**

* ``recorded``: every stored ``concept_map`` record (``tb.prompt`` ``concept_map@*``, or ``tb.role`` ``concept_map``
  or ``concept_select`` alone) lands in exactly one bucket: its study or ``no_study_id``; and in exactly one outcome:
  ``mapped`` (a reply the model client accepts, with a code), ``unmapped`` (accepted, no code) or ``invalid`` (no
  output, or one the client refuses: not JSON, or not the schema). Impossible counts are refused (:func:`check`).
* ``simulated`` (``--model-calls``): each concept the study's accepted ``ir_extract`` replies drafted (demographic
  ones left out) is mapped by today's ``Terminology.map`` with a stand-in for the model. The stand-in counts each
  call by domain and answers it only from a recorded reply of the same study to the same call: the same concept, domain
  and candidate codes (system and code). One reply answers one call. A call with no such reply is ``not_recorded``
  and gets no code.
* ``replay`` (``--replay``): each study compiled again by the compiler's own entry point
  (``tools.public_accuracy.rerun.recompile``) with a model that answers from that study's accepted replies only,
  and its criteria flagged ``concept_unmapped`` counted. A study with any call not recorded, or not compiled, has an
  unknown count (``null``), and so has the total. With ``--answers`` the run's own stored count (its
  ``answers.json`` drafts) is given beside it: the figure as the run made it, not as today's code makes it.

A reply is read as the model client reads it (``tb_common.llm``: a fenced block allowed, null as absent, the
prompt's schema), and a call's inputs from its first user message (a schema-repair retry appends a correction after
it).
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from tb_common.llm import _extract_json, no_sentinel_date
from tb_contracts import LlmConceptMapOutput, LlmExtractOutput
from tb_contracts.schema import load_schema, null_absent, schema_errors

from tools.public_accuracy import rerun

EXTRACT = ("ir_extract", "extract_criteria")  # extract_criteria: older traces named the step by role alone
MAP = ("concept_map", "concept_select")
OUTCOMES = ("mapped", "unmapped", "invalid")


def load(path: Path, set_name: str | None = None) -> list[dict[str, Any]]:
    """The records of a ``raw-traces.json``, or of one set of a replay slice."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(doc, dict) and "sets" in doc:
        if set_name not in (doc.get("sets") or {}):
            raise ValueError(f"{path.name} holds sets {sorted(doc.get('sets') or {})}: name one with --set")
        doc = doc["sets"][set_name]
    traces = doc.get("traces") if isinstance(doc, dict) else None
    if not isinstance(traces, list):
        raise ValueError(f"{path.name} holds no list of traces")
    return [r for r in traces if isinstance(r, dict)]


def step(rec: dict[str, Any]) -> str | None:
    """``extract``, ``map`` or None (another step)."""
    attrs = rec.get("attributes") or {}
    name = str(attrs.get("tb.prompt") or "").split("@")[0] or str(attrs.get("tb.role") or "")
    return "extract" if name in EXTRACT else "map" if name in MAP else None


def study(rec: dict[str, Any]) -> str | None:
    """The record's study id; None when it is missing or empty (never a study's)."""
    return str((rec.get("attributes") or {}).get("tb.study_id") or "").strip() or None


def inputs(rec: dict[str, Any], key: str) -> dict[str, Any] | None:
    """The call's input block: the first user message whose fenced JSON holds ``key``."""
    for m in rec.get("prompt") or []:
        if isinstance(m, dict) and m.get("role", "user") == "user":
            v = rerun._json_block(str(m.get("content") or ""))
            if v is not None and key in v:
                return v
    return None


def _accepted(rec: dict[str, Any], schema: str) -> dict[str, Any] | None:
    """The reply as the model client accepts it (``LlmClient.chat_json``), or None."""
    out = rec.get("output")
    if not isinstance(out, str):
        return None
    try:
        data = null_absent(load_schema(schema), _extract_json(out))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    data = no_sentinel_date(data)
    return None if schema_errors(schema, data) else data


def map_reply(rec: dict[str, Any]) -> LlmConceptMapOutput | None:
    data = _accepted(rec, "llm_concept_map_output")
    try:
        return None if data is None else LlmConceptMapOutput.model_validate(data)
    except ValidationError:
        return None


def extract_reply(rec: dict[str, Any]) -> LlmExtractOutput | None:
    data = _accepted(rec, "llm_extract_output")
    try:
        return None if data is None else LlmExtractOutput.model_validate(data)
    except ValidationError:
        return None


def _key(concept: Any, domain: Any, candidates: Any) -> tuple[str, str, frozenset[tuple[str, str]]]:
    codes = frozenset((str(c.get("system")), str(c.get("code"))) for c in candidates or [] if isinstance(c, dict))
    return rerun.norm(concept), str(domain or ""), codes


class StudyReplies:
    """One study's accepted ``concept_map`` replies. A call is answered only by a reply to the same call (concept,
    domain, candidate codes); each reply answers one call, in recorded order."""

    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.left: dict[tuple[str, str, frozenset[tuple[str, str]]], list[LlmConceptMapOutput]] = defaultdict(list)
        for rec in records:
            v, reply = inputs(rec, "concept"), map_reply(rec)
            if v is not None and reply is not None:
                self.left[_key(v.get("concept"), v.get("domain"), v.get("candidates"))].append(reply)
        self.calls: Counter[str] = Counter()
        self.not_recorded: Counter[str] = Counter()

    def take(self, concept: str, domain: str, candidates: list[dict[str, Any]]) -> LlmConceptMapOutput | None:
        self.calls[domain] += 1
        replies = self.left.get(_key(concept, domain, candidates))
        if not replies:
            self.not_recorded[domain] += 1
            return None
        return replies.pop(0)

    def __call__(self, name: str, domain: str, cands: list[Any]) -> tuple[list[tuple[str, str, float]], bool]:
        """The mapper's model hook (``ConceptMapLLM``), as ``Compiler._concept_map`` reads a reply."""
        reply = self.take(name, domain, [{"system": c.system, "code": c.code} for c in cands])
        if reply is None:
            return [], True
        choices = [(c.code, c.system, c.confidence) for c in reply.choices]
        return choices, reply.needs_review or len(choices) > 1 or any(c[2] < 0.9 for c in choices)


@dataclass
class Records:
    by_study: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    no_study: list[dict[str, Any]] = field(default_factory=list)

    def of(self, sid: str, kind: str) -> list[dict[str, Any]]:
        return [r for r in self.by_study.get(sid, []) if step(r) == kind]


def split(traces: list[dict[str, Any]]) -> Records:
    """The extraction and mapping records, by study; those without a study id apart."""
    out = Records()
    for rec in sorted(traces, key=lambda r: str(r.get("ts") or "")):
        if step(rec) is None:
            continue
        sid = study(rec)
        if sid is None:
            out.no_study.append(rec)
        else:
            out.by_study.setdefault(sid, []).append(rec)
    return out


def _bucket(records: list[dict[str, Any]]) -> dict[str, Any]:
    row: dict[str, Any] = {"calls": 0, **dict.fromkeys(OUTCOMES, 0), "by_domain": {}}
    for rec in records:
        if step(rec) != "map":
            continue
        reply = map_reply(rec)
        outcome = "invalid" if reply is None else "mapped" if reply.choices else "unmapped"
        domain = str((inputs(rec, "concept") or {}).get("domain") or "") or "unknown"
        row["calls"] += 1
        row[outcome] += 1
        row["by_domain"][domain] = row["by_domain"].get(domain, 0) + 1
    return row


def recorded(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Every stored ``concept_map`` record, once: by study (or ``no_study_id``) and outcome."""
    recs = split(traces)
    result: dict[str, Any] = {
        "records": sum(1 for r in traces if step(r) == "map"),
        "by_study": {sid: _bucket(rs) for sid, rs in sorted(recs.by_study.items())},
        "no_study_id": _bucket(recs.no_study),
    }
    rows = [*result["by_study"].values(), result["no_study_id"]]
    total: dict[str, Any] = {k: sum(r[k] for r in rows) for k in ("calls", *OUTCOMES)}
    total["by_domain"] = dict(sum((Counter(r["by_domain"]) for r in rows), Counter()))
    result["total"] = total
    check(result)
    return result


def check(result: dict[str, Any]) -> None:
    """Refuse impossible counts: each bucket's outcomes and domains add up to its calls, the buckets add up to the
    total, and the total is the number of records."""
    rows = {**result["by_study"], "no_study_id": result["no_study_id"]}
    for name, r in rows.items():
        values = [r["calls"], *(r[k] for k in OUTCOMES), *r["by_domain"].values()]
        if any(not isinstance(v, int) or v < 0 for v in values):
            raise ValueError(f"impossible count in {name}: {r}")
        if sum(r[k] for k in OUTCOMES) != r["calls"] or sum(r["by_domain"].values()) != r["calls"]:
            raise ValueError(f"the outcomes or domains of {name} do not add up to its {r['calls']} calls")
    for k in ("calls", *OUTCOMES):
        if sum(r[k] for r in rows.values()) != result["total"][k]:
            raise ValueError(f"the buckets' {k} do not add up to the total {result['total'][k]}")
    if result["total"]["calls"] != result["records"]:
        raise ValueError(f"{result['total']['calls']} calls counted for {result['records']} records")


def model_calls(traces: list[dict[str, Any]], term: Any, synonyms: bool = False) -> dict[str, Any]:
    """``recorded`` and, per study, the calls today's mapper makes on the drafted concepts (``simulated``)."""
    recs = split(traces)
    studies: dict[str, Any] = {}
    for sid in sorted(recs.by_study):
        replies = StudyReplies(recs.of(sid, "map"))
        row: dict[str, Any] = {"extract_records": 0, "extract_invalid": 0, "drafted": 0, "resolved": 0}
        for rec in recs.of(sid, "extract"):
            row["extract_records"] += 1
            out = extract_reply(rec)
            if out is None:
                row["extract_invalid"] += 1
                continue
            for crit in out.criteria:
                for cand in crit.concept_candidates:
                    if cand.domain == "demographic":
                        continue
                    row["drafted"] += 1
                    syn = list(cand.synonyms or []) if synonyms else None
                    row["resolved"] += bool(term.map(cand.domain, cand.name, syn, llm=replies).concepts)
        row["calls"], row["not_recorded"] = sum(replies.calls.values()), sum(replies.not_recorded.values())
        row["calls_by_domain"] = dict(replies.calls)
        studies[sid] = row
    keys = ("extract_records", "extract_invalid", "drafted", "resolved", "calls", "not_recorded")
    total: dict[str, Any] = {k: sum(s[k] for s in studies.values()) for k in keys}
    total["calls_by_domain"] = dict(sum((Counter(s["calls_by_domain"]) for s in studies.values()), Counter()))
    no_study = [r for r in recs.no_study if step(r) == "extract"]
    return {
        "recorded": recorded(traces),
        "simulated": {
            "by_study": studies,
            "total": total,
            "no_study_id": {"extract_records": len(no_study), "mapped": 0},  # never mapped, never answers
        },
    }


class StudyReplayModel(rerun.ReplayModel):
    """The model of a re-compile of one study: its accepted ``ir_extract`` and ``concept_map`` replies only."""

    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.asked: set[tuple[str, str]] = set()
        self.answers: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for rec in records:
            if step(rec) != "extract":
                continue
            out = extract_reply(rec)
            if out is None:
                continue  # a refused attempt neither asks nor answers; its retry does
            for ln in (inputs(rec, "criteria") or {}).get("criteria") or []:
                if isinstance(ln, dict):
                    self.asked.add((str(ln.get("kind")), rerun.norm(ln.get("text"))))
            got: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
            for c in out.criteria:
                got[(c.kind, rerun.norm(c.text))].append(c.model_dump(by_alias=True, exclude_none=True))
            for k, cs in got.items():
                self.answers.setdefault(k, cs)  # as rerun.ReplayModel: the first reply stands
        self.replies = StudyReplies([r for r in records if step(r) == "map"])
        self.concepts_not_stored: list[str] = []
        self.calls: Counter[str] = Counter()

    def chat_json(self, prompt_id: str, variables: dict[str, Any], schema: str | None = None, **kw: Any) -> Any:
        if prompt_id != "concept_map":
            return super().chat_json(prompt_id, variables, schema, **kw)
        from tb_common.llm import LlmResult

        self.calls[prompt_id] += 1
        reply = self.replies.take(
            str(variables.get("concept")), str(variables.get("domain") or ""), list(variables.get("candidates") or [])
        )
        if reply is None:
            self.concepts_not_stored.append(str(variables.get("concept")))
            reply = LlmConceptMapOutput(choices=[], needs_review=True)
        return LlmResult(
            data=reply.model_dump(),
            prompt_id=prompt_id,
            prompt_version=0,
            model="stored-run",
            target="local",
            input_sha="",
            output_sha="",
            tokens_in=0,
            tokens_out=0,
            attempts=1,
        )


def _drafts(answer: Any) -> list[dict[str, Any]]:
    return [c for c in (answer.get("draft") or []) if isinstance(c, dict)] if isinstance(answer, dict) else []


def stored_unmapped(answers: dict[str, Any]) -> dict[str, int]:
    """By ruleset (upper case, as the compiler writes it), the run's own drafts flagged ``concept_unmapped``
    (``answers.json``)."""
    return {
        str(rs).upper(): sum("concept_unmapped" in (c.get("flags") or []) for c in _drafts(a))
        for rs, a in answers.items()
    }


def replay(
    traces: list[dict[str, Any]],
    answers: dict[str, Any] | None = None,
    index_date: date = date(2026, 11, 17),
    tz: str = "UTC",
) -> dict[str, Any]:
    """Each study compiled again on today's code from its own replies; its ``concept_unmapped`` criteria counted."""
    recs = split(traces)
    stored_counts = stored_unmapped(answers) if answers is not None else {}
    studies: dict[str, Any] = {}
    for sid in sorted(recs.by_study):
        if not recs.of(sid, "extract"):
            continue
        stored = rerun.Stored(by_job={sid: recs.by_study[sid]})
        model = StudyReplayModel(recs.by_study[sid])
        r = rerun.recompile(stored, sid, index_date, tz, model=model)
        flagged = sum("concept_unmapped" in (getattr(c, "flags", None) or []) for c in r.criteria)
        known = r.status == "compiled" and not r.concepts_not_stored
        studies[sid] = {
            "ruleset": r.ruleset,
            "status": r.status,
            "criteria": len(r.criteria),
            "not_recorded": len(model.concepts_not_stored),
            "concept_unmapped": flagged if known else None,
            "stored_concept_unmapped": stored_counts.get(r.ruleset.upper()),
        }
    counts = [s["concept_unmapped"] for s in studies.values()]
    return {
        "by_study": studies,
        "concept_unmapped": None if not counts or None in counts else sum(counts),
        "stored_concept_unmapped": sum(stored_counts.values()) if answers is not None else None,
        "no_study_id": {"records": len(recs.no_study), "compiled": 0},
    }
