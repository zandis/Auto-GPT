"""H-89b: the rehearsal with real servers on the remaining shipped profiles (the integrator's ruling 7088891993).

Built: the rtx5090 profile on one slice ``N:M`` of a split card (its own probe form, UUID and memory query), and the
Windows host path (deploy/box-install.sh hands the real-servers options on to install.sh). Stopped, with a question:
dgpu48 and gb10 (tests/unit/test_rehearsal_real_servers_h89.py asserts both stay refused under the mark).
docs/handover/rehearsal-real-servers-h89b-2026-11-23.md says what each row does not prove.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_rehearsal_real_servers_h89 import DRIVER_DIE, GOOD, UUIDS, Bench, _plant, probe_doc
from tools import ballast, engine_probe, rehearsal_real

ROOT = Path(__file__).resolve().parents[2]
SLICES = ["MIG-aaaaaaaa-0000-0000-0000-000000000000", "MIG-bbbbbbbb-1111-1111-1111-111111111111",
          "MIG-cccccccc-2222-2222-2222-222222222222"]  # fmt: skip
# card 1's three slices: (the slice's profile, free, total) as a split card of the bench's class reports them
SLICE_MEM = [("3g.90gb", 89000, 89600), ("2g.45gb", 44000, 44800), ("1g.23gb", 22000, 22400)]
# card 0 split too, listed first: a slice is always the named card's, never another card's slice of that number
CARD0: list[list[Any]] = [["MIG-dddddddd-3333-3333-3333-333333333333", "1g.23gb", 1000, 22400],
         ["MIG-eeeeeeee-4444-4444-4444-444444444444", "1g.23gb", 1000, 22400]]  # fmt: skip
BUDGET = 0.81 * 32607  # the 32 GB class's cap: 0.81 of its own card's 32,607 MiB

# nvidia-smi as the slice form asks it besides the whole-card queries: -L with each split card's slices, and
# -q -x -i N with each slice's own memory (nvidia-smi's XML form, mig_device / fb_memory_usage)
SLICE_SMI = r"""#!/usr/bin/env python3
import json, sys
rows = [r.split("|") for r in open("@ROWS@").read().split("\n") if r]
slices = json.load(open("@SLICES@"))
a = sys.argv[1:]
if a == ["-L"]:
    for i, r in enumerate(rows):
        print(f"GPU {i}: {r[0]} (UUID: {r[1]})")
        for m, s in enumerate(slices.get(str(i), [])):
            print(f"  MIG {s[1]}     Device  {m}: (UUID: {s[0]})")
    sys.exit(0)
if a[:2] == ["-q", "-x"]:
    i = a[a.index("-i") + 1]
    out = ["<?xml version=\"1.0\" ?>", "<nvidia_smi_log>", "<gpu>", "<mig_devices>"]
    for m, s in enumerate(slices.get(i, [])):
        out += ["<mig_device>", f"<index>{m}</index>", "<gpu_instance_id>1</gpu_instance_id>", "<fb_memory_usage>",
                f"<total>{s[3]} MiB</total>", "<reserved>0 MiB</reserved>", f"<used>{s[3] - s[2]} MiB</used>",
                f"<free>{s[2]} MiB</free>", "</fb_memory_usage>", "</mig_device>"]
    print("\n".join(out + ["</mig_devices>", "</gpu>", "</nvidia_smi_log>"])); sys.exit(0)
if "-i" in a:
    i = a[a.index("-i") + 1]
    if not i.isdigit() or int(i) >= len(rows):
        print("No devices were found"); sys.exit(6)
    rows = [rows[int(i)]]
q = next((x.split("=", 1)[1] for x in a if x.startswith("--query-gpu=")), "")
col = {"name": 0, "uuid": 1, "driver_version": 2, "mig.mode.current": 3, "mig.mode.pending": 4, "memory.free": 5,
       "memory.total": 6, "compute_cap": None, "memory.used": None}
for r in rows:
    print(", ".join("10.0" if f == "compute_cap" else "0" if col[f] is None else r[col[f]] for f in q.split(",")))
"""


def slice_bench(tmp: Path, *, mig: str = "Enabled", part: int = 0, **kw: Any) -> Bench:
    """H-89's bench with card 1 split in three slices, and a passing probe taken on slice ``1:part``."""
    b = Bench(tmp, mig=mig, **kw)
    rows = (tmp / "smi.rows").read_text(encoding="utf-8").splitlines()
    rows[0] = "|".join([*rows[0].split("|")[:3], "Enabled", "Enabled", *rows[0].split("|")[5:]])
    (tmp / "smi.rows").write_text("\n".join(rows) + "\n", encoding="utf-8")
    slices = {"0": CARD0, "1": [[u, *m] for u, m in zip(SLICES, SLICE_MEM, strict=True)]} if mig == "Enabled" else {}
    (tmp / "slices.json").write_text(json.dumps(slices), encoding="utf-8")
    smi = SLICE_SMI.replace("@ROWS@", str(tmp / "smi.rows")).replace("@SLICES@", str(tmp / "slices.json"))
    (b.bin / "nvidia-smi").write_text(smi, encoding="utf-8")
    host = {**probe_doc()["host"], "gpu_index": f"1:{part}", "card_id": engine_probe.card_id(SLICES[part])}
    b.probe.write_text(json.dumps(probe_doc(host=host)), encoding="utf-8")
    return b


def real_slice(b: Bench, index: str = "1:0", profile: str = "rtx5090") -> subprocess.CompletedProcess[str]:
    return b.install("--rehearsal", "--rehearsal-real-servers", "--gpu", profile, "--gpu-index", index,
                     "--engine-probe", str(b.probe))  # fmt: skip


def _need(total: int) -> int:
    return rehearsal_real.record_need({}, total, "rtx5090")[0]


# ------------------------------------------------------------------------------------- 3. rtx5090 on a split card's slice
def test_a_slice_is_accepted_under_the_mark_held_to_the_32gb_cap(tmp_path: Path) -> None:
    r = real_slice(slice_bench(tmp_path))
    need = _need(89600)
    assert need <= BUDGET
    assert (f"card 1:0: NVIDIA B200, 89000 MiB free of 89600 (the pair needs {need}), one slice of a split card"
            in r.stdout), r.stdout + r.stderr  # fmt: skip
    assert "WARN  NVIDIA driver 575.57.08" in r.stdout and "FAIL" not in r.stdout
    assert r.stderr.splitlines()[-1].startswith("install: vendor public key missing"), r.stderr


def test_write_pins_the_slice_by_its_own_uuid_held_to_its_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    b = slice_bench(tmp_path)
    (b.deploy / "site" / "rehearsal.json").write_text('{"rehearsal": true}\n', encoding="utf-8")
    monkeypatch.setenv("PATH", b.env()["PATH"])
    monkeypatch.setenv("TB_HOST_ROOT", str(b.hostroot))
    problems, doc = rehearsal_real.write(b.deploy, "1:0", b.probe, None, "rtx5090")
    assert problems == []
    text = (b.deploy / "site" / rehearsal_real.OVERRIDE).read_text(encoding="utf-8")
    assert text.count(f'device_ids: ["{SLICES[0]}"]') == 2 and "GPU-" not in text
    assert doc["card"]["slice_of_a_split_card"] is True and doc["card"]["index"] == "1:0"
    assert doc["card"]["memory_total_mib"] == 89600 and doc["caps"] == rehearsal_real.caps("rtx5090", 89600)
    for u in doc["caps"].values():  # each server, alone on the slice in turn, never more than on its own card
        assert u * 89600 <= BUDGET and u == ballast.util_on(89600, 0.81, 32607)


@pytest.mark.parametrize(
    ("change", "said"),
    [
        ({"card_id": engine_probe.card_id(UUIDS[1])}, "another card than card 1:0"),  # the whole card's probe
        ({"card_id": engine_probe.card_id(SLICES[1])}, "another card than card 1:0"),  # another slice's
        ({"card_id": None}, "another card than card 1:0"),
        ({"host_id": "f" * 32}, "another host"),
    ],
)
def test_the_probes_trust_checks_hold_for_a_slice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: dict[str, Any], said: str
) -> None:
    b = slice_bench(tmp_path)
    monkeypatch.setenv("PATH", b.env()["PATH"])
    monkeypatch.setenv("TB_HOST_ROOT", str(b.hostroot))
    assert rehearsal_real.driver_allowance(b.probe, "1:0", b.deploy)[0] == []
    doc = json.loads(b.probe.read_text(encoding="utf-8"))
    doc["host"].update(change)
    b.probe.write_text(json.dumps(doc), encoding="utf-8")
    problems = rehearsal_real.driver_allowance(b.probe, "1:0", b.deploy)[0]
    assert any(said in p for p in problems), problems


@pytest.mark.parametrize(
    ("change", "said"),
    [
        ({"images": {"pinned": {"verified_in_lock": True}}}, "digest matched"),
        ({"at": "2019-01-01T00:00:00+00:00"}, "older than 7 days"),
    ],
)
def test_the_probes_digest_and_age_hold_for_a_slice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: dict[str, Any], said: str
) -> None:
    b = slice_bench(tmp_path)
    monkeypatch.setenv("PATH", b.env()["PATH"])
    monkeypatch.setenv("TB_HOST_ROOT", str(b.hostroot))
    doc = {**json.loads(b.probe.read_text(encoding="utf-8")), **change}
    if "images" in change:
        doc["images"]["pinned"]["ref"] = probe_doc()["images"]["pinned"]["ref"]
    b.probe.write_text(json.dumps(doc), encoding="utf-8")
    problems = rehearsal_real.driver_allowance(b.probe, "1:0", b.deploy)[0]
    assert any(said in p for p in problems), problems


def test_a_slice_probe_given_as_a_link_or_writable_by_others_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    b = slice_bench(tmp_path)
    monkeypatch.setenv("PATH", b.env()["PATH"])
    monkeypatch.setenv("TB_HOST_ROOT", str(b.hostroot))
    link = tmp_path / "link.json"
    link.symlink_to(b.probe)
    assert any("is a link" in p for p in rehearsal_real.driver_allowance(link, "1:0", b.deploy)[0])
    b.probe.chmod(0o666)
    assert any("writable by group or others" in p for p in rehearsal_real.driver_allowance(b.probe, "1:0", b.deploy)[0])


NEVER_ALL = (
    "install: --rehearsal-real-servers: --gpu-index N names the one whole card (0, 1, ...), or N:M one slice "
    "of a split card, never all"
)


@pytest.mark.parametrize(
    ("bench", "index", "profile", "said"),
    [
        ({}, "1:0", "rtxpro6000", "is a slice of a split card: opened for --gpu rtx5090 only"),
        ({"mig": "Disabled"}, "1:0", "rtx5090", "card 1 (NVIDIA B200) is not split"),
        ({}, "1:5", "rtx5090", "card 1 has no slice 5"),
        ({}, "1:2", "rtx5090", f"has 22000 MiB free; the pair needs {_need(22400)} MiB"),  # 1g: smaller than the cap
        ({}, "1:", "rtx5090", NEVER_ALL),  # the installer's own line, before anything is checked
        ({}, ":0", "rtx5090", NEVER_ALL),
        ({}, "1:0:0", "rtx5090", NEVER_ALL),
        ({}, "1,0", "rtx5090", NEVER_ALL),
    ],
)
def test_a_slice_that_cannot_carry_the_pair_is_refused(
    tmp_path: Path, bench: dict[str, Any], index: str, profile: str, said: str
) -> None:
    r = real_slice(slice_bench(tmp_path, **bench), index, profile)
    assert r.returncode == 1 and said in r.stderr, r.stdout + r.stderr
    assert "WARN" not in r.stdout


def test_the_rehearsal_tool_refuses_a_slice_for_another_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert rehearsal_real.slice_problem("1:0", "rtxpro6000").endswith(
        "opened for the rtx5090 profile only, not rtxpro6000"
    )
    assert (
        rehearsal_real.slice_problem("1", "rtxpro6000") == "" and rehearsal_real.slice_problem("1:0", "rtx5090") == ""
    )
    b = slice_bench(tmp_path)  # the write step judges it again, whoever calls it
    (b.deploy / "site" / "rehearsal.json").write_text('{"rehearsal": true}\n', encoding="utf-8")
    monkeypatch.setenv("PATH", b.env()["PATH"])
    monkeypatch.setenv("TB_HOST_ROOT", str(b.hostroot))
    problems, doc = rehearsal_real.write(b.deploy, "1:0", b.probe, None, "rtxpro6000")
    assert doc == {} and any("opened for the rtx5090 profile only" in p for p in problems)
    assert not (b.deploy / "site" / rehearsal_real.OVERRIDE).exists()


def test_the_slice_is_the_named_cards(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Card 0's slices are listed first with the same numbers: slice 1:0 is card 1's (its UUID, its memory)."""
    b = slice_bench(tmp_path)
    monkeypatch.setenv("PATH", b.env()["PATH"])
    assert rehearsal_real.slice_query("1", "0") == (SLICES[0], "89000", "89600")
    assert rehearsal_real.slice_query("0", "0") == (CARD0[0][0], "1000", "22400")


def test_a_whole_card_with_mig_on_is_still_refused(tmp_path: Path) -> None:
    r = real_slice(slice_bench(tmp_path), "1")
    assert r.returncode == 1 and "has MIG on" in r.stderr


# master's bytes (b6e51e9f), each without the mark: (args, the bench's driver, exit code, the one last line)
MASTER_SLICE = [
    ("index without --rehearsal", ["--mode", "gpu", "--gpu", "rtx5090", "--gpu-index", "1:0"], {}, 2,
     "install: --gpu-index is for a rehearsal with real servers only (--rehearsal --rehearsal-real-servers); nothing was checked or written"),
    ("index with a plain rehearsal", ["--rehearsal", "--gpu", "rtx5090", "--gpu-index", "1:0"], {}, 2,
     "install: --gpu-index and --engine-probe go with --rehearsal-real-servers; nothing was checked or written"),
    ("probe without --rehearsal", ["--mode", "gpu", "--gpu", "rtx5090", "--engine-probe", "/x"], {}, 2,
     "install: --engine-probe is for a rehearsal with real servers only (--rehearsal --rehearsal-real-servers); nothing was checked or written"),
    ("the profile on a split card, low driver", ["--mode", "gpu", "--gpu", "rtx5090"], {}, 1, DRIVER_DIE),
    ("the profile on a split card", ["--mode", "gpu", "--gpu", "rtx5090"], {"driver": GOOD}, 1,
     "install: vendor public key missing"),
    ("a split card detected", ["--mode", "gpu"], {"driver": GOOD}, 1,
     "install: this card has MIG on (shared-quota): install.sh does not serve it; use deploy/platform (RUNBOOK §17)"),
]  # fmt: skip


@pytest.mark.parametrize(("what", "args", "bench", "rc", "said"), MASTER_SLICE, ids=[m[0] for m in MASTER_SLICE])
def test_without_the_mark_a_slice_is_as_on_master(
    tmp_path: Path, what: str, args: list[str], bench: dict[str, Any], rc: int, said: str
) -> None:
    """The rtx5090 profile on a split card without the mark: master's exit code and last line, the same bytes with
    or without a passing slice probe and every rehearsal sign planted."""
    clean = slice_bench(tmp_path / "clean", **bench).install(*args)
    pb = slice_bench(tmp_path / "planted", **bench)
    planted = pb.install(*args, **{**_plant(pb), "TB_GPU_INDEX": "1:0"})
    assert clean.returncode == rc and clean.stderr.splitlines()[-1].startswith(said), clean.stdout + clean.stderr
    got = [(r.returncode, r.stdout.replace(str(t), "<tmp>"), r.stderr.replace(str(t), "<tmp>"))
           for r, t in ((clean, tmp_path / "clean"), (planted, tmp_path / "planted"))]  # fmt: skip
    assert got[0] == got[1]
    assert "rehearsal" not in clean.stdout + "\n".join(clean.stderr.splitlines()[:-1])


def test_the_engine_probe_records_a_slices_own_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "machine-id").write_text("0123456789abcdef0123456789abcdef\n", encoding="utf-8")
    monkeypatch.setenv("TB_HOST_ROOT", str(tmp_path))
    asked: list[list[str]] = []

    def run(cmd: list[str], _t: int) -> tuple[int, str, str]:
        asked.append(cmd)
        if cmd[:2] == ["nvidia-smi", "-L"]:
            return 0, f"GPU 0: NVIDIA B200 (UUID: {UUIDS[0]})\n" + "".join(  # card 0's slices first, same numbers
                f"  MIG 1g.23gb     Device  {m}: (UUID: {c[0]})\n" for m, c in enumerate(CARD0)) + (
                f"GPU 1: NVIDIA B200 (UUID: {UUIDS[1]})\n") + "".join(
                f"  MIG 3g.90gb     Device  {m}: (UUID: {u})\n" for m, u in enumerate(SLICES)), ""  # fmt: skip
        if cmd[0] == "nvidia-smi" and "--query-gpu=uuid" in cmd:
            return 0, UUIDS[1] + "\n", ""
        if cmd[0] == "nvidia-smi":
            return 0, "NVIDIA B200, 183359, 575.57.08, 10.0\n", ""
        return 1, "", ""

    facts = engine_probe.host_facts(run, "1:1")
    assert facts["gpu_index"] == "1:1" and facts["card_id"] == engine_probe.card_id(SLICES[1])
    assert facts["card"] == "NVIDIA B200" and all("1:1" not in c for c in asked)  # nvidia-smi -i takes the card
    assert engine_probe.host_facts(run, "0:1")["card_id"] == engine_probe.card_id(CARD0[1][0])  # card 0's own
    whole = engine_probe.host_facts(run, "1")
    assert whole["gpu_index"] == 1 and whole["card_id"] == engine_probe.card_id(UUIDS[1])


@pytest.mark.parametrize(("index", "rc"), [("1:0", 0), ("1", 0), ("1:x", 2), ("1:0:0", 2), ("all", 2)])
def test_the_engine_probe_takes_the_slice_form(index: str, rc: int) -> None:
    r = subprocess.run([sys.executable, "-m", "tools.engine_probe", "run", "--gpu-index", index, "--dry-run"],
                       cwd=ROOT, capture_output=True, text=True, timeout=60, check=False,
                       env={**os.environ, "PYTHONPATH": f"{ROOT / 'libs'}:{ROOT}"})  # fmt: skip
    assert r.returncode == rc, r.stdout + r.stderr
    if rc == 0:
        assert f"--gpus device={index} " in r.stdout
