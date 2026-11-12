"""Stand-ins for the box's own tools in the box-run rehearsal (synthetic; no model, no GPU, no network).

The runner copies this file as ``tools/<name>.py`` of a stand-in box root, so ``python -m tools.<name>`` reaches it
under the name the VM script calls (the ASSUMED interface of deploy/gcp/box-install-run.sh, functions ``d_*``):

  pin_model --install P --models-root M | --promote BUILD --record R --environment E | --resolve --environment E
  qualify --profile P --out F            knobs: fail-qualify (exit 1 with an error), qualify-seconds (works that long)
  serving_config capture ... --out F
  screen_job start --patients N --llm-concurrency C | status --job ID
  trialbox doctor                        unhealthy for a moment after an interruption
  canary --out F                         54 of 54

``tool.py interrupt`` is what an interruption does to the stand-in box (the docker shim's restart, the reboot
stand-in): unhealthy for 0.6 s, and the screen repeats the calls it had in flight (knob repeat-many: five times as
many, a box that pays calls twice). The screen ends ``job-seconds``
(knob, default 5: longer than a stand-in boot) after its last interruption, so it never ends under a test's feet. Every call goes to calls.log.
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

S = Path(os.environ["BR_S"])
BOX = S / "box"


def knob(name: str, default: str = "") -> str:
    p = S / "knobs" / name
    return p.read_text().strip() if p.exists() else default


def flag(name: str) -> bool:
    return (S / "knobs" / name).exists()


def arg(flag: str) -> str:
    return sys.argv[sys.argv.index(flag) + 1]


def called(what: str) -> None:
    with open(S / "calls.log", "a") as fh:
        fh.write(what + "\n")


def job_load() -> dict[str, Any]:
    job: dict[str, Any] = json.loads((BOX / "job.json").read_text())
    return job


def job_save(job: dict[str, Any]) -> None:
    tmp = BOX / "job.json.tmp"
    tmp.write_text(json.dumps(job))
    tmp.replace(BOX / "job.json")


def main() -> int:
    name = Path(__file__).stem
    if name == "tool":  # tool.py interrupt
        (BOX / "unhealthy-until").write_text(str(time.time() + 0.6))
        if (BOX / "job.json").exists():
            job = job_load()
            job["repeated"] += job["concurrency"] * (5 if flag("repeat-many") else 1)
            job["last_interrupt"] = time.time()
            job_save(job)
        return 0
    if not (BOX / "wizard-done").exists():
        print(f"{name}: the box is not set up (the wizard has not run)", file=sys.stderr)
        return 1
    if name == "pin_model":
        if "--install" in sys.argv:
            called("pin")
            roles = sorted(p.name for p in Path(arg("--models-root")).iterdir() if p.is_dir())
            if roles != ["judge", "verifier"]:
                print(f"pin_model: no real model folders (found {roles})", file=sys.stderr)
                return 1
            print(f"pinned the {arg('--install')} pair from {len(roles)} folders")
        elif "--promote" in sys.argv:
            called("promote " + arg("--promote"))
            record = json.loads(Path(arg("--record")).read_text())
            if not record.get("passed"):
                return 1
            done = json.loads((BOX / "promoted.json").read_text()) if (BOX / "promoted.json").exists() else []
            (BOX / "promoted.json").write_text(json.dumps([*done, arg("--promote")]))
        elif "--resolve" in sys.argv:
            done = json.loads((BOX / "promoted.json").read_text()) if (BOX / "promoted.json").exists() else []
            by_role = {b.split("-")[1]: b for b in done}
            print(
                json.dumps({r: {"build": by_role.get(r, ""), "promoted": r in by_role} for r in ("judge", "verifier")})
            )
        return 0
    if name == "qualify":
        called("qualify")
        print("qualify: the pair gate (stand-in)", flush=True)
        end = time.time() + float(knob("qualify-seconds", "0"))
        while time.time() < end:  # works, and says so: its output is the run's heartbeat
            print("qualify: item", flush=True)
            time.sleep(0.2)
        if flag("fail-qualify"):
            print("qualify: FAIL stand-in gate: schema failures 3 of 54", flush=True)
            return 1
        rec = {
            "standin": True,
            "passed": True,
            "profile": arg("--profile"),
            "builds": {"judge": "standin-judge-1", "verifier": "standin-verifier-1"},
        }
        Path(arg("--out")).write_text(json.dumps(rec))
        return 0
    if name == "serving_config":
        called("capture")
        Path(arg("--out")).write_text(json.dumps({"standin": True, "containers": sys.argv.count("--container")}))
        return 0
    if name == "screen_job":
        if sys.argv[1] == "start":
            called("screen-start")
            now = time.time()
            job_save(
                {
                    "start": now,
                    "last_interrupt": now,
                    "repeated": 0,
                    "concurrency": int(arg("--llm-concurrency")),
                    "patients": int(arg("--patients")),
                }
            )
            print("standin-job-1")
            return 0
        job, now = job_load(), time.time()
        running = now - job["last_interrupt"] < float(knob("job-seconds", "5"))
        print(
            json.dumps(
                {
                    "state": "running" if running else "done",
                    "in_flight": job["concurrency"] if running else 0,
                    "calls_total": int((now - job["start"]) * 50),
                    "calls_repeated": job["repeated"],
                }
            )
        )
        return 0
    if name == "trialbox":  # doctor
        until = float((BOX / "unhealthy-until").read_text()) if (BOX / "unhealthy-until").exists() else 0.0
        return 0 if time.time() >= until else 1
    if name == "canary":
        called("canary")
        Path(arg("--out")).write_text(
            json.dumps({"standin": True, "total": 54, "passed": 54, "schema_failures": 0, "calls_per_s": 3.1})
        )
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
