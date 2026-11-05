"""tools/gpu_sizing.py: the estimates behind the review's hardware table stay consistent with the recommendation
(one RTX PRO 6000 carries the judge alone; the benchmarked pair needs two cards or a Spark; no GPU is a valid start)."""

from __future__ import annotations

import json

from tools.gpu_sizing import HARDWARE, MODELS, PLANS, main, place


def test_kv_cache_arithmetic() -> None:
    g = MODELS["gpt-oss-120b-mxfp4"]
    # 18 full layers x 2 (K,V) x 8 heads x 64 x 2 bytes = 36,864 bytes per token; the 18 sliding layers add ~nothing
    assert abs(g.kv_gb(65_536, 1) - 18 * 2 * 8 * 64 * 2 * 65_536 / 1024**3) < 0.01
    assert g.kv_gb(1024, 2) == 2 * g.kv_gb(1024, 1)
    assert MODELS["qwen3.5-35b-a3b-q4"].kv_gb(16_384) > 0


def test_review_table_conclusions() -> None:
    rows = {r["hardware"]: r for r in (place(HARDWARE[h], *PLANS[h]) for h in PLANS)}
    assert rows["cpu"]["fits"] is None and rows["cpu"]["models"] == []
    assert rows["rtx-pro-6000"]["fits"] and 15 <= rows["rtx-pro-6000"]["headroom_gb"][0] <= 30  # type: ignore[index]
    pair = place(HARDWARE["rtx-pro-6000"], [("gpt-oss-120b-mxfp4", 32_768), ("gemma-4-26b-a4b-fp8", 32_768)])
    assert pair["fits"] is False  # the benchmarked pair does not fit one 96 GB card
    assert rows["2x-rtx-pro-6000"]["fits"] and rows["spark"]["fits"] and rows["2x-spark"]["fits"]
    spark_head = rows["spark"]["headroom_gb"]
    assert isinstance(spark_head, list) and 0 <= spark_head[0] < 10  # tight
    assert isinstance(rows["spark"]["stack_gb"], float) and rows["spark"]["stack_gb"] > 20
    wide = place(HARDWARE["spark"], [("gpt-oss-120b-mxfp4", 65_536), ("gemma-4-26b-a4b-fp8", 32_768)], 4)
    assert wide["fits"] is False  # the v4 spec's 64k/32k pair with four sequences does not fit one Spark
    spark_judge = rows["spark"]["models"][0]  # type: ignore[index]
    assert 10 <= spark_judge["tokens_per_s"] <= 40  # bandwidth-bound: slow for an interactive CASE check
    assert rows["rtx-pro-6000"]["models"][0]["tokens_per_s"] > 100  # type: ignore[index]
    assert rows["rtx-5090"]["fits"] and rows["rtx-pro-5000"]["fits"]


def test_cli_text_and_json(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main([]) == 0
    text = capsys.readouterr().out
    assert "DOES NOT FIT" not in text and "nothing measured" in text and "Assumed" in text
    assert (
        main(
            ["--hardware", "rtx-pro-6000", "--model", "gpt-oss-120b-mxfp4", "--model", "gemma-4-26b-a4b-fp8", "--json"]
        )
        == 0
    )
    doc = json.loads(capsys.readouterr().out)
    assert doc["rows"][0]["fits"] is False and doc["models"]["gemma-4-26b-a4b-fp8"]["assumed"]
    assert main(["--hardware", "rtx-pro-6000", "--model", "gpt-oss-120b-mxfp4", "--model", "gemma-4-26b-a4b-fp8"]) == 0
    assert "DOES NOT FIT" in capsys.readouterr().out


def test_consumer_cards() -> None:
    rows = {r["hardware"]: r for r in (place(HARDWARE[h], *PLANS[h]) for h in PLANS)}
    for h in ("rtx-3090", "rtx-4090", "rtx-5090", "2x-rtx-4090", "2x-rtx-5090"):
        assert rows[h]["fits"], h
    # the both-must-block consumer pair does not fit one 32 GB card, even at 8k and one sequence
    one = place(HARDWARE["rtx-5090"], [("gemma-4-26b-a4b-q4", 8_192), ("qwen3.6-35b-a3b-q4", 8_192)], 1)
    assert one["fits"] is False
    # a dense 31B at 4 bit is bandwidth-bound: far slower per sequence than the 4B-active MoE on the same card
    dense = place(HARDWARE["rtx-5090"], [("gemma-4-31b-q4", 16_384)], 4)["models"][0]  # type: ignore[index]
    assert dense["tokens_per_s"] * 4 < rows["rtx-5090"]["models"][0]["tokens_per_s"]  # type: ignore[index]
