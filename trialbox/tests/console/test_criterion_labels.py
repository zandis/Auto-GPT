"""T-507 (D-309; LLM-045, UX-009, LIFE-004): criterion labels, criterion text and to-dos in Japanese and Traditional
Chinese for the PoC rulesets, the label step required at approval, and the "test model" label on note answers.

The walk opens the investigator's and the coordinator's clinical pages (week list, patient page, candidate pages,
"criteria not matched", approval) in ja and zh-TW with the real GZQO criteria and finds no English word outside an
allow-list: the study's own words kept beside a translation (``data-original``), record quotes, and a fixed list of
codes, units and abbreviations that a Japanese or Taiwanese clinician reads as they are."""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest
import yaml
from console import ruleset_labels, studies
from console.backend import criteria_of
from tb_common.crypto import sha256_bytes
from tb_common.ruleset import Ruleset
from tb_contracts import Job, JobOutput

from tests.console.test_console_app import _ulid, box, login, name_pi, review_book  # noqa: F401 - box is a fixture
from tests.console.test_excluded_page import _with_excluded

ROOT = Path(__file__).resolve().parents[2]
PW = "criterion-labels-password-01"
# the PoC rulesets on master and the languages each ships beside the protocol's own (T-503 and T-504 add theirs)
POC = {"GZQO": ("ja", "zh-TW"), "GOUT-COH": ("ja", "en"), "RA-COH": ("ja", "en")}

# Words a ja or zh-TW clinician reads as they are: product and role abbreviations, codes, units and lab names used in
# Japanese and Taiwanese charts, the study code, and the test fixture's own data (user, doctor, department).
ALLOWED = {
    "TrialBox", "English", "TB_ENV", "TEST", "DEV", "D0", "IRB", "CRC", "SAE", "PI", "SCREEN",
    "GZQO", "BMI", "eGFR", "ACR", "EULAR", "HbA1c", "GLP-1", "GIP", "ALT", "MEN2", "CKD-EPI", "mg", "dL", "kg", "m²",
    "mL", "min", "mmHg", "U", "L", "ICD-10-CM", "DAS28", "HBsAg", "m",
    "walker", "Dr", "Lin", "DR-LIN", "RHEU",
}  # fmt: skip
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9²]*(?:[-_][A-Za-z0-9²]+)*")
_ID = re.compile(r"^[A-Z]+(?:-[A-Z]+)?-(?:INC|EXC)-\d+$")
_PSEUDONYM = re.compile(r"^[a-f]{8}$")
_VOID = {"br", "input", "img", "meta", "link", "hr", "col", "wbr", "source", "area", "base", "embed", "track"}


class _Seen(HTMLParser):
    """The text a reader sees, without what the allow-list lets through by its markup: the study's words beside a
    translation (``data-original``) and record quotes (``q``, ``blockquote``), plus scripts and styles."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[bool] = []
        self.out: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _VOID:
            return
        names = {k for k, _ in attrs}
        skip = tag in ("q", "blockquote", "script", "style", "title") or "data-original" in names
        self.stack.append(skip or (bool(self.stack) and self.stack[-1]))

    def handle_endtag(self, tag: str) -> None:
        if tag not in _VOID and self.stack:
            self.stack.pop()

    def handle_data(self, data: str) -> None:
        if not (self.stack and self.stack[-1]):
            self.out.append(data)


def english_words(page: str) -> list[str]:
    """Every English word a reader of a ja or zh-TW page sees outside the allow-list."""
    p = _Seen()
    p.feed(page)
    text = html.unescape(" ".join(p.out))
    return [
        w for w in _TOKEN.findall(text) if w not in ALLOWED and not _ID.match(w) and not _PSEUDONYM.match(w)
    ]  # fmt: skip


def _gzqo(b: dict[str, Any]) -> None:
    b["backend"].criteria = lambda rs: criteria_of(ROOT / "rulesets", rs)


def _approval_job(b: dict[str, Any], rows: list[tuple[Any, ...]]) -> Job:
    now = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
    jid = _ulid(977)
    book = review_book(rows)
    key = f"outputs/{jid}/review_GZQO_v1.1.0_r1.xlsx"
    b["backend"].objects[key] = book
    out = JobOutput(filename="review_GZQO_v1.1.0_r1.xlsx", sha256=sha256_bytes(book), minio_key=key, recipients=[],
                    tag="aggregate")  # fmt: skip
    job = Job(job_id=jid, type="FEAS", ruleset="GZQO", requested_by="crc@hospa.test", received_at=now,
              updated_at=now, state="awaiting_approval", ruleset_version="1.1.0", options={}, inputs=[],
              outputs=[out])  # fmt: skip
    added: Job = b["backend"].add_job(job)
    return added


def _gzqo_rows(*ids: str) -> list[tuple[Any, ...]]:
    by_id = {r["id"]: r for r in criteria_of(ROOT / "rulesets", "GZQO")}
    return [(i, by_id[i]["kind"], "structured", by_id[i]["text"], "VS_X: 1 one", 100, None) for i in ids]


# ---------------------------------------------------------------------------------------------- the shipped files
@pytest.mark.parametrize("rs", sorted(POC))
def test_every_poc_criterion_has_its_label_and_text_in_the_site_languages(rs: str) -> None:
    rows = criteria_of(ROOT / "rulesets", rs)
    assert rows, rs
    data = yaml.safe_load((ROOT / "rulesets" / rs / "labels.yaml").read_text(encoding="utf-8"))
    assert data["ruleset"] == rs and set(data["criteria"]) == {r["id"] for r in rows}
    for r in rows:
        for lang in POC[rs]:
            got = r["i18n"].get(lang) or {}
            assert got.get("label") and got.get("text"), (r["id"], lang)  # the source still matches the IR text
            assert len(got["label"]) <= 80  # the label editor's limit (D-120)
            if r["action"]:
                assert got.get("todo"), (r["id"], lang)
    # no verdict word about a patient in any shipped translation (T-506's list)
    from tb_common.wording import check

    for entry in data["criteria"].values():
        for lang in POC[rs]:
            assert check(" ".join(entry[lang].values())) == [], (rs, lang)


def test_a_changed_criterion_keeps_the_protocol_words_until_labelled_again(tmp_path: Path) -> None:
    (tmp_path / "GZQO").mkdir()
    (tmp_path / "GZQO" / "labels.yaml").write_text(
        "ruleset: GZQO\ncriteria:\n  GZQO-INC-05:\n    source: At least 2 gout flares within 12 months.\n"
        "    todo_source: confirm flare dates with patient\n"
        "    ja: {label: 発作2回以上, text: 12か月以内に発作2回以上。, todo: 発作の日付を確認する}\n",
        encoding="utf-8",
    )
    entry = ruleset_labels.shipped("GZQO", tmp_path)["GZQO-INC-05"]
    same = ruleset_labels.words(entry, " At least 2 gout flares  within 12 months.", "confirm flare dates with patient")
    assert same["ja"] == {"label": "発作2回以上", "text": "12か月以内に発作2回以上。", "todo": "発作の日付を確認する"}
    assert ruleset_labels.words(entry, "At least 3 gout flares within 12 months.") == {}  # amended: not shown
    assert "todo" not in ruleset_labels.words(entry, "At least 2 gout flares within 12 months.", "other to-do")["ja"]
    # the site's own label wins; the shipped text stays beside the protocol's words
    row = {"id": "GZQO-INC-05", "kind": "inclusion", "class": "note", "label": "≥2 flares", "text": "x",
           "action": "confirm flare dates with patient", "i18n": {"ja": same["ja"]}}  # fmt: skip
    meta = studies.criterion_meta(row, "ja", "サイトの表示名")
    assert (meta.label, meta.original, meta.text, meta.text_original) == (
        "サイトの表示名",
        "≥2 flares",
        same["ja"]["text"],
        "x",
    )
    assert (meta.todo, meta.todo_original) == ("発作の日付を確認する", "confirm flare dates with patient")
    assert studies.criterion_meta(row, "en").label == "≥2 flares" and studies.criterion_meta(row, "en").original == ""


def test_the_labels_file_does_not_change_the_ruleset() -> None:
    """``labels.yaml`` sits beside the approved files; the ruleset the engines load is the same with or without it."""
    rs = Ruleset.load(ROOT / "rulesets" / "GZQO")
    assert [c.id for c in rs.active()][:2] == ["GZQO-INC-01", "GZQO-INC-02"]


# ---------------------------------------------------------------------------------------------- the walk
CLINICAL = ("/studies/GZQO/week", "/studies/GZQO/excluded", "/studies/GZQO/candidates",
            "/studies/GZQO/patients/" + "a" * 32, "/studies/GZQO/patients/" + "b" * 32,
            "/studies/GZQO/candidates/" + "a" * 32, "/studies/GZQO/candidates/" + "b" * 32)  # fmt: skip


def _walk(b: dict[str, Any], user: str, lang: str) -> dict[str, list[str]]:
    c, csrf = login(b["app"], user, PW)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
    bad: dict[str, list[str]] = {}
    for path in CLINICAL:
        r = c.get(path)
        assert r.status_code == 200, (path, r.status_code)
        words = english_words(r.text)
        if words:
            bad[path] = sorted(set(words))
    return bad


@pytest.mark.parametrize("lang", ["ja", "zh-TW"])
@pytest.mark.parametrize("role", ["investigator", "coordinator"])
def test_no_english_word_outside_the_allow_list_on_the_clinical_pages(
    box: dict[str, Any],  # noqa: F811
    role: str,
    lang: str,
) -> None:
    _gzqo(box)
    _with_excluded(box)
    box["users"].create("walker", role, PW, "walker@hospa.test")
    if role == "investigator":
        name_pi(box, "walker")  # D-380 (ROLE-008): the steward names the PI
    assert _walk(box, "walker", lang) == {}
    # the translated words are on the page, with the protocol's own beside them
    c, csrf = login(box["app"], "walker", PW)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
    page = c.get("/studies/GZQO/patients/" + "b" * 32).text
    want = {"ja": ("12か月以内の痛風発作2回以上", "発作の日付を患者に確認する"),
            "zh-TW": ("12個月內痛風發作≥2次", "向病人確認發作日期")}[lang]  # fmt: skip
    assert all(w in page for w in want)
    assert 'data-testid="text-original-GZQO-INC-05"' in page and "At least 2 gout flares" in page


def test_the_walk_finds_an_untranslated_label(
    box: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The check is not blind: without the shipped labels the English criterion words are found."""
    monkeypatch.setattr(ruleset_labels, "SHIPPED", tmp_path)
    box["backend"].criteria = lambda rs: (
        criteria_of(tmp_path / "none", rs)
        or [{k: v for k, v in r.items() if k != "i18n"} for r in criteria_of(ROOT / "rulesets", rs)]
    )
    _with_excluded(box)
    box["users"].create("walker", "investigator", PW, "walker@hospa.test")
    name_pi(box, "walker")  # D-380 (ROLE-008): the steward names the PI
    bad = _walk(box, "walker", "ja")
    assert "flares" in bad["/studies/GZQO/week"] and "confirm" in bad["/studies/GZQO/patients/" + "b" * 32]
    assert english_words("<p>痛風 <q>two flares</q> <span data-original>(Age)</span> eGFR GZQO-INC-01</p>") == []


# ---------------------------------------------------------------------------------------------- approval
def test_approve_all_waits_for_a_label_in_the_page_language(box: dict[str, Any]) -> None:  # noqa: F811
    """D-309: on a Japanese page every criterion needs a short label before Approve all; the shipped label counts for
    an unchanged criterion, a new criterion needs one from the site."""
    new = ("GZQO-INC-10", "inclusion", "structured", "Example criterion added by the amendment.", "VS_X: 1", 100, None)
    job = _approval_job(box, [*_gzqo_rows("GZQO-INC-01", "GZQO-EXC-01"), new])
    box["users"].create("pi", "investigator", PW, "pi@hospa.test")
    name_pi(box, "pi")  # D-380 (ROLE-008): the steward names the PI
    p, csrf = login(box["app"], "pi", PW)
    p.post("/lang", data={"csrf": csrf, "lang": "ja", "back": "/"})
    s20 = p.get(f"/pilot/jobs/{job.job_id}/approval").text
    assert 'data-testid="label-shipped-GZQO-INC-01"' in s20 and 'value="18歳以上"' in s20
    assert 'data-testid="label-missing-GZQO-INC-10"' in s20 and 'data-testid="label-missing-GZQO-INC-01"' not in s20
    assert 'data-testid="approve-unlabelled"' in s20 and '<button type="button" disabled' in s20
    r = p.post(f"/pilot/jobs/{job.job_id}/approve", data={"csrf": csrf})
    assert r.status_code == 409
    r = p.post(
        f"/pilot/jobs/{job.job_id}/approval/label", data={"csrf": csrf, "crit": "GZQO-INC-10", "text": "例の基準"}
    )
    assert r.status_code == 200 and 'data-testid="approve-unlabelled"' not in r.text
    r = p.post(f"/pilot/jobs/{job.job_id}/approve", data={"csrf": csrf}, follow_redirects=False)
    assert r.status_code == 200 and 'data-testid="confirm-text"' in r.text  # the confirmation step comes next
    # an English page asks for no label (the site's language is not English)
    p.post("/lang", data={"csrf": csrf, "lang": "en", "back": "/"})
    assert 'data-testid="approve-unlabelled"' not in p.get(f"/pilot/jobs/{job.job_id}/approval").text


def test_the_approval_page_has_no_english_label_on_a_japanese_page(box: dict[str, Any]) -> None:  # noqa: F811
    job = _approval_job(box, _gzqo_rows("GZQO-INC-01", "GZQO-INC-05", "GZQO-EXC-11"))
    box["users"].create("pi", "investigator", PW, "pi@hospa.test")
    name_pi(box, "pi")  # D-380 (ROLE-008): the steward names the PI
    p, csrf = login(box["app"], "pi", PW)
    for lang, label in (("ja", "現在の痛風発作"), ("zh-TW", "目前痛風發作")):
        p.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
        s20 = p.get(f"/pilot/jobs/{job.job_id}/approval").text
        assert f'data-testid="site-label-GZQO-EXC-11">{label}' in s20 and 'data-testid="approve-unlabelled"' not in s20


# ---------------------------------------------------------------------------------------------- the test model
def test_test_model_in_use() -> None:
    assert studies.test_model_in_use({"TB_LLM_MODE": "stub"}) is True
    assert studies.test_model_in_use({"TB_LLM_MODE": "vllm", "TB_ENV": "DEV"}) is False
    assert studies.test_model_in_use({"TB_ENV": "DEV"}) is True and studies.test_model_in_use({"TB_ENV": "test"})
    assert studies.test_model_in_use({}) is False  # PRODUCTION when unset (D-127)


@pytest.mark.parametrize("lang", ["en", "ja", "zh-TW"])
def test_dev_pages_label_answers_from_the_test_model(
    box: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    lang: str,
) -> None:
    _gzqo(box)
    _with_excluded(box)
    box["users"].create("walker", "investigator", PW, "walker@hospa.test")
    name_pi(box, "walker")  # D-380 (ROLE-008): the steward names the PI
    c, csrf = login(box["app"], "walker", PW)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
    monkeypatch.delenv("TB_LLM_MODE", raising=False)
    monkeypatch.setenv("TB_ENV", "DEV")
    word = {"en": "test model", "ja": "テスト用モデル", "zh-TW": "測試用模型"}[lang]
    page = c.get("/studies/GZQO/patients/" + "a" * 32).text
    assert 'data-testid="test-model-GZQO-INC-05"' in page and word in page  # read from notes
    assert 'data-testid="test-model-GZQO-INC-01"' not in page  # coded data: no model
    assert 'data-testid="test-model-GZQO-INC-05"' in c.get("/studies/GZQO/week").text
    monkeypatch.setenv("TB_LLM_MODE", "vllm")
    assert 'data-testid="test-model-' not in c.get("/studies/GZQO/patients/" + "a" * 32).text
