"""How many drafted concepts the terminology resolves without the model (TERM-2, D-1113; lane E's TERM-1 measure).

    python -m tools.terminology_coverage <raw-traces.json> [--installed DIR] [--synonyms] [--json]
    python -m tools.terminology_coverage <raw-traces.json> --model-calls [--synonyms] [--lang ja]
    python -m tools.terminology_coverage <raw-traces.json> --replay-postprocess [--json]
    python -m tools.terminology_coverage --concepts <concepts.csv> [--installed DIR] [--json]
    python -m tools.terminology_coverage <raw-traces.json> --write-concepts <concepts.csv>

Reads every ``concept_candidates`` entry of the ``extract_criteria`` calls in a launch's ``raw-traces.json`` (launch
P1b's ``sigir.tgz``: public ClinicalTrials.gov protocols), leaves out the ``demographic`` ones, and maps each with
``Terminology.map`` (no model, no synonym dictionary) against the shipped tables and, with ``--installed``, the code
systems loaded into that folder by ``tools.terminology_install``. ``--synonyms`` also passes the model's synonyms of
each candidate (off by default, as lane E measured). The file is data only: it is parsed as JSON and never run.
Prints the concepts and how many resolved, by domain, and the total.

H-17 (D-1128): the traces cannot be committed, so ``--write-concepts`` derives their concepts in a small committable
form (``domain``, ``name`` as drafted, ``count``; the demographic ones left out; no model synonyms) and
``--concepts`` measures from it, the same figures without the archive (CI). The JSON output also counts, by domain,
the resolved concepts whose answer is for review (``for_review``).

``--model-calls`` measures every drafted occurrence. Stored outcome counts describe the actual concept_map
records, including calls the current mapper bypasses. Each simulated invocation without a corresponding
usable reply in its study counts as a replay gap. ``--replay-postprocess`` uses the compiler's normal
synonym handling and counts final flagged criteria. A gap makes the affected study and overall flag count null.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Iterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for _p in ("", "libs", "services"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

from criteria_compiler.terminology.mapper import Concept, Terminology  # noqa: E402
from pydantic import ValidationError  # noqa: E402
from tb_contracts import ExtractedCriterion, LlmConceptMapOutput, LlmExtractOutput  # noqa: E402

from tools.public_accuracy import rerun  # noqa: E402

ORDER = ("condition", "observation", "medication", "procedure", "encounter", "claim")


def candidates(traces: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Each concept candidate the ``extract_criteria`` calls drafted, in order (an output that is not JSON: none)."""
    for call in traces.get("traces") or []:
        if (call.get("attributes") or {}).get("tb.role") == "extract_criteria":
            yield from _drafted(call)


def _drafted(call: dict[str, Any]) -> Iterator[dict[str, Any]]:
    out = rerun._output(call)
    for crit in out.get("criteria") or [] if isinstance(out, dict) else []:
        for cand in crit.get("concept_candidates") or []:
            if isinstance(cand, dict) and cand.get("name"):
                yield cand


def measure(traces: dict[str, Any], term: Terminology, synonyms: bool = False) -> dict[str, Any]:
    """``{"calls", "candidates", "by_domain": {domain: [concepts, resolved]}, "methods": {method: n}, "unmapped":
    {domain: {name: n}}}``. ``candidates`` counts every drafted candidate, the demographic ones included (P1b: 1,533);
    the concepts measured, by domain, leave those out (P1b: 1,273)."""
    calls = sum(
        1 for c in traces.get("traces") or [] if (c.get("attributes") or {}).get("tb.role") == "extract_criteria"
    )
    cands = list(candidates(traces))
    result = _count(((c, 1) for c in cands), term, synonyms)
    return {"calls": calls, "candidates": len(cands), **result}


def _count(weighted: Iterator[tuple[dict[str, Any], int]], term: Terminology, synonyms: bool) -> dict[str, Any]:
    """The counts of :func:`measure` over candidates each counted ``n`` times (one map call per distinct one)."""
    by: dict[str, list[int]] = {}
    methods: Counter[str] = Counter()
    review: Counter[str] = Counter()
    unmapped: dict[str, Counter[str]] = {}
    for cand, n in weighted:
        domain = str(cand.get("domain") or "")
        if domain == "demographic":
            continue
        syn = [str(s) for s in cand.get("synonyms") or []] if synonyms else None
        r = term.map(domain, str(cand["name"]), syn)
        row = by.setdefault(domain, [0, 0])
        row[0] += n
        if r.concepts:
            row[1] += n
            methods[r.method] += n
            review[domain] += n if r.needs_review else 0
        else:
            unmapped.setdefault(domain, Counter())[str(cand["name"]).strip().lower()] += n
    return {"by_domain": by, "methods": dict(methods), "for_review": dict(review),
            "unmapped": {d: dict(c.most_common()) for d, c in unmapped.items()}}  # fmt: skip


CONCEPT_COLUMNS = ("domain", "name", "count")


def concept_rows(traces: dict[str, Any]) -> list[dict[str, str]]:
    """The launch's drafted concepts, distinct by domain and name as drafted, with how often each was drafted
    (demographic ones left out), sorted: the committable form ``--concepts`` reads (H-17, D-1128)."""
    counts: Counter[tuple[str, str]] = Counter()
    for cand in candidates(traces):
        domain = str(cand.get("domain") or "")
        if domain != "demographic":
            counts[(domain, str(cand["name"]))] += 1
    return [{"domain": d, "name": n, "count": str(k)} for (d, n), k in sorted(counts.items())]


def write_concepts(rows: list[dict[str, str]]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CONCEPT_COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def measure_concepts(text: str, term: Terminology) -> dict[str, Any]:
    """:func:`measure`'s counts from the committable concept list (``domain,name,count``): the same figures as from
    the traces, without the model synonyms."""
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows or set(CONCEPT_COLUMNS) - set(rows[0]):
        raise ValueError(f"a concept list has the columns {', '.join(CONCEPT_COLUMNS)}")
    weighted = (({"domain": r["domain"], "name": r["name"]}, int(r["count"])) for r in rows)
    result = _count(weighted, term, False)
    # H-17 review: the list holds no demographic candidates, so here ``candidates`` is the concepts measured (1,273),
    # not :func:`measure`'s count of every candidate (1,533)
    return {"calls": None, "candidates": sum(v[0] for v in result["by_domain"].values()), **result}


def table(result: dict[str, Any]) -> str:
    by = result["by_domain"]
    names = [d for d in ORDER if d in by] + sorted(set(by) - set(ORDER))
    lines = ["| Domain | Concepts | Resolved |", "|---|---|---|"]
    for d in names:
        lines.append(f"| {d} | {by[d][0]} | {by[d][1]} |")
    n, k = sum(v[0] for v in by.values()), sum(v[1] for v in by.values())
    lines.append(f"| **all** | **{n:,}** | **{k} ({100 * k / (n or 1):.1f} %)** |")
    return "\n".join(lines)


def _protocol_records(traces: dict[str, Any]) -> rerun.Stored:
    stored = rerun.Stored()
    for call in sorted(traces.get("traces") or [], key=lambda c: str(c.get("ts") or "")):
        attrs = call.get("attributes") or {}
        prompt = str(attrs.get("tb.prompt") or "")
        if not prompt and attrs.get("tb.role") == "extract_criteria":
            prompt = "ir_extract"  # older coverage traces identified extraction by role alone
            attrs = {**attrs, "tb.prompt": prompt}
            call = {**call, "attributes": attrs}
        if prompt.startswith(("ir_extract", "concept_map")):
            stored.by_job.setdefault(str(attrs.get("tb.study_id") or ""), []).append(call)
    return stored


def _inputs(call: dict[str, Any]) -> dict[str, Any]:
    return rerun._json_block((call.get("prompt") or [{}])[-1].get("content") or "") or {}


class MappingReplies:
    """One study's observed replies. Each observation can account for at most one simulated call."""

    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.by_name: dict[tuple[str, str], list[tuple[set[tuple[str, str]], LlmConceptMapOutput]]] = defaultdict(list)
        self.calls: Counter[str] = Counter()
        self.empty = self.nonempty = self.unknown = self.gaps = 0
        for call in records:
            inputs, out = _inputs(call), rerun._output(call)
            try:
                reply = LlmConceptMapOutput.model_validate(
                    {"needs_review": True, **out} if isinstance(out, dict) else out
                )
            except ValidationError:
                self.unknown += 1
                continue
            if reply.choices:
                self.nonempty += 1
            else:
                self.empty += 1
            key = (rerun.norm(inputs.get("concept")), str(inputs.get("domain") or ""))
            codes = {(c.get("system"), c.get("code")) for c in inputs.get("candidates") or []}
            self.by_name[key].append((codes, reply))

    def answer(self, name: str, domain: str, candidates_: list[Concept]) -> tuple[list[tuple[str, str, float]], bool]:
        self.calls[domain] += 1
        available = {(c.system, c.code) for c in candidates_}
        replies = self.by_name.get((rerun.norm(name), domain), [])
        # ReplayModel's exact, then compatible match, scoped to this study and including the code system.
        idx = next((i for i, (codes, _) in enumerate(replies) if codes == available), None)
        if idx is None:
            idx = next(
                (i for i, (_, r) in enumerate(replies) if all((c.system, c.code) in available for c in r.choices)), None
            )
        if idx is None:
            self.gaps += 1
            return [], True
        _, reply = replies.pop(idx)
        return [(c.code, c.system, c.confidence) for c in reply.choices], reply.needs_review


def model_calls(stored: rerun.Stored, term: Terminology, synonyms: bool) -> dict[str, Any]:
    by_domain: Counter[str] = Counter()
    empty = nonempty = unknown = gaps = resolved = 0
    for job in stored.by_job:
        replies = MappingReplies(stored.calls(job, "concept_map"))
        empty += replies.empty
        nonempty += replies.nonempty
        unknown += replies.unknown
        for call in stored.calls(job, "ir_extract"):
            for cand in _drafted(call):
                domain = str(cand.get("domain") or "")
                if domain == "demographic":
                    continue
                by_domain.setdefault(domain, 0)
                syn = cand.get("synonyms") if synonyms else None
                result = term.map(domain, str(cand["name"]), syn, llm=replies.answer)
                if result.concepts and result.method != "llm":
                    resolved += 1
        by_domain.update(replies.calls)
        gaps += replies.gaps
    return {
        "model_calls": by_domain.total(),
        "model_calls_by_domain": dict(by_domain),
        "table_resolved": resolved,
        "stored_empty": empty,
        "stored_nonempty": nonempty,
        "stored_unknown": unknown,
        "replay_gaps": gaps,
    }


def _line_key(line: dict[str, Any]) -> tuple[str, str, str]:
    return str(line["kind"]), rerun.norm(line["text"]), str(line.get("source_ref") or "")


def _extraction(stored: rerun.Stored, job: str) -> tuple[str, LlmExtractOutput, int]:
    from criteria_compiler.service import _for_a_person, align

    ruleset, _, lines, _ = rerun.protocol_lines(stored, job)
    line_keys = [_line_key(line) for line in lines]
    positions: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    answers: dict[int, ExtractedCriterion | dict[str, Any]] = {}
    omissions: Counter[int] = Counter()
    cursor = 0
    calls = stored.calls(job, "ir_extract")
    gaps = int(not calls)
    for call in calls:
        part = _inputs(call).get("criteria") or []
        if not part:
            gaps += 1
            continue
        keys = [_line_key(line) for line in part]
        if keys == line_keys[cursor : cursor + len(part)]:
            indices = list(range(cursor, cursor + len(part)))
            cursor += len(part)
            for key, i in zip(keys, indices, strict=True):
                positions[key].append(i)
        else:
            # A retry can repeat an answered line alongside the missing ones. For identical unnumbered
            # sentences prefer unfilled positions, keeping the original order among those positions.
            slots = {k: iter(sorted(positions[k], key=lambda i: i in answers)) for k in set(keys)}
            indices = [next(slots[k], -1) for k in keys]
            gaps += indices.count(-1)
        try:
            batch = LlmExtractOutput.model_validate(rerun._output(call))
        except ValidationError:
            continue
        matched, split = align(part, batch.criteria)
        for i, (position, criterion) in enumerate(zip(indices, matched, strict=True)):
            if position < 0:
                continue
            if i in split:
                answers.setdefault(position, _for_a_person(part[i], "split_by_model"))
            elif criterion is not None:
                answers.setdefault(position, criterion)
            else:
                omissions[position] += 1
    ordered = []
    for position, line in enumerate(lines):
        if position in answers:
            ordered.append(answers[position])
        else:
            # The compiler asks an omitted line once more before retaining it for human review.
            gaps += omissions[position] < 2
            ordered.append(_for_a_person(line, "not_extracted"))
    return ruleset or job, LlmExtractOutput.model_validate({"criteria": ordered}), gaps


def replay_postprocess(stored: rerun.Stored, term: Terminology) -> dict[str, Any]:
    from criteria_compiler.ir_extract.postprocess import postprocess

    studies = {}
    total = gaps = 0
    for job in stored.by_job:
        ruleset, extracted, extraction_gaps = _extraction(stored, job)
        replies = MappingReplies(stored.calls(job, "concept_map"))
        post = postprocess(ruleset, extracted, term, llm_map=replies.answer)
        # No ordered input for this study, or a missing choice: its final count is unknown.
        study_gaps = extraction_gaps + replies.gaps
        flagged = sum("concept_unmapped" in (c.flags or []) for c in post.criteria)
        studies[job] = {
            "criteria": len(post.criteria),
            "concept_unmapped": None if study_gaps else flagged,
            "replay_gaps": study_gaps,
        }
        gaps += study_gaps
        total += flagged
    return {"concept_unmapped": None if gaps else total, "replay_gaps": gaps, "by_study": studies}


# Human labels are separate from the JSON keys, which are stable across languages.
LABELS = {
    "model_calls": ("Simulated model calls", "模擬模型呼叫次數", "モデル呼び出し推定回数"),
    "model_calls_by_domain": ("Calls by domain", "各領域的呼叫次數", "領域別の呼び出し回数"),
    "table_resolved": ("Resolved by tables", "由對照表解析的概念數", "表で解決した概念数"),
    "stored_empty": ("Stored empty replies", "已儲存的空回覆數", "選択が空の保存済み応答数"),
    "stored_nonempty": ("Stored nonempty replies", "已儲存的非空回覆數", "選択を含む保存済み応答数"),
    "stored_unknown": (
        "Stored calls without usable replies",
        "缺少可用回覆的已儲存呼叫數",
        "有効な応答がない保存済み呼び出し数",
    ),
    "replay_gaps": ("Replay gaps (unknown outcome)", "重播缺漏數（結果未知）", "再現に必要な記録の欠落数（結果不明）"),
    "concept_unmapped": (
        "Criteria flagged concept_unmapped",
        "標記 concept_unmapped 的條件數",
        "concept_unmapped が付いた基準数",
    ),
    "by_study": ("By study", "依研究分類", "試験別"),
}
DOMAIN_LABELS = {
    "condition": ("condition", "疾病", "疾患"),
    "observation": ("observation", "觀察", "観察"),
    "medication": ("medication", "用藥", "薬剤"),
    "procedure": ("procedure", "處置", "処置"),
    "encounter": ("encounter", "就醫", "受診"),
    "claim": ("claim", "申報", "請求"),
    "report": ("report", "報告", "報告"),
}
LANGUAGES = ("en", "zh-TW", "ja")


def replay_table(result: dict[str, Any], lang: str) -> str:
    index = LANGUAGES.index(lang)
    unknown = ("unknown", "未知", "不明")[index]
    lines = []
    for key, value in result.items():
        label = LABELS[key][index]
        if key == "by_study":
            lines.append(label)
            for job, study in value.items():
                count = study["concept_unmapped"]
                lines.append(f"  {job}  {unknown if count is None else count}")
        elif key == "model_calls_by_domain":
            lines.append(label)
            for domain, n in sorted(value.items()):
                name = DOMAIN_LABELS[domain][index] if domain in DOMAIN_LABELS else domain
                lines.append(f"  {name}  {n}")
        else:
            lines.append(f"{label}  {unknown if value is None else value}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("traces", type=Path, nargs="?", default=None)
    ap.add_argument("--concepts", type=Path, default=None, help="a concept list (domain,name,count) instead")
    ap.add_argument("--write-concepts", type=Path, default=None, help="write the traces' concept list here")
    ap.add_argument("--installed", type=Path, default=None, help="a TB_TERMINOLOGY_DIR (default: an empty one)")
    ap.add_argument("--synonyms", action="store_true", help="also pass each candidate's model synonyms")
    ap.add_argument("--json", action="store_true")
    modes = ap.add_mutually_exclusive_group()
    modes.add_argument("--model-calls", action="store_true", help=" / ".join(LABELS["model_calls"]))
    modes.add_argument(
        "--replay-postprocess",
        "--replay",
        action="store_true",
        help="Replay postprocessing / 重播後處理 / 後処理を再現",
    )
    ap.add_argument("--lang", choices=LANGUAGES, default="en", help="Output language / 輸出語言 / 出力言語")
    args = ap.parse_args(argv)
    replay = args.model_calls or args.replay_postprocess
    if replay and (not args.traces or args.concepts or args.write_concepts):
        ap.error(
            (
                "Replay modes require a trace file alone",
                "重播模式僅接受追蹤檔案",
                "再現モードの入力にはトレースファイルのみ指定できます",
            )[LANGUAGES.index(args.lang)]
        )
    if (args.traces is None) == (args.concepts is None):
        ap.error("give either a raw-traces.json or --concepts")
    traces = json.loads(args.traces.read_text(encoding="utf-8")) if args.traces else {}
    if args.write_concepts:
        if not args.traces:
            ap.error("--write-concepts derives the list from a raw-traces.json")
        rows = concept_rows(traces)
        args.write_concepts.write_text(write_concepts(rows), encoding="utf-8")
        print(f"{len(rows)} distinct concepts, {sum(int(r['count']) for r in rows):,} drafted, "
              f"written to {args.write_concepts}")  # fmt: skip
        return 0
    where = args.installed or Path("/nonexistent/terminology-none")
    term = Terminology(installed=where)
    if term.installed_problems:
        print("refused: " + "; ".join(term.installed_problems), file=sys.stderr)
    if replay:
        stored = _protocol_records(traces)
        result = model_calls(stored, term, args.synonyms) if args.model_calls else replay_postprocess(stored, term)
    elif args.concepts:
        result = measure_concepts(args.concepts.read_text(encoding="utf-8"), term)
    else:
        result = measure(traces, term, args.synonyms)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1, sort_keys=True))
        return 0
    if replay:
        print(replay_table(result, args.lang))
        return 0
    if result["calls"] is not None:
        print(f"{result['calls']} extract_criteria calls, {result['candidates']:,} candidates (demographic ones "
              "included; the table counts the others)")  # fmt: skip
    else:
        print(f"{result['candidates']:,} concepts (no demographic ones) from {args.concepts.name}")
    print(table(result))
    print("methods: " + ", ".join(f"{m} {n}" for m, n in sorted(result["methods"].items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
