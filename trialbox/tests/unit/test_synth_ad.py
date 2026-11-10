"""T-503 scenario J1: the ``ad`` archetype, the Japanese memory-clinic site and the AD-MAB / NEUR-COH rulesets.

* the default generator is unchanged (site A regenerates byte for byte), so the committed fixtures stay valid;
* the ``jp-ad`` site passes the synthetic-hospital checks, every ``ad`` rate cell is checked and within tolerance;
* the Japanese site carries no Chinese note text (UX-004);
* the gold covers every planted state;
* the committed AD-MAB and NEUR-COH rulesets are what the current compiler makes of the Japanese protocol documents.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from tools.synth import ad
from tools.synth import notes as zh
from tools.synth.generator import RATES, Generator, generate

ROOT = Path(__file__).resolve().parents[2]
REF = date(2026, 11, 1)
# characters written only in Chinese (the Japanese forms differ: 医 断 説 発 薬 検 続 応 体 関 歳 与 為 両 対 区 号)
ZH_ONLY = re.compile("[醫斷說發藥檢續應體關歲與為兩對區號]")


@pytest.fixture(scope="module")
def jp_ad(tmp_path_factory: pytest.TempPathFactory) -> Any:
    from tools.synth_hospital import run

    return run(tmp_path_factory.mktemp("jpad"), profile="jp-ad", ref_date=REF)


def test_default_generator_is_unchanged(tmp_path: Path) -> None:
    """Site A from the default generator equals the committed fixture: the ad archetype is additive."""
    from tools.make_fixtures import write_site

    write_site(generate(42, "DEMO-A", date(2026, 10, 5), 600, "1"), tmp_path)
    committed = ROOT / "tests" / "fixtures" / "synthetic_patients" / "site-a"
    for name in ("patient", "practitioner", "encounter", "diagnosis", "medication", "note", "report", "lab"):
        assert (tmp_path / f"{name}.csv").read_bytes() == (committed / f"{name}.csv").read_bytes(), name
    assert (tmp_path / "states.json").read_bytes() == (committed / "states.json").read_bytes()


def test_jp_ad_site_passes_the_checks_and_every_ad_rate(jp_ad: Any) -> None:
    assert jp_ad.passed, jp_ad.failures
    cells = [r for r in jp_ad.rates if r["archetype"] == "ad"]
    assert len(cells) == sum(len(v) for v in RATES["ad"].values())
    assert all(r["status"] == "ok" for r in cells), [r for r in cells if r["status"] != "ok"]
    (site,) = jp_ad.summary["sites"]
    assert site["site_id"] == "JP-AD" and site["patients"] == 2500
    for crit in ad.NOTES:  # every note criterion has planted yes and no sentences
        assert site["findings"].get(f"{crit}=yes", 0) > 20 and site["findings"].get(f"{crit}=no", 0) > 20, crit


def test_no_chinese_note_text_on_the_japanese_site(jp_ad: Any) -> None:
    site = jp_ad.out / "jp-ad"
    zh_sentences = [s for s in zh.FILLER if len(s) > 8] + [zh.no_flare_sentence(), zh.current_flare_sentence()]
    langs = set()
    with (site / "note.csv").open(encoding="utf-8") as fh:
        notes = list(csv.DictReader(fh))
    for gold in (site / "gold" / "notes.jsonl").read_text(encoding="utf-8").splitlines():
        langs.add(json.loads(gold)["lang"])
    assert langs == {"ja", "en"}
    assert len(notes) > 2000
    for n in notes:
        assert not ZH_ONLY.search(n["text"]), (n["note_no"], ZH_ONLY.findall(n["text"]))
        assert not any(s in n["text"] for s in zh_sentences), n["note_no"]
    with (site / "practitioner.csv").open(encoding="utf-8") as fh:
        names = [r["name"] for r in csv.DictReader(fh)]
    assert names and not any(ZH_ONLY.search(x) or "示範" in x for x in names)


def test_a_zh_site_cannot_hold_alzheimer_patients() -> None:
    from tools.synth_hospital import DEFAULT_LANG_MIX, parse_sites

    with pytest.raises(SystemExit):
        parse_sites("tw-ad:TW:100:mix_jp_ad", 1, DEFAULT_LANG_MIX)
    g = Generator(1, "X", REF, 30, "9", style="TW", mix="mix_jp_ad")
    with pytest.raises(ValueError, match="Japanese or English"):
        g.run()


def test_the_gold_covers_every_planted_state() -> None:
    covered: dict[str, tuple[str, set[str]]] = {k: (a, set(v)) for k, (a, v) in ad.STRUCTURED.items()}
    covered |= {k: (a, set(v)) for k, (a, v) in ad.NOTES.items()}
    for crit, (attr, answers) in covered.items():
        if attr == "archetype":
            continue
        assert answers == set(RATES["ad"][attr]), crit
    assert set(RATES["ad"]["partner"]) == {"yes", "no", "no_info"}
    # most patients have no amyloid result: the list must keep them, never drop them
    assert ad.NOTES["AD-MAB-INC-05"][1]["absent"] == "unknown"
    assert float(RATES["ad"]["amyloid"]["absent"]) > 0.5


def test_unknown_amyloid_never_excludes_on_the_gold() -> None:
    base = {
        "archetype": "ad",
        "age_band": "in",
        "ad_dx": "mci",
        "anticoag": "none",
        "stroke": "none",
        "creatinine": "normal",
        "mmse": "in_range",
        "cdr": "half",
        "microbleeds": "few",
        "partner": "yes",
    }
    for amy in ("absent", "not_done"):
        st = {**base, "amyloid": amy}
        assert ad.tier(st, notes_read=True) == "review" and ad.tier(st, notes_read=False) == "review"
    assert ad.tier({**base, "amyloid": "pet_pos"}, notes_read=True) == "high"
    assert ad.tier({**base, "amyloid": "pet_neg"}, notes_read=True) == "excluded"
    assert ad.tier({**base, "amyloid": "absent", "anticoag": "current"}, notes_read=False) == "excluded"


# ------------------------------------------------------------------------------------------------ the rulesets
def _strip(obj: Any) -> Any:
    """A committed file without the approval stamps (who and when), which a rebuild changes."""
    if isinstance(obj, dict):
        return {k: _strip(v) for k, v in obj.items() if k not in ("review", "at", "evaluated_at")}
    return obj


@pytest.mark.parametrize(
    ("rid", "doc", "kind"),
    [("AD-MAB", "AD-MAB_治験実施計画書_v1.docx", "trial"), ("NEUR-COH", "NEUR-COH_登録計画書_v1.docx", "cohort")],
)
def test_committed_ruleset_is_the_current_compilers_output(tmp_path: Path, rid: str, doc: str, kind: str) -> None:
    """Compile the Japanese protocol document again (stub model = the cassette, site time zone Asia/Tokyo) and
    compare the criteria, value sets, SQL and CQL with the committed ruleset."""
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
            tz="Asia/Tokyo",
            audit=audit,
            equivalence=FakeGate(),
        )
    )
    data = (ROOT / "tests" / "fixtures" / "protocols" / doc).read_bytes()
    parsed = parse(data, doc)
    assert parsed.language == "ja"
    store.put("attachments/T/parsed.json", c.dump_json(parsed).encode())
    res = comp.compile(
        c.CompileRequest(
            job_id="01JTEST0000000000000000000",
            ruleset=rid,
            parsed_doc_key="attachments/T/parsed.json",
            kind="trial" if kind == "trial" else "cohort",
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
        vs = {k: v for k, v in json.loads(built[p]).items() if k != "status"}  # draft until approval
        assert vs == {
            k: v for k, v in json.loads((have / "valuesets" / Path(p).name).read_bytes()).items() if k != "status"
        }, p
    assert built[f"{rid}/sql/{rid}.sql"].decode() == (have / "sql" / f"{rid}.sql").read_text(encoding="utf-8")
    for p in (x for x in built if x.endswith(".cql")):
        assert built[p].decode() == (have / "cql" / Path(p).name).read_text(encoding="utf-8"), p
    if rid == "AD-MAB":  # a Japanese site's plain "eGFR" is the JSN 2009 equation (D-149)
        egfr = json.loads((have / "ir" / "AD-MAB-EXC-04.json").read_text(encoding="utf-8"))
        assert egfr["logic"]["derived"] == "egfr_jsn"


def test_japanese_protocol_documents_are_reproducible(tmp_path: Path) -> None:
    """The DOCX regenerates byte for byte from the cassettes; the PDF (when the fonts are fetched) to the same text."""
    from tools import make_protocol_docs as mpd

    have = ROOT / "tests" / "fixtures" / "protocols"
    for rid, spec in mpd.JA_DOCS.items():
        inc, exc = mpd.criteria(rid)
        out = tmp_path / f"{spec['file']}.docx"
        mpd.write_docx_ja(out, spec, inc, exc)
        assert out.read_bytes() == (have / out.name).read_bytes(), out.name
        if (mpd.FONT_DIR / "NotoSansJP-Regular.ttf").exists():
            pdf = tmp_path / f"{spec['file']}.pdf"
            mpd.write_pdf_ja(pdf, spec, inc, exc)
            # the text, not the bytes: the embedded font subset depends on the font build the machine fetched
            assert _pdf_text(pdf.read_bytes(), pdf.name) == _pdf_text((have / pdf.name).read_bytes(), pdf.name)


def _pdf_text(data: bytes, name: str) -> list[str]:
    from doc_parser.parser import parse

    parsed = parse(data, name)
    assert parsed.language == "ja"
    return ["".join(x.split()) for x in parsed.ie_block.inclusion + parsed.ie_block.exclusion]


def test_docx_parses_to_the_cassette_text() -> None:
    from doc_parser.parser import parse
    from llm_stub.handlers import norm

    for rid, name in (("AD-MAB", "AD-MAB_治験実施計画書_v1.docx"), ("NEUR-COH", "NEUR-COH_登録計画書_v1.docx")):
        cas = json.loads((ROOT / f"services/llm_stub/cassettes/ir_extract/{rid}.json").read_text(encoding="utf-8"))
        parsed = parse((ROOT / "tests/fixtures/protocols" / name).read_bytes(), name)
        got = [norm(x) for x in parsed.ie_block.inclusion + parsed.ie_block.exclusion]
        want = [norm(x["text"]) for x in cas["criteria"] if x["kind"] == "inclusion"]
        want += [norm(x["text"]) for x in cas["criteria"] if x["kind"] == "exclusion"]
        assert got == want, rid


def test_manifests_are_japanese_and_unknown_amyloid_is_a_note_question() -> None:
    from tb_common.ruleset import Ruleset

    rs = Ruleset.load(ROOT / "rulesets" / "AD-MAB")
    assert rs.manifest.language == "ja" and rs.manifest.kind == "trial" and rs.manifest.status == "approved"
    by = rs.by_id()
    assert by["AD-MAB-INC-05"].class_ == "note" and by["AD-MAB-INC-06"].class_ == "human"
    assert {c.id for c in rs.criteria if c.class_ == "structured"} == {
        cid for cid in ad.STRUCTURED if cid.startswith("AD-MAB-")
    }
    coh = Ruleset.load(ROOT / "rulesets" / "NEUR-COH")
    assert coh.manifest.kind == "cohort" and coh.manifest.language == "ja"
