"""The checks of the box-run rehearsal (rehearse-box-run.sh): ``check.py <case> <state dir>``, exit 1 on any failure.

It reads what the driver collected from the bucket (evidence/results: state.json, parts/, vm.log, records/), the
bucket itself, and what the stand-ins wrote down (calls.log, POWEROFF, vm-gcloud.log).
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

case, S = sys.argv[1], Path(sys.argv[2])
R = S / "evidence" / "results"
BKT = S / "bucket" / "tb-runs"
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
full_start = case in ("happy", "reboot", "oom", "list-differs")
if full_start:
    ok(keys(START) and all(parts[n]["status"] == "done" for n in START), "G-2: the start steps, done")
    ok(
        parts["07g-gate"].get("pass") is True and calls["canary-gate"] == 2,
        "B2: the canary through the box's own gate holds a passing record",
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
        # 07g-gate restarts the orchestrator once too (its own startup canary), before G-9 begins
        calls["compose-restart orchestrator"] == 1 + ("07g-gate" in parts)
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

print(f"check {case}: {'FAILED ' + str(len(fails)) if fails else 'passed'}")
sys.exit(1 if fails else 0)
