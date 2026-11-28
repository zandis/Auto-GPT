"""Lane K (HOLISTIC-3 §5.2, H3-PROD §2 row 3): feasibility surfaced. Each criterion row of the attrition table opens
its threshold variants in place (what if this criterion's threshold were another value: how many remain at the end,
and the difference), from the variants the feasibility run already computed. The counts are the run's published,
rounded counts; nothing is recomputed on the page. All data is synthetic."""

from __future__ import annotations

import json
from typing import Any

from console import studies as st
from console.sitestore import SiteProfile

from tests.console.test_console_app import FEAS_JSON, _done_feas, box, login  # noqa: F401 - the fixture is used by name

SENS = [
    {"criterion_id": "GZQO-INC-01", "variant": "INC-01=7", "remaining": 10, "delta": 5},
    {"criterion_id": "GZQO-INC-01", "variant": "INC-01=9", "remaining": "<5", "delta": None},
    {"criterion_id": "*", "variant": "unknown_as_pass", "remaining": 40, "delta": 35},
]


def test_each_funnel_row_carries_its_own_variants_in_protocol_order() -> None:
    rep = st.feas_report({**FEAS_JSON, "sensitivity": SENS}, None, SiteProfile(), {})
    by_id = {f["id"]: f["variants"] for f in rep["funnel"]}
    assert [v["variant"] for v in by_id["GZQO-INC-01"]] == ["INC-01=7", "INC-01=9"]
    assert by_id["GZQO-INC-01"][1]["remaining"] == "<5" and by_id["GZQO-INC-02"] == []
    assert [f["id"] for f in rep["funnel"]] == ["GZQO-INC-01", "GZQO-INC-02", "GZQO-EXC-01"]


def test_the_feasibility_page_opens_the_variants_on_the_criterion_row(box: dict[str, Any]) -> None:  # noqa: F811
    job = _done_feas(box["backend"])
    key = next(o.minio_key for o in job.outputs or [] if o.filename.endswith(".json") and o.tag == "aggregate")
    box["backend"].objects[key] = json.dumps({**FEAS_JSON, "sensitivity": SENS}).encode()
    admin, _ = login(box["app"])
    page = admin.get("/studies/GZQO/feasibility").text
    funnel = page.split('data-testid="funnel"')[1].split("</table>")[0]
    assert 'data-testid="whatif-GZQO-INC-01"' in funnel and "INC-01=7" in funnel and "+5" in funnel
    assert 'data-testid="whatif-GZQO-INC-02"' not in funnel  # no variant computed: no toggle
