"""Lane K (HOLISTIC-3 §5.2, H3-PROD §2 row 7): the steward's page of what was published. Every trial-opportunity
feed the box built (its period, how many studies it published and its rounding profile) and every feasibility pack
on the box (study, version, snapshot and the small-cell threshold its counts were rounded with), beside the
departure record by day and route. Counts only: no patient, no content. The steward, the privacy office and the
administrator read it (the roles of ``audit.provenance``); a coordinator is refused. All data is synthetic."""

from __future__ import annotations

import json
from typing import Any

from tb_common.crypto import sha256_bytes
from tb_contracts import JobOutput

from tests.console.test_console_app import _done_feas, box, login  # noqa: F401 - the fixture is used by name

PW = "published-page-password-01"


def test_the_steward_sees_every_feed_and_pack_with_its_rounding(box: dict[str, Any]) -> None:  # noqa: F811
    job = _done_feas(box["backend"])
    data = json.dumps(
        {"schema": "feasprofile/1", "ruleset": "GZQO", "snapshot": "2026-10-04", "small_cell": 10}
    ).encode()
    key = f"outputs/{job.job_id}/feasprofile_GZQO_v1.0.0.json"
    box["backend"].objects[key] = data
    out = JobOutput(filename="feasprofile_GZQO_v1.0.0.json", sha256=sha256_bytes(data), minio_key=key,
                    recipients=[], tag="aggregate")  # fmt: skip
    box["backend"].jobs[job.job_id] = job.model_copy(update={"outputs": [*(job.outputs or []), out]})
    box["audit"].append("opportunity.feed", job_id=job.job_id, detail={
        "conditions": ["gout"], "counted": 4, "published": 3, "threshold": 11,
        "period": {"start": "2026-10-01", "days": 30}, "opt_out_register": "optout"})  # fmt: skip
    box["users"].create("stw", "steward", PW, "stw@hospa.test")
    box["users"].create("crc", "coordinator", PW, "crc@hospa.test")
    stw, _ = login(box["app"], "stw", PW)
    r = stw.get("/audit/published")
    assert r.status_code == 200, r.text[:300]
    feeds = r.text.split('data-testid="published-feeds"')[1].split("</table>")[0]
    assert "2026-10-01" in feeds and ">3<" in feeds and "11" in feeds
    packs = r.text.split('data-testid="published-packs"')[1].split("</table>")[0]
    assert "GZQO" in packs and "2026-10-04" in packs and ">10<" in packs
    assert 'data-testid="published-left"' in r.text
    crc, _ = login(box["app"], "crc", PW)
    assert crc.get("/audit/published").status_code == 403
