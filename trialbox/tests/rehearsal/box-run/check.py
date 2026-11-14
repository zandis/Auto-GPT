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
        else:
            needles.append(json.loads(text)["password"])
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
if (S / "evidence" / "no-key-http-code").exists():
    ok((S / "evidence" / "no-key-http-code").read_text().strip() == "401", "the door refuses a call without the key")


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
    ok(keys(START) and all(parts[n]["status"] == "done" for n in START), "G-2: the twelve start steps, done")
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
    ok(list(parts) == START[:8], "the run stopped at 08-qualify: no later part")
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
    ok(ended.startswith("TB-BOX-RUN-COMPLETE"), "a test rule, not a stop: the run went on")

print(f"check {case}: {'FAILED ' + str(len(fails)) if fails else 'passed'}")
sys.exit(1 if fails else 0)
