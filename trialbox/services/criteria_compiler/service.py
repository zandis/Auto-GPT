"""criteria-compiler orchestration: ``compile`` / ``diff`` / ``approve`` (SPEC §4.3, §5 approval loop, §6.4 gate)."""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import yaml
from lake.client import LakeAPI
from tb_common.audit import AuditLog
from tb_common.config import site_tz
from tb_common.derived import country_of, egfr_for_site
from tb_common.fhir import FhirEvalError, FhirEvaluator, library_resource, server_said
from tb_common.http import ServiceError
from tb_common.llm import LlmClient, LlmError, LlmUpstreamFailed
from tb_common.objstore import ObjectStore
from tb_common.phi_guard import PhiScan, scan, variables_text
from tb_common.ruleset import Ruleset
from tb_contracts import (
    ApproveRequest,
    ApproveResult,
    CompileRequest,
    CompileResult,
    CriterionIR,
    CriterionReview,
    CtgovSearchRequest,
    CtgovSearchResult,
    DiffRequest,
    DiffResult,
    EquivalenceReport,
    LlmConceptMapOutput,
    LlmExtractOutput,
    ParsedDoc,
    RulesetManifest,
    dump,
)

from criteria_compiler import structure
from criteria_compiler.compile_cql.generator import CqlGenerator, render_common
from criteria_compiler.compile_cql.translator import TranslationError, Translator, fhirhelpers_source
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.ctgov import CtGov, CtgovError
from criteria_compiler.equivalence.gate import run_gate, unproven, without_pseudonyms
from criteria_compiler.ir_extract.postprocess import KIND_CODE, postprocess
from criteria_compiler.repo import RulesetRepo
from criteria_compiler.review import draft_zip, json_bytes, review_html, review_xlsx
from criteria_compiler.semantics import FILTERED, CompileError, atoms, class_split, compiled
from criteria_compiler.terminology.mapper import Concept, Terminology, ValueSets

log = logging.getLogger("criteria-compiler")
MAX_ROUNDS = 3
EquivalenceFn = Callable[[list[CriterionIR], str, str, date, str], EquivalenceReport]


def align(lines: list[dict[str, Any]], answers: list[Any]) -> tuple[list[Any], set[int]]:
    """Each answer matched to its line (D-912), by the line's text, in order: ``(matched, twice)``. ``matched[k]`` is
    line k's answer or None; ``twice`` holds the lines the model answered more than once (it split the line). An
    answer whose text is no line's, the model's own wording, is matched by position when the counts agree, else left
    out (its line is asked again)."""
    if len(answers) == len(lines) and all(
        _norm(str(getattr(a, "text", ""))) == _norm(str(ln["text"])) for a, ln in zip(answers, lines, strict=True)
    ):
        return list(answers), set()
    by_text: dict[str, list[int]] = {}
    for k, ln in enumerate(lines):
        by_text.setdefault(_norm(str(ln["text"])), []).append(k)
    matched: list[Any] = [None] * len(lines)
    seen: dict[int, int] = {}
    unplaced = 0
    for a in answers:
        ks = by_text.get(_norm(str(getattr(a, "text", ""))), [])
        free = [k for k in ks if matched[k] is None]
        if free:
            matched[free[0]] = a
            seen[free[0]] = 1
        elif ks:
            seen[ks[-1]] = seen.get(ks[-1], 1) + 1
        else:
            unplaced += 1
    if unplaced and len(answers) == len(lines):  # reworded, not miscounted: by position
        return list(answers), set()
    return matched, {k for k, n in seen.items() if n > 1}


def _for_a_person(line: dict[str, Any], why: str) -> dict[str, Any]:
    """A line the model gave no criterion of its own (D-912), kept as a person's check with its text and kind."""
    said = {
        "not_extracted": "The model gave no criterion for this line",
        "split_by_model": "The model answered this line with more than one criterion",
    }[why]
    out: dict[str, Any] = {
        "kind": line["kind"],
        "class": "human",
        "text": line["text"],
        "human_question": f"{said}: check it by hand. {line['text']}",
        "concept_candidates": [],
    }
    if line.get("source_ref"):
        out["source_ref"] = line["source_ref"]
    return out


#: the answer tokens one extracted criterion takes at most, with its concept candidates and synonyms (measured on the
#: shipped rulesets' compiles: 150 to 330); a part is sized so its answer fits the prompt's ``max_tokens`` (D-911)
TOKENS_PER_CRITERION = 400
ANSWER_SHARE = 0.75  # of max_tokens: room for the JSON's own frame and a long line


#: G4 of the P1b review: the answer tokens a model writes per second while it extracts, for sizing a part by time
#: (``TB_EXTRACT_RATE_PER_S``); a guess until it is measured on the box's GPU, kept low on purpose
EXTRACT_TOKENS_PER_S = 40.0
TIME_SHARE = 0.6  # of the gateway's read timeout: room for the prompt's own reading and a slow moment


def lines_per_part(max_tokens: int | None = None, read_s: float | None = None) -> int:
    """How many protocol lines one ``ir_extract`` call carries (D-911): its answer must fit the prompt's cap, and
    (G4 of the P1b review) it must be written within the gateway's read timeout (``TB_GATEWAY_UPSTREAM_READ_S``,
    180 s): parts of 15 lines ran past it on four protocols, which failed whole."""
    from tb_common.llm import load_prompt

    cap = max_tokens if max_tokens is not None else int(load_prompt("ir_extract").meta.max_tokens or 8192)
    by_tokens = int(cap * ANSWER_SHARE) // TOKENS_PER_CRITERION
    read = read_s if read_s is not None else float(os.environ.get("TB_GATEWAY_UPSTREAM_READ_S") or 180)
    rate = float(os.environ.get("TB_EXTRACT_RATE_PER_S") or EXTRACT_TOKENS_PER_S)
    by_time = int(read * rate * TIME_SHARE) // TOKENS_PER_CRITERION
    return max(1, min(by_tokens, by_time))


MAX_HALVINGS = 2


def extraction_parts(lines: list[dict[str, Any]], size: int) -> list[tuple[int, list[dict[str, Any]]]]:
    """``lines`` as ``(first index, lines)`` parts of at most ``size`` lines (D-911). A line and the lines under it
    (``parent``) stay in one part, whatever its size; a part ends at a section boundary (``kind``) when the next group
    would not fit or the section changes and the part is at least half full. Each part's ``parent`` is rebased."""
    groups: list[list[int]] = []  # contiguous runs of lines: a parent, the lines under it, and any lines between
    owner: dict[int, int] = {}
    for i, ln in enumerate(lines):
        p = ln.get("parent")
        if isinstance(p, int) and p in owner:
            g = owner[p]
            if g < len(groups) - 1:  # a line under an earlier parent: that group runs on to here
                for later in groups[g + 1 :]:
                    groups[g].extend(later)
                del groups[g + 1 :]
                owner.update({j: g for j in groups[g]})
        else:
            groups.append([])
            g = len(groups) - 1
        groups[g].append(i)
        owner[i] = g
    parts: list[list[int]] = []
    cur: list[int] = []
    for group in groups:
        boundary = bool(cur) and lines[cur[-1]].get("kind") != lines[group[0]].get("kind")
        if cur and (len(cur) + len(group) > size or (boundary and len(cur) >= size // 2)):
            parts.append(cur)
            cur = []
        cur.extend(group)
    if cur:
        parts.append(cur)
    out: list[tuple[int, list[dict[str, Any]]]] = []
    for idx in parts:
        start = idx[0]
        rebased = []
        for i in idx:
            ln = dict(lines[i])
            if isinstance(ln.get("parent"), int):
                ln["parent"] = ln["parent"] - start
            rebased.append(ln)
        out.append((start, rebased))
    return out


def flag_unread(criteria: list[CriterionIR], unread: dict[int, str], warnings: list[str]) -> list[CriterionIR]:
    """The criteria of the lines the model gave no criterion of their own (D-912), flagged for the reviewer."""
    out = list(criteria)
    for i, why in sorted(unread.items()):
        c = out[i]
        out[i] = c.model_copy(update={"flags": sorted(set(c.flags or []) | {why, "needs_review"})})
        warnings.append(f"{c.id}: {why.replace('_', ' ')}; kept for a person to check")
    return out


class CompileFailed(RuntimeError):
    def __init__(self, step: str, message: str) -> None:
        super().__init__(f"{step}: {message}")
        self.step = step


def approval_pins(
    manifest: RulesetManifest, criteria: Sequence[CriterionIR] = (), environment: str | None = None
) -> dict[str, Any]:
    """The prompts an approval pins (D-318): the registry's current version of the judge prompt with its text and
    schema shas, and ``models.judge_prompt`` naming that version, so SCREEN runs what the investigator approved.
    D-442: and ``derived_pins``, the score definitions the active criteria follow (:func:`tb_common.scores.pins`).

    The current version is the one served where the box's model calls are checked: this process's ``TB_ENV``, or
    ``environment`` (``CompilerDeps.prompt_environment``) when the box's gateway runs as another one. A PRODUCTION
    gateway serves the newest *qualified* version (D-359); an approval that pinned a newer one still waiting for its
    record would pin a prompt that gateway refuses on every note call (G1 rehearsal, 2026-11-12)."""
    from tb_common.scores import pins as derived_pins
    from tb_llm.prompt_registry import PromptRegistryError, default_registry

    models = dump(manifest.models) if manifest.models else {}
    pid = str(models.get("judge_prompt") or "judge").rsplit("_v", 1)[0]
    try:
        pins = default_registry().pins({pid: None}, environment or None)  # "" names no environment
    except PromptRegistryError as exc:
        raise CompileFailed("approve", f"the judge prompt cannot be pinned ({exc.reason}): {exc}") from exc
    out: dict[str, Any] = {"models": {**models, "judge_prompt": f"{pid}_v{pins[pid]['version']}"}, "prompt_pins": pins}
    dpins = derived_pins(a.derived for c in compiled(list(criteria)) for a in atoms(c.logic) if a.derived)
    if dpins:
        out["derived_pins"] = dpins
    return out


def amendment_record(req: ApproveRequest, today: date) -> dict[str, Any]:
    """D-364 (LIFE-009): when the approved version starts to screen and which IRB approval it rests on. The effective
    date is the approver's; none given = in force from the approval (``review.approved_at``). It is never before the
    approval day, so a version cannot reach back over lists already sent. The IRB number and date are a record printed
    with the approval, not a gate (D-311): an empty one is allowed. A field of the version before is never carried
    over: each version states its own record or none."""
    out: dict[str, Any] = {"effective_from": None, "irb_reference": None, "irb_approved_on": None}
    if req.effective_from is not None:
        if req.effective_from < today:
            raise CompileFailed("approve", f"the effective date {req.effective_from} is before the approval {today}")
        out["effective_from"] = req.effective_from.isoformat()
    if req.irb_reference and req.irb_reference.strip():
        out["irb_reference"] = req.irb_reference.strip()
    if req.irb_approved_on is not None:
        if req.irb_approved_on > today:
            raise CompileFailed("approve", f"the IRB approval date {req.irb_approved_on} is after today {today}")
        out["irb_approved_on"] = req.irb_approved_on.isoformat()
    return out


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip().lower()


@dataclass
class Artifacts:
    cql: dict[str, str]
    elm: dict[str, str]
    sql: str
    library: str
    library_version: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class CompilerDeps:
    store: ObjectStore
    repo: RulesetRepo
    llm: LlmClient
    term: Terminology
    settings_thresholds: dict[str, float]
    tz: str = ""  # the site's zone; empty: TB_TZ (D-315), never a default
    mrn_regex: str | None = None
    lake: LakeAPI | None = None
    fhir: FhirEvaluator | None = None
    translator: Translator | None = None
    audit: AuditLog | None = None
    judge_model: str = ""
    equivalence: EquivalenceFn | None = None  # override for tests
    ctgov: CtGov | None = None  # ClinicalTrials.gov client (COHORT trial simulation); default from TB_CTGOV_MODE
    # what a plain "eGFR" criterion becomes at this site (D-149); None: from the site's time zone (JP: JSN 2009)
    egfr_equation: str | None = None
    # the environment (TB_ENV value) of the model gateway this box's note calls go through, when it is not this
    # process's own: a run harness in front of an installed box's gateway (tools.scenarios). An approval pins the
    # judge prompt that environment serves (approval_pins). None: this process's TB_ENV, as on every installed box
    prompt_environment: str | None = None

    def __post_init__(self) -> None:
        self.tz = site_tz(self.tz or None)

    def egfr(self) -> str:
        if self.egfr_equation:
            return self.egfr_equation
        site = egfr_for_site(country_of(self.tz))
        return "egfr" if site == "egfr_ckd_epi" else site  # a plain egfr already means CKD-EPI 2021


class Compiler:
    def __init__(self, deps: CompilerDeps) -> None:
        self.d = deps

    def ctgov_search(self, req: CtgovSearchRequest) -> CtgovSearchResult:
        """Recruiting studies for COHORT trial simulation (public registry data; no PHI is sent)."""
        client = self.d.ctgov or CtGov()
        try:
            res = client.search(req)
        except CtgovError as exc:
            raise CompileFailed("ctgov", str(exc)) from exc
        self._audit(
            "ctgov.search",
            detail={"condition": req.condition, "source": res.source, "studies": [s.nct_id for s in res.studies]},
        )
        return res

    # ------------------------------------------------------------------ helpers
    def _audit(self, event: str, **kw: Any) -> None:
        if self.d.audit is not None:
            kw.setdefault("actor", "criteria-compiler")
            self.d.audit.append(event, **kw)

    def _today(self) -> date:
        return datetime.now(ZoneInfo(self.d.tz)).date()

    def _profile(self, ruleset: str) -> dict[str, Any]:
        raw = self.d.repo.read("main", f"profiles/{ruleset}.yaml")
        return yaml.safe_load(raw.decode("utf-8")) if raw else {}

    def _approved(self, ruleset: str) -> Ruleset | None:
        files = {p[len(ruleset) + 1 :]: b for p, b in self.d.repo.files("main", f"{ruleset}/").items()}
        if "manifest.yaml" not in files:
            return None
        rs = Ruleset.from_files(files)
        return rs if rs.manifest.status == "approved" else None

    def _next_version(self, ruleset: str, requested: str | None) -> str:
        if requested:
            return requested
        tags = [t.split("/v", 1)[1] for t in self.d.repo.tags(f"{ruleset}/v")]
        if not tags:
            return "1.0.0"
        major, minor, _ = max(tuple(int(x) for x in t.split(".")) for t in tags)
        return f"{major}.{minor + 1}.0"

    def _concept_map(
        self, job_id: str
    ) -> Callable[[str, str, list[Concept]], tuple[list[tuple[str, str, float]], bool]]:
        def fn(name: str, domain: str, cands: list[Concept]) -> tuple[list[tuple[str, str, float]], bool]:
            variables = {
                "concept": name,
                "domain": domain,
                "candidates": [{"code": c.code, "system": c.system, "display": c.display} for c in cands],
            }
            guard = scan(variables_text(variables), self.d.mrn_regex)
            try:
                res = self.d.llm.chat_json(
                    "concept_map", variables, job_id=job_id, clearance=guard.clearance, phi_guard_hit=guard.hit
                )
            except LlmError as exc:  # as ir_extract: the requester's Failed mail names the step, not "internal error"
                raise CompileFailed(
                    "concept_map", f"the model did not map {name!r} ({str(exc)[:160]}); send the protocol again"
                ) from exc
            out = LlmConceptMapOutput.model_validate(res.data)
            choices = [(c.code, c.system, c.confidence) for c in out.choices]
            return choices, out.needs_review or len(choices) > 1 or any(c[2] < 0.9 for c in choices)

        return fn

    def _extract(
        self, job_id: str, ruleset: str, language: str, lines: list[dict[str, Any]]
    ) -> tuple[LlmExtractOutput, PhiScan, dict[int, str]]:
        """The model's criteria for ``lines``, one per line in order, asked in parts (D-911): one call answered a whole
        protocol, and a long one ran past the prompt's answer cap (``max_tokens``), so its JSON was cut and the
        gateway refused it (``upstream_failed``). Each part holds at most :func:`lines_per_part` lines, split at a
        section boundary where it can be, a line never apart from the lines under it.

        D-912: an answer with another count of criteria than lines was a hard refusal of the whole compile. Each
        answer is now matched to its line by the line's text (the prompt has the model copy it verbatim); the lines
        left without one are asked once more, alone; a line still without one, or one the
        model answered twice, is a person's check. Nothing is dropped or merged in silence: the third value names
        those lines (index -> ``not_extracted`` or ``split_by_model``) for the caller to flag."""
        variables = {"ruleset": ruleset, "language": language, "criteria": lines}
        guard = scan(variables_text(variables), self.d.mrn_regex)  # exactly what the prompts carry (cloud routing)
        got: list[Any] = [None] * len(lines)
        notes: dict[int, str] = {}
        parts = extraction_parts(lines, lines_per_part())
        for n, (start, part) in enumerate(parts, start=1):
            where = f" (part {n} of {len(parts)}, lines {start + 1}-{start + len(part)})" if len(parts) > 1 else ""
            answers = self._ask_in_halves(job_id, ruleset, language, part, guard, where)
            matched, twice = align(part, answers)
            missing = [k for k, c in enumerate(matched) if c is None and k not in twice]
            if missing:  # once more, the lines without an answer alone (naming the mismatch to the model would
                # need a new prompt version: the template shows the lines only, and the lines are data to it)
                retry = [{**part[k], "parent": None} for k in missing]
                again, _ = align(retry, self._ask_extract(job_id, ruleset, language, retry, guard, where))
                for k, c in zip(missing, again, strict=True):
                    matched[k] = c
            for k, c in enumerate(matched):
                i = start + k
                if k in twice:
                    notes[i] = "split_by_model"
                elif c is None:
                    notes[i] = "not_extracted"
                got[i] = c if c is not None and k not in twice else _for_a_person(lines[i], notes[i])
        out = LlmExtractOutput.model_validate({"criteria": [c if isinstance(c, dict) else dump(c) for c in got]})
        return out, guard, notes

    def _ask_in_halves(
        self,
        job_id: str,
        ruleset: str,
        language: str,
        part: list[dict[str, Any]],
        guard: PhiScan,
        where: str,
        depth: int = 0,
    ) -> list[Any]:
        """G4 of the P1b review (D-981): a part the gateway gave up on (``LlmUpstreamFailed``) is asked again as two
        halves, each a smaller answer, at most :data:`MAX_HALVINGS` times deep; any other failure, or a single line,
        fails as before. The halves are cut where :func:`extraction_parts` would cut (a line never apart from the
        lines under it); the answers are matched to their lines by text afterwards (D-912)."""
        try:
            return self._ask_extract(job_id, ruleset, language, part, guard, where)
        except CompileFailed as exc:
            # by the cause's type (D-651: never its text): the gateway gave up on the answer, a shorter one may do
            halves = extraction_parts(part, max(1, (len(part) + 1) // 2)) if len(part) > 1 else []
            if not isinstance(exc.__cause__, LlmUpstreamFailed) or depth >= MAX_HALVINGS or len(halves) < 2:
                raise
            log.warning("ir_extract%s: the gateway gave up on the answer; asking it again in %d parts", where,
                        len(halves))  # fmt: skip
            out: list[Any] = []
            for _, half in halves:
                out.extend(self._ask_in_halves(job_id, ruleset, language, half, guard, where, depth + 1))
            return out

    def _ask_extract(
        self,
        job_id: str,
        ruleset: str,
        language: str,
        part: list[dict[str, Any]],
        guard: PhiScan,
        where: str,
    ) -> list[Any]:
        variables: dict[str, Any] = {"ruleset": ruleset, "language": language, "criteria": part}
        try:
            res = self.d.llm.chat_json(
                "ir_extract", variables, job_id=job_id, clearance=guard.clearance, phi_guard_hit=guard.hit
            )
        except LlmError as exc:  # was an unhandled 500 ("internal error") in the requester's Failed mail
            raise CompileFailed(
                "ir_extract",
                f"the model did not return usable criteria{where} ({str(exc)[:160]}); send the protocol again",
            ) from exc
        return list(LlmExtractOutput.model_validate(res.data).criteria)

    def demote_uncompilable(
        self, ruleset: str, version: str, criteria: list[CriterionIR], valuesets: dict[str, dict[str, Any]]
    ) -> tuple[list[CriterionIR], list[str]]:
        """A structured criterion whose IR cannot be compiled goes to a person instead of failing the whole protocol
        (stress test #24: one model-made demographic atom without age or sex blocked every other criterion). It
        becomes class ``human`` with ``needs_review`` and ``compile_error`` flags; the reviewer edits or accepts it. A
        ``mixed`` criterion keeps its note question and becomes ``note`` (D-98)."""
        vsi = ValueSets(ruleset, valuesets, self.d.term)
        out: list[CriterionIR] = []
        warnings: list[str] = []
        for c in criteria:
            if c.class_ not in FILTERED or (c.review and c.review.status == "rejected"):
                out.append(c)
                continue
            try:
                CqlGenerator(ruleset, version, vsi).render([c])
                SqlGenerator(ruleset, version, vsi).render([c])
            except CompileError as exc:
                flags = sorted(set(c.flags or []) | {"needs_review", "compile_error"})
                if c.class_ == "mixed":
                    out.append(c.model_copy(update={"class_": "note", "flags": flags}))
                    warnings.append(f"{c.id}: {exc}; the coded pre-check is dropped, the notes decide it")
                    continue
                question = c.human_question or f"Confirm with the patient/clinician: {c.text}"
                out.append(c.model_copy(update={"class_": "human", "human_question": question, "flags": flags}))
                warnings.append(f"{c.id}: {exc}; moved to human review")
                continue
            out.append(c)
        return out, warnings

    def build_artifacts(
        self,
        ruleset: str,
        version: str,
        criteria: list[CriterionIR],
        valuesets: dict[str, dict[str, Any]],
        lookback: int = 36,
    ) -> Artifacts:
        vsi = ValueSets(ruleset, valuesets, self.d.term)
        active = [c for c in criteria if not (c.review and c.review.status == "rejected")]
        try:
            gen = CqlGenerator(ruleset, version, vsi, lookback)
            cql_text = gen.render(active)
            sql = SqlGenerator(ruleset, version, vsi).render(active)
        except CompileError as exc:
            raise CompileFailed("compile", str(exc)) from exc
        cql = {"FHIRHelpers": "", "TB_Common": render_common(), gen.library: cql_text}
        elm: dict[str, str] = {}
        warnings: list[str] = []
        if self.d.translator is not None:
            try:  # T-501 (LIFE-005): a checkout or image without the translator jars fails by name, not a traceback
                cql["FHIRHelpers"] = fhirhelpers_source()
            except (OSError, KeyError) as exc:
                raise CompileFailed(
                    "cql_translate",
                    "the CQL translator is not installed (FHIRHelpers-4.0.1.cql not found in its jars): "
                    "run `make jvm-deps` or set TB_CQL_TRANSLATOR_LIB",
                ) from exc
            try:
                tr = self.d.translator.translate(cql)
            except TranslationError as exc:
                raise CompileFailed("cql_translate", "; ".join(exc.messages[:5])) from exc
            elm = tr.elm
            warnings.extend(w for w in tr.warnings if not w.startswith("FHIRHelpers"))
        else:
            warnings.append("cql-translator unavailable: ELM not produced (approval blocked)")
        cql.pop("FHIRHelpers", None)
        return Artifacts(cql, elm, sql, gen.library, gen.library_version, warnings)

    def _equivalence(
        self,
        criteria: list[CriterionIR],
        art: Artifacts,
        valuesets: dict[str, dict[str, Any]],
        index_date: date,
        seed: str,
    ) -> EquivalenceReport:
        threshold = float(self.d.settings_thresholds.get("equivalence_min_pct", 98.0))
        active = [c for c in criteria if not (c.review and c.review.status == "rejected")]
        if not compiled(active):
            return EquivalenceReport(overall_pct=100.0, per_criterion={}, failing=[], sample_size=0, engine="none")
        if self.d.equivalence is not None:
            return self.enforce(self.d.equivalence(active, art.sql, art.library, index_date, seed), active)
        if self.d.fhir is None or self.d.lake is None or not art.elm:
            ids = [c.id for c in compiled(active)]
            return EquivalenceReport(
                overall_pct=0.0, per_criterion=dict.fromkeys(ids, 0.0), failing=ids, sample_size=0, engine="unavailable"
            )
        libs = [
            library_resource("FHIRHelpers", "4.0.1", fhirhelpers_source(), art.elm.get("FHIRHelpers")),
            library_resource("TB_Common", "1.0.0", art.cql["TB_Common"], art.elm.get("TB_Common")),
            library_resource(art.library, art.library_version, art.cql[art.library], art.elm.get(art.library)),
        ]
        try:
            self.d.fhir.load(libs, valuesets.values())
            report = run_gate(active, art.sql, art.library, self.d.lake, self.d.fhir, index_date, seed, threshold)
        except (FhirEvalError, ServiceError, httpx.HTTPError) as exc:
            # D-910: the FHIR server refusing a ruleset's CQL or ValueSets, or the lake its SQL, is a reason the
            # equivalence check could not run, said by type and status, not an HTTP 500. G11 (D-959): with what the
            # server said, masked (``server_said``: never a patient's id), in the job's error and the log
            status = getattr(exc, "status", None) or getattr(getattr(exc, "response", None), "status_code", None)
            where = "the FHIR server" if isinstance(exc, FhirEvalError) else "the data lake"
            said = server_said(exc) if isinstance(exc, FhirEvalError) else ""
            log.warning("equivalence of %s could not run: %s refused it: %s", art.library, where,
                        said or type(exc).__name__)  # fmt: skip
            raise CompileFailed(
                "equivalence",
                f"the comparison of the compiled CQL and SQL could not run: {where} refused it "
                f"({type(exc).__name__}{f', HTTP {status}' if status else ''}){f': {said}' if said else ''}; "
                f"check the criteria flagged for review",
            ) from exc
        return self.enforce(report, active)

    @staticmethod
    def enforce(tests: EquivalenceReport, criteria: list[CriterionIR]) -> EquivalenceReport:
        """T-652 (ENG-016): a report that compared no patient, or has no figure for a compiled criterion, never passes
        it, whoever produced the report (the gate, an injected one, or one stored by an earlier version)."""
        active = [c for c in criteria if not (c.review and c.review.status == "rejected")]
        missing = unproven(tests, active)
        if not missing or set(missing) <= set(tests.failing):
            return tests
        per = {**tests.per_criterion, **{cid: tests.per_criterion.get(cid, 0.0) for cid in missing}}
        if tests.sample_size <= 0:
            per.update(dict.fromkeys(missing, 0.0))
        return tests.model_copy(update={"failing": sorted(set(tests.failing) | set(missing)), "per_criterion": per})

    @staticmethod
    def _flag(criteria: list[CriterionIR], tests: EquivalenceReport) -> list[CriterionIR]:
        out = []
        for c in criteria:
            flags = set(c.flags or []) - {"equivalence_fail"}
            if c.id in tests.failing:
                flags |= {"equivalence_fail", "needs_review"}
            elif not (flags - {"needs_review"}):
                flags.discard("needs_review")
            out.append(c.model_copy(update={"flags": sorted(flags) or None}))
        return out

    def _files(
        self,
        manifest: RulesetManifest,
        criteria: list[CriterionIR],
        valuesets: dict[str, dict[str, Any]],
        art: Artifacts,
        tests: EquivalenceReport,
    ) -> dict[str, bytes]:
        files: dict[str, bytes] = {
            "manifest.yaml": yaml.safe_dump(dump(manifest), allow_unicode=True, sort_keys=False).encode("utf-8")
        }
        for c in criteria:
            files[f"ir/{c.id}.json"] = json_bytes(dump(c))
        for name, vs in valuesets.items():
            files[f"valuesets/{name}.json"] = json_bytes(vs)
        for name, text in art.cql.items():
            files[f"cql/{name}.cql"] = text.encode("utf-8")
        for name, text in art.elm.items():
            if name != "FHIRHelpers":
                files[f"cql/elm/{name}.json"] = text.encode("utf-8")
        files[f"sql/{manifest.id}.sql"] = art.sql.encode("utf-8")
        files["tests/equivalence.json"] = json_bytes(dump(without_pseudonyms(tests)))  # D-862: no pseudonym kept
        return files

    def _manifest(
        self,
        ruleset: str,
        version: str,
        kind: str,
        title: str | None,
        criteria: list[CriterionIR],
        profile: dict[str, Any],
        options: dict[str, str],
        requested_by: str,
        sources: list[str],
        language: str,
        library: str,
        base: RulesetManifest | None,
    ) -> RulesetManifest:
        m: dict[str, Any] = dump(base) if base else {}
        m.update({k: v for k, v in profile.items() if k not in ("criteria",)})
        m.update(
            {
                "id": ruleset,
                "kind": profile.get("kind", m.get("kind", kind)),
                "title": title or profile.get("title") or m.get("title") or ruleset,
                "version": version,
                "status": "draft",
                "source_documents": sources,
                "language": language,
                "index_date_rule": m.get("index_date_rule", "run_date"),
                "library": library,
                "criteria": [c.id for c in criteria],
            }
        )
        m.setdefault(
            "scopes",
            {
                "feas": {"population": "hospital", "lookback_months": 36},
                "screen": {"practitioners": [], "appointment_window_days": 180},
                "nav": {"departments": [], "appointment_window_days": 14, "renewal_lead_days": 42},
            },
        )
        if options.get("pract"):
            m["scopes"].setdefault("screen", {})["practitioners"] = options["pract"].split(",")
        if options.get("window"):
            m["scopes"].setdefault("screen", {})["appointment_window_days"] = int(options["window"])
        if options.get("dept"):
            m["scopes"].setdefault("nav", {})["departments"] = options["dept"].split(",")
        if options.get("lookback"):
            m["scopes"].setdefault("feas", {})["lookback_months"] = int(options["lookback"])
        m.setdefault("routing", {"aggregate_to": [requested_by], "list_to": [requested_by]})
        m.setdefault(
            "thresholds",
            {
                "tier_high_confidence": self.d.settings_thresholds.get("tier_high_confidence", 0.75),
                "small_cell": int(self.d.settings_thresholds.get("small_cell", 5)),
            },
        )
        m.setdefault("models", {"judge": self.d.judge_model, "judge_prompt": "judge_v4"})
        # the terminology release the ValueSets resolve through (D-301): a run against another one is refused
        release = getattr(self.d.term, "release", "") if self.d.term is not None else ""
        if release:
            m["terminology_release"] = release
        else:
            m.pop("terminology_release", None)
        m.pop("review", None)
        m.pop("equivalence", None)
        m.pop("prompt_pins", None)  # pinned again at approval (D-318)
        m.pop("derived_pins", None)  # pinned again at approval (D-442)
        for k in ("effective_from", "irb_reference", "irb_approved_on"):  # each version's own record (D-364)
            m.pop(k, None)
        return RulesetManifest.model_validate(m)

    def _package(
        self,
        job_id: str,
        manifest: RulesetManifest,
        criteria: list[CriterionIR],
        valuesets: dict[str, dict[str, Any]],
        tests: EquivalenceReport,
        files: dict[str, bytes],
        round_no: int,
        notes: list[str],
    ) -> tuple[str, str, str]:
        html_doc = review_html(manifest.id, manifest.version, round_no, criteria, valuesets, tests, notes)
        xlsx = review_xlsx(manifest.id, manifest.version, round_no, job_id, criteria, valuesets, tests)
        zipped = draft_zip(
            {f"{manifest.id}/{p}": b for p, b in files.items()}, {"review.html": html_doc.encode("utf-8")}
        )
        base = f"outputs/{job_id}/"
        keys = (
            f"{base}review.html",
            f"{base}review.xlsx",
            f"{base}ruleset_{manifest.id}_v{manifest.version}-draft.zip",
        )
        self.d.store.put(keys[0], html_doc.encode("utf-8"), "text/html; charset=utf-8")
        self.d.store.put(keys[1], xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.d.store.put(keys[2], zipped, "application/zip")
        return keys

    # ------------------------------------------------------------------ public API
    def compile(self, req: CompileRequest) -> CompileResult:
        options = dict(req.options or {})
        try:
            parsed = ParsedDoc.model_validate_json(self.d.store.get(req.parsed_doc_key))
        except KeyError as exc:
            raise CompileFailed("parse", f"parsed document {req.parsed_doc_key} not found") from exc
        block = parsed.ie_block
        refs = block.refs or {}
        lines: list[dict[str, Any]] = []
        for kind, items in (
            ("inclusion", block.inclusion),
            ("exclusion", block.exclusion),
            ("renewal", block.renewal or []),
            ("documentation", block.documentation or []),
        ):
            # NEW-LIFE-2: the parser's positional refs (each item's own section and its lead-in) when it gave them;
            # else the text-keyed refs of a parsed document from before them
            pos = (block.item_refs or {}).get(kind)
            base = len(lines)
            for i, t in enumerate(items):
                if pos is not None and len(pos) == len(items):
                    r = pos[i]
                    parent = None if r.parent is None else base + r.parent
                    lines.append({"text": t, "kind": kind, "source_ref": f"{r.section} #{r.n}", "parent": parent})
                else:
                    lines.append({"text": t, "kind": kind, "source_ref": refs.get(t, "")})
        if not lines:
            raise CompileFailed("parse", "no eligibility criteria were found in the document")
        ruleset = req.ruleset
        version = self._next_version(ruleset, req.version or options.get("version"))
        self._audit(
            "compile.start", job_id=req.job_id, ruleset=ruleset, ruleset_version=version, input_sha=parsed.source_sha256
        )
        approved = self._approved(ruleset)
        reuse: dict[tuple[str, str], CriterionIR] = {}
        if approved and options.get("incremental", "true") != "false":
            reuse = {(c.kind, _norm(c.text)): c for c in approved.criteria}
        todo = [ln for ln in lines if (ln["kind"], _norm(str(ln["text"]))) not in reuse]
        offsets: dict[str, int] = {}
        for c in reuse.values():
            code = KIND_CODE[c.kind]
            offsets[code] = max(offsets.get(code, 0), int(c.id.rsplit("-", 1)[1]))
        guard_hit = False
        criteria_new: list[CriterionIR] = []
        valuesets: dict[str, dict[str, Any]] = dict(approved.valuesets) if approved else {}
        # the parser's warnings (hidden text, a planted instruction, masked contact lines; T-208, T-606): to the review
        warnings: list[str] = list(parsed.warnings or [])
        if todo:
            extracted, guard, unread = self._extract(req.job_id, ruleset, parsed.language, todo)
            guard_hit = guard.hit
            post = postprocess(
                ruleset, extracted, self.d.term, version, self._concept_map(req.job_id), dict(offsets), self.d.egfr()
            )
            criteria_new = flag_unread(post.criteria, unread, warnings)
            valuesets.update(post.valuesets)
            warnings.extend(post.warnings)
        # changed criteria keep the id of the approved criterion they replace (positional pairing per kind)
        used = {
            c.id
            for c in reuse.values()
            if (c.kind, _norm(c.text)) in {(ln["kind"], _norm(str(ln["text"]))) for ln in lines}
        }
        freed: dict[str, list[str]] = {}
        if approved:
            for c in approved.ordered():
                if c.id not in used:
                    freed.setdefault(c.kind, []).append(c.id)
        new_iter = iter(criteria_new)
        criteria: list[CriterionIR] = []
        reused: set[int] = set()
        for ln in lines:
            hit = reuse.get((ln["kind"], _norm(str(ln["text"]))))
            if hit:
                reused.add(len(criteria))
                criteria.append(hit.model_copy(update={"review": CriterionReview(status="draft")}))
                continue
            fresh = next(new_iter)
            code = KIND_CODE[fresh.kind]
            if freed.get(fresh.kind):
                new_id = freed[fresh.kind].pop(0)
            else:
                offsets[code] = offsets.get(code, 0) + 1
                new_id = f"{ruleset}-{code}-{offsets[code]:02d}"
            criteria.append(fresh.model_copy(update={"id": new_id}))
        profile = self._profile(ruleset)
        lookback = int(options.get("lookback") or profile.get("scopes", {}).get("feas", {}).get("lookback_months", 36))
        # NEW-LIFE-2: a heading, a group's alternatives, a glued heading, another phase or a second section is not one
        # required criterion: a person decides it, and the warnings say why (LIFE-002)
        shape = structure.check(lines, req.kind or "trial")
        # D-793: a set of alternative groups whose members are all structured is one criterion, or(and(group …));
        # its lines carry no structure finding any more. The rest goes to a person (D-785)
        grouped, folded, combined = structure.combine(criteria, lines, keep=reused, report=shape)
        shape.findings = [f for f in shape.findings if f.index not in folded]
        if not any(f.flag in ("group_member", "alternatives_in_line") for f in shape.findings):
            shape.warnings = [w for w in shape.warnings if not w.startswith("some lines may be alternatives")]
        criteria, moved = structure.send_to_a_person(criteria, shape, keep=reused)  # a reviewer decided those
        if folded:
            keep_ids = {c.id for c in grouped}
            by_id = {c.id: c for c in grouped}
            criteria = [by_id.get(c.id, c) for c in criteria if c.id in keep_ids]
        warnings.extend(combined)
        warnings.extend(shape.warnings + moved)
        criteria, demoted = self.demote_uncompilable(ruleset, version, criteria, valuesets)
        warnings.extend(demoted)
        art = self.build_artifacts(ruleset, version, criteria, valuesets, lookback)
        warnings.extend(art.warnings)
        index_date = date.fromisoformat(options["index_date"]) if options.get("index_date") else self._today()
        tests = self._equivalence(criteria, art, valuesets, index_date, f"{ruleset}|{version}")
        criteria = self._flag(criteria, tests)
        manifest = self._manifest(
            ruleset,
            version,
            req.kind or "trial",
            req.title,
            criteria,
            profile,
            options,
            req.requested_by or "unknown",
            [parsed.filename],
            parsed.language,
            art.library,
            approved.manifest if approved else None,
        )
        manifest = manifest.model_copy(update={"review": None, "equivalence": None})
        files = self._files(manifest, criteria, valuesets, art, tests)
        branch = f"draft/{req.job_id}"
        self.d.repo.write_dir(branch, "main", f"{ruleset}/", files, f"compile {ruleset} v{version} (job {req.job_id})")
        notes = [
            f"PHI guard: {'hit — local model used' if guard_hit else 'clean'}",
            f"{len(lines) - len(todo)} criteria reused from the approved version, {len(todo)} extracted",
        ]
        notes.extend(warnings)
        keys = self._package(req.job_id, manifest, criteria, valuesets, tests, files, 1, notes)
        needs = [c.id for c in criteria if c.flags and "needs_review" in c.flags]
        self._audit(
            "compile.done",
            job_id=req.job_id,
            ruleset=ruleset,
            ruleset_version=version,
            detail={
                "criteria": len(criteria),
                "equivalence_pct": tests.overall_pct,
                "failing": tests.failing,
                "needs_review": needs,
                "phi_guard_hit": guard_hit,
                "branch": branch,
            },
        )
        return CompileResult(
            ruleset=ruleset,
            version=version,
            branch=branch,
            criteria=criteria,
            tests=tests,
            manifest=manifest,
            review_html_key=keys[0],
            review_xlsx_key=keys[1],
            draft_zip_key=keys[2],
            needs_review=needs,
            warnings=warnings,
            phi_guard_hit=guard_hit,
            round=1,
        )

    def diff(self, req: DiffRequest) -> DiffResult:
        approved = self._approved(req.ruleset)
        if approved is None:
            raise CompileFailed("diff", f"{req.ruleset} has no approved version")
        parsed = ParsedDoc.model_validate_json(self.d.store.get(req.new_doc_key))
        b = parsed.ie_block
        new = [
            (k, t)
            for k, items in (
                ("inclusion", b.inclusion),
                ("exclusion", b.exclusion),
                ("renewal", b.renewal or []),
                ("documentation", b.documentation or []),
            )
            for t in items
        ]
        old: dict[tuple[str, str], CriterionIR] = {(c.kind, _norm(c.text)): c for c in approved.criteria}
        seen: set[str] = set()
        unchanged, added = [], []
        for kind, text in new:
            hit = old.get((kind, _norm(text)))
            if hit:
                unchanged.append(hit.id)
                seen.add(hit.id)
            else:
                added.append((kind, text))
        removed = [c for c in approved.criteria if c.id not in seen]
        changed: list[str] = []
        by_kind: dict[str, list[CriterionIR]] = {}
        for c in removed:
            by_kind.setdefault(c.kind, []).append(c)
        still_added = []
        for kind, text in added:  # positional pairing within a kind = "changed"
            pool = by_kind.get(kind) or []
            if pool:
                changed.append(pool.pop(0).id)
            else:
                still_added.append(text)
        removed_ids = [c.id for cs in by_kind.values() for c in cs]
        return DiffResult(
            ruleset=req.ruleset,
            base_version=approved.version,
            changed=changed,
            added=still_added,
            removed=removed_ids,
            unchanged=unchanged,
        )

    def _draft(self, ruleset: str, version: str) -> tuple[str, Ruleset]:
        best: tuple[int, str, Ruleset] | None = None
        for br in self.d.repo.branches():
            if not br.startswith("draft/"):
                continue
            raw = self.d.repo.read(br, f"{ruleset}/manifest.yaml")
            if not raw:
                continue
            files = {p[len(ruleset) + 1 :]: data for p, data in self.d.repo.files(br, f"{ruleset}/").items()}
            rs = Ruleset.from_files(files)
            if rs.version != version or rs.manifest.status != "draft":
                continue
            sha = self.d.repo.ref(br)
            assert sha is not None
            commit: Any = self.d.repo.repo[sha]
            t = int(commit.commit_time)
            if best is None or t > best[0]:
                best = (t, br, rs)
        if best is None:
            raise CompileFailed("approve", f"no draft of {ruleset} v{version} awaiting approval")
        return best[1], best[2]

    def approve(self, req: ApproveRequest) -> ApproveResult:
        branch, rs = self._draft(req.ruleset, req.version)
        job_id = req.job_id or branch.split("/", 1)[1]
        now = datetime.now(ZoneInfo(self.d.tz))
        decisions = {d.id: d for d in req.decisions}
        round_no = rs.manifest.review.rounds if rs.manifest.review and rs.manifest.review.rounds else 1
        criteria = rs.ordered()
        valuesets = dict(rs.valuesets)
        unknown = sorted(set(decisions) - {c.id for c in criteria})
        if unknown:
            raise CompileFailed("approve", f"review.xlsx lists unknown criteria {unknown}")
        edits = [d for d in req.decisions if d.status == "edit"]
        updated: list[CriterionIR] = []
        to_extract: list[tuple[CriterionIR, str]] = []
        for c in criteria:
            d = decisions.get(c.id)
            review = CriterionReview(status="draft")
            if d is None:
                updated.append(c.model_copy(update={"review": review}))
                continue
            if d.status == "approve":
                review = CriterionReview(status="approved", by=req.by, at=now, comment=d.comment)
            elif d.status == "reject":
                review = CriterionReview(status="rejected", by=req.by, at=now, comment=d.comment)
            new = c.model_copy(update={"review": review})
            if d.status == "edit":
                if d.edited_ir is not None:
                    new = d.edited_ir.model_copy(update={"id": c.id, "ruleset": c.ruleset, "review": review})
                elif d.edited_text:
                    to_extract.append((c, d.edited_text))
                if d.edited_class and not d.edited_text and d.edited_ir is None:
                    upd: dict[str, Any] = {"class_": d.edited_class, "review": review}
                    if d.edited_class in ("note", "mixed") and not c.note_question:
                        upd["note_question"] = f"Do the notes support: {c.text}"
                    if d.edited_class == "human" and not c.human_question:
                        upd["human_question"] = f"Confirm with the patient/clinician: {c.text}"
                    new = c.model_copy(update=upd)
            updated.append(new)
        if to_extract:
            lines = [{"text": text, "kind": c.kind, "source_ref": c.source_ref or ""} for c, text in to_extract]
            extracted, _, unread = self._extract(job_id, req.ruleset, rs.manifest.language or "en", lines)
            post = postprocess(
                req.ruleset, extracted, self.d.term, req.version, self._concept_map(job_id), egfr=self.d.egfr()
            )
            post.criteria = flag_unread(post.criteria, unread, [])
            valuesets.update(post.valuesets)
            replaced = {
                orig.id: new.model_copy(update={"id": orig.id, "review": CriterionReview(status="draft")})
                for (orig, _), new in zip(to_extract, post.criteria, strict=True)
            }
            for orig, _ in to_extract:
                d = decisions[orig.id]
                if d.edited_class:
                    replaced[orig.id] = replaced[orig.id].model_copy(update={"class_": d.edited_class})
            updated = [replaced.get(c.id, c) for c in updated]
        if edits:
            round_no += 1
            if round_no > MAX_ROUNDS:
                self._audit(
                    "approve.max_rounds",
                    job_id=req.job_id,
                    ruleset=req.ruleset,
                    ruleset_version=req.version,
                    actor=req.by,
                )
                return ApproveResult(
                    ruleset=req.ruleset,
                    version=req.version,
                    status="max_rounds",
                    round=round_no,
                    criteria=updated,
                    blocking=[d.id for d in edits],
                )
        index_date = self._today()
        art = self.build_artifacts(req.ruleset, req.version, updated, valuesets)
        prev = self.d.repo.read(branch, f"{req.ruleset}/tests/equivalence.json")
        if edits or prev is None or any(d.status == "reject" for d in req.decisions):
            tests = self._equivalence(updated, art, valuesets, index_date, f"{req.ruleset}|{req.version}")
        else:
            tests = self.enforce(EquivalenceReport.model_validate_json(prev), updated)
        updated = self._flag(updated, tests)
        active = [c for c in updated if not (c.review and c.review.status == "rejected")]
        blocking = sorted(
            {c.id for c in active if c.id in tests.failing}
            | {c.id for c in active if not c.review or c.review.status != "approved"}
        )
        if not art.elm and compiled(active):
            blocking.append("ELM translation unavailable")
        manifest = rs.manifest.model_copy(update={"criteria": [c.id for c in updated]})
        if edits or blocking:
            manifest = RulesetManifest.model_validate({**dump(manifest), "review": {"rounds": round_no}})
            files = self._files(manifest, updated, valuesets, art, tests)
            self.d.repo.write_dir(
                branch,
                "main",
                f"{req.ruleset}/",
                files,
                f"review round {round_no} for {req.ruleset} v{req.version} by {req.by}",
                req.by,
            )
            notes = (
                [f"Round {round_no}: {len(edits)} edited criteria recompiled"]
                if edits
                else [f"Blocking: {', '.join(blocking)}"]
            )
            keys = self._package(job_id, manifest, updated, valuesets, tests, files, round_no, notes)
            self._audit(
                "approve.needs_review",
                job_id=req.job_id,
                ruleset=req.ruleset,
                ruleset_version=req.version,
                actor=req.by,
                detail={"round": round_no, "blocking": blocking, "edits": len(edits)},
            )
            return ApproveResult(
                ruleset=req.ruleset,
                version=req.version,
                status="needs_review",
                round=round_no,
                manifest=manifest,
                criteria=updated,
                tests=tests,
                review_html_key=keys[0],
                review_xlsx_key=keys[1],
                draft_zip_key=keys[2],
                blocking=blocking,
            )
        valuesets = {k: {**v, "status": "active"} for k, v in valuesets.items()}
        manifest = RulesetManifest.model_validate(
            {
                **dump(manifest),
                **approval_pins(manifest, updated, self.d.prompt_environment),
                **amendment_record(req, now.date()),
                "status": "approved",
                "review": {
                    "approved_by": req.by,
                    "approved_at": now.isoformat(),
                    "approved_via": req.via or "e-mail",
                    "rounds": round_no,
                    "split": class_split(updated),
                    "routing_confirmed": True,  # approval is the person's confirmation of every class (D-101)
                },
                "equivalence": {
                    "overall_pct": tests.overall_pct,
                    "sample_size": tests.sample_size,
                    "per_criterion": tests.per_criterion,
                    "failing": tests.failing,
                    "evaluated_at": now.isoformat(),
                },
            }
        )
        files = self._files(manifest, updated, valuesets, art, tests)
        # G3 of the P1b review (D-952): the FHIR load ran after the tag and the promotion, unguarded; a server that
        # refused it (FhirEvalError) left the ruleset approved and released while the job failed with an HTTP 500. It
        # runs first: a refusal changes nothing in the repo and fails the approval by its step, with the server's text
        if self.d.fhir is not None and art.elm:
            libs = [
                library_resource("FHIRHelpers", "4.0.1", fhirhelpers_source(), art.elm.get("FHIRHelpers")),
                library_resource("TB_Common", "1.0.0", art.cql["TB_Common"], art.elm.get("TB_Common")),
                library_resource(art.library, art.library_version, art.cql[art.library], art.elm[art.library]),
            ]
            try:
                self.d.fhir.load(libs, valuesets.values())
            except (FhirEvalError, httpx.HTTPError) as exc:
                log.warning("approve %s v%s: the FHIR server refused the load: %s", req.ruleset, req.version, exc)
                raise CompileFailed(
                    "approve", f"the FHIR server did not take the ruleset's libraries or value sets: {exc}"
                ) from exc
        self.d.repo.write_dir(
            branch, "main", f"{req.ruleset}/", files, f"approve {req.ruleset} v{req.version} by {req.by}", req.by
        )
        tag = f"{req.ruleset}/v{req.version}"
        self.d.repo.tag(tag, branch, f"{req.ruleset} v{req.version} approved by {req.by}", req.by)
        self.d.repo.promote(req.ruleset, tag, f"release {tag}", req.by)
        self._audit(
            "approve.done",
            job_id=req.job_id,
            ruleset=req.ruleset,
            ruleset_version=req.version,
            actor=req.by,
            detail={
                "tag": tag,
                "rounds": round_no,
                "effective_from": str(manifest.effective_from or ""),
                "irb_reference": manifest.irb_reference or "",
            },
        )
        return ApproveResult(
            ruleset=req.ruleset,
            version=req.version,
            status="approved",
            tag=tag,
            round=round_no,
            manifest=manifest,
            criteria=updated,
            tests=tests,
            blocking=[],
        )
