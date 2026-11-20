"""H-53: the 48 GB measuring run's start-up script (tools/measure48-vm.sh) rehearsed on stand-ins: no card, no
Docker, no cloud, no root. The script runs unchanged with its rehearsal knobs (TB_M48_*): the metadata is a folder,
the bucket is a folder behind a stand-in gcloud, every repository tool is one stand-in program, and nvidia-smi,
docker, apt-get, ubuntu-drivers and systemctl are stand-ins on PATH. A second is a second unless a case scales it."""

from __future__ import annotations

import hashlib
import io
import json
import os
import signal
import subprocess
import sys
import tarfile
import time
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "measure48-vm.sh"
HELPER = ROOT / "tools" / "measure48_vm.py"
KEY = "sk-standin-key-0123456789abcdef"
ADMIN = "standin-admin-pass-42"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
LINE_MIN = 204

STANDIN = r"""#!/usr/bin/env python3
import json, os, pathlib, signal, sys, time
a = sys.argv[1:]
with open(os.environ["M48_CALLS"], "a") as f:
    f.write(" ".join(a) + "\n")
KEY = "@KEY@"
ck = pathlib.Path(os.environ["M48_CK"])
def arg(n):
    return a[a.index(n) + 1]
t = a[0]
if t == "fetch_weights":
    print("fetched 27.9 GB")
    sys.exit(int(os.environ.get("M48_WEIGHTS_RC", "0")))
if t == "poc":
    if len(a) == 1:
        (ck / "deploy/secrets/model").mkdir(parents=True, exist_ok=True)
        (ck / "deploy/.env").write_text("TB_ADMIN_PASSWORD=@ADMIN@\n")
        (ck / "deploy/secrets/model/vllm.env").write_text('VLLM_API_KEY="' + KEY + '"\n')
        print("the box is up; sign in as admin with @ADMIN@")
    sys.exit(0)
if t == "pinned_ref":
    print("vllm/vllm-openai:v0.32.0@sha256:0000")
    sys.exit(0)
if t == "ballast":
    if a[1] == "hold":
        def bye(*_):
            print("released", flush=True)
            sys.exit(0)
        signal.signal(signal.SIGTERM, bye)
        print("ready: start the servers now", flush=True)
        while True:
            time.sleep(0.05)
    sys.exit(0)
if t == "ballast48":
    sub = a[1]
    if sub == "measure":
        opt, out = arg("--option"), pathlib.Path(arg("--out-dir"))
        out.mkdir(parents=True, exist_ok=True)
        print("measuring " + opt + " with the key " + KEY, flush=True)
        if os.environ.get("M48_CRASH") == opt:
            print("Traceback (most recent call last):", flush=True)
            print("ZeroDivisionError: a bug", flush=True)
            sys.exit(1)
        if os.environ.get("M48_HANG") == opt:
            # as lane J's measure: Python's own KeyboardInterrupt, no handler of its own (an ignored SIGINT never
            # becomes one: the VM script must start the tool with SIGINT at its default)
            try:
                while True:
                    time.sleep(0.05)
            except KeyboardInterrupt:
                (out / ("measure." + opt + ".json")).write_text(json.dumps({"option": opt, "started": False,
                    "interrupted": True, "outcome": "BY BALLAST: stopped"}))
                sys.exit(130)
        started = opt not in os.environ.get("M48_FAIL", "").split()
        (out / ("measure." + opt + ".json")).write_text(json.dumps({"option": opt, "started": started,
            "outcome": "BY BALLAST", "card_peak_mib": 45000, "ballast": {"free_at_peak_mib": 4100},
            "engine_log": {"judge": {"kv_cache_tokens": 98304}}}))
        if started:
            (out / ("canary." + opt + ".json")).write_text(json.dumps({"models": [{"role": "judge", "cases": 54,
                "seconds": 108.0}]}))
            (out / ("serving_config.dgpu48." + opt + ".json")).write_text("{}")
            if "--keep" in a:
                (out / "down.json").write_text(json.dumps({"cmd": ["docker"], "env": {"VLLM_API_KEY": KEY}}))
        sys.exit(0 if started else 1)
    if sub == "plan" and os.environ.get("M48_PLAN_REFUSED"):
        print("ballast48: refused: " + os.environ["M48_PLAN_REFUSED"], file=sys.stderr)
        sys.exit(2)
    if sub == "during":
        parts = pathlib.Path(arg("--dir")) / "parts"
        parts.mkdir(parents=True, exist_ok=True)
        (parts / "hospital-ja.json").write_text(json.dumps({"wall_seconds": 640.0}))
        (parts / "prepare.json").write_text("{}")
        (parts / "hospital-ja.debug.txt").write_text("the key " + os.environ.get("TB_GPU_KEY", ""))
        pathlib.Path(arg("--out")).write_text(json.dumps({"wall_seconds": 700.0, "exit_code": 0,
            "free_at_peak_mib": 3900, "ballast_held_at_end": True}))
        sys.exit(0)
    if sub == "verifier-flag":
        sys.exit(int(os.environ.get("M48_FLAG_RC", "0")))
    if sub == "canary-diff":
        pathlib.Path(arg("--json")).write_text(json.dumps({"verdicts_differ": 2, "exact": True, "runs": {}}))
    sys.exit(0)
if t == "canary":
    print(json.dumps({"ok": True, "models": []}))
sys.exit(0)
""".replace("@KEY@", KEY).replace("@ADMIN@", ADMIN)

SHIMS = {
    "nvidia-smi": '#!/bin/sh\n[ -z "${M48_DRIVER_MARK:-}" ] || [ -f "$M48_DRIVER_MARK" ] || exit 9\n'
    'echo "NVIDIA RTX PRO 6000, 97887 MiB, 12.0, 580.95, Enabled"\n',
    "docker": '#!/bin/sh\necho "docker $*" >> "$M48_CALLS"\ncase "$1" in\n info) echo "Runtimes: nvidia runc" ;;\n'
    ' inspect) case "$*" in *IPAddress*) echo 172.17.0.2 ;; *) echo true ;; esac ;;\n'
    ' system) echo "Images 0 0 0B 0B" ;;\nesac\nexit 0\n',
    "gcloud": '#!/bin/bash\nm() { case "$1" in gs://*) echo "$M48_GCS/${1#gs://}" ;; *) echo "$1" ;; esac; }\n'
    'if [ "$1 $2" = "storage cp" ]; then mkdir -p "$(dirname "$(m "$4")")"; cp "$(m "$3")" "$(m "$4")"; exit; fi\n'
    'if [ "$1 $2" = "storage rsync" ]; then d=$(m "$5"); mkdir -p "$d"; cp -a "$(m "$4")/." "$d/"; exit; fi\n'
    "exit 3\n",
    "apt-get": '#!/bin/sh\ncase "$*" in *nvidia-driver-580-server-open*)\n'
    '  [ -z "${M48_DRIVER_MARK:-}" ] || touch "$M48_DRIVER_MARK" ;;\nesac\n',
    "systemctl": "#!/bin/sh\nexit 0\n",
}


class Rig:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.w = tmp / "vm"
        self.md = tmp / "md"
        self.gcs = tmp / "gcs"
        self.bin = tmp / "bin"
        self.calls = tmp / "calls.txt"
        for d in (self.md, self.gcs, self.bin, tmp / "etc" / "apt" / "apt.conf.d"):
            d.mkdir(parents=True)
        for name, text in {**SHIMS, "standin": STANDIN}.items():
            (self.bin / name).write_text(text)
            (self.bin / name).chmod(0o755)
        (self.bin / "off").write_text(f"#!/bin/sh\ntouch {tmp}/powered-off\n")
        (self.bin / "reboot").write_text(f"#!/bin/sh\ntouch {tmp}/rebooted\n")
        for x in ("off", "reboot"):
            (self.bin / x).chmod(0o755)
        src = tmp / "src.tgz"
        with tarfile.open(src, "w:gz") as tf:
            head = json.dumps({"head": COMMIT}).encode()
            info = tarfile.TarInfo("TB_HEAD.json")
            info.size = len(head)
            tf.addfile(info, io.BytesIO(head))
            folder = tarfile.TarInfo("trialbox/deploy")
            folder.type = tarfile.DIRTYPE
            folder.mode = 0o755  # TarInfo's default 0o644 leaves a folder only root can enter (CI is not root)
            tf.addfile(folder)
        self.metadata(**{"tb-run-id": "m48-test", "tb-bucket": "gs://bk", "tb-commit": COMMIT, "tb-src": str(src),
                         "tb-src-sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
                         "tb-stop-line-minutes": str(LINE_MIN), "tb-cap-minutes": "240", "tb-o": "1",
                         "tb-m48-helper": HELPER.read_text()})  # fmt: skip

    def metadata(self, **kv: str) -> None:
        for k, v in kv.items():
            (self.md / k).write_text(v)

    @property
    def run_dir(self) -> Path:
        return self.w / "run"

    @property
    def up(self) -> Path:
        return self.gcs / "bk" / "m48runs" / "m48-test"

    def boot(self, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["bash", str(SCRIPT)], env=self.env(**env), capture_output=True, text=True,
                              timeout=180, check=False)  # fmt: skip

    def env(self, **env: str) -> dict[str, str]:
        e = {k: v for k, v in os.environ.items() if k != "PYTHONUNBUFFERED"}
        e.update({"PATH": f"{self.bin}:{e['PATH']}", "TB_M48_ROOT": str(self.w), "TB_M48_SBIN": str(self.tmp / "sbin"),
                  "TB_M48_SERIAL": str(self.tmp / "serial"), "TB_M48_MD_DIR": str(self.md), "TB_M48_POLL_S": "0.2",
                  "TB_M48_STANDIN": str(self.bin / "standin"), "TB_M48_POWEROFF": str(self.bin / "off"),
                  "TB_M48_REBOOT": str(self.bin / "reboot"), "TB_M48_NO_TIMER": "1", "TB_M48_ETC": str(self.tmp / "etc"),
                  # the disk guard sees a fixed 200 GB, not the host's / (a CI runner has far less than the 30 GB
                  # the weights need); the disk guard's own case sets less
                  "TB_M48_FREE_BYTES": str(200 * 10**9),
                  "M48_CALLS": str(self.calls), "M48_GCS": str(self.gcs), "M48_CK": str(self.w / "src" / "trialbox")})  # fmt: skip
        e.update(env)
        return e

    def decisions(self) -> dict[str, str]:
        d = json.loads((self.up / "decisions.json").read_text())
        return {x["what"]: f"{x['choice']} | {x['why']}" for x in d["decisions"]}

    def steps(self) -> dict[str, dict[str, Any]]:
        return {s["step"]: s for s in json.loads((self.up / "steps.json").read_text())["steps"]}

    def resume_after(self, last: str, kept: str | None = None, used_s: int = 0) -> None:
        """A disk as a later boot finds it: the steps up to ``last`` finished (state/), the checkout there."""
        order = ["s01-host", "s02-card", "s03-source", "s04-weights", "s05-stub", "s06-engine", "s07-ballast",
                 "s08-ladder"]  # fmt: skip
        r = self.run_dir
        for d in ("state", "kv", "logs", "records", "raw"):
            (r / d).mkdir(parents=True, exist_ok=True)
        for s in order[: order.index(last) + 1]:
            (r / "state" / s).write_text("0")
        ck = self.w / "src" / "trialbox" / "deploy" / "secrets" / "model"
        ck.mkdir(parents=True)
        (ck / "vllm.env").write_text(f"VLLM_API_KEY={KEY}\n")
        (r / "kv" / "ballast-on").write_text("")
        (r / "used-s").write_text(str(used_s))
        if kept:
            (r / "kv" / "kept").write_text(kept)
            m = r / "records" / f"tb-dgpu48-{kept}"
            m.mkdir(parents=True)
            (m / f"canary.{kept}.json").write_text("{}")


def _all_text(d: Path) -> str:
    return "\n".join(p.read_text(errors="replace") for p in d.rglob("*") if p.is_file())


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


def test_happy_path_reboots_once_then_runs_every_stage_and_uploads_only_records(rig: Rig) -> None:
    mark = rig.tmp / "driver-installed"
    first = rig.boot(M48_DRIVER_MARK=str(mark))
    assert first.returncode == 0, first.stdout[-2000:]
    assert (rig.tmp / "rebooted").exists() and not (rig.tmp / "powered-off").exists()
    second = rig.boot(M48_DRIVER_MARK=str(mark))
    assert second.returncode == 0, second.stdout[-3000:]
    assert (rig.tmp / "powered-off").exists()
    steps = rig.steps()
    assert list(steps) == ["s01-host", "s02-card", "s03-source", "s04-weights", "s05-stub", "s06-engine",
                           "s07-ballast", "s08-ladder", "s09-tools", "s10-screen", "s11-o", "s12-down",
                           "s13-host53", "s14-release"]  # fmt: skip
    assert all(s["rc"] == 0 for s in steps.values()), steps
    assert json.loads((rig.up / "steps.json").read_text())["ended"].startswith("complete")
    dec = rig.decisions()
    assert dec["reboot"].startswith("yes")
    assert dec["kept"].startswith("pair-32k")
    assert dec["O"].startswith("run") and dec["O result"].startswith("flag started")
    assert dec["step 9"].startswith("run")
    for rel in ("records/tb-dgpu48-pair-32k/measure.pair-32k.json", "records/tb-dgpu48-pair-32k/canary.pair-32k.json",
                "records/tb-dgpu48-pair-32k/serving_config.dgpu48.pair-32k.json",
                "records/tb-dgpu48-pair-32k-host53/measure.pair-32k-host53.json", "records/screen-during.json",
                "records/screen/parts/hospital-ja.json", "records/canary-verifier-flag.json",
                "records/canary-verifier-flag-diff.json", "records/o0-card.csv", "records/plan.txt",
                "records/ballast.log", "records/head.json", "logs/s08-ladder.log", "disk.jsonl"):  # fmt: skip
        assert (rig.up / rel).is_file(), rel
    # never up: the stub's output, deploy/.env, deploy/secrets/, down.json, the screen's other files; no key anywhere
    names = [p.relative_to(rig.up).as_posix() for p in rig.up.rglob("*") if p.is_file()]
    assert not [n for n in names if "raw" in n or "down.json" in n or ".env" in n or "secrets" in n or "debug" in n]
    text = _all_text(rig.up)
    assert KEY not in text and ADMIN not in text
    assert (rig.run_dir / "raw" / "poc-up.txt").read_text().count(ADMIN) == 1  # it stayed on the VM, in raw/
    assert "released" in (rig.up / "records" / "ballast.log").read_text()
    calls = rig.calls.read_text()
    assert "ballast48 measure --option pair-32k --keep" in calls
    assert "--patients 1000 --langs ja --only prepare hospital-ja --llm-concurrency 16" in calls
    assert "ballast48 measure --option pair-32k-host53 --out-dir" in calls  # no --keep
    assert calls.index("verifier-flag") < calls.index("ballast48 down") < calls.index("pair-32k-host53")
    assert "docker builder prune -af" in calls  # the build cache freed after the stub


def test_ladder_keeps_the_first_that_starts_and_skips_o_and_step_9(rig: Rig) -> None:
    r = rig.boot(M48_FAIL="pair-32k")
    assert r.returncode == 0, r.stdout[-2000:]
    dec = rig.decisions()
    assert dec["ladder pair-32k"].startswith("try") and dec["ladder pair-16k"].startswith("try")
    assert "pair-32k did not start" in dec["ladder pair-16k"]
    assert dec["kept"].startswith("pair-16k")
    assert dec["O"].startswith("skipped") and "pair-16k, not pair-32k" in dec["O"]
    assert dec["step 9"].startswith("skipped")
    assert "s10-screen" in rig.steps() and "s11-o" not in rig.steps() and "s13-host53" not in rig.steps()


def test_judge_alone_skips_the_screen(rig: Rig) -> None:
    r = rig.boot(M48_FAIL="pair-32k pair-16k")
    assert r.returncode == 0, r.stdout[-2000:]
    dec = rig.decisions()
    assert dec["kept"].startswith("judge-alone") and dec["screen"].startswith("skipped")
    assert "s09-tools" not in rig.steps()


def test_no_option_starts_ends_the_run_with_records_and_power_off(rig: Rig) -> None:
    r = rig.boot(M48_FAIL="pair-32k pair-16k judge-alone")
    assert r.returncode == 0
    assert (rig.tmp / "powered-off").exists()
    assert rig.decisions()["ladder"].startswith("pair-32k:1 pair-16k:1 judge-alone:1")
    steps = rig.steps()
    assert steps["s08-ladder"]["rc"] == 1 and steps["s14-release"]["rc"] == 0 and "s12-down" not in steps
    assert "s08-ladder" in json.loads((rig.up / "steps.json").read_text())["ended"]


def test_a_boot_after_the_end_keeps_why_the_run_ended(rig: Rig) -> None:
    rig.boot(M48_FAIL="pair-32k pair-16k judge-alone")
    ended = (rig.run_dir / "ended").read_text()
    assert "s08-ladder" in ended
    again = rig.boot()
    assert again.returncode == 0 and "power off: ended before: s08-ladder" in again.stdout
    assert "ended unexpectedly" not in again.stdout
    assert (rig.run_dir / "ended").read_text() == ended
    assert json.loads((rig.up / "steps.json").read_text())["ended"] == ended


def test_a_refused_flag_is_the_result(rig: Rig) -> None:
    r = rig.boot(M48_FLAG_RC="1")
    assert r.returncode == 0
    dec = rig.decisions()
    assert dec["O result"].startswith("flag refused (exit 1)")
    assert not (rig.up / "records" / "canary-verifier-flag.json").exists()
    assert rig.steps()["s11-o"]["rc"] == 0


def test_tb_o_0_leaves_o_out(rig: Rig) -> None:
    rig.metadata(**{"tb-o": "0"})
    assert rig.boot().returncode == 0
    assert rig.decisions()["O"].startswith("skipped | not taken at the launch")


def test_late_o_runs_and_step_9_is_dropped_first(rig: Rig) -> None:
    rig.resume_after("s08-ladder", kept="pair-32k", used_s=LINE_MIN * 60 - int(0.5 * 3600))
    assert rig.boot().returncode == 0
    dec = rig.decisions()
    assert dec["screen"].startswith("not started")  # the tools and the screen, 0.90 h, do not fit in 0.5 h
    assert dec["O"].startswith("run")
    assert dec["step 9"].startswith("dropped")
    assert "s12-down" in rig.steps() and "s13-host53" not in rig.steps()


def test_later_still_o_is_skipped_too(rig: Rig) -> None:
    rig.resume_after("s08-ladder", kept="pair-32k", used_s=LINE_MIN * 60 - int(0.2 * 3600))
    assert rig.boot().returncode == 0
    dec = rig.decisions()
    assert dec["O"].startswith("skipped | stage O not started: 0.20 h left")
    assert dec["step 9"].startswith("dropped")
    steps = rig.steps()
    assert "s11-o" not in steps and steps["s12-down"]["rc"] == 0 and steps["s14-release"]["rc"] == 0


def test_a_stage_that_does_not_fit_before_the_line_ends_the_run(rig: Rig) -> None:
    rig.metadata(**{"tb-stop-line-minutes": "30"})  # stage 2's high is 0.75 h
    assert rig.boot().returncode == 0
    assert rig.decisions()["s01-host"].startswith("not started | stage 2 not started")
    assert "stop line" in json.loads((rig.up / "steps.json").read_text())["ended"]
    assert (rig.tmp / "powered-off").exists()


def test_the_stop_line_interrupts_a_running_measure(rig: Rig) -> None:
    # 0.8 h (stage 6 high) plus 1,800 s of slack: 3 s real at x600, so a loaded machine still reaches the ladder in time
    rig.resume_after("s07-ballast", used_s=LINE_MIN * 60 - int(0.8 * 3600) - 1800)
    r = rig.boot(M48_HANG="pair-32k", TB_M48_TIME_SCALE="600")
    assert r.returncode == 0, r.stdout[-2000:]
    assert "the stop line" in (rig.up / "vm.log").read_text()
    rec = json.loads((rig.up / "records/tb-dgpu48-pair-32k/measure.pair-32k.json").read_text())
    assert rec["interrupted"] is True  # lane J's measure wrote what it had
    assert "pair-32k:130" in rig.decisions()["ladder"]
    assert (rig.tmp / "powered-off").exists()


def test_the_disk_guard_fails_the_step_with_its_record(rig: Rig) -> None:
    r = rig.boot(TB_M48_FREE_BYTES=str(20 * 10**9))
    assert r.returncode == 0
    s = rig.steps()["s04-weights"]
    assert s["rc"] == 1 and "DISK-SHORT" in s["note"] and "30 GB needed" in s["note"]
    assert "fetch_weights" not in rig.calls.read_text()


def test_a_gated_weight_fails_its_step_and_nothing_waits(rig: Rig) -> None:
    r = rig.boot(M48_WEIGHTS_RC="1")
    assert r.returncode == 0
    assert "no token is sent" in rig.steps()["s04-weights"]["note"]
    assert (rig.tmp / "powered-off").exists()


def test_a_ballast48_plan_refusal_ends_the_run_naming_both_free_figures(rig: Rig) -> None:
    """H-66: the 11-19 run ended at s07 with "ballast48 plan refused (records/plan.txt)" and no figures; the refusal's
    own line (both figures) is now the step's note and the run's end reason. The run still ends cleanly: the ballast
    released, the records up, the VM off."""
    why = "49776 MiB free, not 49140 +/- 512 (nvidia-smi memory.free; 48111 used, 0 reserved by the driver)"
    r = rig.boot(M48_PLAN_REFUSED=why)
    assert r.returncode == 0, r.stdout[-2000:]
    steps = rig.steps()
    assert steps["s07-ballast"]["rc"] == 1 and "s08-ladder" not in steps and steps["s14-release"]["rc"] == 0
    assert steps["s07-ballast"]["note"] == f"ballast48 plan refused (records/plan.txt): ballast48: refused: {why}"
    ended = json.loads((rig.up / "steps.json").read_text())["ended"]
    assert ended.startswith("s07-ballast failed: ballast48 plan refused") and "49776 MiB free, not 49140" in ended
    assert (rig.tmp / "powered-off").exists()


def test_a_wrong_archive_is_refused(rig: Rig) -> None:
    rig.metadata(**{"tb-src-sha256": "0" * 64})
    assert rig.boot().returncode == 0
    assert "sha256" in rig.steps()["s03-source"]["note"]


def test_the_docker_and_toolkit_lines_are_gpu_sim_startups() -> None:
    """The host set-up reuses deploy/gcp/gpu-sim-startup.sh's commands (a start-up script is one metadata file, so
    they are restated, and this holds them equal)."""
    gs = (ROOT / "deploy" / "gcp" / "gpu-sim-startup.sh").read_text().splitlines()
    m48 = SCRIPT.read_text()
    block = m48[m48.index("docker_toolkit() {") : m48.index("step_host() {")]
    start = next(i for i, x in enumerate(gs) if x.startswith("if ! command -v docker"))
    end = next(i for i, x in enumerate(gs) if "systemctl restart docker" in x) + 1
    for line in gs[start:end]:
        if line.strip() and line.strip() != "fi":
            assert line.strip() in block, line


@pytest.mark.skipif(sys.platform != "linux", reason="bash and GNU tools")
def test_the_script_is_bash_clean() -> None:
    assert subprocess.run(["bash", "-n", str(SCRIPT)], check=False).returncode == 0


def test_a_crash_is_not_did_not_start(rig: Rig) -> None:
    r = rig.boot(M48_CRASH="pair-32k")
    assert r.returncode == 0
    dec = rig.decisions()
    assert dec["ladder pair-32k result"].startswith("the tool broke")
    assert "ladder pair-16k" not in dec and "pair-32k:3" in dec["ladder"]


def test_a_did_not_start_is_recorded_as_such(rig: Rig) -> None:
    assert rig.boot(M48_FAIL="pair-32k").returncode == 0
    assert rig.decisions()["ladder pair-32k result"].startswith("did not start")


def test_sigterm_saves_but_does_not_end_the_run_and_the_next_boot_resumes(rig: Rig) -> None:
    """A Spot pre-emption or an ACPI stop (SIGTERM): the clock and the records go up, the run is NOT ended, and
    the next boot goes on from the step that was cut."""
    e = rig.env(M48_HANG="pair-32k")
    p = subprocess.Popen(["bash", str(SCRIPT)], env=e, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(600):
            if rig.calls.exists() and "measure --option pair-32k" in rig.calls.read_text():
                break
            time.sleep(0.1)
        else:
            pytest.fail("the ladder never started")
        time.sleep(1)
        p.send_signal(signal.SIGTERM)
        assert p.wait(timeout=60) == 143
    finally:
        subprocess.run(["pkill", "-f", str(rig.bin / "standin")], check=False)
    assert not (rig.run_dir / "ended").exists()
    assert json.loads((rig.up / "steps.json").read_text())["ended"] == ""
    assert "the run goes on at the next boot" in (rig.up / "vm.log").read_text()
    assert not (rig.tmp / "powered-off").exists()
    assert (rig.run_dir / "state" / "s07-ballast").exists() and not (rig.run_dir / "state" / "s08-ladder").exists()
    r = rig.boot()
    assert r.returncode == 0, r.stdout[-2000:]
    steps = [s["step"] for s in json.loads((rig.up / "steps.json").read_text())["steps"]]
    assert steps.count("s01-host") == 1 and steps.count("s08-ladder") == 1  # nothing finished ran twice
    assert rig.decisions()["kept"].startswith("pair-32k") and (rig.tmp / "powered-off").exists()


def test_tools_start_with_sigint_at_its_default() -> None:
    text = SCRIPT.read_text()
    assert "env --default-signal=INT" in text
    for line in text[text.index("tool() {") : text.index("# ---", text.index("tool() {"))].splitlines():
        if "python" in line and "-c 'import tools.engine_probe" not in line and "trialbox-py" not in line:
            assert "sigint " in line, line


def test_the_driver_is_d966s_open_module() -> None:
    text = SCRIPT.read_text()
    assert "nvidia-driver-580-server-open" in text and "nvidia:580-server " not in text


def test_sigint_restores_what_a_background_start_ignores() -> None:
    """The hazard and the fix, both measured: a simple command started with & gets SIGINT ignored (Python then never
    raises KeyboardInterrupt); the script's sigint() starts it with SIGINT at its default."""
    text = SCRIPT.read_text()
    i = text.index("if env --default-signal=INT true")
    define = text[i : text.index("\nfi\n", i) + 4]
    probe = "import signal; print(signal.getsignal(signal.SIGINT) is signal.SIG_IGN)"
    out = subprocess.run(["bash", "-c", f"{define}\npython3 -c '{probe}' & wait\nsigint python3 -c '{probe}' & wait"],
                         capture_output=True, text=True, check=True).stdout.split()  # fmt: skip
    assert out == ["True", "False"]
