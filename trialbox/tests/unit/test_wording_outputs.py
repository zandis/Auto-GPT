"""T-116 (CR-078, FIT-006 rest; TB-IU-01 §1 condition C1): the intended-use statement on every output that leaves the
console. Each report writer is run once and the file is opened as a reader would open it (pypdf for a PDF, openpyxl
for a workbook, the HTML text for a sheet, the parsed MIME parts for a mail); the statement must be there in the
output's language. A mail or a page without it fails :func:`_has_statement`, which the negative tests show."""

from __future__ import annotations

import dataclasses
import io
import re
from email import message_from_bytes, policy
from email.message import EmailMessage
from pathlib import Path

import pytest
from mail_gateway.outbound import prepare, render_body
from openpyxl import load_workbook
from orchestrator.reports import (
    candidate_xlsx,
    case_html,
    cohort_pdf,
    consent_html,
    feasibility_pdf,
    feasibility_xlsx,
    nav_xlsx,
    screen_summary_pdf,
    trial_sim_xlsx,
)
from orchestrator.reports.common import ReportMeta
from pypdf import PdfReader
from tb_common.objstore import FsStore
from tb_common.ruleset import Ruleset
from tb_common.wording import STATEMENT, check_page, statement, text_lang
from tb_contracts import CohortTable, SendRequest, TrialSimResult

from tests.unit.test_consent_unit import _rec as _consent_rec
from tests.unit.test_feas_unit import META as FEAS_META
from tests.unit.test_feas_unit import _result as _feas_result

ROOT = Path(__file__).resolve().parents[2]
GZQO = Ruleset.load(ROOT / "rulesets" / "GZQO")
LANGS = ("en", "ja", "zh-TW")


def _squash(text: str) -> str:
    """Whitespace out: a PDF wraps the statement over lines and a mail's quoted-printable part folds it."""
    return re.sub(r"\s+", "", text)


def _has_statement(text: str, lang: str) -> bool:
    return _squash(STATEMENT[lang]) in _squash(text)


def _case_rec(lang: str, in_lake: bool = True, model: str = "judge-model") -> dict[str, object]:
    return {
        "lang": lang,
        "ruleset": "GZQO",
        "version": "1.0.0",
        "index_date": "2026-10-05",
        "requested_by": "crc1@hospa.test",
        "subject": {"in_lake": in_lake, "snapshot": "2026-10-04", "pid": "c" * 8, "note": ""},
        "judge": {"model": model, "verifier": "check-model", "calls": 4, "disagreements": 1},
        "charts": [
            {
                "filename": "note.txt",
                "excerpts": 2,
                "earliest": "2026-09-01",
                "latest": "2026-09-18",
                "sha256": "0" * 64,
            }
        ],
        "excerpts": 2,
        "undated_excerpts": 1,
        "criteria": [
            {"id": "GZQO-INC-01", "text": "Aged 18 or older", "kind": "inclusion", "verdict": "pass", "source": "lake"},
            {
                "id": "GZQO-EXC-01",
                "text": "Type 1 diabetes",
                "kind": "exclusion",
                "verdict": "unknown",
                "source": "chart",
                "reason": "not_in_record",
                "resolve": "ask",
            },
            {
                "id": "GZQO-INC-05",
                "text": "Two flares",
                "kind": "inclusion",
                "verdict": "pending_human",
                "source": "human",
            },
        ],
        "counts": {"met": 1, "not_met": 0, "unknown": 1, "human": 1, "total": 3},
        "job_id": "01JB0000000000000000000000",
        "recipients": ["crc1@hospa.test"],
    }


def _meta(lang: str) -> ReportMeta:
    return dataclasses.replace(FEAS_META, locale=lang)


def _pdf_text(data: bytes) -> str:
    return "".join(p.extract_text() for p in PdfReader(io.BytesIO(data)).pages)


def _xlsx_text(data: bytes) -> str:
    wb = load_workbook(io.BytesIO(data))
    return "\n".join(str(v) for ws in wb.worksheets for row in ws.iter_rows(values_only=True) for v in row if v)


def _xlsx_every_sheet(data: bytes, lang: str) -> list[str]:
    """The sheets of a workbook that do not carry the statement (a reader may open any one of them)."""
    wb = load_workbook(io.BytesIO(data))
    missing = []
    for ws in wb.worksheets:
        text = "\n".join(str(v) for row in ws.iter_rows(values_only=True) for v in row if v)
        if not _has_statement(text, lang):
            missing.append(ws.title)
    return missing


@pytest.mark.parametrize("lang", LANGS)
def test_feasibility_pdf_and_workbook_carry_the_statement(lang: str) -> None:
    r = _feas_result()
    assert _has_statement(_pdf_text(feasibility_pdf.render(r, GZQO, _meta(lang), {"cold_chain": True})), lang)
    assert _xlsx_every_sheet(feasibility_xlsx.render(r, GZQO, _meta(lang)), lang) == []


@pytest.mark.parametrize("lang", LANGS)
def test_screening_summary_pdf_carries_the_statement(lang: str) -> None:
    pdf = screen_summary_pdf.render("Screening summary", [], GZQO, _meta(lang), ["scope"])
    assert _has_statement(_pdf_text(pdf), lang)


@pytest.mark.parametrize("lang", LANGS)
def test_candidate_and_nav_workbooks_carry_the_statement(lang: str) -> None:
    cand = candidate_xlsx.render([], GZQO, _meta(lang), {}, {})
    assert _has_statement(_xlsx_text(cand), lang)
    nav = nav_xlsx.render({name: [] for name in nav_xlsx.SHEETS}, GZQO, _meta(lang), {}, {}, {})
    assert _xlsx_every_sheet(nav, lang) == []


def test_cohort_pdf_and_trial_workbook_carry_the_statement() -> None:
    table = CohortTable.model_validate(
        {
            "schema_version": "alliance-v1",
            "rows": [
                {
                    "site_id": "DEMO-A",
                    "disease": "GZQO",
                    "quarter": "2026Q3",
                    "criterion_id": "START",
                    "criterion_label": "population",
                    "n": 40,
                    "n_contactable": 12,
                    "definition_version": "1.0.0",
                }
            ],
        }
    )
    sims = TrialSimResult.model_validate(
        {
            "ruleset": "GZQO",
            "condition": "gout",
            "run_date": "2026-10-05",
            "snapshot": "2026-10-04",
            "source": "cassette",
            "rows": [],
        }
    )
    for lang in LANGS:
        assert _has_statement(_pdf_text(cohort_pdf.render(GZQO, table, None, _meta(lang))), lang)
        assert _has_statement(_xlsx_text(trial_sim_xlsx.render(sims, _meta(lang))), lang)


@pytest.mark.parametrize("lang", LANGS)
def test_case_sheet_carries_the_statement_in_its_language(lang: str) -> None:
    page = case_html.sheet(_case_rec(lang)).decode()
    m = re.search(r'data-testid="intended-use">(.*?)</p>', page, re.S)
    assert m and m.group(1) == STATEMENT[lang].replace("'", "&#x27;")
    assert all(STATEMENT[o] not in page for o in LANGS if o != lang)
    # the sheet's own fixed words, in every branch (chart only, no model), give no verdict word of TB-IU-01 §2
    for rec in (_case_rec(lang), _case_rec(lang, in_lake=False, model="")):
        assert check_page(case_html.sheet(rec).decode()) == []


def test_consent_pages_carry_the_statement() -> None:
    from orchestrator.scenarios import consent as c

    rec = _consent_rec()

    for lang in ("en", "ja"):
        page = consent_html.patient(rec, lang, c.released_view(rec, lang, [], []), release=None).decode()
        assert _has_statement(page.replace("&#x27;", "'"), lang)
    assert _has_statement(consent_html.review(rec).decode().replace("&#x27;", "'"), "en")


# ------------------------------------------------------------------ mail
@pytest.mark.parametrize(
    ("body", "lang"),
    [
        ("Screening **GZQO v1.0.0** finished: 12 patients in scope.", "en"),
        ("スクリーニング **GZQO v1.0.0** が完了：対象 12 名。", "ja"),
        ("篩選 **GZQO v1.0.0** 完成：範圍內 12 位病人。", "zh-TW"),
    ],
)
def test_every_mail_body_carries_the_statement_in_its_language(body: str, lang: str) -> None:
    assert text_lang(body) == lang
    text, html = render_body(body)
    assert text.endswith(statement(lang) + "\n")
    assert _has_statement(html.replace("&#x27;", "'"), lang)


def test_a_sent_mail_carries_the_statement_in_both_parts_and_no_password_zip(tmp_path: Path) -> None:
    store = FsStore(tmp_path / "obj")
    store.put("outputs/J/list.xlsx", b"PK list")
    req = SendRequest.model_validate(
        {
            "job_id": "01JB0000000000000000000000",
            "to": ["pi@hospa.test"],
            "subject": "[GZQO] SCREEN done",
            "body_md": "候選名單已以加密郵件寄出。請登入主控台查看。",
            "tag": "phi",
            "encrypt": True,
            "attachments": [{"minio_key": "outputs/J/list.xlsx", "filename": "list.xlsx", "tag": "phi"}],
        }
    )
    p = prepare(req, store=store, sender="trialbox@hospa.test", internal_domains=["hospa.test"], mode="link",
                link_base="https://trialbox.hospa.test/")  # fmt: skip
    msg = message_from_bytes(p.data, policy=policy.default)
    assert isinstance(msg, EmailMessage)
    plain, html = msg.get_body(("plain",)), msg.get_body(("html",))
    assert plain is not None and html is not None
    assert _has_statement(plain.get_content(), "zh-TW")
    assert _has_statement(html.get_content().replace("&#x27;", "'"), "zh-TW")
    assert not p.password_mails  # D-369: patient files go by console link, never as a password zip


def test_a_mail_without_the_statement_fails_the_check() -> None:
    """Negative: the check is not blind. A body that lost its footer, or carries another language's statement, fails."""
    text, _ = render_body("plain **md**")
    cut = text.split("\n\n-- \n")[0]
    assert _has_statement(text, "en") and not _has_statement(cut, "en")
    assert not _has_statement(text, "ja")
