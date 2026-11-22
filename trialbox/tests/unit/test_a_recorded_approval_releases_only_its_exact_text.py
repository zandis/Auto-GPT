"""Gate 1, the owner's ruling of 2026-11-22: a held presence line runs only on a recorded approval of its exact text.

Planted cases, through ``postprocess`` (first extraction) and the compiler service:

* a held line never executes without an approval, nor with one when the audit receipt cannot be written;
* an approval for text A does not release text B that differs by one character, by whitespace, or by Unicode form.
  The rule is stated in ``presence_approvals``: the text is compared code point by code point, nothing is
  normalised (no whitespace folding or trimming, no NFC/NFD/NFKC, no case folding);
* a shipped synthetic approval is refused for a protocol that is not one of the four synthetic ones, and on any box
  that is not a test box (``TB_ENV`` DEV or TEST; unset is PRODUCTION, D-127), PRODUCTION and VALIDATION included;
* a malformed approvals file refuses with one message key in en, zh-TW and ja, and nothing falls back to releasing;
* the label travels: the review record, the review report, the audit receipt, and the approved ruleset.

Synthetic protocols and the recorded model answers (cassettes) only.
"""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from criteria_compiler.ir_extract import presence_approvals as pa
from criteria_compiler.ir_extract.postprocess import PresenceSource, postprocess
from criteria_compiler.semantics import compiled
from criteria_compiler.service import CompileFailed, _presence_passages
from criteria_compiler.terminology.mapper import Terminology
from doc_parser.parser import parse
from tb_common.audit import AuditLog
from tb_common.config import environment_name
from tb_contracts import LlmExtractOutput

from tests.unit.test_compiler_service import _approve, _compile, _decisions, env  # noqa: F401 (fixture)

ROOT = Path(__file__).resolve().parents[2]
PROTOCOLS = ("GZQO", "AD-MAB", "NEUR-COH", "RA-JAK")
# What the owner's rule withholds even in the synthetic protocols: a planned (hypothetical) and a negated clause.
WITHHELD = {"GZQO-EXC-05": "Prior or planned", "RA-JAK-EXC-04": "without tuberculosis preventive therapy"}


@pytest.fixture(scope="module")
def term() -> Terminology:
    return Terminology()


def _protocol(ruleset: str) -> tuple[LlmExtractOutput, list[PresenceSource]]:
    suffix = "pdf" if ruleset == "GZQO" else "docx"
    (document,) = (ROOT / "tests/fixtures/protocols").glob(f"{ruleset}*.{suffix}")
    parsed = parse(document.read_bytes(), document.name, backend="lite")
    sources = [s for section in _presence_passages(parsed).values() for _, _, s in section]
    cassette = ROOT / "services/llm_stub/cassettes/ir_extract" / f"{ruleset}.json"
    return LlmExtractOutput.model_validate_json(cassette.read_bytes()), sources


def _released(post: Any) -> set[str]:
    return {c.id for c in compiled(post.criteria) if pa.release_note(c)}


@pytest.mark.parametrize("ruleset", PROTOCOLS)
def test_a_held_line_never_executes_without_its_approval(ruleset: str, term: Terminology, tmp_path: Path) -> None:
    extracted, sources = _protocol(ruleset)
    approvals = pa.shipped_approvals(ruleset, "TEST")
    approved = {a.criterion for a in approvals}
    assert approved and not approved & set(WITHHELD)
    without = postprocess(ruleset, extracted, term, sources=sources, audit=AuditLog(tmp_path / "a"), environment="TEST")
    assert not {c.id for c in compiled(without.criteria)} & approved
    with_them = postprocess(
        ruleset,
        extracted,
        term,
        sources=sources,
        audit=AuditLog(tmp_path / "b"),
        approvals=approvals,
        environment="TEST",
    )
    assert _released(with_them) == approved
    # no audit receipt: nothing is released, not even with its approval
    unaudited = postprocess(ruleset, extracted, term, sources=sources, approvals=approvals, environment="TEST")
    assert not {c.id for c in compiled(unaudited.criteria)} & approved
    for c in unaudited.criteria:
        if c.id in approved:
            assert c.class_ == "human" and "presence_requires_review" in (c.flags or []) and not pa.release_note(c)


def _one_character(text: str) -> str:
    return text[:-2] + ("X" if text[-2] != "X" else "Y") + text[-1]


VARIANTS: dict[str, Callable[[str], str]] = {
    "one character": _one_character,
    "final period dropped": lambda t: t.rstrip(".。"),
    "doubled space": lambda t: t.replace(" ", "  ", 1) if " " in t else t[:3] + "  " + t[3:],
    "trailing space": lambda t: t + " ",
    "leading space": lambda t: " " + t,
    "no-break space": lambda t: t.replace(" ", " ", 1) if " " in t else t[:3] + " " + t[3:],
    "ideographic space": lambda t: t[:3] + "　" + t[3:],
    "tab": lambda t: t[:3] + "\t" + t[3:],
    "line break": lambda t: t[:3] + "\n" + t[3:],
    "NFD": lambda t: unicodedata.normalize("NFD", t),
    "NFKC": lambda t: unicodedata.normalize("NFKC", t),
    "upper case": str.upper,
}
COMMON = [v for v in VARIANTS if v not in {"NFD", "NFKC", "upper case"}]
# Each variant changes its text: Unicode forms on the Japanese line (グ decomposes; full-width brackets fold), case
# on the English one.
CASES = [("GZQO", "GZQO-EXC-04", v) for v in [*COMMON, "upper case"]] + [
    ("AD-MAB", "AD-MAB-EXC-01", v) for v in [*COMMON, "NFD", "NFKC"]
]


@pytest.mark.parametrize(("ruleset", "criterion", "variant"), CASES)
def test_an_approval_for_one_text_does_not_release_another(
    ruleset: str, criterion: str, variant: str, term: Terminology, tmp_path: Path
) -> None:
    extracted, sources = _protocol(ruleset)
    approvals = pa.shipped_approvals(ruleset, "TEST")
    (approval,) = [a for a in approvals if a.criterion == criterion]
    changed = VARIANTS[variant](approval.text)
    assert changed != approval.text, variant
    assert unicodedata.normalize("NFC", approval.text) == approval.text  # the record holds the NFC spelling
    i = next(n for n, s in enumerate(sources) if s.text == approval.text)
    # the model and the parser both give the changed text: only the approval differs
    sources[i] = PresenceSource(changed, sources[i].kind, sources[i].language, sources[i].standalone)
    answers = extracted.model_copy(deep=True)
    answers.criteria[i].text = changed
    post = postprocess(
        ruleset, answers, term, sources=sources, audit=AuditLog(tmp_path), approvals=approvals, environment="TEST"
    )
    held = post.criteria[i]
    assert held.id == criterion and held.class_ == "human" and held not in compiled(post.criteria)
    assert "presence_requires_review" in (held.flags or []) and held.text == changed
    assert _released(post) == {a.criterion for a in approvals} - {criterion}


def test_the_approval_binds_the_logic_the_codes_and_the_id(term: Terminology, tmp_path: Path) -> None:
    extracted, sources = _protocol("RA-JAK")
    approvals = pa.shipped_approvals("RA-JAK", "TEST")
    changed: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
        "logic": lambda r: {
            **r,
            "logic": {**r["logic"], "window": {"anchor": "index", "from_days": -366, "to_days": 0}},
        },
        "codes": lambda r: {**r, "codes": {k: {**v, "count": v["count"] + 1} for k, v in r["codes"].items()}},
        "criterion id": lambda r: {**r, "criterion": "RA-JAK-EXC-99"},
        "kind": lambda r: {**r, "kind": "inclusion"},
        "notes question": lambda r: {**r, "note_question": "Do the notes document shingles?"},
    }
    target = "RA-JAK-EXC-06"
    for name, change in changed.items():
        records = [change(a.record()) if a.criterion == target else a.record() for a in approvals]
        altered = pa.parse_approvals({"form": pa.FORM, "approvals": records})
        post = postprocess(
            "RA-JAK", extracted, term, sources=sources, audit=AuditLog(tmp_path / name), approvals=altered,
            environment="TEST",
        )  # fmt: skip
        assert target not in _released(post), name
        assert _released(post) == {a.criterion for a in approvals} - {target}, name


@pytest.mark.parametrize("environment", ["PRODUCTION", "VALIDATION", " production ", "unset"])
def test_a_shipped_approval_is_refused_off_a_test_box(environment: str, term: Terminology, tmp_path: Path) -> None:
    box = environment_name({}) if environment == "unset" else environment
    extracted, sources = _protocol("GZQO")
    assert pa.shipped_approvals("GZQO", box) == ()
    approvals = pa.shipped_approvals("GZQO", "TEST")
    post = postprocess(
        "GZQO", extracted, term, sources=sources, audit=AuditLog(tmp_path), approvals=approvals, environment=box
    )
    assert not _released(post)
    assert not {c.id for c in compiled(post.criteria)} & {a.criterion for a in approvals}


def test_a_shipped_approval_is_refused_for_another_protocol(term: Terminology, tmp_path: Path) -> None:
    assert pa.shipped_approvals("TRIAL", "TEST") == ()
    extracted, sources = _protocol("GZQO")
    # the same records, moved to a protocol that is not one of the four synthetic ones
    moved = [
        {**a.record(), "protocol": "GZQO2", "criterion": a.criterion.replace("GZQO-", "GZQO2-")}
        for a in pa.shipped_approvals("GZQO", "TEST")
    ]
    approvals = pa.parse_approvals({"form": pa.FORM, "approvals": moved})
    post = postprocess(
        "GZQO2", extracted, term, sources=sources, audit=AuditLog(tmp_path), approvals=approvals, environment="TEST"
    )
    assert not _released(post)
    # The same records as a person's approvals apply: only the shipped basis is bound to the four protocols.
    person = [{**r, "basis": "person", "label": pa.PERSON_LABEL, "recorded_by": "reviewer A", "actor": "reviewer A"}
              for r in moved]  # fmt: skip
    post = postprocess(
        "GZQO2", extracted, term, sources=sources, audit=AuditLog(tmp_path / "person"),
        approvals=pa.parse_approvals({"form": pa.FORM, "approvals": person}), environment="PRODUCTION",
    )  # fmt: skip
    assert _released(post) == {a.criterion for a in approvals}


def _malformed() -> dict[str, Callable[[dict[str, Any]], Any]]:
    def first(change: Callable[[dict[str, Any]], dict[str, Any]]) -> Callable[[dict[str, Any]], Any]:
        return lambda body: {**body, "approvals": [change(body["approvals"][0]), *body["approvals"][1:]]}

    return {
        "not JSON": lambda body: "{not json",
        "another form": lambda body: {**body, "form": "trialbox.presence-approvals/0"},
        "an unknown field": first(lambda r: {**r, "approved": True}),
        "a missing field": first(lambda r: {k: v for k, v in r.items() if k != "text_sha256"}),
        "a hash of other text": first(lambda r: {**r, "text": r["text"] + " "}),
        "the label removed": first(lambda r: {**r, "label": "approved"}),
        "another recorder": first(lambda r: {**r, "recorded_by": "crc1@hospa.test"}),
        "a bad date": first(lambda r: {**r, "date": "2026-13-40"}),
        "logic that is not IR": first(lambda r: {**r, "logic": {"domain": "condition"}}),
        "a negated flag": first(lambda r: {**r, "flags": ["negated_logic_rewritten"]}),
        "a duplicate": lambda body: {**body, "approvals": [body["approvals"][0], *body["approvals"]]},
        "another protocol's entry": first(lambda r: {**r, "protocol": "RA-JAK", "criterion": "RA-JAK-EXC-06"}),
    }


@pytest.mark.parametrize("damage", list(_malformed()))
def test_a_malformed_approvals_file_refuses_with_one_key(
    damage: str,
    env: dict[str, Any],  # noqa: F811 (compiler service fixture)
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    body = json.loads((pa.SHIPPED_DIR / "GZQO.json").read_text(encoding="utf-8"))
    broken = _malformed()[damage](body)
    folder = tmp_path / "shipped"
    folder.mkdir()
    (folder / "GZQO.json").write_text(broken if isinstance(broken, str) else json.dumps(broken), encoding="utf-8")
    monkeypatch.setattr(pa, "SHIPPED_DIR", folder)
    with pytest.raises(pa.PresenceApprovalsRefused) as refused:
        pa.shipped_approvals("GZQO", "TEST")
    assert refused.value.key == pa.REFUSED == "compile.presence_approvals_invalid"
    assert set(pa.REFUSAL_TEXT) == {"en", "zh-TW", "ja"} and len(set(pa.REFUSAL_TEXT.values())) == 3
    # the compile refuses before any line is extracted: no fallback, no release
    events = env["tmp"] / "audit"
    with pytest.raises(CompileFailed) as failed:
        _compile(env)
    assert failed.value.step == "presence_approvals" and pa.REFUSED in str(failed.value)
    rows = [json.loads(r) for p in events.glob("*.jsonl") for r in p.read_text().splitlines()]
    assert not [r for r in rows if r["event"] == "compile.presence_admitted"]


def test_the_label_travels_to_the_review_the_report_the_audit_and_the_approved_ruleset(
    env: dict[str, Any],  # noqa: F811 (compiler service fixture)
) -> None:
    res = _compile(env)
    approvals = {a.criterion: a for a in pa.shipped_approvals("GZQO", "TEST")}
    by_id = {c.id: c for c in res.criteria}
    for cid, approval in approvals.items():
        note = pa.release_note(by_id[cid])
        assert by_id[cid] in compiled(res.criteria) and note == approval.release_note()
        assert "released_by: recorded_approval" in note and pa.SYNTHETIC_LABEL in note and pa.SHIPPED_BY in note
    # the lines the plain rule released, and the held lines, carry no such note
    assert {c.id for c in res.criteria if pa.release_note(c)} == set(approvals)
    assert by_id["GZQO-EXC-05"].class_ == "human" and not pa.release_note(by_id["GZQO-EXC-05"])
    # the review report the person receives (review.html as the compile stored it)
    assert res.review_html_key
    html = env["store"].get(res.review_html_key).decode()
    assert html.count(pa.SYNTHETIC_LABEL) == len(approvals)
    rows = [json.loads(r) for p in (env["tmp"] / "audit").glob("*.jsonl") for r in p.read_text().splitlines()]
    admitted = {r["detail"]["criterion"]: r["detail"] for r in rows if r["event"] == "compile.presence_admitted"}
    for cid in approvals:
        assert admitted[cid]["basis"] == "recorded_approval"
        assert admitted[cid]["approval_label"] == pa.SYNTHETIC_LABEL
    assert {admitted[c]["basis"] for c in ("GZQO-EXC-01", "GZQO-EXC-02")} == {"text"}
    # a person's approval of the draft keeps the note under the person's own comment
    out = _approve(env, _decisions(env["store"], res.review_xlsx_key))
    kept = {c.id: c for c in out.criteria or []}
    for cid, approval in approvals.items():
        review = kept[cid].review
        assert review is not None and review.status == "approved"
        assert pa.release_note(kept[cid]) == approval.release_note()
