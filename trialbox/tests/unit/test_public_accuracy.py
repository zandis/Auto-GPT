"""The public accuracy run's fetchers, item builders and scorer (``tools/public_accuracy``), on synthetic fixtures.

No network, no model and no box: the fixtures in ``tests/fixtures/public_accuracy`` are made up in the sources' shapes.
The plumbing proof on the stand-in models (``python -m tools.public_accuracy dryrun``) is run by hand, not here.
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from pathlib import Path

import pytest

from tools.public_accuracy import box, plan, score, sets, site
from tools.public_accuracy import sources as src

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "public_accuracy"


# ---------------------------------------------------------------- sources
def test_every_source_is_pinned_https_and_licensed() -> None:
    assert len({s.id for s in src.SOURCES}) == len(src.SOURCES)
    for s in src.SOURCES:
        assert re.fullmatch(r"[0-9a-f]{64}", s.sha256), s.id
        assert s.url.startswith("https://"), s.id
        assert s.colour in ("green", "yellow") and s.licence and s.attribution and s.bytes > 0, s.id
        assert s.colour == "green" or s.caveat, f"{s.id}: a yellow set states its caveat"
    assert {s.set for s in src.SOURCES} >= {"trec", "sigir", "tfda", "chia", "tcga"}
    assert "bioscope-clinical" in src.BLOCKED  # looked at, not usable: its clinical text is masked


def test_fetch_keeps_a_pinned_file_and_fetches_otherwise(tmp_path: Path) -> None:
    s = src.Source(
        "f.txt",
        "x",
        "https://example.invalid/f.txt",
        __import__("hashlib").sha256(b"ok").hexdigest(),
        2,
        "CC0",
        "CC0-1.0",
        "green",
        "",
        "a",
    )
    calls: list[str] = []

    def get(url: str, out: Path, sha: str) -> None:
        calls.append(url)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"ok")

    assert src.fetch_one(s, tmp_path, get=get) == "fetched"
    assert src.fetch_one(s, tmp_path, get=get) == "kept"
    assert calls == [s.url]
    (tmp_path / "x" / "f.txt").write_bytes(b"changed")  # a file that is not the pin is fetched again
    assert src.fetch_one(s, tmp_path, get=get) == "fetched"


def test_polite_get_spaces_requests_to_one_host() -> None:
    now = [100.0]
    slept: list[float] = []
    src._LAST.clear()

    def sleep(s: float) -> None:
        slept.append(round(s, 2))
        now[0] += s

    for _ in range(3):
        src.polite_get("https://h.invalid/a", get=lambda u: b"x", sleep=sleep, clock=lambda: now[0], wait=3.0)
    assert slept == [3.0, 3.0]


# ---------------------------------------------------------------- readers
def test_criteria_lines_split_ncbi_bullets_and_numbered_zh() -> None:
    assert sets.criteria_lines("inclusion criteria: \n\n Age 18 or older \n\n Has asthma \n\n ") == [
        "Age 18 or older",
        "Has asthma",
    ]
    assert sets.criteria_lines("* ECOG \\<=2\n  continued here\n* Signed consent") == [
        "ECOG <=2 continued here",
        "Signed consent",
    ]
    assert sets.criteria_lines("1. 年滿 20 歲\n2. 確診為合成疾病\n納入條件") == ["年滿 20 歲", "確診為合成疾病"]
    inc, exc = sets.split_ctgov_criteria("Inclusion Criteria:\n\n* Adult\n* Asthma\n\nExclusion Criteria:\n\n* Smoker")
    assert inc == ["Adult", "Asthma"] and exc == ["Smoker"]


def test_placed_age_and_sex_lines() -> None:
    inc, notes = sets.placed_lines("18 Years", "6 Months", "FEMALE")
    assert inc == ["Aged 18 years or older", "Age <= 0.5 years", "Female participants only"] and notes
    assert sets.placed_lines(None, "N/A", "ALL") == ([], [])


def test_trec_topics_qrels_and_a_balanced_sample() -> None:
    pats = sets.trec_topics((FIX / "topics2021.xml").read_text(encoding="utf-8"), "2021")
    assert pats["trec2021:1"].age == 61 and pats["trec2021:1"].sex == "F" and pats["trec2021:3"].sex == "M"
    q23 = sets.trec_topics((FIX / "topics2023.xml").read_text(encoding="utf-8"), "2023")["trec2023:1"]
    assert q23.age == 52 and q23.sex == "F" and "definitive diagnosis: made-up condition" in q23.text
    pairs = sets.trec_qrels((FIX / "qrels2021.txt").read_text(encoding="utf-8"), "2021")
    assert len(pairs) == 6 and {p.label for p in pairs} == {"eligible", "excluded"}  # label 0 is not a pair
    s1, s2 = sets.trec_sample(pairs, 4, per_patient_min=1), sets.trec_sample(pairs, 4, per_patient_min=1)
    assert [(p.patient, p.trial) for p in s1] == [(p.patient, p.trial) for p in s2]  # seeded
    assert ("trec2021:1", "NCT90000001") in {(p.patient, p.trial) for p in s1}  # a trial judged twice comes first
    assert {p.patient for p in s1} == {"trec2021:1", "trec2021:2", "trec2021:3"} and len(s1) == 4


def test_tfda_quirks_are_cleaned(tmp_path: Path) -> None:
    i, e, issues = sets.tfda_clean("A &#8805; 1", "B")
    assert i == "A ≥ 1" and "html_entities" in issues
    block = "主要納入條件：\n●年滿 18 歲\n主要排除條件：\n●懷孕"
    i, e, issues = sets.tfda_clean(block, block)
    assert "duplicated_block" in issues and "unsplittable" not in issues
    assert sets.criteria_lines(i) == ["年滿 18 歲"] and sets.criteria_lines(e) == ["懷孕"]
    _, e2, issues2 = sets.tfda_clean("●年滿 18 歲", "●年滿 18 歲")
    assert e2 == "" and "unsplittable" in issues2
    d = tmp_path / "tfda"
    d.mkdir()
    with zipfile.ZipFile(d / "tfda_205_csv.zip", "w") as z:
        z.writestr("205_2.csv", "\ufeff" + (FIX / "tfda.csv").read_text(encoding="utf-8"))
    rows = {r.protocol: r for r in sets.read_tfda_rows(tmp_path)}
    assert set(rows) == {"SYN-001", "SYN-002", "SYN-003"}
    assert rows["SYN-001"].title == "合成試驗一" and rows["SYN-001"].inclusion == ["年滿 20 歲≥", "確診為合成疾病"]
    assert rows["SYN-002"].exclusion == ["懷孕"] and "unsplittable" in rows["SYN-003"].issues


def test_tfda_pairs_with_ctgov_by_protocol_number(tmp_path: Path) -> None:
    study = {
        "protocolSection": {
            "identificationModule": {
                "nctId": "NCT90000042",
                "orgStudyIdInfo": {"id": "SYN 001"},
                "briefTitle": "Synthetic",
            },
            "eligibilityModule": {
                "eligibilityCriteria": "Inclusion Criteria:\n\n* Adult\n\nExclusion Criteria:\n\n* Pregnant",
                "minimumAge": "20 Years",
            },
        }
    }
    asked: list[str] = []

    def get(url: str) -> bytes:
        asked.append(url)
        return json.dumps({"studies": [study]}).encode()

    assert sets.ctgov_by_protocol("SYN-001", tmp_path, get=get) == "NCT90000042"  # spaces and dashes ignored
    assert sets.ctgov_by_protocol("SYN-001", tmp_path, get=get) == "NCT90000042" and len(asked) == 1  # kept
    assert sets.ctgov_by_protocol("OTHER", tmp_path, get=get) is None  # the search hit names another protocol
    live = json.loads((tmp_path / "ctgov" / "LIVE.json").read_text(encoding="utf-8"))
    assert all(r["retrieved"] and len(r["sha256"]) == 64 for r in live.values())


def test_jrct_page_cells() -> None:
    inc, exc, title, ncts = sets.jrct_criteria((FIX / "jrct_page.html").read_text(encoding="utf-8"))
    assert inc == ["同意取得時の年齢が20歳以上のもの", "合成疾患と診断されたもの"]
    assert exc == ["妊娠中のもの", "他の治験に参加中のもの"] and ncts == ["NCT90000099"] and "synthetic" in title


def test_chia_line_features() -> None:
    inc = sets.chia_line_features((FIX / "chia_inc.txt").read_text(), (FIX / "chia_inc.ann").read_text())
    exc = sets.chia_line_features((FIX / "chia_exc.txt").read_text(), (FIX / "chia_exc.ann").read_text())
    assert inc[0]["features"] == ["person", "value"] and inc[1]["features"] == ["condition"]
    assert exc[0]["features"] == ["drug", "negation", "temporal"]


# ---------------------------------------------------------------- the item builder
def _bundle() -> sets.Bundle:
    b = sets.Bundle("trec")
    b.patients = {
        "trec2021:1": sets.Patient("trec2021:1", "en", "A 61-year-old woman with diabetes.", 61, "F"),
        "trec2021:2": sets.Patient("trec2021:2", "en", "A man with asthma.", None, "M"),
    }
    b.trials = {
        "NCT90000001": sets.Trial(
            "NCT90000001", "en", "Synthetic", ["Diabetes"], ["Pregnancy"], ["Aged 18 years or older"]
        ),
        "TFDA:SYN-001": sets.Trial("TFDA:SYN-001", "zh-Hant", "合成", ["年滿 20 歲"], ["懷孕"], pair_key="NCT90000001"),
    }
    b.pairs = [
        sets.Pair("trec2021:1", "NCT90000001", "eligible", "trec2021"),
        sets.Pair("trec2021:2", "NCT90000001", "excluded", "trec2021"),
    ]
    b.criteria = [sets.CriterionGold("trec2021:1", "NCT90000001", "exclusion", "Pregnancy", "not excluded", [0])]
    return b


def test_site_build_keeps_the_gold_out_of_the_site(tmp_path: Path) -> None:
    summary = site.build(_bundle(), tmp_path)
    s, g = tmp_path / "site", tmp_path / "gold"
    ids = json.loads((g / "ids.json").read_text(encoding="utf-8"))
    assert ids["rulesets"] == {"NCT90000001": "NCT90000001", "TFDA:SYN-001": "TW0001"}
    assert all(site.RULESET_ID.match(r) for r in ids["rulesets"].values())
    site_text = "".join(f.read_text(encoding="utf-8") for f in s.rglob("*") if f.is_file())
    for word in ("eligible", "excluded", "not excluded", "trec2021:1"):
        assert word not in site_text, f"gold word {word!r} leaked into the site"
    pats = list(csv.DictReader((s / "hospital" / "patient.csv").open(encoding="utf-8-sig")))
    assert [p["mrn"] for p in pats] == ["71000001", "71000002"] and pats[1]["birth_date"] == ""  # never guessed
    appts = list(csv.DictReader((s / "hospital" / "appointment.csv").open(encoding="utf-8-sig")))
    pi = ids["investigators"]["NCT90000001"]
    assert {a["mrn"] for a in appts if a["staff_id"] == pi} == {"71000001", "71000002"}
    prof = (s / "profiles" / "NCT90000001.yaml").read_text(encoding="utf-8")
    assert f'practitioners: ["{pi}"]' in prof
    zh = (s / "protocols" / "TW0001.txt").read_text(encoding="utf-8")
    assert "納入條件\n1. 年滿 20 歲" in zh and "排除條件\n1. 懷孕" in zh
    en = (s / "protocols" / "NCT90000001.txt").read_text(encoding="utf-8")
    assert "1. Diabetes\n2. Aged 18 years or older" in en  # the placed age line after the source's lines
    gold_pairs = [json.loads(x) for x in (g / "pairs.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {(p["mrn"], p["ruleset"], p["label"]) for p in gold_pairs} == {
        ("71000001", "NCT90000001", "eligible"),
        ("71000002", "NCT90000001", "excluded"),
    }
    assert ids["pair_of"] == {"TW0001": "NCT90000001", "NCT90000001": "TW0001"} or ids["pair_of"]["TW0001"]
    assert summary["appointments"] == 2
    assert (s / "hospital" / "note.csv").read_bytes().startswith(b"\xef\xbb\xbf")  # UTF-8 with a BOM, unambiguous


def test_a_compile_only_set_gets_one_placeholder_chart(tmp_path: Path) -> None:
    b = sets.Bundle("chia")
    b.trials = {"NCT90000007": sets.Trial("NCT90000007", "en", "x", ["Adult"], [])}
    site.build(b, tmp_path)
    rows = list(csv.DictReader((tmp_path / "site" / "hospital" / "note.csv").open(encoding="utf-8-sig")))
    assert len(rows) == 1 and rows[0]["text"].startswith("Placeholder chart")


# ---------------------------------------------------------------- the scorer
def test_clopper_pearson_known_values() -> None:
    assert score.clopper_pearson(0, 10) == (0.0, 0.3085)
    assert score.clopper_pearson(5, 10) == (0.1871, 0.8129)
    assert score.clopper_pearson(10, 10) == (0.6915, 1.0)
    assert score.clopper_pearson(0, 0) == (0.0, 1.0)


def _answers(tmp_path: Path) -> tuple[Path, Path]:
    site.build(_bundle(), tmp_path / "built")
    pid1, pid2 = score.pid_of("71000001"), score.pid_of("71000002")
    answers = {
        "NCT90000001": {
            "draft": [
                {"id": "NCT90000001-INC-01", "kind": "inclusion", "class": "note", "text": "Diabetes"},
                {"id": "NCT90000001-EXC-01", "kind": "exclusion", "class": "note", "text": "Pregnancy"},
            ],
            "screen": "done",
            "patients": {
                pid1: {
                    "tier": "excluded",
                    "verdicts": [
                        {"id": "NCT90000001-EXC-01", "verdict": "fail", "quote": "A 61-year-old woman with diabetes."}
                    ],
                },
                pid2: {"tier": "review", "verdicts": [{"id": "NCT90000001-INC-01", "verdict": "unknown"}]},
            },
        },
        "TW0001": {
            "draft": [
                {
                    "id": "TW0001-INC-01",
                    "kind": "inclusion",
                    "class": "structured",
                    "text": "年滿 20 歲",
                    "logic": {"domain": "demographic", "age": {"min": 20}},
                }
            ]
        },
    }
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "answers.json").write_text(json.dumps(answers, ensure_ascii=False), encoding="utf-8")
    return tmp_path / "built", tmp_path / "work"


def test_score_joins_by_ids_after_the_run(tmp_path: Path) -> None:
    built, work = _answers(tmp_path)
    r = score.score(built, work)
    en = r["pairs"]["summary"]["en"]
    assert en["eligible_lost"]["k"] == 1 and en["eligible_lost"]["n"] == 1  # the eligible patient was excluded
    assert en["excluded_caught"]["k"] == 0 and en["left_open"]["k"] == 1  # the excluded one left open
    assert en["wrong_exclusions"] == score.rate(1, 1)
    crit = r["criteria"]
    assert crit["wrong_exclusion"]["k"] == 1  # blocked on "Pregnancy" that the gold says does not apply
    cp = r["compile_pairs"]["rows"][0]
    assert cp["local"] == "TW0001" and cp["n_local"] == 1 and cp["n_en"] == 2 and cp["age_agree"] is False


def test_evidence_hit_against_the_deciding_sentence() -> None:
    sents = ["A 61-year-old woman.", "She has diabetes.", "No pregnancy."]
    assert score.evidence_hit("She has diabetes.", sents, [1]) is True
    assert score.evidence_hit("She has diabetes.", sents, [2]) is False
    assert score.evidence_hit(None, sents, [1]) is None


# ---------------------------------------------------------------- the box side (no box started)
def test_draft_criteria_read_from_the_review_zip() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(
            "R1/ir/R1-INC-01.json",
            json.dumps(
                {
                    "id": "R1-INC-01",
                    "kind": "inclusion",
                    "class": "structured",
                    "text": {"source": "Age 18"},
                    "logic": {"domain": "demographic"},
                }
            ),
        )
        z.writestr("R1/manifest.yaml", "id: R1\n")
        z.writestr("review.html", "<html/>")
    got = box.draft_criteria(buf.getvalue())
    assert got == [
        {
            "id": "R1-INC-01",
            "kind": "inclusion",
            "class": "structured",
            "text": "Age 18",
            "domain": "demographic",
            "logic": {"domain": "demographic"},
            "flags": [],
        }
    ]


def test_model_calls_counted_from_the_gateway_audit(tmp_path: Path) -> None:
    rows = [
        {"event": "llm.gateway.call", "prompt_version": "ir_extract@2"},
        {"event": "llm.gateway.call", "prompt_version": "judge@4"},
        {"event": "llm.gateway.call", "prompt_version": "judge@4"},
        {"event": "other"},
    ]
    (tmp_path / "a.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    assert box.llm_calls([tmp_path]) == {"ir_extract@2": 1, "judge@4": 2}


def test_the_run_lifts_only_the_daily_job_limit() -> None:
    assert box.RUN_SETTINGS == {"rate_limits_per_day": {"FEAS": 0, "SCREEN": 0}}


# ---------------------------------------------------------------- the plan's arithmetic
def test_hours_from_calls_and_measured_rates() -> None:
    from tools.complete_run import SINGLE_CALL_CPS

    r = plan.Row("x", "s", "en", 10, 2, 20, 5.0, 2, 12, 200, "g")
    h = plan.hours(r, box_s_per_protocol=None)
    assert h["hours_low"] == round(2 / SINGLE_CALL_CPS / 3600, 2)
    assert h["hours_high"] == round((12 / SINGLE_CALL_CPS + 200 / plan.SCREEN_CPS_16) / 3600, 2)
    assert pytest.approx((4.391 + 4.613) / 2, abs=1e-3) == plan.SCREEN_CPS_16
