"""Step 1 end to end, in process: the 5,000-patient synthetic hospital (ci profile) -> ingest -> console S2 paste of the
GOUT-COH criteria -> FEAS in Japanese -> S3 funnel. Stub model, TB_ENV=DEV, no network."""

from __future__ import annotations

import json
from pathlib import Path

from tools import feas_demo


def test_paste_gout_coh_criteria_gives_the_japanese_funnel(tmp_path: Path) -> None:
    box, client, repo, summary = feas_demo.build(tmp_path)
    assert sum(s["patients"] for s in summary["sites"]) == 5000 and not summary["failures"]
    app = feas_demo.console(tmp_path, box, client, repo, "pw-" + "x" * 16)
    path, html = feas_demo.paste_and_report(app, "pw-" + "x" * 16, "ja")
    assert path == "/studies/GOUT-COH/feasibility"
    assert '<html lang="ja">' in html and 'data-testid="funnel"' in html and "2026-10-31" in html
    got = feas_demo.funnel(box)
    job, res = got["job"], got["result"]
    assert job.state == "done" and job.options.get("lang") == "ja"
    assert res["start_n"] == 5000 and res["snapshot"] == "2026-10-31"
    ids = [f["criterion_id"] for f in res["funnel"]]
    assert ids == [f"GOUT-COH-INC-0{i}" for i in range(1, 8)]
    for f in res["funnel"]:
        assert f["criterion_id"] in html  # every per-criterion row is on S3
    # the first step is the gout diagnosis (30 % gout archetype plus coded gout among the others)
    first = res["funnel"][0]["remaining"]
    assert isinstance(first, int) and 1000 < first < 2500
    # the mail the coordinator gets is Japanese too
    done = [s for s in box.sent if "FEAS done" in s.subject]
    assert done and "実施可能性" in done[-1].text()
    assert json.loads((tmp_path / "synth" / "summary.json").read_text(encoding="utf-8"))["profile"] == "ci"
