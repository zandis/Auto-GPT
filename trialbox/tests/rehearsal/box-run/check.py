"""The checks of the box-run rehearsal (rehearse-box-run.sh): ``check.py <case> <state dir>``, exit 1 on any failure.

It reads what the driver collected from the bucket (evidence/results: state.json, parts/, vm.log, records/), the
bucket itself, and what the stand-ins wrote down (calls.log, POWEROFF, vm-gcloud.log).
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

case, S = sys.argv[1], Path(sys.argv[2])
R = S / "evidence" / "results"
BKT = S / "bucket" / "tb-runs"
fails: list[str] = []


def ok(cond: bool, what: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        fails.append(what)


if case == "session-wide":  # the driver only (D-1130): no VM was booted, so no state to read
    rcs = dict(line.split("\t") for line in (S / "evidence" / "wide.rc").read_text().splitlines())
    err = (S / "evidence" / "wide.err").read_text()
    ok(len(rcs) == 5 and set(rcs.values()) == {"2"}, f"every too-wide range is refused before anything (exit 2): {rcs}")
    ok("whole internet" in err and "'any' opens tcp:443 to every address" in err and "broader than /24" in err,
       "each refusal says why")  # fmt: skip
    ok("instances start" not in err and not (S / "vm").exists(), "nothing was started")
    print(f"check {case}: {'FAILED ' + str(len(fails)) if fails else 'passed'}")
    sys.exit(1 if fails else 0)

state = json.loads((R / "state.json").read_text())
parts = {p.stem: json.loads(p.read_text()) for p in sorted((R / "parts").glob("*.json"))}
calls = Counter((S / "calls.log").read_text().split("\n"))
vm_log = (R / "vm.log").read_text()
poweroff = (S / "POWEROFF").read_text() if (S / "POWEROFF").exists() else ""
gcloud = (S / "vm-gcloud.log").read_text().split("\n")
ended = state.get("ended", "")
START = [
    "01-bundle",
    "02-install",
    "03-wizard",
    "04-pin",
    "05-serving",
    "06-g1",
    "07-canary",
    "07g-gate",
    "08-qualify",
    "09-promote-judge",
    "10-promote-verifier",
    "11-resolve",
    "12-doctor",
]
BUILD = ["b01-source", "b02-venv", "b03-images", "b04-gates", "b05-sign", "b06-verify", "b07-upload"]
G6 = ["20-g6-study", "21-g6-feed", "22-g6-ingest", "23-g6-rebuild", "24-g6-screen", "25-g6-backup", "26-g6-result"]
G9 = [
    "30-g9-baseline",
    "31-g9-screen",
    "32-g9-restart-orchestrator",
    "33-g9-restart-gateway",
    "37-g9-outage",
    "38-g9-power",
    "39-g9-result",
]
G10 = ["41-g10-image", "42-g10-canary", "43-g10-qualify"]

# ---------------------------------------------------------------- every case: the cloud calls, the secrets, the power
ok(
    all(line in ("", "storage cp") or line.startswith("secrets versions access ") for line in gcloud),
    "the VM's only cloud calls read secrets by name and copy to or from the bucket (no VM is started or stopped)",
)
secrets = [S / "secrets" / "answers" / "1", S / "secrets" / "vendor-key" / "1", S / "driver" / "hdr"]
needles = []
for f in secrets:
    if f.exists():
        text = f.read_text()
        if f.name == "hdr":
            needles.append(text.split()[-1])
        elif "PRIVATE KEY" in text:
            needles.append("".join(text.strip().splitlines()[1:-1]))  # the key's base64 body
        elif text.lstrip().startswith("{"):
            needles.append(json.loads(text)["password"])
# the session's one-time codes (D-1133): the private links object only, never a log, a result or the serial port
codes_file = S / "evidence" / "session-codes.txt"
session_codes = codes_file.read_text().split() if codes_file.exists() else []
needles += session_codes
# validation mode: the first administrator's password and enrolment code the installer prints once (stand-in values)
if (S / "metadata" / "tb-mode").exists() and (S / "metadata" / "tb-mode").read_text() == "validation":
    needles += ["standin-admin-pw-0001", "ENROL-424242-STANDIN"]
leaked = [
    str(p)
    for p in [*R.rglob("*"), *S.glob("boot-*.out"), S / "vm" / "serial.log", *(S / "vm" / "log").glob("*")]
    if p.is_file() and any(n and n in p.read_text(errors="replace") for n in needles)
]
ok(not leaked, f"no secret (the vendor key, the owner's password, the door key) in any log or result {leaked or ''}")
ok(not list((S / "vm" / "shm").glob("tbk.*")) if (S / "vm" / "shm").exists() else True, "no vendor key left on tmpfs")
ok(all(isinstance(p["seconds"], float) and p["started"] and p["ended"] for p in parts.values()), "every part is timed")
ok(not (S / "vm" / "tb" / "wizard-answers").exists(), "the wizard's answers file is gone from the disk")
ok(
    "done, results in the bucket" in poweroff or "cost cap" in poweroff,
    "the VM powered itself off once its results were up",
)
if (S / "metadata" / "tb-door-port").exists():  # a case with the door probes it while the run waits for its power cycle

    def code(name: str) -> str:
        f = S / "evidence" / f"{name}-http-code"
        return f.read_text().strip() if f.exists() else "not probed"

    ok(code("with-key") == "200", f"the door answers the key while the run is up ({code('with-key')})")
    ok(code("no-key") == "401", f"the door refuses a call without the key ({code('no-key')})")


def keys(prefix: list[str]) -> bool:
    return list(parts)[: len(prefix)] == prefix


# ---------------------------------------------------------------- R2's build
if case in ("build", "build-preempt"):
    ok(list(parts) == BUILD and all(p["status"] == "done" for p in parts.values()), "the seven build steps, done")
    ok(ended.startswith("TB-BOX-RUN-COMPLETE"), "the run ended complete")
    rec = json.loads((R / "records" / "bundle.json").read_text())
    obj = BKT / "r2" / "out" / "trialbox-2026.11-r.tar"
    import hashlib

    ok(
        obj.exists() and hashlib.sha256(obj.read_bytes()).hexdigest() == rec["sha256"],
        "the bundle is in the bucket, its sha256 recorded",
    )
    ok(
        (BKT / "r2" / "out" / "trialbox-2026.11-r.tar.sha256").read_text().split()[0] == rec["sha256"],
        "and its .sha256 beside it",
    )
    ok(gcloud.count("secrets versions access vendor-key") == 1, "the vendor key was read once, by its secret's name")
    ok(calls["make-bundle key-ok"] == 1, "make_bundle.sh found the key file at mode 600")
    ok(
        calls["make-bundle models embedder gemma-4-26b-a4b-it-4bit qwen3.5-9b-4bit "] == 1,
        "H-43: make_bundle.sh was given the weights (--models: the pair's folders and embedder/)",
    )
    ok(parts["b05-sign"]["detail"]["key_left_on_tmpfs"] is False, "the key file was gone after the signing step")
    v = parts["b06-verify"]["detail"]
    ok(
        v["refused"] == [] and v["release"]["dirty"] is False and v["release"]["rehearsal"] is False,
        "b06: the signature verifies (verify_update.py) and the release record is one PRODUCTION takes",
    )
    ok(bool(v.get("signature_sha256")) and bool(v.get("key_id")), "b06 names the signature and the signing key")
    if case == "build-preempt":
        ok(
            parts["b03-images"]["attempts"] == 2 and parts["b02-venv"]["attempts"] == 1,
            "the cut step ran again, the ones before were kept",
        )
        ok(calls["venv"] == 1 and calls["images"] == 2, "make venv once, make images twice")

if case == "build-gate-fails":
    ok(list(parts) == BUILD[:4] and parts["b04-gates"]["status"] == "stop", "the build stopped at the gates")
    ok(
        "TB-GATES-FAILED" in parts["b04-gates"]["stop"]["reason"]
        and "CVE-2026-128089" in parts["b04-gates"]["stop"]["reason"],
        "the stop names the failed gate",
    )
    ok("secrets versions access vendor-key" not in gcloud, "the vendor key was never read")
    ok(not (BKT / "r2" / "out").exists(), "nothing was uploaded")

if case == "build-refused":
    ok(list(parts) == BUILD[:6] and parts["b06-verify"]["status"] == "stop", "the build stopped at b06")
    ok(
        any("rehearsal bundle" in r for r in parts["b06-verify"]["detail"]["refused"]),
        "refused: a rehearsal bundle (D-726)",
    )
    ok(not (BKT / "r2" / "out").exists(), "nothing was uploaded")

# ---------------------------------------------------------------- G-2 and the tests on the installed box
full_start = case in ("happy", "reboot", "oom", "list-differs", "gate-closed")
if full_start:
    ok(keys(START) and all(parts[n]["status"] == "done" for n in START), "G-2: the start steps, done")
    ok(
        parts["07g-gate"].get("pass") is True and calls["canary-gate once"] == 1,
        "B2: the canary through the box's own gate holds a passing record, read with the service token",
    )
    if case != "gate-closed":
        ok(
            calls["canary-gate wait"] == 0,
            "D2: the gate was open at the first read (07's canary is its result): no restart, no wait",
        )
    ok(calls["install"] == 1 and calls["hostcheck"] == 1, "the installer ran once (prepare), the first run once")
    w = parts["03-wizard"]["detail"]
    ok(w.get("wizard") == "done" and w.get("owner") == "owner", "the wizard was answered through the console's page")
    ok(not (S / "vm" / "firstrun" / "answers.json").exists(), "the installer applied the answers and removed them")
    b = parts["01-bundle"]["detail"]
    ok(
        b["refused"] == [] and b["host_payload"] == "trialbox-host.tar" and bool(b["vendor_pub_sha256"]),
        "01: the signed bundle checked, its host tree the bootstrap, the vendor public key placed",
    )
    ok(
        (S / "box-root" / "deploy" / "keys" / "vendor_ed25519.pub").exists(),
        "deploy/keys/vendor_ed25519.pub on the box",
    )
    idn = json.loads((R / "records" / "identity.json").read_text())
    ok(
        idn["pass"] is True
        and idn["checks"]["chat_template_served_is_pinned"]
        and idn["checks"]["images_in_images_lock"],
        "06-g1: the served chat template and the image digests are the pinned ones",
    )
    ok(
        len(idn["served_prompts"]) > 0 and all("version" in p for p in idn["served_prompts"]),
        "06-g1 names the served prompt versions",
    )
    tk = idn.get("token_identity") or {}
    ok(
        tk.get("pass") is True
        and tk["verdicts"]["server_vs_folder_token_ids"] is True
        and tk["prompts"] == 20
        and tk["server"]["keyed"] is True
        and calls["g1-tokenize"] == 1,
        "06-g1's token half: 20 prompts, the server's ids (keyed /tokenize) equal the folder tokenizer's",
    )
    ok(
        parts["07-canary"].get("pass") is True and parts["12-doctor"].get("pass") is True,
        "the canary passed; doctor: no unexpected FAIL",
    )
    commit = (S / "metadata" / "tb-commit").read_text().strip()
    qrec = json.loads((R / "records" / "qualification.json").read_text())
    ok(
        parts["08-qualify"]["detail"].get("code_commit") == commit and qrec.get("git_head") == commit,
        "H-19: the record names its code by the installed release's commit (installed.json), not the image",
    )
    q = parts["11-resolve"]["detail"]
    ok(q.get("production_resolves_promoted") is True, "G-2: PRODUCTION resolves both roles to the promoted builds")
    ok(parts["12-doctor"]["detail"]["fails"] == ["backup"], "doctor's one FAIL is the expected one")

if case == "happy":
    ok(list(parts) == START + G6 + G9 + G10, f"every step of start, g6, g9, g10 in order ({len(parts)} parts)")
    ok(ended.startswith("TB-BOX-RUN-COMPLETE"), "the run ended complete")
    for n in G6[2:6]:
        mem = parts[n]["detail"]["memory"]["containers"]
        ok(
            parts[n].get("pass") is True and all("peak_bytes" in c for c in mem.values()),
            f"G-6 {n}: wall time and peak memory per container",
        )
    ok(
        parts["22-g6-ingest"]["detail"]["memory"]["containers"]["adapter"]["peak_bytes"] >= 3 << 30,
        "the ingest's peak is the adapter's",
    )
    top = parts["26-g6-result"]["detail"]["top_costs"]
    ok(
        len(top["by_seconds"]) == 3 and len(top["by_peak_memory"]) == 3,
        "G-6: the top three costs by time and by memory",
    )
    ok(parts["26-g6-result"].get("pass") is True, "G-6: every stage ended, no OOM kill")
    ok(parts["30-g9-baseline"]["detail"]["baseline"] == "G-6's screen", "G-9's baseline is G-6's undisturbed screen")
    pw = parts["38-g9-power"]
    ok(
        len(pw["boots"]) == 2 and pw["detail"]["boot_before"] != pw["detail"]["boot_after"],
        "G-9 power cycle: asked in one boot, finished in the next",
    )
    ok(
        # D2: 07g-gate found the gate open and restarted nothing; G-9 restarts the orchestrator once
        calls["compose-restart orchestrator"] == 1
        and calls["compose-restart gateway"] == 1
        and calls["compose-stop llm-service"] == 1,
        "G-9: two restarts and the judge's outage, once each",
    )
    res = parts["39-g9-result"]
    ok(
        res.get("pass") is True and res["detail"]["compare"]["equal"] is True,
        "G-9: the list equals the undisturbed one",
    )
    ok(
        all(parts[n].get("pass", True) for n in G10)
        and parts["41-g10-image"]["detail"]["image_llm-service"] == "standin/model-server:new",
        "G-10: the declared image, the canary and the qualification",
    )

if case == "oom":
    ing = parts["22-g6-ingest"]
    ok(
        ing.get("pass") is False and ing["detail"]["oom_kills"] == 1 and ing["detail"]["exit"] == 137,
        "T-692 recorded: the ingest was killed at the adapter's cap (oom_kills 1, exit 137), pass false",
    )
    ok(ing["detail"]["memory"]["containers"]["adapter"]["peak_bytes"] == 6 << 30, "its peak is the cap (6 GiB)")
    ok(
        parts["23-g6-rebuild"].get("pass") is False and "blocked_by" in parts["23-g6-rebuild"]["detail"],
        "the rebuild is recorded as blocked by the ingest (no publish is coming)",
    )
    ok(
        parts["26-g6-result"].get("pass") is False and ended.startswith("TB-BOX-RUN-COMPLETE"),
        "G-6 fails; the run went on to its end",
    )

if case == "list-differs":
    c = parts["39-g9-result"]["detail"]["compare"]
    ok(
        parts["39-g9-result"].get("pass") is False and c["equal"] is False and c["only_in_a"] == ["P0000"],
        "G-9: the disturbed list differs from the baseline: pass false, the patient named",
    )

if case == "reboot":
    ok(
        parts["08-qualify"]["attempts"] == 2 and calls["qualify"] == 2,
        "the cut step (08-qualify) ran again in the next boot",
    )
    ok(
        calls["install"] == 1 and vm_log.count("TB-STEP 02-install kept") == 1,
        "the installer was kept, never run again",
    )

if case == "step-fails":
    ok(list(parts) == START[:9], "the run stopped at 08-qualify: no later part")
    p = parts["08-qualify"]
    ok(p["status"] == "stop" and "the full qualification: exit 1" in p["stop"]["reason"], "the stop's record")
    ok(
        any("schema failures 3 of 54" in line for line in p["stop"]["log_tail"]),
        "the stop's record has the step's last log lines",
    )

if case == "gate-closed":
    ok(
        calls["canary-gate wait"] == 1 and calls["compose-restart orchestrator"] == 1,
        "D2: the gate was closed at the first read: the orchestrator restarted once, the gate read until open",
    )

if case in ("gate-401", "gate-never"):
    ok(list(parts) == START[:8], "D2: the run stopped at 07g-gate: no later part")
    g = parts["07g-gate"]
    want = "TB-GATE-REFUSED" if case == "gate-401" else "TB-GATE-CLOSED"
    ok(g["status"] == "stop" and want in g["stop"]["reason"], f"D2: the stop says {want}")
    if case == "gate-401":
        ok(
            calls["canary-gate wait"] == 0 and calls["compose-restart orchestrator"] == 0,
            "D2: a 401 is a failure at once: no restart, no wait",
        )
    else:
        ok(calls["canary-gate wait"] == 1, "D2: a closed gate is read once more after the restart, then stops the run")

if case == "cap":
    ok("cost cap of 30 minutes reached" in poweroff, "the cap powered the VM off")
    ok((S / "evidence" / "results-at-cap.tgz").stat().st_size > 0, "a results.tgz was in the bucket at the cap")
    ok(ended.startswith("TB-CAP-REACHED"), "the next boot ended at once: the cap counts every boot")
    ok(calls["qualify"] == 1 and calls["install"] == 1, "no step ran again after the cap")

if case in ("bad-hash", "bad-tar-hash", "refused-rehearsal"):
    p = parts.get("01-bundle", {})
    ok(
        list(parts) == ["01-bundle"] and p["status"] == "stop" and "TB-BUNDLE-REFUSED" in p["stop"]["reason"],
        "the bundle is refused",
    )
    ok(
        (calls["install"] == 0 and not (S / "box-root" / "deploy").exists()) or calls["install"] == 0,
        "the installer never ran",
    )
    if case == "bad-hash":
        ok(
            any("rulesets/rules.json: sha256" in r for r in p["detail"]["refused"]),
            "the record names the payload that differs",
        )
    if case == "refused-rehearsal":
        ok(any("rehearsal bundle" in r for r in p["detail"]["refused"]), "refused as a rehearsal bundle (D-726)")

if case == "wizard-refused":
    ok(list(parts) == START[:3] and parts["03-wizard"]["status"] == "stop", "the run stopped at the wizard")
    ok("answers were not taken" in parts["03-wizard"]["stop"]["reason"], "the stop says the answers were refused")
    ok(any("password" in line for line in parts["03-wizard"]["stop"]["log_tail"]), "and which field")

if case == "identity-differs":
    idn = json.loads((R / "records" / "identity.json").read_text())
    ok(
        parts["06-g1"].get("pass") is False
        and not idn["checks"]["chat_template_served_is_pinned"]
        and not idn["checks"]["images_in_images_lock"],
        "06-g1: a template and an image that are not pinned: pass false",
    )
    tk = idn.get("token_identity") or {}
    ok(
        tk.get("pass") is False
        and tk["verdicts"]["server_vs_folder_token_ids"] is False
        and tk["verdicts"]["passed_vs_folder_text_sha256"] is False
        and tk["server_different"][0]["prompt"] == 0,
        "06-g1's token half: the server's ids and the folder's template differ: said, with the prompt",
    )
    ok(ended.startswith("TB-BOX-RUN-COMPLETE"), "a test rule, not a stop: the run went on")

if case == "resume-after-stop":
    ok(list(parts) == START and all(parts[n]["status"] == "done" for n in START), "after the retry: every start step")
    ok(ended.startswith("TB-BOX-RUN-COMPLETE"), "the retried run ended complete")
    kept = sorted(p.name for p in (R / "logs").glob("08-qualify.stop-*.json"))
    ok(len(kept) == 1, f"the first stop's part is kept beside the logs {kept}")
    ok(calls["qualify"] == 2 and calls["install"] == 1, "qualify ran again; the installer and the steps before it kept")
    ok(all(parts[n]["attempts"] == 1 for n in START[:8]), "the steps before 08 ran once")
    ok("TB-RETRY" in vm_log or "TB-RETRY" in "".join(
        f.read_text(errors="replace") for f in S.glob("boot-*.out")), "the boot said what the retry cleared")  # fmt: skip

if case == "acc-qualify-fails":
    ok(list(parts) == START and all(parts[n]["status"] == "done" for n in START), "validation: no stop at 08")
    q = parts["08-qualify"]
    ok(
        q.get("pass") is False and q["detail"]["verdict"]["status"] == "failed"
        and q["detail"]["verdict"]["failed_steps"] == ["schema"]
        and "3 of 54" in q["detail"]["verdict"]["steps"]["schema"]["reason"],
        "08: the failed gate is a result: which step and its figure",
    )  # fmt: skip
    for n in ("09-promote-judge", "10-promote-verifier"):
        ok(
            parts[n]["detail"]["promoted"] is False and "did not pass" in parts[n]["detail"]["why"],
            f"{n}: not promoted",
        )
    ok(not any(c.startswith("promote ") for c in calls), "no promotion was asked")
    ok("none" in parts["11-resolve"]["detail"]["judge_d3"], "11: PRODUCTION routes no judge (a candidate pair)")
    ok(ended.startswith("TB-BOX-RUN-COMPLETE"), "the run went on to its end")

if case == "happy":
    dk = json.loads((R / "records" / "disk.json").read_text())
    ok(
        dk["what"].startswith("grown") and calls["growpart /dev/sda 1"] == 1 and calls["resize2fs /dev/sda1"] == 1,
        "the root partition and file system grown once to the larger disk; later boots find nothing to grow",
    )

if case == "direct":
    ok(
        list(parts) == START and parts["02-install"]["status"] == "done",
        "direct: every start step, 02 by the direct route",
    )
    d = parts["02-install"]["detail"]
    ok(
        d["route"].startswith("direct") and "not sealed" in d["site_keys"],
        "direct: the route and the unsealed keys said",
    )
    ok(
        calls["install"] == 0 and calls["trialbox-secrets"] == 1 and calls["pin"] == 1 and calls["trialbox-db-up"] == 1
        and calls["compose-run adapter python adapter.cli keys-init"] == 1,
        "direct: no install.sh; the product's own secrets init, pin, keys-init and db-up, once each",
    )  # fmt: skip

if case == "dev":
    ok(
        state["order"] == [*BUILD[:3], "d04-tree", *START[1:]],
        "dev: b01-b03, the tree, then the start from 02 (no bundle), in that order",
    )
    ok(ended.startswith("TB-BOX-RUN-COMPLETE") and parts["02-install"]["detail"]["route"].startswith("direct"),
       "dev: the direct route brought the stack up")  # fmt: skip
    ok("no bundle" in parts["d04-tree"]["detail"]["release"] and (S / "box-root" / "current").is_symlink(),
       "dev: current points at the commit's tree, said as no bundle and no signature")  # fmt: skip
    ok(
        calls["images"] == 1 and calls["release-gates"] == 0 and calls["install"] == 0,
        "dev: images built; no gates, no install",
    )

if case == "acc-cut":
    c = parts["60-acc-jmed"]["detail"]["counts"]
    ok(c.get("not_run_time_budget", 0) >= 1 and parts["60-acc-jmed"]["detail"]["deadline_s"] == 3,
       "acc-cut: the set's time budget (1.5 x plan x 4, here 3 s) left protocols not started, said")  # fmt: skip
    ok(c.get("screened", 0) + c.get("refused_by_tripwire", 0) >= 1, "acc-cut: what finished before it is kept")
    ok((BKT / "boxruns" / f"rehearsal-{case}" / "acc" / "jmed.tgz").exists()
       and (BKT / "boxruns" / f"rehearsal-{case}" / "acc-partial" / "jmed.tgz").exists(),
       "acc-cut: the set's partial went to the bucket while it ran, and its final after")  # fmt: skip
    ok("TB-PROGRESS" in vm_log and "set jmed: protocols" in vm_log, "acc-cut: progress lines with protocols done/all")
    ok(
        parts["61-acc-sigir"]["detail"].get("rate_used") == "not measured yet: 4",
        "acc-cut: a set cut by its budget measures no slowdown; the next set's budget keeps 4 (F22)",
    )

if case == "acc-cut":
    ok(any(ln.startswith("TB-PROGRESS") and "set jmed: protocols" in ln and "embed requests 1 " in ln
           and "embed-service 97.5% 1.2GiB" in ln and "oom_killed=false restarts=0" in ln for ln in vm_log.splitlines()),
       "acc-cut: one progress line says the set, the embed service's requests, CPU, memory and its kills or restarts "
       "(F23, F26)")  # fmt: skip
    ok(any(c.startswith("compose-logs ") and c.endswith(" orchestrator embed-service criteria-compiler gateway") for c in calls),
       "acc-cut: the set's services' own lines read into its work")  # fmt: skip

if case == "acc-cut":
    ok("acc-send FEAS SNCT90000001 new" not in calls and parts["61-acc-sigir"]["detail"].get("protocols_only")
       == "SNCT90000002", "acc-cut: tb-acc-protocols: only the named protocol of sigir was sent, and said")  # fmt: skip
    ok(parts["62-acc-tfda"]["detail"].get("streams") == 2, "acc-cut: tb-acc-streams: tfda, 2 protocols at once")

if case == "direct":
    env = (S / "box-root" / "deploy" / ".env").read_text()
    ok("TB_MEM_EMBED=16g" in env and "TB_ENV=VALIDATION" in env and "TB_MEM_DB" not in env
       and "TB-SITE-ENV TB_MEM_EMBED=16g" in vm_log,
       "direct: tb-site-env sets only a TB_MEM_ size in deploy/.env, said; anything else is refused")  # fmt: skip

if case == "acc-gate":
    j = parts["60-acc-jmed"]
    ok(j["status"] == "stop" and "the gate set jmed is not scored" in j["stop"]["reason"],
       "acc-gate: the gate set answered nobody: its step stopped the run with the reason, not 'done'")  # fmt: skip
    ok("61-acc-sigir" not in parts, "acc-gate: no later set ran")
    ok((BKT / "boxruns" / f"rehearsal-{case}" / "acc" / "jmed.tgz").exists(), "acc-gate: its work is in the bucket")
    ok(j["detail"].get("not_scored", "").startswith("it answered no patient"), "acc-gate: the part says why")

if case == "acc-redo":
    j = parts["60-acc-jmed"]
    ok(j["status"] == "done" and j["detail"]["counts"].get("patients_answered", 0) > 0,
       "acc-redo: the set ran again and answered patients")  # fmt: skip
    ok(calls["acc-send FEAS MNCT90000001 new"] == 2 and calls["acc-send FEAS MNCT90000001 dup"] == 0,
       "acc-redo: the redone set mailed its protocol under a new id (a second new job), never the old id")  # fmt: skip
    ok((R / "logs" / "60-acc-jmed.work-retry-1").is_dir(), "acc-redo: the earlier work kept beside the logs")

if case == "qualify-timebox":
    q = parts["08-qualify"]
    ok(q["status"] == "done" and q.get("pass") is False and q["detail"].get("timeboxed_s") == 2,
       "qualify-timebox: ended at its time box, said, the run went on")  # fmt: skip
    cps = (R / "logs" / "08-qualify.checkpoints.jsonl").read_text().splitlines()
    ok(len(cps) >= 1 and all("qualify gate" in json.loads(c)["now"] for c in cps),
       f"qualify-timebox: {len(cps)} checkpoint(s) with the gate it was in, in the bucket's results")  # fmt: skip
    ok("TB-TIMEBOX 08-qualify" in vm_log and "TB-PROGRESS" in vm_log, "qualify-timebox: the console said both")
    ok(ended.startswith("TB-BOX-RUN-COMPLETE"), "qualify-timebox: the run ended complete")

if case == "probe":
    ok(list(parts) == ["00-facts"] and ended.startswith("TB-PROBE-DONE"), "probe: the facts, then the run ends")
    facts = (R / "records" / "facts-vm.txt").read_text()
    ok(
        "$ df -h" in facts and "$ docker ps -a" in facts and "[exit" in facts,
        "probe: each fact with its command and exit",
    )
    ok(not any(c.startswith(("install", "acc-", "qualify")) for c in calls), "probe: nothing built or installed")

# ---------------------------------------------------------------- validation mode and the accuracy group
if case == "build-validation":
    ok(list(parts) == BUILD and all(p["status"] == "done" for p in parts.values()), "the seven build steps, done")
    rec = json.loads((R / "records" / "bundle.json").read_text())
    ok(
        rec["mode"] == "validation" and rec["not_a_release"] is True and "throwaway" in rec["signed_with"],
        "records/bundle.json: validation mode, NOT a release, signed with a throwaway key",
    )
    ok(not any(x.startswith("secrets versions access") for x in gcloud), "the vendor key was never read")
    ok((BKT / "r2" / "out" / "throwaway-signing-key.pub").exists(), "the throwaway public key beside the bundle")
    v = parts["b06-verify"]["detail"]
    ok(v["refused"] == [] and bool(v.get("key_id")), "b06: the signature verifies with the throwaway public key")
    ok(parts["b05-sign"]["detail"]["key_left_on_tmpfs"] is False, "the throwaway key was gone after signing")
    ok("TB-THROWAWAY-KEY" in (R / "logs" / "b05-sign.log").read_text(), "the signing log says the key is throwaway")
    ok(
        calls["make-bundle models embedder gemma-4-26b-a4b-it-4bit qwen3.5-9b-4bit "] == 1,
        "H-43: the throwaway-key bundle was given the weights too (--models)",
    )
    ok(
        calls["gates-args --vuln-mode report"] == 1 and rec["release_gates_vuln_mode"] == "report"
        and rec["release_gates"].startswith("NOT all green"),
        "validation: the gates' report mode (the test-only mail images), and the bundle record says not all green",
    )  # fmt: skip
if case in ("build", "build-preempt", "build-validation"):
    ok(any(c.startswith("docker-build trialbox-demo:step5") or "demo/Dockerfile" in c for c in calls),
       "b03: the demo image the gates scan was built (demo/Dockerfile)")  # fmt: skip
if case in ("build", "build-preempt"):
    ok(calls["gates-args "] >= 1 and calls["gates-args --vuln-mode report"] == 0, "production: the gates enforcing")

ACC_SETS = ["jmed", "sigir", "tfda"]
ACC = ["50-acc-tools", "51-acc-settings", "52-acc-routes", "53-acc-data", "54-acc-ingest",
       "60-acc-jmed", "61-acc-sigir", "62-acc-tfda", "79-acc-result"]  # fmt: skip
if case in ("acc", "acc-preempt", "acc-blocked"):
    ok(keys(START) and all(parts[n]["status"] == "done" for n in START), "the start steps, done, in validation mode")
    ok(parts["03-wizard"]["detail"].get("environment") == "VALIDATION", "03: the box says VALIDATION (deploy/.env)")
    ok(calls["install"] == 1 and calls["hostcheck"] == 0, "install.sh ran once, box-install.sh never")
    ok("[redacted]" in (R / "logs" / "02-install.log").read_text(), "the installer's printed password was redacted")
    ok(
        "deploy/gcp/validation-site-answers.yaml" in json.dumps(parts["02-install"]["detail"])
        and not any(x.startswith("secrets versions access") for x in gcloud),
        "the synthetic site's committed answers, no secret read",
    )
    ok(
        "standin-judge-1" in parts["11-resolve"]["detail"].get("judge_d3", "")
        and "standin-verifier-1" in parts["11-resolve"]["detail"].get("second_opinion_d3", ""),
        "11: pin_model --resolve names the promoted pair on D3 (judge and second opinion)",
    )
    st_ = parts["51-acc-settings"]["detail"]
    ok(
        st_["limits"]["after"]["jobs_per_sender_per_day"] == "0"
        and st_["limits"]["after"]["mail_per_recipient_per_day"] == "0"
        and st_["limits"]["before"]["jobs_per_sender_per_day"] == "0"
        and "acc-limits" not in calls,
        "51: the declared limit settings (D-775) off from the install's answers, recorded; settings.yaml untouched",
    )
    ok("own" in st_["authserv"], "51: the box's own MTA id from the answers (D-825), not the run's")
    if case != "acc-blocked":  # it stops at 52, before the data
        ok(calls["acc-optional"] >= 1, "54: the site's optional tables for the public feed set before the ingest")
    if case == "acc-preempt":  # the driver's default for a validation run: the declared setting turns it off
        ok(st_["tripwire"] == "set by the declared setting TB_GATEWAY_PHI_TRIPWIRE=off", "51: the tripwire off, said")
        ok(st_["limits"]["environment"] == "VALIDATION", "51: the box's environment after the change")
    else:
        ok(st_["tripwire"].startswith("on: no setting used"), "51: the tripwire stays on, and the record says so")
if case in ("acc", "acc-preempt"):
    ok(list(parts) == START + ACC, f"every step of start and acc in order ({len(parts)} parts)")
    ok(ended.startswith("TB-BOX-RUN-COMPLETE"), "the run ended complete")
    rt = json.loads((R / "records" / "acc-routes.json").read_text())
    ok(
        rt["routes_ok"] is True and rt["environment"] == "VALIDATION" and "judge@5" in rt["served_prompts"],
        "52: the box routes the run's calls; the record names the environment and the served prompts",
    )
    ok("hash stand-in" in rt["embedder"], "52: the embedder SCREEN ranks with is recorded (#589 not in)")
    for n in ACC_SETS:
        ok((BKT / "boxruns" / f"rehearsal-{case}" / "acc" / f"{n}.tgz").exists(), f"{n}: uploaded as it finished")
        raw = S / "evidence" / "collected" / "acc" / n / "work" / "raw-traces.json"
        ok(raw.exists() and json.loads(raw.read_text())["calls"] >= 0, f"{n}: the raw answers came with the set")
    sent = [c for c in calls if c.startswith("acc-send ")]
    news = Counter(" ".join(c.split()[1:3]) for c in sent if c.endswith(" new"))
    ok(all(v == 1 for v in news.values()), "no request mailed twice as a new job (a re-sent mail is the same job)")
    ok(
        sum(1 for k in news if k.startswith("FEAS ")) == 5,
        "every protocol's FEAS once: 2 (jmed) + 2 (sigir) + 1 (tfda)",
    )
    ok(sum(1 for k in news if k.startswith("SCREEN ")) >= 2, "the screened sets' protocols were screened")
    ok(not any(k.startswith(("APPROVE TF", "SCREEN TF", "APPROVE F", "SCREEN F")) for k in news),
       "the compile-only set was compiled, never approved or screened")  # fmt: skip
    score = json.loads((S / "evidence" / "acc-score.json").read_text())
    if case == "acc":  # tfda's one protocol was refused by the tripwire: nothing compiled, so no figure (F22)
        ok(set(score) == set(ACC_SETS) and score["tfda"]["scored"] is False and "compiled no" in score["tfda"]["why"]
           and all(score[n]["scored"] for n in ("jmed", "sigir")),
           "the screened sets scored outside the box; tfda (nothing compiled) is 'not scored, because'")  # fmt: skip
        ok(parts["62-acc-tfda"]["detail"].get("not_scored") == "it compiled no protocol"
           and "79-acc-result" in parts, "62: tfda says why it is not scored, and the group went on (not the gate)")  # fmt: skip
    else:
        ok(set(score) == set(ACC_SETS) and all(v["scored"] for v in score.values()), "every set scored outside the box")
    pairs = json.loads((S / "evidence" / "collected" / "acc" / "jmed" / "score.json").read_text())["pairs"]["rows"]
    ok(
        sum(r["excluded"] + r["listed"] + r["open"] for r in pairs) > 0,
        "the answers joined the gold through the box's pseudonyms (not all unanswered)",
    )
if case == "acc":
    for n in ("jmed", "sigir"):
        c = parts[f"6{ACC_SETS.index(n)}-acc-{n}"]["detail"]["counts"]
        ok(
            c["refused_by_tripwire"] == 1
            and c.get("screened") == 1
            and parts[f"6{ACC_SETS.index(n)}-acc-{n}"]["pass"] is False,
            f"{n}: one protocol refused by the PHI tripwire, counted (a product defect), the other screened",
        )
    ok(parts["79-acc-result"].get("pass") is False, "79: the accuracy group says not every protocol went through")
if case == "acc-preempt":
    p = parts["60-acc-jmed"]
    ok(p["attempts"] == 2 and len(p["boots"]) == 2, "the cut set ran again in the next boot")
    ok(all(parts[n]["attempts"] == 1 for n in ACC[:5]), "the steps before it were kept")
    ok(calls["install"] == 1, "the installer was kept")
    ok(parts["79-acc-result"].get("pass") is True, "every protocol went through")
if case == "acc-blocked":
    ok(list(parts) == START + ACC[:3] and parts["52-acc-routes"]["status"] == "stop", "stopped at 52-acc-routes")
    ok("TB-ACC-BLOCKED" in parts["52-acc-routes"]["stop"]["reason"] and "ceiling D2" in parts["52-acc-routes"]["stop"]["reason"],
       "the stop names the gateway's reason (a product defect, not worked around)")  # fmt: skip
    ok(not any(c.startswith("acc-data") for c in calls), "no data fetched or built")

if case == "acc-cut-resume":  # D-1129 (card H-14)
    import tarfile

    R1 = S / "evidence" / "results-attempt-1"
    p1 = {p.stem: json.loads(p.read_text()) for p in sorted((R1 / "parts").glob("*.json"))}
    j1 = p1["60-acc-jmed"]["detail"]
    c1 = int(j1.get("budget_cut") or 0)
    total = int(j1["counts"]["protocols"])
    ok(p1["60-acc-jmed"]["status"] == "done" and c1 >= 1 and c1 == j1["counts"].get("not_run_time_budget")
       and str(j1.get("attempts_line", "")).startswith("attempts: 1;"),
       f"attempt 1: the set ended on its own budget, done, with {c1} of {total} protocols cut, said in its part")  # fmt: skip
    with tarfile.open(S / "evidence" / "jmed-attempt-1.tgz") as t:
        fh = t.extractfile("work/answers.json")
        a1 = json.loads(fh.read()) if fh else {}
    done1 = sorted(rs for rs, a in a1.items() if a.get("outcome") != "not_run_time_budget")
    ok(len(done1) == total - c1 and all(a1[rs].get("attempt") == 1 for rs in done1),
       "attempt 1: its finished protocols say attempt 1")  # fmt: skip
    plan = json.loads((S / "evidence" / "resume-plan.json").read_text())
    pj: dict[str, Any] = next((r for r in plan["sets"] if r["set"] == "jmed"), {})
    ok(pj.get("budget_cut") == c1 and pj.get("budget_s") == 60 and "runs only its" in pj.get("what", "")
       and "jmed" not in plan["needs_deadline"] and plan["state"] == "the last collect",
       "the driver's free resume plan (no bucket read) says jmed's cut protocols run in a new attempt with 60 s")  # fmt: skip
    others = [r for r in plan["sets"] if r["set"] != "jmed" and r["budget_cut"]]
    ok(any(r["set"] == "sigir" for r in others) and all("stays done unless --acc-deadline" in r["what"] for r in others)
       and sorted(plan["needs_deadline"]) == sorted(r["set"] for r in others),
       f"the plan says the other cut sets ({[r['set'] for r in others]}) stay done without a budget of their own")  # fmt: skip
    j = parts["60-acc-jmed"]
    d = j["detail"]
    ok(j["status"] == "done" and int(d.get("budget_cut") or 0) == 0 and not d["counts"].get("not_run_time_budget")
       and d["counts"].get("screened") == total and d.get("resumed_for_budget_cut") == "retry-1",
       "attempt 2: every protocol screened, nothing cut, the part says the resume that took it up")  # fmt: skip
    line = f"attempts: 2; protocols finished in attempt 1: {total - c1}; in attempt 2: {c1}; still cut: 0"
    ok(d.get("attempts_line") == line, f"the set's report says '{line}' (it says '{d.get('attempts_line')}')")
    ok((R / "logs" / "60-acc-jmed.budget-retry-1.json").exists()
       and (R / "logs" / "79-acc-result.budget-retry-1.json").exists() and "79-acc-result" in parts,
       "the first attempt's part and the group's result kept beside the logs; the result read again")  # fmt: skip
    c_1 = Counter((S / "evidence" / "calls-attempt-1.log").read_text().split("\n"))
    later = calls - c_1
    sends = [c for c in later if c.startswith("acc-send ") and " MNCT" in c]
    ok(not any(c.split()[2] in done1 for c in sends),
       "attempt 2 sent no protocol finished in attempt 1 to FEAS, APPROVE or SCREEN (calls counted)")  # fmt: skip
    news = Counter(
        " ".join(c.split()[1:3]) for c in calls.elements() if c.startswith("acc-send ") and c.endswith(" new")
    )
    jm = {k: v for k, v in news.items() if k.split()[1].startswith("MNCT")}
    ok(all(v == 1 for v in jm.values()) and not any(c.startswith("acc-send ") and c.endswith(" dup")
                                                    and " MNCT" in c for c in calls)
       and sum(1 for k in jm if k.startswith("FEAS ")) == total and sum(1 for k in jm if k.startswith("SCREEN ")) == total,
       "over both attempts each jmed protocol's FEAS, APPROVE and SCREEN went once (no mail twice, no duplicate)")  # fmt: skip
    for k, n in (("61-acc-sigir", "sigir"), ("62-acc-tfda", "tfda")):
        cut = int(p1[k]["detail"].get("budget_cut") or 0)
        ok(parts[k]["attempts"] == 1 and parts[k]["detail"] == p1[k]["detail"]
           and (not cut or f"TB-RESUME-PLAN retry-1: {k} ended on its budget with {cut} protocols cut: kept" in vm_log),
           f"{n}: given no budget, it stayed done as it was (cut {cut}), said first thing")  # fmt: skip
    ok(f"TB-RESUME-PLAN retry-1: 60-acc-jmed: the {c1} protocols its budget cut run again" in vm_log,
       "the VM said what the resume takes up first thing (TB-RESUME-PLAN)")  # fmt: skip
    W = S / "evidence" / "collected" / "acc" / "jmed" / "work"
    ans = json.loads((W / "answers.json").read_text())
    ok(len(ans) == total and Counter(a.get("attempt") for a in ans.values()) == Counter({1: total - c1, 2: c1})
       and all(ans[rs]["patients"] == a1[rs]["patients"] for rs in done1),
       "answers.json: the union, each protocol once with its attempt; attempt 1's answers untouched")  # fmt: skip
    clk = json.loads((W / "set-clock.json").read_text())
    ok(clk.get("attempt") == 2 and clk.get("attempt_tag") == "retry-1" and clk.get("deadline_s") == 60
       and [x["attempt"] for x in clk.get("attempts") or []] == [1] and clk["attempts"][0]["deadline_s"] == 3,
       "set-clock.json: attempt 2 on its own 60 s budget, attempt 1's seconds and 3 s budget kept")  # fmt: skip
    env_tz = json.loads((R / "logs" / "acc-env-jmed.json").read_text()).get("tz")
    ok(bool(env_tz) and clk.get("tz") == env_tz and parts["60-acc-jmed"]["detail"].get("site_tz") == env_tz,
       f"set-clock.json records the site's zone the box reported ({env_tz}), for the replay")  # fmt: skip
    jobs = sum(jm.values())
    au = json.loads((W / "gateway-audit.json").read_text())
    tr = json.loads((W / "raw-traces.json").read_text())
    ids = [r["call_id"] for r in tr["traces"]]
    ok(sorted(au.get("attempts") or {}) == ["1", "2"] and au["calls_by_prompt"]["ir_extract@3"] == jobs
       and tr["calls"] == jobs == len(ids) == len(set(ids)),
       f"the audit and the traces of attempt 2 were added to attempt 1's, nothing counted twice ({jobs} jobs)")  # fmt: skip
    ok("== attempt 1" in (W / "services.earlier.log").read_text() and "== attempt 2" in (W / "box-calls.log").read_text(),
       "the services' lines and the box's calls of attempt 1 kept, attempt 2's after them")  # fmt: skip
    sc = json.loads((S / "evidence" / "collected" / "acc" / "jmed" / "score.json").read_text())
    pr = sc["protocols"]
    ok(sc["schema_version"] == 5 and pr["screened"] == total and pr["not_run_time_budget"] == 0
       and pr["attempts"]["line"] == line and json.loads((S / "evidence" / "acc-score.json").read_text())["jmed"]["scored"],
       "the scorer reads the two attempts as one: every protocol screened once, the attempts line in its block")  # fmt: skip
    ok(state.get("kv", {}).get("acc_rate_set") != "jmed", "a set run in two attempts measures no slowdown (F22)")
    ok(ended.startswith("TB-BOX-RUN-COMPLETE"), "the resumed run ended complete")
# ---------------------------------------------------------------- the owner's live session (D-1130 to D-1133)
OPEN_LEFT = ("session-close-fails", "session-ss-fails")  # cases whose accounts stay open at their end
SESSION = ["50-acc-tools", "51-acc-settings", "51s-session-env", "52-acc-routes", "53-acc-data",
           "53h-session-hospital", "54-acc-ingest", "55-session-egress", "56-session-accounts", "57-session-open",
           "58-session-close"]  # fmt: skip
if case.startswith("session"):
    import importlib.util
    import re

    _gcp = Path(__file__).resolve().parents[3] / "deploy" / "gcp"
    sys.path.insert(0, str(_gcp))  # session_vm.py imports demo_vm.py beside it
    _spec = importlib.util.spec_from_file_location("session_vm", _gcp / "session_vm.py")
    assert _spec is not None and _spec.loader is not None
    session_vm = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(session_vm)

    boots = sorted(S.glob("boot-*.out"))
    out = [b.read_text(errors="replace") for b in boots]
    links = sorted((BKT / "session" / f"rehearsal-{case}").glob("links-*.txt"))
    env_now = (S / "box-root" / "deploy" / ".env").read_text()
    accounts = json.loads((S / "box" / "accounts.json").read_text()) if (S / "box" / "accounts.json").exists() else {}
    rec = json.loads((R / "records" / "session.json").read_text()) if (R / "records" / "session.json").exists() else {}
    units = (S / "units.log").read_text() if (S / "units.log").exists() else ""
    booted = "TB-SESSION-BOOT" in "".join(out)  # a boot refused at its preflight gets no further
    ok(not booted or ("systemctl stop ssh.socket ssh.service" in units and "systemctl mask ssh.socket ssh.service" in units),
       "ssh.socket and ssh.service stopped and masked at the session's boot (D-1130, the review's finding 5)")  # fmt: skip
    ok(all("listening on :22: nothing" in o for o in out if "TB-SESSION no SSH" in o) or case == "session-ssh",
       "nothing listens on tcp:22 after the stop, checked")  # fmt: skip
    ok(all(re.search(r"TB-SESSION-BOOT boot=[0-9a-f]{16} started=", o) for o in out if "groups dev session" in o),
       "every boot of the session prints its own id")  # fmt: skip
    ok(case in OPEN_LEFT  # its accounts could not be closed: the box is left as the session set it
       or (re.search(r"^TB_ENV=VALIDATION$", env_now, re.M) is not None and env_now.count("TB_ENV=") == 1),
       "the box is back in VALIDATION on the kept disk")  # fmt: skip
    ok(not list((S / "vm" / "tb" / "session").glob("*.t*")), "no codes' file left on the VM's disk")
    ok(rec == {} or rec.get("evidence") == "nothing from this session is evidence", "the record says it is no evidence")
    ok(not any(c in json.dumps(rec) for c in session_codes), "the record holds no code")
    md = "".join(f.read_text() for f in (S / "metadata").iterdir() if f.is_file() and f.name != "tb-helper")
    ok(not re.search(r"STANDIN-[0-9A-F]{12}|enrol#", md), "the metadata holds no code and no link")
    opened = [a for a in accounts if not a.startswith("_")]
    ok(case in OPEN_LEFT
       or (all(accounts[a]["disabled"] and not accounts[a]["extra"] for a in opened) and not accounts.get("_flag_acting")),
       "every session account is disabled, its extra roles taken back, the acting flag off")  # fmt: skip
    seq = (S / "calls.log").read_text().splitlines()
    closed_marker = BKT / "session" / f"rehearsal-{case}" / "CLOSED"
    if case not in OPEN_LEFT:  # the re-review's C: every session run ends with its marker, accounts or none
        ok(closed_marker.exists() and closed_marker.read_text().startswith("closed "),
           "the run's CLOSED marker is written once no session account is open (an account opened or not)")  # fmt: skip
CUT = (
    "session-cut",
    "session-unit",
    "session-unit-race",
    "session-ops",
    "session-quiet-fails",
)  # a power cut while the session is open
if case in ("session", "session-stop", *CUT):
    first_people = next((i for i, c in enumerate(seq) if c.startswith("session-people")), -1)
    ok(0 <= seq.index("network.sh apply") < seq.index("network.sh status") < first_people,
       "the box's own egress rules applied, then read back, before any account is opened")  # fmt: skip
    ok(len(links) == 1 and len(session_codes) == len(opened) >= 1, "one links object, one code per account")
    text = links[0].read_text() if links else ""
    ok("NOTHING FROM THIS SESSION IS EVIDENCE" in text and "Public or synthetic text only" in text,
       "the links object says the session is no evidence and takes public text only")  # fmt: skip
    meta = session_vm.links_meta(text)
    ok(re.fullmatch(r"[0-9a-f]{16}", meta["boot_id"]) is not None and meta["certificate_sha256"] != "none"
       and meta["stop"] != "none", "the links object names the boot id, the certificate's SHA-256 and the stop")  # fmt: skip
    ok(all(f"&c={c}" in text for c in session_codes), "each code is in the links object, as a one-time link")
    ok(f"boot={meta['boot_id']}" in out[0] and session_vm.boot_state(out[0], None, meta["boot_id"])[0]
       == ("ready" if case in CUT else "ended"),
       "the ready line and the end carry the links' boot id (D-1120's rule reads it)")  # fmt: skip
    ok('add the line "34.80.0.10 trialbox.hospa.test"' in text, "the hosts line for the box's own name is given")
    ok(parts["55-session-egress"]["status"] == "done" and calls["network.sh apply"] == 1, "the egress rules applied")
    eg = json.loads((R / "records" / "session-egress.json").read_text())
    ok(eg["live"] and not eg["text_can_leave"] and eg["box_networks"] == eg["under_default_deny"],
       "read back: the table is live, every network of the box under its default deny, nothing lets text out")  # fmt: skip
if case == "session":
    ok(state["order"] == [*BUILD[:3], "d04-tree", *START[1:], *SESSION], "dev's bring-up, then the session's steps")
    ok(ended.startswith("TB-BOX-RUN-COMPLETE"), "the run completed")
    ok(all(parts[s].get("detail", {}).get("skipped") for s in START[8:]), "qualify and what follows it left out, said")
    ok(parts["51s-session-env"]["detail"]["environment"] == "DEV" and calls["session-people DEV owner-s1117" + "0000"]
       == 0, "the session ran in DEV")  # fmt: skip
    ok(any(c.startswith("session-people DEV owner-s") for c in calls) and len(opened) == 1,
       "one sign-in for the owner (the acting role, D-1063)")  # fmt: skip
    ok(parts["57-session-open"]["detail"]["ended_by"] == "the session's stop" and calls["compose-logs caddy"] >= 2,
       "the heartbeat read the owner's requests until the stop")  # fmt: skip
    ok(rec["closed_by"] == "the session's stop" and rec["environment"] == "DEV" and rec["planned_stop"],
       "the record: opened, stopped, closed, in DEV")  # fmt: skip
    ok(any(c.startswith("feed 20") for c in calls) and calls["ingest"] == 1, "the synthetic hospital fed and ingested")
if case == "session-stop":
    opened_at = session_vm.demo_vm.instant(rec["opened_at"])
    stop_at = session_vm.demo_vm.instant(rec["planned_stop"])
    ok(opened_at is not None and stop_at is not None and (stop_at - opened_at).total_seconds() < 60,
       "asked 600 minutes, the session stopped within the cost cap less its margin")  # fmt: skip
    ok(rec["closed_by"] == "the session's stop" and "done, results in the bucket" in poweroff,
       "its accounts disabled before the cap: the VM went off on its own, not by the cap")  # fmt: skip
    ok(len(opened) == 4 and all("+" not in accounts[a]["roles"] for a in opened), "VALIDATION: one account per role")
if case in (*CUT, "session-cut-56"):
    b2 = out[1] if len(out) > 1 else ""
    ok(len(out) == 2 and "TB-SESSION-READY" not in b2 and ("TB-SESSION-READY" in out[0]) is (case != "session-cut-56"),
       "the session opened once at most")  # fmt: skip
    ok(0 <= b2.find("TB-SESSION-END") < b2.find("TB-SESSION-AGAIN") and "TB-STEP" not in b2,
       "the next boot disabled the accounts, then stopped: no step of the run ran again (round 3's finding 4)")  # fmt: skip
    ok("TB-SESSION-AGAIN" in ended and "never opened again" in ended, "the session is never opened again (D-1123 4.4)")
    ok(rec.get("closed_by", "").startswith("the next boot") or case == "session-cut-56",
       "the record says the next boot closed it")  # fmt: skip
    ok("TB-SESSION-NOT-READY" in b2, "the second boot says it opened no session")
    boot2 = next((i for i, c in enumerate(seq) if c.startswith("vm-boot 2 ")), len(seq))
    ok(not any(c.startswith(("session-people", "session-marker open")) for c in seq[boot2:]),
       "the later boot opened no account and never set the run's marker to open again")  # fmt: skip
if case == "session-cut-56":  # round 3's finding 4: a cut while 56 opened the accounts, a later boot without tb-retry
    ok(calls["session-people-start"] == 1 and not any(c.startswith("session-people ") for c in seq) and not links,
       "56 was cut while it opened the accounts; no link was ever written")  # fmt: skip
    ok("TB-SESSION-READY" not in "".join(out), "the session never opened")
# ---------------------------------------------------------------- rounds 3 and 4: lane D's units (finding 1, b, c, d)
UNIT = ("session-unit", "session-unit-race", "session-unit-fails", "session-ops", "session-unit-dbus", "session-stop",
        "session-quiet-fails")  # fmt: skip
if case in UNIT:
    units = json.loads((S / "box" / "units.json").read_text())
    first_people = next((i for i, c in enumerate(seq) if c.startswith("session-people")), len(seq))
    boot2 = next((i for i, c in enumerate(seq) if c.startswith("vm-boot 2 ")), len(seq))
    after = seq[boot2:]
    dis2 = next((i for i, c in enumerate(after) if c.startswith("session-disable ")), len(after))
    if case in ("session-unit-fails", "session-unit-dbus"):
        ok(parts["56-session-accounts"]["status"] == "stop"
           and "could not be read, disabled or stopped" in parts["56-session-accounts"]["stop"]["reason"],
           "the box's own unit cannot be disabled (or read): step 56 stops")  # fmt: skip
        ok(not links and not opened and not any(c.startswith("session-people") for c in seq)
           and not any(c.startswith("docker-update") for c in seq), "no account, no link, no restart policy changed")  # fmt: skip
        ok("TB-SESSION-READY" not in "".join(out), "the session never opened")
        ok(units["trialbox.service"]["enabled"] == "enabled", "the unit is as it was (enabled)")
        if case == "session-unit-dbus":
            ok("systemctl disable trialbox.service" not in seq, "no answer from systemctl is never read as no unit")
    else:
        for u in [n for n in ("trialbox.service", "trialbox-ops.timer", "trialbox-watchdog.timer")
                  if units[n]["enabled"] != "not-found"]:  # fmt: skip
            dis = next((i for i, c in enumerate(seq) if c == f"systemctl disable {u}"), -1)
            ok(0 <= dis < first_people, f"step 56 disabled {u} before any account was opened")
        for tm in [n for n in ("trialbox-ops.timer", "trialbox-watchdog.timer") if units[n]["enabled"] != "not-found"]:
            stop = next((i for i, c in enumerate(seq) if c == f"systemctl stop {tm}"), -1)
            ok(0 <= stop < first_people, f"step 56 stopped {tm} before any account was opened")
    if case == "session-quiet-fails":  # the unit, enabled again by hand, brought Caddy up at the boot itself
        cs = after.index("compose-stop caddy") if "compose-stop caddy" in after else len(after)
        ok(cs < dis2 < len(after) and not any(c.startswith("caddy up") for c in after[cs:dis2])
           and "session-disable-caddy down" in after and "session-disable-caddy up" not in seq,
           "Caddy, up from the boot, was stopped before the close and stayed down through the disable")  # fmt: skip
    elif case in CUT:
        ok(dis2 < len(after) and not any(c.startswith("caddy up") for c in after[:dis2])
           and "session-disable-caddy down" in after and "session-disable-caddy up" not in seq,
           "at the next boot the box's Caddy never served while the accounts were open, units or none")  # fmt: skip
    if case in CUT:
        by_hand = "trialbox.service enabled again by hand" in seq
        ok(not any(c.startswith("systemctl enable") for c in after) and "are not put back" in out[1]
           and (by_hand or all(x["enabled"] in ("disabled", "not-found", "static") for x in units.values())),
           "a later boot of the session's own run does not put the units back, and says so (round 4's d)")  # fmt: skip
    if case == "session-stop":  # a clean close: the units put back only after the accounts and the CLOSED marker
        dis = next((i for i, c in enumerate(seq) if c.startswith("session-disable ")), len(seq))
        marks = [i for i, c in enumerate(seq) if c == "session-marker closed"]
        back = [i for i, c in enumerate(seq) if c.startswith("systemctl enable ")]
        ok(bool(marks) and len(back) == 3 and dis < marks[0] < min(back)
           and all(units[n]["enabled"] == "enabled" for n in ("trialbox.service", "trialbox-ops.timer", "trialbox-watchdog.timer")),
           "a clean close put the three units back (enabled) only after the accounts were disabled and CLOSED written")  # fmt: skip
    if case == "session-unit-race":
        stop = next((i for i, c in enumerate(after) if c == "systemctl stop trialbox.service"), len(after))
        ok("trialbox.service enabled again by hand" in seq and stop < after.index("compose-stop caddy") < dis2,
           "the unit, enabled again by hand and starting at the boot, was stopped before Caddy and the close")  # fmt: skip
        ok(any(c.startswith("unit trialbox.service activating at boot 2") for c in after),
           "the race was rehearsed: the unit's compose up was still to come when the close began")  # fmt: skip
    if case == "session-ops":
        ok(any(c.startswith("unit trialbox-ops.timer active at boot 2") for c in after)
           and not any("update_apply" in c for c in seq),
           "the Operations runner's timer, enabled again at the boot, was stopped before its update could bring Caddy up")  # fmt: skip
    if case == "session-quiet-fails":
        ok("are not all stopped" in out[1] and after.index("compose-stop caddy") < dis2,
           "trialbox.service would not stop: Caddy was stopped all the same and tcp:443 decided (round 4's a)")  # fmt: skip
if case in ("session", "session-stop"):  # the re-review's F: the address put back first, then the console recreated
    ups = [i for i, c in enumerate(seq) if c.startswith("compose-up-console ")]
    dis = max(i for i, c in enumerate(seq) if c.startswith("session-disable "))
    ok(bool(ups) and ups[-1] > dis and seq[ups[-1]] == "compose-up-console url=none",
       "after the close the console runs on the box's own address again (it was recreated after the restore)")  # fmt: skip
if case in ("session-cut", "session-close-fails"):  # the re-review's A: nothing served before the accounts are closed
    boot2_at = next((i for i, c in enumerate(seq) if c.startswith("vm-boot 2 ")), -1)
    ok(boot2_at >= 0 and seq[boot2_at] == "vm-boot 2 caddy down",
       "the box's Caddy did not come back by itself at the next boot (its restart policy was no)")  # fmt: skip
    after_boot2 = seq[boot2_at:] if boot2_at >= 0 else []
    caddy_up_at = next((i for i, c in enumerate(after_boot2) if c.startswith("caddy up")), len(after_boot2))
    if case == "session-cut":
        ok("session-disable-caddy down" in after_boot2[:caddy_up_at] and "session-disable-caddy up" not in seq,
           "the next boot disabled the accounts with the box's Caddy down, before anything brought it up")  # fmt: skip
    else:
        ok("session-disable-failed" in after_boot2 and caddy_up_at == len(after_boot2),
           "the close could not be made: the box's Caddy never came up on that boot")  # fmt: skip
        ok("TB-SESSION-ACCOUNTS-OPEN" in ended and "TB-STEP" not in out[-1], "the run stopped before any step")
        ok(not closed_marker.exists() or not closed_marker.read_text().startswith("closed "),
           "the run's marker does not say closed (it says open): the driver keeps the door's deny-all and the tag")  # fmt: skip
if case == "session-update-fails":  # the re-review's E: no restart policy, no session
    ok(parts["56-session-accounts"]["status"] == "stop" and "restart policy" in parts["56-session-accounts"]["stop"]["reason"],
       "the step stops when the restart policy cannot be set to no")  # fmt: skip
    ok(
        not links and not opened and not any(c.startswith("session-people") for c in seq),
        "no account and no link was made",
    )
    ok("TB-SESSION-READY" not in "".join(out), "the session never opened")
if case in ("session", "session-stop", "session-then-acc"):
    closed = BKT / "session" / f"rehearsal-{case}" / "CLOSED"
    ok(closed.exists() and "closed " in closed.read_text(), "the VM wrote the CLOSED marker once the accounts closed")
    ok(any(c.startswith("docker-update --restart=no cid-console cid-caddy") for c in calls)
       and any(c.startswith("docker-update --restart=unless-stopped") for c in calls),
       "the console and Caddy did not restart by themselves while the accounts were open, and do again after")  # fmt: skip
    ok("TB_CONSOLE_PUBLIC_URL" not in env_now, "the box's public address is put back (it had none)")
if case in ("session-skip", "session-resume", "session-ssh"):
    why = {"session-skip": "tb-skip names 55-session-egress", "session-resume": "a session run is never resumed",
           "session-ssh": "TB-SESSION-SSH"}[case]  # fmt: skip
    ok(why in ended, f"refused: {why} ({ended[:160]})")
    ok(not links and not any(c.startswith("session-people") for c in calls), "no account and no link was made")
    if case == "session-skip":
        ok(state["order"] == [], "refused before any step")
    if case == "session-resume":
        ok("TB-SESSION-READY" not in "".join(out), "the session never opened")
if case == "session-then-acc":
    units_order = units.splitlines()
    mask = next(i for i, x in enumerate(units_order) if "mask ssh.socket" in x and "unmask" not in x)
    ok(any("unmask ssh.socket ssh.service" in x for x in units_order[mask:])
       and any("enable ssh.socket" in x for x in units_order[mask:])
       and any("start ssh.socket" in x for x in units_order[mask:])
       and not any("enable ssh.service" in x or "start ssh.service" in x for x in units_order[mask:]),
       "the next boot that is no session put SSH back exactly as it was (socket enabled and active, service not)")  # fmt: skip
    feed = S / "feed" / "acc"
    ok(feed.is_dir() and not (feed / "vital.csv").exists()
       and "10000001" not in (feed / "patient.csv").read_text(),
       "the accuracy run's feed holds only its own sets: no table or patient of the session's hospital")  # fmt: skip
    ok(ended.startswith("TB-BOX-RUN-COMPLETE") and "TB-SESSION-ACCOUNTS-OPEN" not in out[-1],
       "the accuracy run ran with no session account open")  # fmt: skip
if case in ("session-egress", "session-dev-refused"):
    at = "55-session-egress" if case == "session-egress" else "52-acc-routes"
    ok(state["order"][-1] == at and parts[at]["status"] == "stop", f"stopped at {at}")
    why = parts[at]["stop"]["reason"]
    ok(("TB-SESSION-EGRESS" in why and "could let a box container out" in why and "198.51.100.7" in why) if case == "session-egress"
       else ("TB-ACC-BLOCKED" in why and "ceiling D0" in why), "the stop names the box's own reason")  # fmt: skip
    ok(not links and not opened and not any(c.startswith("session-people") for c in calls),
       "no account and no link was made")  # fmt: skip
    ok("TB-SESSION-NOT-READY" in out[-1] and "TB-SESSION-READY" not in out[-1], "the boot says it opened no session")
    if case == "session-dev-refused":
        ok(not any(c.startswith("acc-data") for c in calls), "no data fetched or built")

# ---------------------------------------------------------------- round 4's f and g
if case == "session-ss-fails":  # ss gives no answer at the next boot: tcp:443 cannot be told, no close of any kind
    b2 = out[1] if len(out) > 1 else ""
    ok("tcp:443 is unknown" in b2 and "TB-SESSION-ACCOUNTS-OPEN" in ended and "unknown" in ended,
       "the next boot could not tell what listens on tcp:443: the run stops and says so")  # fmt: skip
    boot2 = next((i for i, c in enumerate(seq) if c.startswith("vm-boot 2 ")), len(seq))
    ok(not any(c.startswith("session-disable") for c in seq[boot2:]) and any(not accounts[a]["disabled"] for a in opened),
       "no close ran while tcp:443 could not be told (the accounts wait for a boot that can)")  # fmt: skip
    ok(not closed_marker.exists() or not closed_marker.read_text().startswith("closed "),
       "the run's marker does not say closed: the driver keeps the deny-all and the tag")  # fmt: skip
if case == "session-ended-again":  # the run ended with its accounts open; a later boot of the SAME run closes them
    ok(len(out) == 3 and "TB-SESSION-ACCOUNTS-OPEN" in out[1] and "TB-RUN-ENDED-BEFORE" in out[2],
       "boot 2 could not close and ended the run; boot 3 is a later boot of the same ended run")  # fmt: skip
    b3 = out[2]
    ok(0 <= b3.find("TB-SESSION-END") < b3.find("TB-RUN-ENDED-BEFORE"),
       "boot 3 closed the session's accounts before it handed the ended run over again (round 4's g)")  # fmt: skip
print(f"check {case}: {'FAILED ' + str(len(fails)) if fails else 'passed'}")
sys.exit(1 if fails else 0)
