"""T-504 scenario T2: the ``rajak`` archetype, the Taiwanese rheumatology site and the RA-JAK ruleset.

* the ``tw-ra`` site passes the synthetic-hospital checks; no ``rajak`` rate cell is out of tolerance;
* the two planted states (herpes zoster, venous thromboembolism) have coded, note-only and negated patients;
* the notes are Traditional Chinese or English only; the gold covers every planted state;
* the protocol document parses (zh-TW) to the cassette's text, and the committed ruleset is what the current compiler
  makes of it; its labels are in en, ja and zh-TW for the criterion text it has.
"""

from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.synth import rajak
from tools.synth.generator import RATES, Generator

ROOT = Path(__file__).resolve().parents[2]
REF = date(2026, 11, 1)
DOC = "RA-JAK_試驗計畫書_v1.pdf"
KANA = tuple(range(0x3040, 0x3100))  # hiragana and katakana: never on a Taiwanese site


@pytest.fixture(scope="module")
def tw_ra(tmp_path_factory: pytest.TempPathFactory) -> Any:
    from tools.synth_hospital import run

    return run(tmp_path_factory.mktemp("twra"), profile="tw-ra", ref_date=REF)


def test_tw_ra_site_passes_the_checks_and_every_rajak_rate(tw_ra: Any) -> None:
    assert tw_ra.passed, tw_ra.failures
    cells = [r for r in tw_ra.rates if r["archetype"] == "rajak"]
    assert len(cells) == sum(len(v) for v in RATES["rajak"].values())
    # a cell is checked when the site holds enough patients for the tolerance; the others are too small, never off
    bad = [r for r in cells if r["status"] != "ok" and not str(r["status"]).startswith("skipped (n<")]
    assert not bad and sum(1 for r in cells if r["status"] == "ok") >= 40, bad
    (site,) = tw_ra.summary["sites"]
    assert site["patients"] == 1500
    for crit in rajak.NOTES:  # every mixed criterion has planted yes and no sentences
        assert site["findings"].get(f"{crit}=yes", 0) > 20 and site["findings"].get(f"{crit}=no", 0) > 20, crit


def test_the_planted_states_and_the_note_languages(tw_ra: Any) -> None:
    site = tw_ra.out / "tw-ra"
    states = json.loads((site / "states.json").read_text(encoding="utf-8"))
    rj = [s for s in states.values() if s.get("archetype") == "rajak"]
    for attr, kinds in (("zoster", ("coded_recent", "note_recent", "negated")), ("vte", ("coded_dvt", "note_only"))):
        for k in kinds:
            assert sum(1 for s in rj if s[attr] == k) > 10, (attr, k)
    langs = {json.loads(x)["lang"] for x in (site / "gold" / "notes.jsonl").read_text(encoding="utf-8").splitlines()}
    assert langs <= {"zh-TW", "en"} and "zh-TW" in langs
    text = (site / "note.csv").read_text(encoding="utf-8")
    assert not any(ord(ch) in KANA for ch in text)
    assert rajak.SENTENCES.keys() == {"zh-TW", "en"}


def test_the_gold_covers_every_planted_state() -> None:
    covered: dict[str, tuple[str, set[str]]] = {k: (a, set(v)) for k, (a, v) in rajak.STRUCTURED.items()}
    covered |= {k: (a, set(v)) for k, (a, v) in rajak.NOTES.items()}
    for crit, (attr, answers) in covered.items():
        planted = set(RATES["rajak"][attr]) | ({"na"} if attr == "pregnancy" else set())
        assert answers == planted, crit
    # a coded zoster or thromboembolism rules a patient out; one in a note alone never does on the codes
    base = {a: next(k for k, v in ans.items() if v is (rajak.KINDS[c] == "inclusion")) for c, (a, ans) in
            rajak.STRUCTURED.items()}  # fmt: skip
    base |= {"csdmard_response": "yes", "ahbc": "neg"}
    assert rajak.coded_candidate(base)
    assert not rajak.coded_candidate({**base, "zoster": "coded_recent"})
    assert not rajak.coded_candidate({**base, "vte": "coded_pe"})
    assert rajak.coded_candidate({**base, "zoster": "note_recent", "vte": "note_only"})
    assert rajak.expected({**base, "zoster": "note_recent"})["RA-JAK-EXC-06/notes"] == "yes"


def test_a_generator_without_the_mix_has_no_rajak_patient() -> None:
    g = Generator(3, "X", REF, 60, "9", style="TW")
    assert not any(s.get("archetype") == "rajak" for s in g.run().states.values())


# ------------------------------------------------------------------------------------------------ the ruleset
def test_document_parses_to_the_cassette_text() -> None:
    from doc_parser.parser import parse
    from llm_stub.handlers import norm

    cas = json.loads((ROOT / "services/llm_stub/cassettes/ir_extract/RA-JAK.json").read_text(encoding="utf-8"))
    for name in (DOC, DOC.replace(".pdf", ".docx")):
        parsed = parse((ROOT / "tests/fixtures/protocols" / name).read_bytes(), name)
        assert parsed.language == "zh-TW", name
        got = [norm(x) for x in parsed.ie_block.inclusion + parsed.ie_block.exclusion]
        want = [norm(x["text"]) for x in cas["criteria"] if x["kind"] == "inclusion"]
        want += [norm(x["text"]) for x in cas["criteria"] if x["kind"] == "exclusion"]
        assert got == want, name


def test_docx_regenerates_byte_for_byte(tmp_path: Path) -> None:
    from tools import make_protocol_docs as mpd

    spec = mpd.TW_DOCS["RA-JAK"]
    inc, exc = mpd.criteria("RA-JAK")
    out = tmp_path / f"{spec['file']}.docx"
    mpd.write_docx_ja(out, spec, inc, exc)
    assert out.read_bytes() == (ROOT / "tests/fixtures/protocols" / out.name).read_bytes()


def _strip(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip(v) for k, v in obj.items() if k not in ("review", "at", "evaluated_at")}
    return obj


def test_committed_ruleset_is_the_current_compilers_output(tmp_path: Path) -> None:
    """Compile the zh-TW protocol document again (stub model = the cassette, Asia/Taipei) and compare the criteria,
    value sets, SQL and CQL with the committed ruleset."""
    import tb_contracts as c
    from criteria_compiler.repo import RulesetRepo
    from criteria_compiler.service import Compiler, CompilerDeps
    from criteria_compiler.terminology.mapper import Terminology
    from doc_parser.parser import parse
    from fastapi.testclient import TestClient
    from llm_stub.app import app as stub
    from tb_common.audit import AuditLog
    from tb_common.llm import LlmClient
    from tb_common.objstore import FsStore

    from tests.unit.test_compiler_service import FakeGate

    rid = "RA-JAK"
    seed = tmp_path / "seed"
    shutil.copytree(ROOT / "rulesets", seed, ignore=shutil.ignore_patterns(rid))
    store = FsStore(tmp_path / "obj")
    audit = AuditLog(tmp_path / "audit")
    llm = LlmClient("http://stub/v1", "stub", audit=audit)
    llm.http = TestClient(stub)
    comp = Compiler(
        CompilerDeps(
            store=store,
            repo=RulesetRepo(tmp_path / "repo", seed),
            llm=llm,
            term=Terminology(),
            settings_thresholds={"equivalence_min_pct": 98.0},
            tz="Asia/Taipei",
            audit=audit,
            equivalence=FakeGate(),
        )
    )
    parsed = parse((ROOT / "tests" / "fixtures" / "protocols" / DOC).read_bytes(), DOC)
    store.put("attachments/T/parsed.json", c.dump_json(parsed).encode())
    res = comp.compile(
        c.CompileRequest(
            job_id="01JTEST0000000000000000000",
            ruleset=rid,
            parsed_doc_key="attachments/T/parsed.json",
            kind="trial",
            version="1.0.0",
            requested_by="crc1@hospa.test",
            options={"index_date": "2026-11-02"},
        )
    )
    assert not res.needs_review and not [w for w in res.warnings or [] if "translator" not in w], res.warnings
    assert res.branch
    built = dict(comp.d.repo.files(res.branch, f"{rid}/"))
    have = ROOT / "rulesets" / rid
    ir = sorted(p for p in built if "/ir/" in p)
    assert [Path(p).name for p in ir] == sorted(p.name for p in (have / "ir").glob("*.json"))
    for p in ir:
        assert _strip(json.loads(built[p])) == _strip(json.loads((have / "ir" / Path(p).name).read_bytes())), p
    for p in (x for x in built if "/valuesets/" in x):
        vs = {k: v for k, v in json.loads(built[p]).items() if k != "status"}
        assert vs == {
            k: v for k, v in json.loads((have / "valuesets" / Path(p).name).read_bytes()).items() if k != "status"
        }, p
    assert built[f"{rid}/sql/{rid}.sql"].decode() == (have / "sql" / f"{rid}.sql").read_text(encoding="utf-8")
    for p in (x for x in built if x.endswith(".cql")):
        assert built[p].decode() == (have / "cql" / Path(p).name).read_text(encoding="utf-8"), p


def test_manifest_split_and_labels_in_three_languages() -> None:
    from tb_common.ruleset import Ruleset

    rs = Ruleset.load(ROOT / "rulesets" / "RA-JAK")
    assert rs.manifest.language == "zh-TW" and rs.manifest.kind == "trial" and rs.manifest.status == "approved"
    by = rs.by_id()
    assert {k for k, v in by.items() if v.class_ == "mixed"} == set(rajak.NOTES)
    assert {k for k, v in by.items() if v.class_ == "human"} == set(rajak.HUMAN)
    assert set(by) == set(rajak.KINDS)
    labels = yaml.safe_load((ROOT / "rulesets" / "RA-JAK" / "labels.yaml").read_text(encoding="utf-8"))["criteria"]
    assert set(labels) == set(by)
    for cid, crit in by.items():
        e = labels[cid]
        assert e["source"] == crit.text, cid  # a label is shown only while the criterion has exactly this text
        assert (e.get("todo_source") or None) == (crit.action or None), cid
        for lang in ("en", "ja", "zh-TW"):
            assert e[lang]["label"] and e[lang]["text"], (cid, lang)
            assert bool(e[lang].get("todo")) == bool(crit.action), (cid, lang)
    # the planted states' criteria in Traditional Chinese
    assert labels["RA-JAK-EXC-06"]["zh-TW"]["label"] == "12個月內帶狀皰疹"
    assert labels["RA-JAK-EXC-07"]["zh-TW"]["label"] == "靜脈血栓栓塞病史"
