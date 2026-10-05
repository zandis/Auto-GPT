"""criteria-compiler orchestration: ``compile`` / ``diff`` / ``approve`` (SPEC §4.3, §5 approval loop, §6.4 gate)."""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from lake.client import LakeAPI
from tb_common.audit import AuditLog
from tb_common.fhir import FhirEvaluator, library_resource
from tb_common.llm import LlmClient
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

from criteria_compiler.compile_cql.generator import CqlGenerator, render_common
from criteria_compiler.compile_cql.translator import TranslationError, Translator, fhirhelpers_source
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.ctgov import CtGov, CtgovError
from criteria_compiler.equivalence.gate import run_gate
from criteria_compiler.ir_extract.postprocess import KIND_CODE, postprocess
from criteria_compiler.repo import RulesetRepo
from criteria_compiler.review import draft_zip, json_bytes, review_html, review_xlsx
from criteria_compiler.semantics import CompileError, compiled
from criteria_compiler.terminology.mapper import Concept, Terminology, ValueSets

log = logging.getLogger("criteria-compiler")
MAX_ROUNDS = 3
EquivalenceFn = Callable[[list[CriterionIR], str, str, date, str], EquivalenceReport]


class CompileFailed(RuntimeError):
    def __init__(self, step: str, message: str) -> None:
        super().__init__(f"{step}: {message}")
        self.step = step


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
    tz: str = "Asia/Taipei"
    mrn_regex: str | None = None
    lake: LakeAPI | None = None
    fhir: FhirEvaluator | None = None
    translator: Translator | None = None
    audit: AuditLog | None = None
    judge_model: str = ""
    equivalence: EquivalenceFn | None = None  # override for tests
    ctgov: CtGov | None = None  # ClinicalTrials.gov client (COHORT trial simulation); default from TB_CTGOV_MODE


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
            out = LlmConceptMapOutput.model_validate(
                self.d.llm.chat_json(
                    "concept_map", variables, job_id=job_id, clearance=guard.clearance, phi_guard_hit=guard.hit
                ).data
            )
            choices = [(c.code, c.system, c.confidence) for c in out.choices]
            return choices, out.needs_review or len(choices) > 1 or any(c[2] < 0.9 for c in choices)

        return fn

    def _extract(
        self, job_id: str, ruleset: str, language: str, lines: list[dict[str, Any]]
    ) -> tuple[LlmExtractOutput, PhiScan]:
        variables = {"ruleset": ruleset, "language": language, "criteria": lines}
        guard = scan(variables_text(variables), self.d.mrn_regex)  # exactly what the prompt carries (cloud routing)
        res = self.d.llm.chat_json(
            "ir_extract",
            variables,
            job_id=job_id,
            clearance=guard.clearance,
            phi_guard_hit=guard.hit,
        )
        out = LlmExtractOutput.model_validate(res.data)
        if len(out.criteria) != len(lines):
            raise CompileFailed("ir_extract", f"model returned {len(out.criteria)} criteria for {len(lines)} lines")
        return out, guard

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
            cql["FHIRHelpers"] = fhirhelpers_source()
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
            return self.d.equivalence(active, art.sql, art.library, index_date, seed)
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
        self.d.fhir.load(libs, valuesets.values())
        return run_gate(active, art.sql, art.library, self.d.lake, self.d.fhir, index_date, seed, threshold)

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
        files["tests/equivalence.json"] = json_bytes(dump(tests))
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
        m.setdefault("models", {"judge": self.d.judge_model, "judge_prompt": "judge_v3"})
        m.pop("review", None)
        m.pop("equivalence", None)
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
        lines = [
            {"text": t, "kind": kind, "source_ref": refs.get(t, "")}
            for kind, items in (
                ("inclusion", block.inclusion),
                ("exclusion", block.exclusion),
                ("renewal", block.renewal or []),
                ("documentation", block.documentation or []),
            )
            for t in items
        ]
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
        warnings: list[str] = []
        if todo:
            extracted, guard = self._extract(req.job_id, ruleset, parsed.language, todo)
            guard_hit = guard.hit
            post = postprocess(ruleset, extracted, self.d.term, version, self._concept_map(req.job_id), dict(offsets))
            criteria_new = post.criteria
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
        for ln in lines:
            hit = reuse.get((ln["kind"], _norm(str(ln["text"]))))
            if hit:
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
                    if d.edited_class == "note" and not c.note_question:
                        upd["note_question"] = f"Do the notes support: {c.text}"
                    if d.edited_class == "human" and not c.human_question:
                        upd["human_question"] = f"Confirm with the patient/clinician: {c.text}"
                    new = c.model_copy(update=upd)
            updated.append(new)
        if to_extract:
            lines = [{"text": text, "kind": c.kind, "source_ref": c.source_ref or ""} for c, text in to_extract]
            extracted, _ = self._extract(job_id, req.ruleset, rs.manifest.language or "en", lines)
            post = postprocess(req.ruleset, extracted, self.d.term, req.version, self._concept_map(job_id))
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
            tests = EquivalenceReport.model_validate_json(prev)
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
                "status": "approved",
                "review": {"approved_by": req.by, "approved_at": now.isoformat(), "rounds": round_no},
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
        self.d.repo.write_dir(
            branch, "main", f"{req.ruleset}/", files, f"approve {req.ruleset} v{req.version} by {req.by}", req.by
        )
        tag = f"{req.ruleset}/v{req.version}"
        self.d.repo.tag(tag, branch, f"{req.ruleset} v{req.version} approved by {req.by}", req.by)
        self.d.repo.promote(req.ruleset, tag, f"release {tag}", req.by)
        if self.d.fhir is not None and art.elm:
            libs = [
                library_resource("FHIRHelpers", "4.0.1", fhirhelpers_source(), art.elm.get("FHIRHelpers")),
                library_resource("TB_Common", "1.0.0", art.cql["TB_Common"], art.elm.get("TB_Common")),
                library_resource(art.library, art.library_version, art.cql[art.library], art.elm[art.library]),
            ]
            self.d.fhir.load(libs, valuesets.values())
        self._audit(
            "approve.done",
            job_id=req.job_id,
            ruleset=req.ruleset,
            ruleset_version=req.version,
            actor=req.by,
            detail={"tag": tag, "rounds": round_no},
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
