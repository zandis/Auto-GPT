"""O-6: the share of Japanese judge calls the excerpt budget cuts, on the site box and on the head box (D-1346).

Plan 10 row 10E-38 (review 19, card 19-19; acceptance A6). Counted offline: no GPU, no gateway, no network, no model.

    TB_ENV=DEV PYTHONPATH=libs:services:. python -m tools.ja_call_sizes --out <file.json>

What it does:

1. the synthetic Japanese hospital (``tools.synth_hospital``, every note in Japanese: ``JP=ja:1.0``), the sites of
   :data:`SITES`, from a seed;
2. each site through the one ingest path (``tools.ingest_local.run_local``) into a lake, in a scratch folder that is
   removed afterwards (:func:`scratch`);
3. SCREEN's cascade (``matching.cascade.run_cascade``, the settings SCREEN gives it) over every shipped ruleset, once
   per arm. The only stand-in is the judge (:class:`SizingJudge`): it sizes the excerpts exactly as the box does
   (``NoteJudge.excerpt_budget`` over ``tb_common.llm.LlmClient.text_budget``, told the context of the arm's
   registered judge and verifier builds), records each call the cascade puts to it, and answers "unknown". The
   excerpt builder, the windows, the routing and ``left_out`` are the product's own code.

A call is **truncated** when the excerpt builder left a note of its window out or cut it (``left_out`` above 0: the
cascade marks the criterion in ``PatientTrace.notes_over_budget``). The box decides that with its own token estimate
(``tb_llm.budget``), never with a tokenizer, so the share is what the box's code does with these charts at these
contexts. The call **sizes** in the record are that estimate too. The judge's own tokenizer is not in the repository
and not installed; :func:`tokenizer_bound` reads what the repository measured of it on Japanese excerpts
(``tests/fixtures/llm/token_counts_cjk.json``), and the record says so (``tokenizer.true_count`` is false).

A6 (review 19): the share at 8k may exceed the 32k share by at most two percentage points, compared unrounded
(:func:`compare`). It is a result, not a target: nothing here is tuned to it. A record is filed as a measurement of
card 10E-38; it is never a tier value (D-1322).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import statistics
import sys
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, timedelta
from fractions import Fraction
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CARD = "10E-38"
DECISION = "D-1346"
#: the 8k arm (the site box, review 19's first site) and the 32k control (the head box)
ARMS = ("rtx5090", "rtxpro6000")
#: the general site and the memory clinic of the synthetic hospital, both writing Japanese notes only
SITES = "jp-a:JP:2500,jp-ad:JP:2500:mix_jp_ad"
LANG_MIX = {"JP": {"ja": 1.0}}
SEED = 42
REF_DATE = date(2026, 11, 1)
TZ = "Asia/Tokyo"
#: A6: at most this many points above the 32k control
A6_POINTS = 2
TOKEN_FIXTURE = ROOT / "tests" / "fixtures" / "llm" / "token_counts_cjk.json"


class SizesError(RuntimeError):
    pass


# -------------------------------------------------------------------------------------------------- the contexts
def arm_contexts(profile: str, doc: Mapping[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """The judge's and the verifier's registered context on ``profile`` (``models/registry.yaml``, read through
    ``tools.qualify.profile_builds``): ``{role: {"alias", "profile", "context"}}``. The record names the alias and the
    profile, never the build. A profile with no positive whole context for a role is refused: the box would fall back
    to its default budget, which is no arm of O-6."""
    from tools.qualify import QualifyError, profile_builds

    try:
        builds = profile_builds(profile, dict(doc) if doc is not None else None)
    except QualifyError as exc:
        raise SizesError(str(exc)) from exc
    out: dict[str, dict[str, Any]] = {}
    for role, b in sorted(builds.items()):
        ctx = b.context_length
        if type(ctx) is not int or ctx <= 0:
            raise SizesError(f"profile {profile}: the {role} build records no context ({ctx!r})")
        out[role] = {"alias": b.alias, "profile": profile, "context": ctx}
    return out


class FixedContext:
    """What ``LlmClient.context_tokens`` asks of a gateway: the context of the arm's build. Nothing else; no call."""

    prompt_environment = None

    def __init__(self, tokens: int) -> None:
        self.tokens = tokens

    def context(self, alias: str | None = None) -> int:
        return self.tokens


# -------------------------------------------------------------------------------------------------- the judge
@dataclass
class Call:
    """One judge call as the cascade put it: who, and the estimated size of the prompt and of its parts."""

    call_id: str
    role: str
    pid: str
    criterion_hash: str
    prompt_tokens: int  # tb_llm.budget.estimate_messages of the rendered prompt
    fixed_tokens: int  # the same prompt with no excerpts
    excerpts: int
    excerpt_chars: int


class SizingJudge:
    """The cascade's ``JudgeClient`` for O-6. ``excerpt_budget`` is the box's (``NoteJudge`` over two ``LlmClient``
    told the arm's contexts); ``judge`` records the call and answers "unknown" (an answer never shortens or lengthens
    a later prompt: every pending criterion of a patient is asked, so the count is of every S3 question)."""

    def __init__(self, contexts: Mapping[str, Mapping[str, Any]]) -> None:
        from orchestrator.scenarios.evaluate import NoteJudge
        from tb_common.llm import LlmClient

        def client(role: str) -> Any:
            c = contexts[role]
            return LlmClient("", str(c["alias"]), gateway=FixedContext(int(c["context"])))

        self.note = NoteJudge(None, client("judge"), verifier=client("verifier"))
        self.calls: dict[str, Call] = {}
        self.budgets: dict[str, int] = {}

    def excerpt_budget(self, c: Any, index_date: date) -> int | None:
        room = self.note.excerpt_budget(c, index_date)
        if isinstance(room, int):
            self.budgets[c.id] = room
        return room

    def judge(self, *, role: str, criterion_text: str, note_question: str, index_date: date,
              excerpts: list[dict[str, Any]], **_: Any) -> Any:  # fmt: skip
        from matching.cascade.judge import ASKING, JudgeReply
        from tb_common.llm import load_prompt, render
        from tb_llm.budget import estimate_messages, shown

        p = load_prompt(self.note.prompt)
        base = {"criterion_text": criterion_text, "note_question": note_question, "index_date": index_date.isoformat()}
        full = estimate_messages(render(p, {**base, "excerpts": [shown(e) for e in excerpts]}))
        fixed = estimate_messages(render(p, {**base, "excerpts": []}))
        asking = ASKING.get()
        call_id = f"o6-{len(self.calls) + 1}"
        self.calls[call_id] = Call(
            call_id, role, asking.pid if asking else "", asking.criterion_hash if asking else "", full, fixed,
            len(excerpts), sum(len(str(e.get("text") or "")) for e in excerpts),
        )  # fmt: skip
        prompt = f"{p.meta.id}@{p.meta.version}"
        return JudgeReply("unknown", 0.0, None, None, "abstained", call_id=call_id, prompt=prompt, prompt_sha=p.sha256)


# -------------------------------------------------------------------------------------------------- the counts
@dataclass
class Arm:
    """What one arm counted. ``truncated`` <= ``judge_calls``; every call has a size above its fixed part."""

    profile: str
    contexts: dict[str, dict[str, Any]]
    judge_calls: int = 0
    truncated: int = 0
    prompt_tokens: list[int] = field(default_factory=list)
    excerpt_tokens: list[int] = field(default_factory=list)
    budgets: list[int] = field(default_factory=list)
    pairs: set[tuple[str, str, str]] = field(default_factory=set)  # (study, patient, criterion) asked at S3
    per_study: dict[str, dict[str, int]] = field(default_factory=dict)

    def add(self, study: str, calls: Sequence[tuple[str, Call, bool]], budgets: Sequence[int]) -> None:
        """``calls``: (criterion id, the call, truncated) for each S3 judge call of ``study``."""
        row = self.per_study.setdefault(study, {"judge_calls": 0, "truncated": 0})
        for cid, call, cut in calls:
            if call.role != "judge":
                raise SizesError(f"{study}: call {call.call_id} is a {call.role} call, not an S3 judge call")
            if call.prompt_tokens <= 0 or call.fixed_tokens <= 0 or call.prompt_tokens < call.fixed_tokens:
                raise SizesError(f"{study}: call {call.call_id} has an impossible size "
                                 f"({call.prompt_tokens} with {call.fixed_tokens} fixed)")  # fmt: skip
            key = (study, call.pid, cid)
            if key in self.pairs:
                raise SizesError(f"{study}: patient {call.pid} criterion {cid} was asked twice at S3")
            self.pairs.add(key)
            self.judge_calls += 1
            self.truncated += bool(cut)
            row["judge_calls"] += 1
            row["truncated"] += bool(cut)
            self.prompt_tokens.append(call.prompt_tokens)
            self.excerpt_tokens.append(call.prompt_tokens - call.fixed_tokens)
        self.budgets.extend(budgets)

    @property
    def share(self) -> Fraction | None:
        if self.judge_calls <= 0:
            return None
        if not 0 <= self.truncated <= self.judge_calls or len(self.prompt_tokens) != self.judge_calls:
            raise SizesError(f"{self.profile}: {self.truncated} truncated of {self.judge_calls} calls is impossible")
        return Fraction(self.truncated, self.judge_calls)

    def record(self) -> dict[str, Any]:
        share = self.share
        ctx = min(int(c["context"]) for c in self.contexts.values())
        return {
            "contexts": self.contexts,
            "judge_calls": self.judge_calls,
            "truncated_calls": self.truncated,
            "share": None if share is None else f"{share.numerator}/{share.denominator}",
            "share_percent": None if share is None else round(float(share) * 100, 3),
            "excerpt_budget_tokens": _spread(self.budgets),
            "prompt_tokens_estimate": _spread(self.prompt_tokens),
            "excerpt_tokens_estimate": _spread(self.excerpt_tokens),
            "largest_prompt_share_of_context": round(max(self.prompt_tokens) / ctx, 4) if self.prompt_tokens else None,
            "per_study": dict(sorted(self.per_study.items())),
        }


def _spread(xs: Sequence[int]) -> dict[str, int] | None:
    if not xs:
        return None
    s = sorted(xs)
    return {"min": s[0], "median": int(statistics.median(s)), "p95": s[min(len(s) - 1, (95 * len(s)) // 100)],
            "max": s[-1]}  # fmt: skip


def compare(small: Arm, large: Arm) -> dict[str, Any]:
    """A6: the 8k share at most :data:`A6_POINTS` points above the 32k share, unrounded. Not judged when either arm
    made no judge call, or when the arms asked different questions (their shares would not be of one set)."""
    a, b = small.share, large.share
    if a is None or b is None:
        return {"result": "not judged", "why": "an arm made no judge call", "difference_points": None}
    if small.pairs != large.pairs:
        why = f"the arms asked different questions ({len(small.pairs ^ large.pairs)} differ)"
        return {"result": "not judged", "why": why, "difference_points": None}
    diff = (a - b) * 100
    return {
        "result": "pass" if diff <= A6_POINTS else "fail",
        "why": f"{float(diff):+.3f} points against a limit of +{A6_POINTS}",
        "difference_points": f"{diff.numerator}/{diff.denominator}" if diff.denominator != 1 else str(diff.numerator),
        "limit_points": A6_POINTS,
    }


def tokenizer_bound(path: Path = TOKEN_FIXTURE) -> dict[str, Any]:
    """What the repository measured of the judge's tokenizer on Japanese excerpts (D-645's set): the ratio of its
    count to the box's estimate. Only the judge's column, only the ``ja`` rows; the template is not in that set."""
    from tb_llm.budget import estimate_tokens

    doc = json.loads(path.read_text("utf-8"))
    cols = doc["columns"]
    lang, text, judge = cols.index("language"), cols.index("text"), cols.index("judge")
    ratios = sorted(Fraction(r[judge], estimate_tokens(r[text])) for r in doc["rows"] if r[lang] == "ja")
    if not ratios:
        raise SizesError(f"{path}: no Japanese rows")
    return {
        "true_count": False,
        "counted_with": "tb_llm.budget.estimate_tokens (the box's own estimate; the judge's tokenizer is not here)",
        "measured_set": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "ja_excerpts": len(ratios),
        "judge_over_estimate": {
            "min": round(float(ratios[0]), 4),
            "median": round(float(statistics.median(ratios)), 4),
            "max": round(float(ratios[-1]), 4),
        },
    }


# -------------------------------------------------------------------------------------------------- one run
def screen_config(study: str, run_date: date, snapshot: str) -> Any:
    """SCREEN's cascade settings (``orchestrator.scenarios.screen_cascade.screen_with_cascade``) for an offline run:
    screening, one index date, every zero-hit pair to the judge, no pair budget, no sampling."""
    from matching.cascade import CascadeConfig

    return CascadeConfig(
        study_id=study,
        run_date=run_date,
        lookback_months=36,
        index_mode="single",
        purpose="screening",
        step_id=f"o6:{study}",
        language="ja",
        notes_language="auto",
        sample_per_stratum=None,
        snapshot=snapshot,
        absence_semantics=False,
        s2b_when_fits=False,
        require_retrieval=True,
        max_llm_items=10**9,
        llm_concurrency=1,
    )


def s3_calls(res: Any, judge: SizingJudge) -> list[tuple[str, Call, bool]]:
    """Each S3 judge call of a cascade result, with its criterion and whether its window was cut (the cascade marks
    a cut criterion in ``notes_over_budget``, at S3 only). A call the result does not name, or an outcome naming a
    call this judge never made, is an error: the count would not be of the calls made."""
    out: list[tuple[str, Call, bool]] = []
    named: set[str] = set()
    for pid, t in sorted(res.traces.items()):
        for cid, o in sorted(t.outcomes.items()):
            if o.stage != "S3":
                continue
            ids = [e["call_id"] for e in o.evidence if isinstance(e, dict) and e.get("call_id")]
            for call_id in ids:
                call = judge.calls.get(call_id)
                if call is None or call.pid != pid:
                    raise SizesError(f"the outcome of {pid} {cid} names call {call_id}, which this judge did not make")
                named.add(call_id)
                out.append((cid, call, cid in t.notes_over_budget))
    missing = {k for k, c in judge.calls.items() if c.role == "judge"} - named
    if missing:
        raise SizesError(f"{len(missing)} judge call(s) are named by no S3 outcome")
    return out


def studies() -> list[str]:
    return sorted(p.parent.name for p in (ROOT / "rulesets").glob("*/manifest.yaml"))


def measure_site(lake: Any, run_date: date, snapshot: str, arms: dict[str, Arm], study_ids: Sequence[str]) -> None:
    from embed_service.embedder import HashEmbedder
    from matching.cascade import run_cascade

    from tools.cascade_e2e import load_trial

    for study in study_ids:
        rs = load_trial(study)
        for arm in arms.values():
            judge = SizingJudge(arm.contexts)
            res = run_cascade(lake, rs, screen_config(rs.id, run_date, snapshot), judge=judge,
                              embedder=HashEmbedder(), reviewer=None)  # fmt: skip
            arm.add(rs.id, s3_calls(res, judge), list(judge.budgets.values()))


@contextmanager
def scratch() -> Iterator[Path]:
    """A private scratch folder under the scratch root (``tools.pglocal.scratch_root``: never the output's folder,
    never a home folder), and the database schemas the ingest makes there; both removed however the run ends,
    a SIGTERM included (it is turned into ``SystemExit``). ``TB_DB_URL`` is put back as it was."""
    from tools import pglocal

    root = pglocal.scratch_root()
    root.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="tb-o6-", dir=root))
    before_url = os.environ.get("TB_DB_URL")
    before_term = signal.getsignal(signal.SIGTERM)

    def term(signum: int, frame: Any) -> None:
        raise SystemExit(128 + signum)

    try:
        signal.signal(signal.SIGTERM, term)
    except ValueError:  # not the main thread: the caller's handler stays
        before_term = None
    try:
        yield work
    finally:
        try:
            markers = list(work.glob("**/.tb_db")) if before_url is None else []
            if markers:  # the schemas pglocal.for_work made for each ingest folder (none when TB_DB_URL was given)
                base = pglocal.ensure(pglocal.shared_dir())
                for marker in markers:
                    prefix = marker.read_text("utf-8").strip()
                    if prefix:
                        pglocal.drop_prefix(base, prefix)
        finally:
            shutil.rmtree(work, ignore_errors=True)
            if before_url is None:
                os.environ.pop("TB_DB_URL", None)
            else:
                os.environ["TB_DB_URL"] = before_url
            if before_term is not None:
                signal.signal(signal.SIGTERM, before_term)


def run(sites: str = SITES, seed: int = SEED, study_ids: Sequence[str] | None = None) -> dict[str, Any]:
    """Generate, ingest and screen in a scratch folder; return the record (complete or not)."""
    from embed_service.embedder import HashEmbedder
    from lake.client import LakeLocal

    from tools.cascade_e2e import SITE_KEY
    from tools.ingest_local import run_local
    from tools.synth_hospital import run as synth

    study_ids = list(study_ids or studies())
    arms = {p: Arm(p, arm_contexts(p)) for p in ARMS}
    small, large = (arms[p] for p in ARMS)
    if min(c["context"] for c in small.contexts.values()) >= min(c["context"] for c in large.contexts.values()):
        raise SizesError(f"{ARMS[0]} is not the smaller context of the two arms")
    charts: dict[str, Any] = {"generator": "tools.synth_hospital", "sites": sites, "lang_mix": LANG_MIX, "seed": seed,
                              "ref_date": REF_DATE.isoformat()}  # fmt: skip
    given_db = bool(os.environ.get("TB_DB_URL"))
    with scratch() as work:
        made = synth(work / "charts", sites=sites, lang_mix=LANG_MIX, seed=seed, ref_date=REF_DATE)
        if made.failures:
            raise SizesError(f"the synthetic hospital's checks failed: {made.failures[:3]}")
        s = made.summary
        charts |= {"digest": s["digest"], "patients": sum(x["patients"] for x in s["sites"]),
                   "notes": sum(x["notes"] for x in s["sites"]),
                   "note_languages": _merge(x["note_languages"] for x in s["sites"])}  # fmt: skip
        snapshot = (REF_DATE - timedelta(days=1)).isoformat()
        for site in s["sites"]:
            src = work / "charts" / site["dir"]
            if not given_db:  # each site its own schemas (pglocal.for_work keys them by the ingest folder)
                os.environ.pop("TB_DB_URL", None)
            night = run_local(src, work / "ingest" / site["dir"], kind="csv", site_id=site["site_id"],
                              site_key=SITE_KEY, snapshot=snapshot, tz=TZ)  # fmt: skip
            if not night.published:
                raise SizesError(f"{site['site_id']}: the ingest gate held the night: {night.blocking_reasons}")
            measure_site(LakeLocal(night.lake_dir, HashEmbedder(), TZ), REF_DATE, snapshot, arms, study_ids)
    return {
        "card": CARD,
        "decision": DECISION,
        "complete": True,
        "method": "offline: synthetic Japanese charts through SCREEN's cascade with the box's excerpt budget at each "
        "arm's registered context; truncation is the excerpt builder's left_out; sizes are the box's estimate",
        "charts": charts,
        "studies": study_ids,
        "tokenizer": tokenizer_bound(),
        "arms": {p: a.record() for p, a in arms.items()},
        "same_questions": small.pairs == large.pairs,
        "a6": compare(small, large),
    }


def _merge(maps: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for m in maps:
        for k, v in (m or {}).items():
            out[k] = out.get(k, 0) + int(v)
    return dict(sorted(out.items()))


def write(record: Mapping[str, Any], out: Path) -> None:
    """The record, whole or not at all: written beside ``out`` and moved over it."""
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f".{out.name}.{os.getpid()}.part")
    try:
        tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, out)
    finally:
        tmp.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.ja_call_sizes", description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, required=True, help="the record (JSON)")
    ap.add_argument("--sites", default=SITES)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--study", action="append", help="a ruleset id (default: every shipped ruleset)")
    args = ap.parse_args(argv)
    try:
        record = run(args.sites, args.seed, args.study)
    except (Exception, KeyboardInterrupt, SystemExit) as exc:
        why = f"{type(exc).__name__}: {exc}"[:500]
        write({"card": CARD, "decision": DECISION, "complete": False, "why": why}, args.out)
        print(f"incomplete: {why}", file=sys.stderr)
        return 1
    write(record, args.out)
    a6 = record["a6"]
    for p, a in record["arms"].items():
        print(f"{p}: {a['truncated_calls']} of {a['judge_calls']} judge calls truncated ({a['share_percent']} %)")
    print(f"A6: {a6['result']} ({a6['why']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["ARMS", "Arm", "Call", "SizesError", "SizingJudge", "arm_contexts", "compare", "run", "tokenizer_bound"]
