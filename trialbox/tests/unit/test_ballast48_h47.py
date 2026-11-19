"""H-47: the 48 GB class's measuring run under the ballast (tools/ballast48.py). Lane J's ``tools/dgpu48.py measure``
is run unchanged; the wrapper's runner shows it the RTX PRO 6000 as a 49,140 MiB card, scales the two utilisations to
the real total and marks the serving record "by ballast" (D-1320 rule 4: never a tier record). No card, no Docker here:
every command goes to a stand-in runner."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tools import ballast, ballast48 as b48, dgpu48, serving_config

pytestmark = pytest.mark.nodb

PRO6000 = 97887
TARGET = b48.TARGET_MIB


class Card:
    """A stand-in for nvidia-smi and docker on the RTX PRO 6000 with the ballast holding all but 49,140 MiB."""

    def __init__(self, used: int = PRO6000 - TARGET, ballast_up: bool = True) -> None:
        self.used, self.ballast_up = used, ballast_up
        self.calls: list[tuple[list[str], dict[str, str] | None]] = []

    def __call__(self, cmd: list[str], timeout: int, env: dict[str, str] | None = None,
                 stream: bool = False) -> tuple[int, str, str]:  # fmt: skip
        self.calls.append((list(cmd), env))
        if cmd[0] == "nvidia-smi":
            fields = cmd[1].split("=", 1)[1].split(",")
            val = {"name": "NVIDIA RTX PRO 6000 Blackwell Server Edition", "memory.total": str(PRO6000),
                   "memory.used": str(self.used), "driver_version": "580.95.05", "display_active": "Disabled"}
            return 0, ", ".join(val[f] for f in fields) + "\n", ""
        if cmd[:2] == ["docker", "ps"] and any("tb-ballast" in c for c in cmd):
            return 0, ("abc123\n" if self.ballast_up else ""), ""
        return 0, "", ""


def test_the_target_is_the_class_card_total() -> None:
    assert dgpu48.load()["card"]["memory_total_mib"] == TARGET
    lo, hi = dgpu48.load()["card"]["memory_range_mib"]
    assert lo <= TARGET <= hi < PRO6000  # the class refuses the real card's total, takes the target


def test_the_view_shows_a_48gb_card_and_what_the_servers_use() -> None:
    card = Card(used=PRO6000 - TARGET + 30000)
    view = b48.BallastView(card, PRO6000)
    rc, out, _ = view(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"],
                      60)  # fmt: skip
    assert rc == 0 and out.split(", ")[1] == str(TARGET)
    _, out, _ = view(["nvidia-smi", "--query-gpu=display_active,memory.used", "--format=csv,noheader,nounits"], 60)
    assert out.strip() == "Disabled, 30000"
    card.used = PRO6000 - TARGET - 200  # the ballast's own context counted: never below zero
    _, out, _ = view(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], 60)
    assert out.strip() == "0"


def test_the_start_gets_the_same_mib_of_the_real_card_and_a_down_command() -> None:
    card = Card()
    view = b48.BallastView(card, PRO6000)
    up = ["docker", "compose", "-f", "deploy/docker-compose.yml", "-f", dgpu48.OVERLAY, "-f", "run.yml", "up", "-d",
          "--wait", "--wait-timeout", "2160", "llm-service", "llm-verifier"]  # fmt: skip
    view(up, 2400, {"JUDGE_GPU_MEM_UTIL": "0.57", "VERIFIER_GPU_MEM_UTIL": "0.27", "TB_MODELS_DIR": "/m"})
    sent = card.calls[-1][1] or {}
    assert sent["JUDGE_GPU_MEM_UTIL"] == str(ballast.util_on(PRO6000, 0.57, TARGET)) == "0.286"
    assert sent["VERIFIER_GPU_MEM_UTIL"] == "0.135"
    assert float(sent["JUDGE_GPU_MEM_UTIL"]) * PRO6000 <= 0.57 * TARGET  # never a larger budget
    assert view.scaled["JUDGE_GPU_MEM_UTIL"] == {"class": "0.57", "on_card": "0.286"}
    assert view.down is not None and view.down["cmd"][-4:] == ["rm", "-sf", "llm-service", "llm-verifier"]
    assert view.down["cmd"][:3] == ["docker", "compose", "-f"]


def test_the_record_is_capped_and_never_a_tier_record() -> None:
    card = Card()
    view = b48.BallastView(card, PRO6000)
    view([sys.executable, "/x/tools/serving_config.py", "capture", "--container", "judge=j", "--out", "r.json"], 60)
    sent = card.calls[-1][0]
    assert sent[-2:] == ["--capped-to", "48 GB class (49,140 MiB), by ballast"]
    rec = {"card": {"capped_to": sent[-1], "name": "NVIDIA RTX PRO 6000", "memory_total_mib": PRO6000}}
    assert any("capped" in w for w in serving_config.measured_for(rec, "rtxpro6000"))


@pytest.mark.parametrize(
    ("card", "why"),
    [(Card(ballast_up=False), "no tb-ballast"), (Card(used=1000), "not 49140"), (Card(used=PRO6000 - TARGET - 900),
                                                                                 "not 49140")],
)
def test_it_refuses_without_the_ballast_holding_the_target(card: Card, why: str, tmp_path: Path) -> None:
    called = []
    with pytest.raises(b48.Refused, match=why):
        b48.measure(card, "pair-32k", tmp_path, "pinned", False, False, measure_fn=lambda *a, **k: called.append(a) or {})
    assert not called  # refused before lane J's measure is asked anything


def test_measure_runs_lane_js_measure_and_marks_the_summary(tmp_path: Path) -> None:
    card = Card()
    got: dict[str, Any] = {}

    def fake_measure(run: Any, oid: str, out_dir: Path, probe: Any, engine: str, dry: bool, keep: bool, **_: Any) -> dict:
        got.update(oid=oid, engine=engine, probe=probe, keep=keep)
        run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"], 60)
        run(["docker", "compose", "-f", dgpu48.OVERLAY, "up", "-d", "llm-service"], 60, {"JUDGE_GPU_MEM_UTIL": "0.57"})
        return {"option": oid, "started": True, "card_peak_mib": 45000, "outcome": "STARTED, RECORD TAKEN: send"}

    s = b48.measure(card, "pair-32k", tmp_path, "pinned", True, False, measure_fn=fake_measure, say=lambda _: None)
    assert got == {"oid": "pair-32k", "engine": "pinned", "probe": None, "keep": True}
    assert s["outcome"].startswith("BY BALLAST: STARTED")
    bl = s["ballast"]
    assert bl["tier_record"] is False and bl["held_mib"] == PRO6000 - TARGET and bl["free_at_peak_mib"] == 4140
    assert bl["card_peak_mib_real"] == 45000 + PRO6000 - TARGET
    assert json.loads((tmp_path / "measure.pair-32k.json").read_text())["ballast"]["capped_to"].endswith("by ballast")
    assert json.loads((tmp_path / "down.json").read_text())["cmd"][-3:] == ["rm", "-sf", "llm-service"]


def test_a_lost_ballast_is_said(tmp_path: Path) -> None:
    card = Card()

    def fake_measure(*_: Any, **__: Any) -> dict:
        card.ballast_up = False
        return {"started": True, "outcome": "STARTED"}

    s = b48.measure(card, "pair-16k", tmp_path, "pinned", False, False, measure_fn=fake_measure, say=lambda _: None)
    assert s["outcome"].startswith("BALLAST LOST") and s["ballast"]["still_held_at_end"] is False
    assert not (tmp_path / "down.json").exists()


def test_during_records_wall_time_and_free_at_peak(tmp_path: Path) -> None:
    card = Card()

    def fake_cmd(cmd: list[str], check: bool) -> subprocess.CompletedProcess:
        card.used = PRO6000 - TARGET + 44000  # the screen's peak
        return subprocess.CompletedProcess(cmd, 0)

    rec = b48.during(["/opt/x/python", "-m", "tools.complete_run"], tmp_path / "s.json", card, every=0.01,
                     popen=fake_cmd)  # fmt: skip
    assert rec["exit_code"] == 0 and rec["command"][0] == "python"
    assert rec["free_at_peak_mib"] == TARGET - 44000 and rec["peak_used_mib_as_48gb"] == 44000
    assert rec["ballast_held_at_end"] is True
    assert json.loads((tmp_path / "s.json").read_text())["schema"] == "tb-ballast48-during/1"


def test_down_replays_the_kept_command(tmp_path: Path) -> None:
    card = Card()
    (tmp_path / "down.json").write_text(json.dumps({"cmd": ["docker", "compose", "rm", "-sf"], "env": {"A": "1"}}))
    assert b48.down(tmp_path, card) == 0 and card.calls[-1] == (["docker", "compose", "rm", "-sf"], {"A": "1"})
    assert b48.down(tmp_path / "none", card) == 2


def test_the_ballast_image_is_the_engine_measure_pulls() -> None:
    from tools import engine_probe

    # the ballast never pulls (image-not-local): the run sheet pulls the pinned engine first, which must be its image
    assert ballast.default_image() == engine_probe.pinned_ref()


def test_the_dry_run_is_lane_js_with_this_cards_utils(tmp_path: Path) -> None:
    said: list[str] = []
    s = b48.measure(Card(), "pair-32k", tmp_path, "pinned", False, True, say=said.append)
    assert s["dry_run"] is True and s["engine"]["use"] == "pinned" and s["engine"]["pinned_engine"] is True
    assert any(line.startswith("dry run: option pair-32k") for line in said)  # lane J's own dry run, unchanged
    assert "on this card: JUDGE_GPU_MEM_UTIL=0.286 (the class's 0.57)" in said
    assert "on this card: VERIFIER_GPU_MEM_UTIL=0.135 (the class's 0.27)" in said
    assert any("by ballast" in line for line in said)
