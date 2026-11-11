# ruff: noqa: E501 - one string per line, as in the other catalogues
"""The admin Models tile's build list (T-012b, LLM-029): each model build pinned on this box, its status and the
qualification record that made it champion, read from the gateway's registry view (``/registry/v1/builds``).

A champion without a record that qualifies PRODUCTION for its pinned weights is refused by a PRODUCTION gateway
(``champion_unqualified``); the tile says so before a run finds out. Joined into ``console.i18n`` on import.
"""

from __future__ import annotations

from typing import Any

from console.i18n import CATALOGUES

EN: dict[str, str] = {
    "models.builds": "Model builds on this box",
    "models.builds.none": "No model build is pinned on this box.",
    "models.record": "qualified: record {record}, promoted {at}",
    "models.record.none": "no qualification record: a PRODUCTION box refuses this model until it is qualified and promoted",
    "models.weights.unexpected": "these weights are not the expected release: refused",
}
JA: dict[str, str] = {
    "models.builds": "TrialBox のモデルビルド",
    "models.builds.none": "TrialBox に固定されたモデルビルドはありません。",
    "models.record": "適格性確認済み: 記録 {record}、昇格 {at}",
    "models.record.none": "適格性確認の記録がありません: 確認と昇格が済むまで、PRODUCTION の TrialBox はこのモデルを拒否します",
    "models.weights.unexpected": "この重みは想定されたリリースではありません: 拒否",
}
ZH: dict[str, str] = {
    "models.builds": "本機的模型版本",
    "models.builds.none": "本機尚未固定任何模型版本。",
    "models.record": "已通過資格確認: 紀錄 {record}, 於 {at} 升級",
    "models.record.none": "沒有資格確認紀錄: 在確認並升級之前, PRODUCTION 的機器會拒絕此模型",
    "models.weights.unexpected": "此權重不是預期的發行版本: 已拒絕",
}

for _lang, _cat in (("en", EN), ("ja", JA), ("zh-TW", ZH)):
    CATALOGUES[_lang].update(_cat)


def build_rows(builds: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """The builds the tile lists: every pinned build that is not the stub, and every champion that is not the stub.
    None when the gateway's registry view was not read (the tile then shows nothing about builds)."""
    if builds is None:
        return None
    out: list[dict[str, Any]] = []
    for b in builds:
        if str(b.get("build_id", "")).endswith("-stub-1") or b.get("alias") in ("trialbox-stub", "stub-verifier"):
            continue
        if not b.get("pinned") and b.get("status") != "champion":
            continue
        q = b.get("qualification") or {}
        expected = b.get("expected") or {}
        out.append(
            {
                "build_id": b.get("build_id"),
                "alias": b.get("alias"),
                "status": b.get("status"),
                "qualified": bool(b.get("qualified_for_production")),
                "record": q.get("record_id") or "",
                "at": str(q.get("promoted_at") or "")[:16].replace("T", " "),
                "unexpected": bool(expected.get("manifest_sha256")) and not b.get("weights_expected"),
            }
        )
    return sorted(out, key=lambda r: (r["status"] != "champion", str(r["build_id"])))
