"""Application draft (SPEC §9.4): the ruleset's docxtpl template filled with patient facts; every unknown field is a
highlighted ``[待補]``; the clinical-course paragraph comes from ``draft_doc`` (§7.6) and is dropped (→ ``[待補]``)
when it contains a number that is not in the input facts. Never signed by the system."""

from __future__ import annotations

import io
import json
import re
from pathlib import Path
from typing import Any

from tb_common.deterministic import normalize_ooxml

from orchestrator.reports.common import ReportMeta
from orchestrator.scenarios.facts import MISSING, Facts

TEMPLATES = Path(__file__).resolve().parent / "templates"
_NUM = re.compile(r"\d+(?:\.\d+)?")


def numbers_ok(paragraph: str, facts: dict[str, Any]) -> bool:
    """Every number in the paragraph appears in the facts (dates count as their parts)."""
    allowed = set(_NUM.findall(json.dumps(facts, ensure_ascii=False)))
    allowed |= {str(int(float(x))) for x in allowed if "." in x}
    return all(n in allowed for n in _NUM.findall(paragraph))


def render(
    template: str,
    facts: Facts,
    mrn: str,
    physician: str,
    department: str,
    apply_type: str,
    course: str | None,
    exclusions: list[tuple[str, str]],
    meta: ReportMeta,
) -> bytes:
    from docxtpl import DocxTemplate, RichText

    path = TEMPLATES / template
    if not path.exists():
        raise FileNotFoundError(f"application template {template} not found")

    def val(v: Any) -> Any:
        """Every template field is ``{{r …}}``: RichText escapes the text; unknowns are highlighted [待補]."""
        if v in (None, "", MISSING):
            return RichText(MISSING, highlight="yellow", bold=True)
        return RichText(str(v))

    def rows(items: list[dict[str, str]]) -> list[dict[str, Any]]:
        return [{k: val(v) for k, v in it.items()} for it in items]

    ctx = {
        "apply_type": val(apply_type),
        "run_date": val(meta.run_date),
        "site_name": val(meta.site_name),
        "mrn": val(mrn),
        "sex": val(facts.get("sex")),
        "birth_date": val(facts.get("birth_date")),
        "age": val(facts.get("age")),
        "physician": val(physician),
        "department": val(department),
        "diagnosis": val(facts.get("diagnosis")),
        "diagnosis_code": val(facts.get("diagnosis_code")),
        "diagnosis_date": val(facts.get("diagnosis_date")),
        "dmards": rows(facts.dmards) or [{k: val(None) for k in ("name", "dose", "start", "end", "days")}],
        "prednisolone": val(facts.get("prednisolone")),
        "das28": rows(facts.das28),
        "hbsag": val(facts.get("hbsag")),
        "ahbc": val(facts.get("ahbc")),
        "tb_screen": val(facts.get("tb_screen")),
        "exclusions": [{"label": val(lbl), "status": val(st)} for lbl, st in exclusions],
        "course": val(course),
        "footer": val(meta.footer),
    }
    doc = DocxTemplate(str(path))
    doc.render(ctx)
    doc.docx.core_properties.author = f"TrialBox {meta.site_id}"
    doc.docx.core_properties.title = f"{template} draft"
    buf = io.BytesIO()
    doc.save(buf)
    return normalize_ooxml(buf.getvalue())
