"""Level (b) of the offline replay of a stored run (card H-4, D-1111): the parts of FEAS, APPROVE and SCREEN that need
no model, re-run on the current code from what the run stored.

What is re-run, and how, with nothing changed in the code it calls (lane A2's public entry points, as their own
tests replay the P1b drafts):

* **The compile (FEAS up to the equivalence step).** ``criteria_compiler.service.Compiler.compile`` is called with a
  model that answers only from the run's stored replies (``raw-traces.json``): ``ir_extract`` by the line's text,
  ``concept_map`` by the concept, its domain and its candidate codes. The protocol's lines are the ones the run sent
  to ``ir_extract`` (the stored prompts). A line the run asked about with no stored reply is a gap, and the protocol
  is "not re-run": the model would be needed. A concept the run mapped with no stored reply is answered "no choice"
  (the criterion goes to a person) and counted. The CQL translator, the FHIR server and the lake of the box are not
  run, so the equivalence step itself never runs here: what is checked is the cause the P1b review named for each
  failure (G1 D-955 a ValueSet id over 64 characters; G2 D-957 an encounter with no code; G5 D-956 ``None`` in the
  CQL), on the ruleset the current compile writes.
* **SCREEN's deterministic steps.** G7 (D-953) ``screen_cascade.notes_only_budget`` on the re-compiled ruleset; G6
  (D-951) ``screen.candidate_list`` with the judging mode the cascade writes when nothing decides; G8 (D-958) the
  stored ``judge`` replies of the job read again by ``matching.cascade.judge.GatewayJudge``.
* **Coded age and sex lines.** Each demographic line of the re-compiled ruleset (and of the stored draft) is turned
  into a truth table by its own SQL (``SqlGenerator``) on a small in-process lake (``lake.store.Lake``) of synthetic
  people of every whole age 0 to 110, each sex and none, and no birth date, on the run's index date. A patient's
  verdict is read from it by the patient's age on that day: from the birth date the answer key places (key v1 or v2,
  ``site.birth_date_v1`` / ``site.birth_date``, from the public note where the repository holds it), or, where no
  birth date can be known here, from the ages the patient's stored coded verdicts allow.
* **Stored note exclusions** are read again by the current inference guard (F6, D-985, ``matching.inferred``): the
  model's verdict and quote are as stored; only the deterministic check after it is re-run.

Everything else (a note verdict, an ``ir_extract`` reply the run did not get, a time budget) is "as stored, not
re-run", and said per protocol. Nothing here calls a model, the network or a GPU.
"""

from __future__ import annotations

import json
import re
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

FHIR_ID = re.compile(r"[A-Za-z0-9.\-]{1,64}")
OLD_VS_ID_MAX = 64  # D-955: P1b's ValueSet id was ``<ruleset>-<name>``; the FHIR server refuses an id over 64
NONE_IN_CQL = re.compile(r"\(None\b|\bNone\s+in\b|\bin\s+None\b")
AGES = range(0, 111)
SEXES = ("male", "female", "")


class ReplayGap(Exception):
    """The run stored no reply for a model call the current code makes: the step needs the model."""


def norm(text: Any) -> str:
    return " ".join(str(text or "").split()).lower()


def _json_block(content: str) -> dict[str, Any] | None:
    m = re.search(r"```json\n(.*)\n```", content or "", re.S)
    if not m:
        return None
    try:
        out = json.loads(m.group(1))
    except ValueError:
        return None
    return out if isinstance(out, dict) else None


def _output(x: dict[str, Any]) -> Any:
    o = x.get("output")
    if not isinstance(o, str):
        return None
    try:
        return json.loads(o)
    except ValueError:
        return None


# ---------------------------------------------------------------- the stored replies
@dataclass
class Stored:
    """A run's stored model calls (``raw-traces.json``), by job."""

    by_job: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    concept: dict[tuple[str, str, tuple[str, ...]], dict[str, Any]] = field(default_factory=dict)
    concept_loose: dict[tuple[str, str], list[dict[str, Any]]] = field(default_factory=dict)

    @classmethod
    def read(cls, work: Path) -> Stored:
        f = work / "raw-traces.json"
        traces = json.loads(f.read_text(encoding="utf-8")).get("traces") if f.exists() else []
        s = cls()
        for x in sorted(traces or [], key=lambda t: str(t.get("ts") or "")):
            attrs = x.get("attributes") or {}
            s.by_job.setdefault(str(attrs.get("tb.study_id") or ""), []).append(x)
            if str(attrs.get("tb.prompt") or "").startswith("concept_map"):
                v = _json_block(str((x.get("prompt") or [{}])[-1].get("content") or ""))
                out = _output(x)
                if not v or not isinstance(out, dict):
                    continue
                codes = tuple(sorted(str(c.get("code")) for c in v.get("candidates") or []))
                k = (norm(v.get("concept")), str(v.get("domain") or ""))
                s.concept.setdefault((*k, codes), out)
                s.concept_loose.setdefault(k, []).append(out)
        return s

    def calls(self, job: str, prompt: str) -> list[dict[str, Any]]:
        return [
            x
            for x in self.by_job.get(job, [])
            if str((x.get("attributes") or {}).get("tb.prompt", "")).startswith(prompt)
        ]


def protocol_lines(stored: Stored, job: str) -> tuple[str, str, list[dict[str, Any]], dict[str, Any]]:
    """(ruleset id on the box, language, the protocol's lines in order with absolute ``parent``, what is known) from
    the ``ir_extract`` prompts the run stored for the FEAS job. A call whose lines were all asked before is the
    compile's retry of lines without an answer (D-912), not a new part."""
    lines: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    ruleset, language = "", "en"
    answered = unanswered = 0
    for x in stored.calls(job, "ir_extract"):
        v = _json_block(str((x.get("prompt") or [{}])[-1].get("content") or "")) or {}
        part = [ln for ln in v.get("criteria") or [] if isinstance(ln, dict)]
        ruleset = ruleset or str(v.get("ruleset") or "")
        language = str(v.get("language") or language)
        if _output(x) is None:
            unanswered += 1
        else:
            answered += 1
        keys = [(str(ln.get("kind")), norm(ln.get("text"))) for ln in part]
        if part and all(k in seen for k in keys):
            continue
        start = len(lines)
        for ln, k in zip(part, keys, strict=True):
            p = ln.get("parent")
            lines.append({**ln, "parent": p + start if isinstance(p, int) else None})
            seen.add(k)
    return ruleset, language, lines, {"ir_extract_calls_stored": answered + unanswered,
                                      "ir_extract_calls_without_reply": unanswered}  # fmt: skip


class ReplayModel:
    """The model of a re-run: it answers ``ir_extract`` and ``concept_map`` from the run's stored replies only."""

    def __init__(self, stored: Stored, job: str) -> None:
        self.stored, self.job = stored, job
        self.asked: set[tuple[str, str]] = set()
        self.answers: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for x in stored.calls(job, "ir_extract"):
            v = _json_block(str((x.get("prompt") or [{}])[-1].get("content") or "")) or {}
            out = _output(x)
            if not isinstance(out, dict):
                continue
            for ln in v.get("criteria") or []:
                self.asked.add((str(ln.get("kind")), norm(ln.get("text"))))
            got: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
            for c in out.get("criteria") or []:
                if isinstance(c, dict):
                    got[(str(c.get("kind")), norm(c.get("text")))].append(c)
            for k, cs in got.items():
                self.answers.setdefault(k, cs)  # the first reply stands; a retry fills a line the first left out
        self.concepts_not_stored: list[str] = []
        self.calls: Counter[str] = Counter()

    def chat_json(self, prompt_id: str, variables: dict[str, Any], schema: str | None = None, **_: Any) -> Any:
        from tb_common.llm import LlmResult

        self.calls[prompt_id] += 1
        if prompt_id == "ir_extract":
            out: list[dict[str, Any]] = []
            for ln in variables.get("criteria") or []:
                k = (str(ln.get("kind")), norm(ln.get("text")))
                if k not in self.asked:
                    raise ReplayGap(f"ir_extract: the run stored no reply for the line {str(ln.get('text'))[:80]!r}")
                out.extend(self.answers.get(k, []))  # asked and not answered: the model left it out, as in the run
            data: dict[str, Any] = {"criteria": out}
        elif prompt_id == "concept_map":
            codes = tuple(sorted(str(c.get("code")) for c in variables.get("candidates") or []))
            k = (norm(variables.get("concept")), str(variables.get("domain") or ""))
            hit = self.stored.concept.get((*k, codes))
            if hit is None:
                allowed = set(codes)
                hit = next((o for o in self.stored.concept_loose.get(k, [])
                            if {str(c.get("code")) for c in o.get("choices") or []} <= allowed), None)  # fmt: skip
            if hit is None:
                self.concepts_not_stored.append(str(variables.get("concept")))
                hit = {"choices": [], "needs_review": True}
            data = hit
        else:
            raise ReplayGap(f"{prompt_id}: a model call the re-run cannot answer from the stored run")
        return LlmResult(data=data, prompt_id=prompt_id, prompt_version=0, model="stored-run", target="local",
                         input_sha="", output_sha="", tokens_in=0, tokens_out=0, attempts=1)  # fmt: skip


# ---------------------------------------------------------------- the compile, re-run
def parsed_doc(lines: list[dict[str, Any]], language: str) -> Any:
    """The parsed protocol the compile reads, from the lines the run sent to ``ir_extract``."""
    import tb_contracts as c

    kinds: dict[str, list[str]] = defaultdict(list)
    refs: dict[str, list[Any]] = defaultdict(list)
    base: dict[str, int] = {}
    ok = True
    for i, ln in enumerate(lines):
        k = str(ln.get("kind"))
        base.setdefault(k, i)
        kinds[k].append(str(ln.get("text")))
        m = re.match(r"(.+?) #(\d+)$", str(ln.get("source_ref") or ""))
        p = ln.get("parent")
        if not m:
            ok = False
            continue
        refs[k].append({"section": m.group(1), "n": int(m.group(2)),
                        "parent": None if p is None else int(p) - base[k]})  # fmt: skip
    block: dict[str, Any] = {
        "inclusion": kinds.get("inclusion", []),
        "exclusion": kinds.get("exclusion", []),
        "renewal": kinds.get("renewal") or None,
        "documentation": kinds.get("documentation") or None,
        "refs": {str(ln.get("text")): str(ln.get("source_ref") or "") for ln in lines},
    }
    if ok:
        block["item_refs"] = {k: v for k, v in refs.items() if v}
    return c.ParsedDoc.model_validate({
        "source_sha256": "0" * 64, "filename": "protocol.txt", "parser": "lite", "language": language,
        "sections": [], "tables": [], "ie_block": block})  # fmt: skip


@dataclass
class Recompiled:
    ruleset: str
    status: str  # compiled | failed | not_rerun
    step: str = ""
    message: str = ""
    criteria: list[Any] = field(default_factory=list)
    rs: Any = None  # tb_common.ruleset.Ruleset of the draft
    concepts_not_stored: list[str] = field(default_factory=list)
    lines: int = 0
    known: dict[str, Any] = field(default_factory=dict)


def recompile(stored: Stored, job: str, index_date: date, tz: str) -> Recompiled:
    """``Compiler.compile`` on the stored lines and replies. No translator, no FHIR server, no lake: the equivalence
    step reports "unavailable" and fails nothing (it is not run)."""
    import tb_contracts as c
    from criteria_compiler.repo import RulesetRepo
    from criteria_compiler.service import CompileFailed, Compiler, CompilerDeps
    from criteria_compiler.terminology.mapper import Terminology
    from tb_common.objstore import FsStore
    from tb_common.ruleset import Ruleset

    ruleset, language, lines, known = protocol_lines(stored, job)
    if not lines:
        return Recompiled(ruleset or job, "not_rerun", "ir_extract", "the run stored no ir_extract prompt for the job")
    model = ReplayModel(stored, job)
    with tempfile.TemporaryDirectory(prefix="tb-replay-") as t:
        tmp = Path(t)
        store = FsStore(tmp / "obj")
        store.put("attachments/R/parsed.json", c.dump_json(parsed_doc(lines, language)).encode())
        repo = RulesetRepo(tmp / "repo")
        deps = CompilerDeps(store=store, repo=repo, llm=model, term=Terminology(),  # type: ignore[arg-type]
                            settings_thresholds={"equivalence_min_pct": 98.0}, tz=tz)  # fmt: skip
        out = Recompiled(ruleset, "compiled", lines=len(lines), known=known)
        try:
            res = Compiler(deps).compile(c.CompileRequest(job_id=job, ruleset=ruleset,
                                                          parsed_doc_key="attachments/R/parsed.json",
                                                          requested_by="replay@example.invalid",
                                                          options={"index_date": index_date.isoformat()}))  # fmt: skip
        except ReplayGap as exc:
            out.status, out.step, out.message = "not_rerun", "ir_extract", str(exc)
        except CompileFailed as exc:
            out.status, out.step, out.message = "failed", exc.step, str(exc)
        else:
            files = {p[len(ruleset) + 1 :]: b for p, b in repo.files(res.branch, f"{ruleset}/").items()}
            out.criteria = list(res.criteria)
            out.rs = Ruleset.from_files(files)
        out.concepts_not_stored = sorted(set(model.concepts_not_stored))
        return out


def cause_checks(r: Recompiled) -> dict[str, Any]:
    """The causes the P1b review named for the FEAS and APPROVE failures, on the re-compiled ruleset."""
    if r.rs is None:
        return {}
    vs_ids = [str(v.get("id") or "") for v in r.rs.valuesets.values()]
    old_ids = [f"{r.ruleset}-{name}" for name in r.rs.valuesets]
    enc_no_code = []
    for cr in r.rs.active():
        if cr.class_ not in ("structured", "mixed"):
            continue
        for a in _atoms(cr.logic):
            if getattr(a, "domain", "") == "encounter":
                vs = r.rs.valuesets.get(str(getattr(a, "valueset", "") or "")) or {}
                if not _codes(vs):
                    enc_no_code.append(cr.id)
    cql = "\n".join(r.rs.cql.values())
    return {
        "valueset_ids_are_fhir_ids": all(FHIR_ID.fullmatch(i) for i in vs_ids),
        "valuesets": len(vs_ids),
        "valuesets_whose_p1b_style_id_is_over_64": sum(len(i) > OLD_VS_ID_MAX for i in old_ids),
        "encounter_atoms_without_a_code": sorted(set(enc_no_code)),
        "none_in_cql": bool(NONE_IN_CQL.search(cql)),
        "coded_criteria": sum(1 for cr in r.rs.active() if f'"C_{cr.id}"' in r.rs.sql),
        "classes": dict(Counter(str(cr.class_) for cr in r.rs.active())),
    }


def _atoms(logic: Any) -> list[Any]:
    if logic is None:
        return []
    args = getattr(logic, "args", None)
    if args is not None:
        return [a for x in args for a in _atoms(x)]
    return [logic]


def _codes(vs: dict[str, Any]) -> list[Any]:
    comp = (vs.get("compose") or {}).get("include") or []
    return [c for inc in comp for c in inc.get("concept") or []] + [
        c for c in (vs.get("expansion") or {}).get("contains") or []
    ]


# ---------------------------------------------------------------- SCREEN's deterministic steps
def screen_checks(r: Recompiled, patients: int) -> dict[str, Any]:
    """G7 (D-953) and G6 (D-951) on the re-compiled ruleset."""
    if r.rs is None:
        return {}
    from orchestrator.scenarios import screen
    from orchestrator.scenarios.screen_cascade import notes_only_budget

    budget = notes_only_budget(r.rs, [f"p{i}" for i in range(max(1, patients))])
    machine = [cr for cr in r.rs.active() if cr.class_ in ("structured", "mixed", "note")
               and cr.kind in ("inclusion", "exclusion")]  # fmt: skip
    out: dict[str, Any] = {"notes_only_budget": budget, "nothing_decides": not machine}
    # G6: the candidate list the report builds when nothing decides (the judging mode P1b's contract refused)
    judging = {**screen.judging_info(None), "mode": "nothing"}
    run = screen.ScreenRun(rs=r.rs, run_date=date(2026, 11, 16), snapshot="2026-11-15", scoped=[], results={},
                           rows=[], practitioners=["D1"], departments=[], window_days=30, judge=None,
                           judging=judging, cascade={"stages": []})  # fmt: skip
    try:
        screen.candidate_list(run)
        out["candidate_list_builds"] = True
    except Exception as exc:  # what the report step would raise is the finding
        out["candidate_list_builds"] = False
        out["candidate_list_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
    return out


def judge_replies(stored: Stored, job: str) -> dict[str, Any]:
    """G8 (D-958): the job's stored ``judge`` replies read again by the current judge client: how many are still no
    answer (outside the schema)."""
    from matching.cascade.judge import GatewayJudge

    class _Res:
        def __init__(self, data: Any) -> None:
            self.data, self.call_id, self.build_sha, self.tokens_in, self.tokens_out = data, "replay", "replay", 0, 0

    class _Client:
        def __init__(self, data: Any) -> None:
            self.data = data

        def chat(self, *a: Any, **kw: Any) -> _Res:
            return _Res(self.data)

    n = refused = no_output = 0
    for x in stored.calls(job, "judge"):
        out = _output(x)
        n += 1
        if out is None:
            no_output += 1
            continue
        kw: dict[str, Any] = {"role": "judge", "criterion_text": "replay", "note_question": "replay?",
                              "index_date": date(2026, 11, 16), "excerpts": [], "study_id": job, "data_class": "D0",
                              "step_id": "replay", "purpose": "screening"}  # fmt: skip
        reply = GatewayJudge(_Client(out)).judge(**kw)
        refused += int(reply.refused is not None)
    return {"stored_replies": n, "still_no_answer": refused, "no_reply_stored": no_output}


# ---------------------------------------------------------------- coded age and sex lines
def _birth_for(age: int, on: date) -> str:
    """A birth date that is exactly ``age`` complete years old on ``on`` (born on that day, ``age`` years before)."""
    try:
        return on.replace(year=on.year - age).isoformat()
    except ValueError:  # 29 February
        return (on.replace(day=28).replace(year=on.year - age)).isoformat()


class AgeTable:
    """Truth tables of demographic criteria over (age, sex), by their own SQL on an in-process lake."""

    def __init__(self, on: date, tmp: Path, tz: str) -> None:
        from embed_service.embedder import HashEmbedder
        from lake.store import Lake

        self.on, self.tz = on, tz
        nd = tmp / "nd"
        nd.mkdir(parents=True, exist_ok=True)
        pats = []
        for age in AGES:
            for sex in SEXES:
                p: dict[str, Any] = {"resourceType": "Patient", "id": f"A{age}S{sex or 'x'}",
                                     "birthDate": _birth_for(age, on)}  # fmt: skip
                if sex:
                    p["gender"] = sex
                pats.append(p)
        for sex in SEXES:
            pats.append({"resourceType": "Patient", "id": f"NOBIRTHS{sex or 'x'}", **({"gender": sex} if sex else {})})
        (nd / "Patient.ndjson").write_text("\n".join(json.dumps(p) for p in pats) + "\n", encoding="utf-8")
        (nd / "Observation.ndjson").write_text("", encoding="utf-8")
        self.lake = tmp / "lake"
        Lake(self.lake, tz=tz).rebuild(on.isoformat(), HashEmbedder(), nd)
        self.cache: dict[str, dict[tuple[int | None, str], Any]] = {}

    def table(self, crit: Any, ruleset: str) -> dict[tuple[int | None, str], Any] | None:
        """{(age or None, sex): True/False/None} of one criterion, or None when it does not compile to SQL."""
        from criteria_compiler.compile_sql.generator import SqlGenerator
        from criteria_compiler.semantics import CompileError
        from criteria_compiler.terminology.mapper import Terminology, ValueSets
        from embed_service.embedder import HashEmbedder
        from lake.client import LakeLocal

        key = json.dumps([crit.kind, crit.model_dump(mode="json", by_alias=True).get("logic")], sort_keys=True)
        if key in self.cache:
            return self.cache[key]
        try:
            sql = SqlGenerator(ruleset, "1.0.0", ValueSets(ruleset, {}, Terminology())).render([crit])
        except (CompileError, ValueError, KeyError):
            self.cache[key] = None  # type: ignore[assignment]
            return None
        rows = LakeLocal(self.lake, HashEmbedder(), tz=self.tz).query(sql, [[self.on.isoformat()], None]).to_pylist()
        out: dict[tuple[int | None, str], Any] = {}
        for r in rows:
            pid = str(r["pid"])
            m = re.match(r"A(\d+)S(\w+)$", pid)
            sex = (m.group(2) if m else pid.removeprefix("NOBIRTHS")).replace("x", "")
            out[(int(m.group(1)) if m else None, sex)] = r[f"C_{crit.id}"]
        self.cache[key] = out
        return out


def verdict_of(kind: str, value: Any) -> str:
    """A coded criterion's verdict from its SQL value: an inclusion met passes, an exclusion present fails."""
    if value is None:
        return "unknown"
    present = bool(value)
    return ("pass" if present else "fail") if kind == "inclusion" else ("fail" if present else "pass")


def is_demographic(crit: Any) -> bool:
    """A criterion whose whole logic is age and sex atoms (what the age table can decide)."""
    atoms = _atoms(getattr(crit, "logic", None))
    return bool(atoms) and all(getattr(a, "domain", "") == "demographic" for a in atoms)


def criterion_ir(d: dict[str, Any], ruleset: str) -> Any:
    """A stored draft criterion (``answers.json``) as a CriterionIR, or None when it no longer validates."""
    from tb_contracts import CriterionIR

    try:
        return CriterionIR.model_validate({"id": d["id"], "ruleset": ruleset, "kind": d["kind"],
                                           "class": d.get("class"), "text": d.get("text") or "",
                                           "logic": d.get("logic"), "review": {"status": "approved"}})  # fmt: skip
    except Exception:  # a stored IR the current contract refuses is a finding, said by the caller
        return None


def age_on(birth: str, on: date) -> int | None:
    if not birth:
        return None
    b = date.fromisoformat(birth)
    return on.year - b.year - ((on.month, on.day) < (b.month, b.day))


def sigir_births(ids: dict[str, Any], built_day: date, mrn0: int) -> dict[str, dict[str, Any]]:
    """mrn -> {age_v1, age_v2 (on the run day), sex, why}: the birth dates the answer key placed (``site.build``: the
    i-th patient by sorted id has chart number ``mrn0 + i`` and a visit ``7 + (i * 37) % 300`` days before the build
    day; v1 ``birth_date_v1``, v2 ``birth_date`` with the stated unit), from the public note in
    ``eval/criterion_ml/notes_en.json`` (TrialGPT's sentences of each SIGIR patient)."""
    from tools.public_accuracy import sets, site

    notes = json.loads((sets.CRITERION_ML / "notes_en.json").read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for pkey, mrn in (ids.get("patients") or {}).items():
        sents = notes.get(pkey)
        if not sents:
            out[str(mrn)] = {"why": "no note in eval/criterion_ml/notes_en.json"}
            continue
        text = " ".join(s.strip() for s in sents)
        age, sex = sets.derive_age_sex(text)
        i = int(mrn) - mrn0
        visit = built_day - timedelta(days=7 + (i * 37) % 300)
        b1 = site.birth_date_v1(visit, age)
        b2 = site.birth_date(visit, age, sets.stated_age(text))
        out[str(mrn)] = {"birth_v1": b1, "birth_v2": b2, "sex": {"F": "female", "M": "male"}.get(sex or "", "")}
    return out


def table_verdict(tab: dict[tuple[int | None, str], Any], kind: str, age: int | None, sex: str) -> str:
    v = tab.get((age if age is None else min(age, max(AGES)), sex), "absent")
    return "unknown" if v == "absent" else verdict_of(kind, v)


def consistent_cells(evidence: list[tuple[dict[tuple[int | None, str], Any], str, str]]) -> set[tuple[int | None, str]]:
    """The (age, sex) cells a patient can be in, given stored coded verdicts and the tables of their lines."""
    cells = {(a, s) for a in [None, *AGES] for s in SEXES}
    for tab, kind, verdict in evidence:
        cells = {c for c in cells if verdict_of(kind, tab.get(c)) == verdict}
    return cells


# ---------------------------------------------------------------- SCREEN's verdicts, the deterministic parts again
CODED_CLASSES = ("structured", "mixed")


@dataclass
class Rescreen:
    """A set's stored answers with their deterministic parts decided again (one answer key's birth dates)."""

    answers: dict[str, Any]
    changes: Counter[str] = field(default_factory=Counter)
    calibration: Counter[str] = field(default_factory=Counter)
    notes: list[str] = field(default_factory=list)


def _sql_of(c: Any, rs: Any) -> bool:
    return rs is not None and f'"C_{c.id}"' in (rs.sql or "")


def rescreen(
    answers: dict[str, Any],
    recompiled: dict[str, Recompiled],
    tables: AgeTable,
    pid_mrn: dict[str, str],
    ages: dict[str, tuple[int | None, str]] | None,
    calib_ages: dict[str, tuple[int | None, str]] | None = None,
) -> Rescreen:
    """The stored answers of the screened protocols with what needs no model decided again by the current code.

    Per patient and criterion of the re-compiled ruleset (matched to the stored verdict by id and text):

    * a coded demographic line: the verdict its own SQL gives at the patient's age and sex (``ages``: mrn ->
      (age on the index date, sex) from the answer key's birth date; else the cells the patient's stored coded
      age and sex verdicts, in any protocol of the set, allow, decided only where every such cell gives one verdict);
    * a line now a person's (``human``): ``pending_human``;
    * a stored note verdict: as stored, except an exclusion's "present" whose quote does not state the condition,
      which the current guard sends to review (F6, D-985: ``unknown``);
    * any other line: the stored verdict; a line the run never decided that now needs the notes or a coded check
      this table cannot make: ``not_evaluated`` (open), and no verdict at all when the patient is excluded (the
      cascade stores none for a line it never reached, and the scorer counts such a row as "no verdict", S2).

    The tier is ``excluded`` when a verdict fails (the stored answers hold that rule for every patient), else open
    or listed by the scorer's own rule."""
    from matching.inferred import inferred

    out = Rescreen(answers=json.loads(json.dumps(answers)))
    # a patient's stored coded age and sex verdicts, over every protocol of the set (one pseudonym per patient)
    evidence: dict[str, list[tuple[dict[tuple[int | None, str], Any], str, str]]] = defaultdict(list)
    for rs_id, a in answers.items():
        draft = {d.get("id"): d for d in a.get("draft") or []}
        for pid, p in (a.get("patients") or {}).items():
            mrn = pid_mrn.get(pid, "")
            for v in p.get("verdicts") or []:
                sc = criterion_ir(draft.get(v.get("id")) or {}, rs_id.upper())
                if v.get("basis") != "coded" or sc is None or not is_demographic(sc):
                    continue
                tab = tables.table(sc, rs_id.upper())
                if tab is None:
                    continue
                evidence[pid].append((tab, sc.kind, str(v.get("verdict"))))
                if calib_ages and mrn in calib_ages:
                    same = table_verdict(tab, sc.kind, *calib_ages[mrn]) == v.get("verdict")
                    out.calibration["agrees" if same else "differs"] += 1
    for rs_id, a in out.answers.items():
        r = recompiled.get(rs_id)
        if not a.get("patients") or r is None or r.rs is None:
            if a.get("patients"):
                out.notes.append(f"{rs_id}: not re-compiled ({r.status if r else 'no job'}); verdicts as stored")
            continue
        stored_draft = {d.get("id"): d for d in a.get("draft") or []}
        new = {c.id: c for c in r.rs.active()}
        for cid, c in new.items():
            sd = stored_draft.get(cid)
            if sd is not None and norm(sd.get("text")) != norm(c.text):
                out.notes.append(f"{rs_id}: {cid} is another line in the re-compile; matched by id is wrong here")
        for pid, p in (a.get("patients") or {}).items():
            mrn = pid_mrn.get(pid, "")
            stored = {v.get("id"): v for v in p.get("verdicts") or []}
            cells = consistent_cells(evidence[pid]) if evidence.get(pid) else None
            verdicts = []
            for cid, c in new.items():
                v = stored.get(cid)
                got: dict[str, Any] = dict(v) if v else {"id": cid, "verdict": "not_evaluated", "basis": None}
                coded = c.class_ in CODED_CLASSES and _sql_of(c, r.rs) and is_demographic(c)
                if c.class_ == "human" or (c.review and c.review.status == "rejected"):
                    if c.class_ == "human":
                        got = {"id": cid, "verdict": "pending_human", "basis": "person", "quote": None}
                    else:
                        got = {"id": cid, "verdict": "not_evaluated", "basis": None, "quote": None}
                elif coded:
                    tab = tables.table(c, rs_id.upper())
                    verdict = "not_evaluated"
                    if tab is not None and ages is not None and mrn in ages:
                        verdict = table_verdict(tab, c.kind, *ages[mrn])
                    elif tab is not None and cells:
                        seen = {verdict_of(c.kind, tab.get(cell)) for cell in cells}
                        verdict = seen.pop() if len(seen) == 1 else "not_evaluated"
                    got = {"id": cid, "verdict": verdict, "basis": "coded", "quote": None}
                elif v is not None and v.get("basis") in ("notes", "pair") and v.get("verdict") == "fail":
                    if c.kind == "exclusion" and inferred(str(v.get("quote") or ""), c.text):
                        got = {**v, "verdict": "unknown", "basis": "notes"}
                elif v is not None and v.get("basis") == "coded":
                    got = dict(v)  # a coded line this table cannot decide (not age or sex): as stored
                if (v or {}).get("verdict") != got.get("verdict"):
                    out.changes[f"{(v or {}).get('verdict', 'none')} -> {got.get('verdict')}"] += 1
                verdicts.append(got)
            excluded = any(x.get("verdict") == "fail" for x in verdicts)
            if excluded:  # as the cascade stores it: a line it never reached for an excluded patient has no verdict
                verdicts = [
                    x for x in verdicts if not (x.get("id") not in stored and x.get("verdict") == "not_evaluated")
                ]
            p["verdicts"] = verdicts
            p["tier"] = (
                "excluded" if excluded else ("review" if any(x.get("verdict") != "pass" for x in verdicts) else "high")
            )
    return out
