from dataclasses import replace

import pytest
import yaml

from tools import licence_register as lr


def test_shipped_judge_needs_its_own_revision() -> None:
    builds = yaml.safe_load(lr.MODELS.read_text(encoding="utf-8"))["builds"]
    judge = next(b for b in builds if b["build_id"] == "gemma-4-26b-a4b-it-rtxpro6000")
    judge["expected"]["revision"] = judge["revision"] = None

    (problem,) = lr.model_problems(lr.load(), [judge])
    assert all(word in problem for word in (judge["build_id"], "revision", judge["licence"]["register"]))


@pytest.mark.parametrize(
    ("name", "spdx", "excluded"),
    [
        ("health-developer", "LicenseRef-Health-Developer", "health-developer"),
        ("Fixture terms", "LicenseRef-Health-Developer", "LicenseRef-Health-Developer"),
    ],
)
def test_health_developer_short_name_and_identifier_are_excluded(name: str, spdx: str, excluded: str) -> None:
    row = next(r for r in lr.load() if r.id == "model-medgemma")
    row = replace(row, status="cleared", spdx=spdx, raw={**row.raw, "licence": name, "status": "cleared", "spdx": spdx})
    build = {
        "build_id": "synthetic-champion",
        "status": "champion",
        "repository": row.source,
        "revision": row.raw["version"].removeprefix("revision "),
        "licence": {"verified": True, "register": row.id, "name": name, "spdx": spdx},
    }

    (problem,) = lr.model_problems([row], [build])
    assert all(word in problem for word in (build["build_id"], excluded, "93"))
