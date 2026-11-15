"""The checks of the box-run rehearsal (rehearse-box-run.sh): ``check.py <case> <state dir>``, exit 1 on any failure.

It reads what the driver collected over the door (evidence/results: state.json, parts/, vm.log, records/) and what the
stand-ins wrote down (calls.log, POWEROFF, vm-gcloud.log).
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

case, S = sys.argv[1], Path(sys.argv[2])
R = S / "evidence" / "results"
fails: list[str] = []


def ok(cond: bool, what: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        fails.append(what)


state = json.loads((R / "state.json").read_text())
parts = {p.stem: json.loads(p.read_text()) for p in sorted((R / "parts").glob("*.json"))}
calls = Counter((S / "calls.log").read_text().split("\n"))
vm_log = (R / "vm.log").read_text()
poweroff = (S / "POWEROFF").read_text() if (S / "POWEROFF").exists() else ""
gcloud = (S / "vm-gcloud.log").read_text()
ALL = [
    "01-bundle",
    "02-install",
    "03-wizard",
    "04-pin",
    "05-qualify",
    "06-promote-judge",
    "07-promote-verifier",
    "08-resolve",
    "09-serving",
    "10-g9-screen",
    "11-g9-restart-orchestrator",
    "12-g9-restart-adapter",
    "13-g9-restart-judge",
    "14-g9-power",
    "15-g9-result",
    "16-g10-canary",
]

# every case: the door, the cloud calls, the secrets
ok((S / "evidence" / "no-key-http-code").read_text().strip() == "401", "the door refuses a call without the key (401)")
ok(
    "NOT-REHEARSED" not in gcloud and set(gcloud.split("\n")) <= {"secrets versions access", ""},
    "the VM's only cloud calls read its two secrets (no VM is started, stopped or resized)",
)
key = (S / "driver" / "hdr").read_text().split()[-1]
leaked = [
    str(p)
    for p in list(R.rglob("*")) + list(S.glob("boot-*.out")) + [S / "vm" / "serial.log"]
    if p.is_file() and key in p.read_text(errors="replace")
]
ok(not leaked, f"the door's key is in no log and no result {leaked or ''}")
ok(all(isinstance(p["seconds"], float) and p["started"] and p["ended"] for p in parts.values()), "every part is timed")
ok(not (S / "vm" / "tb" / "wizard-answers").exists(), "the wizard's answers file is gone from the disk")

if case in ("happy", "reboot", "paid-twice"):
    ok(list(parts) == ALL and state["order"] == ALL, f"the sixteen steps, in order ({len(parts)} parts)")
    ok(all(p["ok"] and p["status"] == "done" for p in parts.values()), "every step is done, no stop")
    ok(state["ended"].startswith("TB-BOX-RUN-COMPLETE"), "the run ended complete")
    for what in (
        "install",
        "wizard",
        "pin",
        "capture",
        "screen-start",
        "canary",
        "promote standin-judge-1",
        "promote standin-verifier-1",
        "docker-restart orchestrator",
        "docker-restart adapter",
        "docker-restart judge",
    ):
        ok(calls[what] == 1, f"'{what}' ran exactly once ({calls[what]})")
    q = parts["08-resolve"]["detail"]
    ok(
        q.get("production_resolves_promoted") is True
        and q["judge"] == "standin-judge-1"
        and q["verifier"] == "standin-verifier-1",
        "G-2: PRODUCTION resolves judge and verifier to the promoted builds",
    )
    ok(all("minutes" in parts[n] for n in ALL[:9]), "G-2: minutes per step")
    sv = parts["09-serving"]["detail"]
    ok(sv["host_rss_kib_judge"] > 0 and sv["host_rss_kib_verifier"] > 0, "G-2: host RSS of both model servers")
    ok(
        (R / "records" / "qualification.json").exists() and (R / "records" / "serving_config.json").exists(),
        "the qualification record and the serving record come back",
    )
    for c in ("orchestrator", "adapter", "judge"):
        d = parts[next(n for n in ALL if n.endswith("restart-" + c))]
        ok(
            "seconds_to_healthy" in d["detail"]
            and d["detail"]["job_state"] == "running"
            and "calls_repeated" in d["detail"],
            f"G-9 restart of {c}: seconds to healthy, the job's state, calls repeated",
        )
    pw = parts["14-g9-power"]
    ok(
        len(pw["boots"]) == 2 and pw["attempts"] == 2 and pw["detail"]["boot_before"] != pw["detail"]["boot_after"],
        "G-9 power cycle: asked in one boot, finished in the next",
    )
    ok(
        pw["detail"]["job_state"] == "running" and "seconds_to_healthy" in pw["detail"],
        "G-9 power cycle: the job is running again after the boot; seconds to healthy from the boot's start",
    )
    ok("TB-POWER-CYCLE-REQUESTED" in vm_log and "TB-POWER-CYCLE-DONE" in vm_log, "the power cycle is in the run log")
    ok(not (S / "vm" / "tb" / "POWER-CYCLE-REQUEST").exists(), "the request marker is gone after the cycle")
    res = parts["15-g9-result"]["detail"]
    ok(
        res["final_job_state"] == "done" and res["current_moved"] is False and res["interruptions"] == 4,
        "G-9 result: final job state, CURRENT did not move, four interruptions",
    )
    g10 = parts["16-g10-canary"]
    ok(
        g10["pass"] is True
        and g10["detail"]["cases"] == 54
        and g10["detail"]["passed"] == 54
        and g10["detail"]["image_judge"] == "standin/model-server:new",
        "G-10: 54 of 54 on the declared image",
    )
    ok("done, results collected" in poweroff, "power-off once the driver collected")
    g9 = [parts[n]["pass"] for n in ALL[10:15]]
    if case == "paid-twice":
        ok(g9 == [False] * 5, "a box that pays calls twice: every G-9 rule says pass false, and the run went on")
    else:
        ok(g9 == [True] * 5, "G-9: no call repeated beyond the ones in flight, at every interruption")
    if case == "reboot":
        ok(
            calls["qualify"] == 2 and parts["05-qualify"]["attempts"] == 2 and len(parts["05-qualify"]["boots"]) == 2,
            "the cut step (05-qualify) ran again in the next boot",
        )
        ok(
            calls["reboot"] == 2
            and vm_log.count("TB-STEP 02-install kept") == 2
            and vm_log.count("TB-STEP 02-install start") == 1,
            "two reboots; the installer was kept both times, never run again",
        )
    else:
        ok(calls["qualify"] == 1 and calls["reboot"] == 1, "the qualification ran once; one power cycle")

if case == "step-fails":
    ok(list(parts) == ALL[:5], "the run stopped at 05-qualify: no later part")
    p = parts["05-qualify"]
    ok(
        p["status"] == "stop" and not p["ok"] and "the full qualification: exit 1" in p["stop"]["reason"],
        "the stop's record: the step, what failed, its exit code",
    )
    ok(
        any("schema failures 3 of 54" in line for line in p["stop"]["log_tail"]),
        "the stop's record has the step's last log lines",
    )
    ok(state["ended"].startswith("TB-STOP 05-qualify"), "the run's last marker is the stop")
    ok(
        calls["install"] == 1
        and calls["wizard"] == 1
        and calls["qualify"] == 1
        and calls["pin"] == 1
        and calls["capture"] == 0,
        "nothing was repeated by the second boot, nothing ran after the stop",
    )
    ok("TB-RUN-ENDED-BEFORE" in vm_log, "the second boot only handed the results over")
    ok(
        "grace of 3 minutes over" in poweroff and "done, results collected" in poweroff,
        "power-off after the grace, then once collected",
    )

if case == "cap":
    ok("cost cap of 12 minutes reached" in poweroff, "the cap powered the VM off")
    ok((S / "evidence" / "results-at-cap.tgz").stat().st_size > 0, "a results.tgz was packed at the cap")
    ok("TB-WATCHDOG cost cap of 12 minutes reached" in vm_log, "the run log says why")
    ok(state["ended"].startswith("TB-CAP-REACHED"), "the next boot ended at once: the cap counts every boot")
    ok(calls["qualify"] == 1 and calls["install"] == 1, "no step ran again after the cap")
    ok(
        "05-qualify" not in parts and state["steps"]["05-qualify"]["status"] == "started",
        "the cut step has no part result",
    )

if case in ("bad-hash", "bad-tar-hash"):
    p = parts.get("01-bundle", {})
    ok(
        list(parts) == ["01-bundle"] and p["status"] == "stop" and "TB-BUNDLE-REFUSED" in p["stop"]["reason"],
        "the bundle is refused",
    )
    ok(calls["install"] == 0, "the installer never ran")
    ok(state["ended"].startswith("TB-STOP 01-bundle"), "the run ended with the refusal")
    if case == "bad-hash":
        ok(any("images/app.tar: sha256" in r for r in p["detail"]["refused"]), "the record names the file that differs")
        ok(
            not (S / "vm" / "tb" / "boxruns" / "rehearsal-bad-hash" / "bundle" / "images" / "app.tar").exists(),
            "the file that differs is not left unpacked",
        )
    else:
        ok("manifest_files" not in p["detail"], "a bundle that is not the declared one is never unpacked")

print(f"check {case}: {'FAILED ' + str(len(fails)) if fails else 'passed'}")
sys.exit(1 if fails else 0)
