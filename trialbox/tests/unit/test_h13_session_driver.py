"""The owner's live session through the driver (deploy/gcp/box-run.sh; D-1130 to D-1133), against a fake ``gcloud``.

Nothing touches GCP: a fake ``gcloud`` on the PATH logs every call and answers from a little state (the firewall's
rules, the VM's tags, the bucket's objects and IAM policy, the serial pages), as the demo VM's tests do. One test per
"must never be possible" of D-1123 section 6, besides the door's own (test_h13_session_door.py) and the VM's
(the rehearsal cases session*, tests/unit/test_g1_box_install_run.py). Synthetic codes and documentation-style
addresses only."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tools import box_run

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / "deploy" / "gcp" / "box-run.sh"
VM_SCRIPT = ROOT / "deploy" / "gcp" / "box-install-run.sh"
RUN = "box-20261117T060000Z-abcdef12"
OWNER = "1.2.3.4/32"
CODE = "SYNTHETIC-CODE-7F3A"
FP = ":".join(["C3"] * 32)
NET = "https://www.googleapis.com/compute/v1/projects/p/global/networks/default"

pytestmark = pytest.mark.nodb

FAKE = r"""#!/bin/bash
# the fake gcloud of test_h13_session_driver.py: every call logged, a little state in $S
S=${FAKE_STATE:?}
{ printf '%q ' "$@"; echo; } >> "$S/argv.log"
fmt=""; for a in "$@"; do case "$a" in --format=*) fmt=${a#--format=} ;; esac; done
case "$1 $2 $3" in
  "auth activate-service-account"*|"auth print-access-token"*) exit 0 ;;
  "config get-value project") echo fake-project ;;
  "compute instances network-interfaces") cat "$S/effective.json" ;;
  "compute instances describe")
    case "$fmt" in
      json) python3 -c 'import json,sys; t=[x for x in open(sys.argv[1]).read().split() if x]; n=json.load(open(sys.argv[2])); print(json.dumps({"tags": {"items": t}, "networkInterfaces": n}))' "$S/tags" "$S/nics.json" ;;
      *tags.items*) cat "$S/tags" ;;
      *networkInterfaces*) echo "https://x/global/networks/default" ;;
      *lastStartTimestamp*) echo 2026-11-17T06:00:00.000-08:00 ;;
      *serviceAccounts*) echo "TERMINATED x@developer.gserviceaccount.com" ;;
      *) cat "$S/status" ;;
    esac ;;
  "compute instances add-tags") echo "tb-session" >> "$S/tags" ;;
  "compute instances remove-tags") sed -i '/^tb-session$/d' "$S/tags" ;;
  "compute instances start") echo RUNNING > "$S/status" ;;
  "compute instances stop") echo TERMINATED > "$S/status" ;;
  "compute instances set-scheduling"|"compute instances add-metadata"|"compute instances remove-metadata") true ;;
  "compute instances get-serial-port-output")
    start=0; prev=""; for a in "$@"; do [ "$prev" = --start ] && start=$a; prev=$a; done
    python3 -c 'import json,sys; d=open(sys.argv[1]).read(); s=int(sys.argv[2]); c=d[s:]; print(json.dumps({"contents": c, "start": str(s), "next": str(s+len(c))}))' "$S/serial" "$start" ;;
  "compute firewall-rules describe") [ -f "$S/fw/$4.json" ] || exit 1; echo "$4" ;;
  "compute firewall-rules create"|"compute firewall-rules update")
    python3 - "$S" "$@" <<'PY'
import json, sys, os
s, args = sys.argv[1], sys.argv[2:]
name = args[3]
p = os.path.join(s, "fw", name + ".json")
r = json.load(open(p)) if os.path.exists(p) else {"name": name, "direction": "INGRESS"}
r["network"] = "https://www.googleapis.com/compute/v1/projects/p/global/networks/default"
it = iter(args[4:])
for a in it:
    k, _, v = a.partition("=")
    if not _ and k in ("--network", "--direction", "--action", "--target-tags", "--priority", "--description"):
        v = next(it)
    if k == "--rules":
        if v == "all": rule = [{"IPProtocol": "all"}]
        else: rule = [{"IPProtocol": x.split(":")[0], "ports": [x.split(":")[1]]} for x in v.split(",")]
        r["_rules"] = rule
    elif k == "--source-ranges": r["sourceRanges"] = v.split(",")
    elif k == "--target-tags": r["targetTags"] = v.split(",")
    elif k == "--priority": r["priority"] = int(v)
    elif k == "--action": r["_action"] = v
kind = "denied" if r.get("_action") == "DENY" or "denied" in r else "allowed"
r[kind] = r.pop("_rules", r.get(kind)); r.pop("_action", None)
json.dump(r, open(p, "w"))
PY
    ;;
  "compute firewall-rules delete") for n in "${@:4}"; do case "$n" in --*) ;; *) rm -f "$S/fw/$n.json" ;; esac; done ;;
  "compute firewall-rules list") python3 -c 'import glob,json,sys; print(json.dumps([json.load(open(f)) for f in sorted(glob.glob(sys.argv[1] + "/fw/*.json"))]))' "$S" ;;
  "storage buckets get-iam-policy") cat "$S/iam.json" ;;
  "storage buckets describe") cat "$S/bucket.json" ;;
  # the bucket as a folder: gs://b-test/<path> is $S/gcs/<path>; ls takes its pattern, rm its --all-versions
  "storage ls "*)
    pat="${*: -1}"; rel="${pat#gs://b-test/}"
    found=0; for f in $S/gcs/$rel; do [ -f "$f" ] && { echo "gs://b-test/${f#$S/gcs/}"; found=1; }; done
    [ "$found" = 1 ] || { echo "ERROR: One or more URLs matched no objects." >&2; exit 1; } ;;
  "storage cat "*) cat "$S/gcs/${3#gs://b-test/}" ;;
  "storage rm "*)
    for a in "${@:3}"; do case "$a" in --all-versions) echo all-versions >> "$S/rm-flags" ;; gs://*) rm "$S/gcs/${a#gs://b-test/}" ;; esac; done ;;
  "storage cp "*)
    src="${@: -2:1}"; dst="${@: -1}"
    case "$src" in gs://*) src="$S/gcs/${src#gs://b-test/}" ;; esac
    case "$dst" in gs://*) dst="$S/gcs/${dst#gs://b-test/}" ;; esac
    mkdir -p "$(dirname "$dst")"; cp "$src" "$dst" ;;
  *) echo "fake gcloud: not faked: $*" >&2; exit 1 ;;
esac
"""


def _env(tmp: Path) -> dict[str, str]:
    s, b = tmp / "state", tmp / "bin"
    if not b.exists():
        for d in (b, s / "fw", s / "gcs", tmp / "gc", tmp / "runs"):
            d.mkdir(parents=True)
        (b / "gcloud").write_text(FAKE, encoding="utf-8")
        (b / "gcloud").chmod(stat.S_IRWXU)
        (s / "status").write_text("TERMINATED\n")
        (s / "tags").write_text("tb-gpu\ntb-gpu-door\n")
        (s / "nics.json").write_text(json.dumps([{"network": NET, "stackType": "IPV4_ONLY",
                                                   "accessConfigs": [{"natIP": "34.80.0.10"}]}]))  # fmt: skip
        (s / "effective.json").write_text(json.dumps({"firewalls": [], "firewallPolicys": []}))
        (s / "bucket.json").write_text(json.dumps({"uniform_bucket_level_access": True, "versioning_enabled": False,
                                                   "public_access_prevention": "inherited",
                                                   "soft_delete_policy": {"retentionDurationSeconds": "604800"}}))  # fmt: skip
        (s / "iam.json").write_text(json.dumps({"bindings": [{"role": "roles/storage.objectAdmin",
                                                               "members": ["serviceAccount:x@p.iam.gserviceaccount.com"]}]}))  # fmt: skip
        # the hand-over's network: the project's SSH rule for every instance and the old door on tb-gpu-door
        rules = {
            "default-allow-ssh": {"priority": 65534, "sourceRanges": ["0.0.0.0/0"],
                                  "allowed": [{"IPProtocol": "tcp", "ports": ["22"]}]},
            "tb-gpu-door": {"priority": 1000, "sourceRanges": ["5.6.7.0/24"], "targetTags": ["tb-gpu-door"],
                            "allowed": [{"IPProtocol": "tcp", "ports": ["443"]}]},
        }  # fmt: skip
        for name, r in rules.items():
            (s / "fw" / f"{name}.json").write_text(
                json.dumps({"name": name, "network": NET, "direction": "INGRESS", **r})
            )
        (tmp / "key.json").write_text("{}")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TB_", "CLOUDSDK_", "GC_"))}
    env.update(PATH=f"{b}:{os.environ['PATH']}", FAKE_STATE=str(s), CLOUDSDK_CONFIG=str(tmp / "gc"), PY=sys.executable,
               TB_SA_KEY_FILE=str(tmp / "key.json"), TB_BUCKET="gs://b-test", TB_BOXRUN_DIR=str(tmp / "runs" / RUN),
               TMPDIR=str(tmp), HOME=str(tmp))  # fmt: skip
    return env


def _run(tmp: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(DRIVER), *args], env=_env(tmp), capture_output=True, text=True, check=False)


def _argv(tmp: Path) -> str:
    p = tmp / "state" / "argv.log"
    return p.read_text() if p.exists() else ""


def _door(tmp: Path, **change: Any) -> None:
    """The session's two rules as the launch made them (the launch itself is tested below)."""
    _env(tmp)
    fw = tmp / "state" / "fw"
    (fw / "tb-session-https.json").write_text(json.dumps({"name": "tb-session-https", "network": NET, "direction":
        "INGRESS", "priority": 500, "sourceRanges": [OWNER], "targetTags": ["tb-session"],
        "allowed": [{"IPProtocol": "tcp", "ports": ["443"]}]}))  # fmt: skip
    (fw / "tb-session-deny.json").write_text(json.dumps({"name": "tb-session-deny", "network": NET, "direction":
        "INGRESS", "priority": 510, "sourceRanges": ["0.0.0.0/0"], "targetTags": ["tb-session"],
        "denied": [{"IPProtocol": "all"}]}))  # fmt: skip
    for name, ch in change.items():
        r = json.loads((fw / f"{name}.json").read_text())
        r.update(ch)
        (fw / f"{name}.json").write_text(json.dumps(r))
    (tmp / "state" / "tags").write_text("tb-gpu\ntb-gpu-door\ntb-session\n")
    (tmp / "runs" / RUN).mkdir(parents=True, exist_ok=True)
    (tmp / "runs" / RUN / "session").write_text(OWNER + "\n")


def _objects(tmp: Path) -> list[Path]:
    return [f for f in (tmp / "state" / "gcs").rglob("*") if f.is_file()]


def _closed(tmp: Path) -> None:
    """The VM's CLOSED marker beside the links (it writes it once the session's accounts are disabled)."""
    d = tmp / "state" / "gcs" / "session" / RUN
    d.mkdir(parents=True, exist_ok=True)
    (d / "CLOSED").write_text("closed 2026-11-17T09:41:00Z by the session's stop\n")


def _links_object(tmp: Path) -> None:
    d = tmp / "state" / "gcs" / "session" / RUN
    d.mkdir(parents=True, exist_ok=True)
    (d / "links-20261117T064000Z.txt").write_text(
        f"TrialBox live session for the owner (run {RUN}, boot id {'a1' * 8}). NOTHING FROM THIS SESSION IS EVIDENCE:\n"
        f"Address: https://trialbox.hospa.test/ (root SHA-256 {FP}, compare it).\n"
        "The session closes at 2026-11-17T09:40:00Z (UTC); the pages then stop answering.\n\n"
        f"owner-s11170600 (coordinator+investigator): https://trialbox.hospa.test/enrol#u=owner-s11170600&c={CODE}\n"
    )  # fmt: skip


def test_links_are_printed_once_then_deleted_with_the_boot_id_and_the_certificate(tmp_path: Path) -> None:
    """D-1133: the door proved and the bucket private first, then the object printed once and deleted."""
    _door(tmp_path)
    _links_object(tmp_path)
    r = _run(tmp_path, "--links", RUN)
    assert r.returncode == 0, r.stderr
    assert r.stdout.count(f"&c={CODE}") == 1
    assert (
        f"== boot id: {'a1' * 8}" in r.stdout and FP in r.stdout and "closes at (UTC): 2026-11-17T09:40:00Z" in r.stdout
    )
    assert "nothing from this session is evidence" in r.stdout
    argv = _argv(tmp_path)
    assert argv.index("firewall-rules list") < argv.index("get-iam-policy") < argv.index("storage cat")
    assert "storage rm" in argv and not _objects(tmp_path)
    again = _run(tmp_path, "--links", RUN)  # read once: a second read finds nothing
    assert again.returncode == 3 and "read already" in again.stderr and CODE not in again.stdout + again.stderr


@pytest.mark.parametrize("case", ["door-not-proved", "bucket-public"])
def test_no_link_is_given_unless_the_door_is_proved_and_the_bucket_private(tmp_path: Path, case: str) -> None:
    """Must never: any port but 443 or any source but the owner's (the old door before the deny), a public bucket."""
    if case == "door-not-proved":
        _door(tmp_path, **{"tb-session-https": {"sourceRanges": ["0.0.0.0/0"]}})
    else:
        _door(tmp_path)
        (tmp_path / "state" / "iam.json").write_text(json.dumps({"bindings": [{"role": "roles/storage.objectViewer",
                                                                               "members": ["allUsers"]}]}))  # fmt: skip
    _links_object(tmp_path)
    r = _run(tmp_path, "--links", RUN)
    assert r.returncode == 3 and "no link is given" in r.stderr
    assert CODE not in r.stdout + r.stderr and "storage cat" not in _argv(tmp_path)
    assert _objects(tmp_path)  # left for the integrator to look at, not read


def _launch(tmp: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    r = tmp / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    (r / "f").write_text("x")
    subprocess.run(["git", "-C", str(r), "add", "f"], check=True)
    subprocess.run(["git", "-C", str(r), "-c", "user.email=t@x.invalid", "-c", "user.name=t", "commit", "-qm", "x"],
                   check=True)  # fmt: skip
    sha = subprocess.run(["git", "-C", str(r), "rev-parse", "HEAD"], capture_output=True, text=True,
                         check=True).stdout.strip()  # fmt: skip
    assert box_run.src_bundle(sha, out=tmp / "src.bundle", root=r)["ok"]
    return _run(tmp, "--mode", "validation", "--steps", "dev,session", "--release-id", "dev-x", "--commit", sha,
                "--src-bundle", str(tmp / "src.bundle"), "--no-wait", *extra)  # fmt: skip


def test_the_launch_makes_the_door_and_proves_it_before_the_vm_starts(tmp_path: Path) -> None:
    r = _launch(tmp_path, "--session-allow", OWNER, "--session-env", "validation")
    assert r.returncode == 0, r.stderr + r.stdout
    argv = _argv(tmp_path)
    for want in ("firewall-rules create tb-session-deny", "firewall-rules create tb-session-https",
                 "instances add-tags tb-gpu-sim", "firewall-rules list", "get-iam-policy", "instances start"):  # fmt: skip
        assert want in argv, want
    assert argv.index("firewall-rules list") < argv.index("get-iam-policy") < argv.index("instances start")
    allow = json.loads((tmp_path / "state" / "fw" / "tb-session-https.json").read_text())
    assert allow["allowed"] == [{"IPProtocol": "tcp", "ports": ["443"]}] and allow["sourceRanges"] == [OWNER]
    assert "--max-run-duration=4h" in argv and "--instance-termination-action=STOP" in argv
    md = tmp_path / "runs" / RUN / "md"
    assert (md / "block-project-ssh-keys").read_text() == "TRUE"
    assert (md / "tb-session-env").read_text() == "VALIDATION" and (md / "tb-max-minutes").read_text() == str(
        4 * 60 - 5
    )
    assert (md / "tb-acc-sets").read_text() == "jmed:300 tcga:500"  # the integrator's answer 6, public sets only
    assert "door: reaches the VM: tcp:443 from 1.2.3.4/32 only" in r.stdout
    assert "--session-status" in r.stdout and "--links" in r.stdout


def test_the_metadata_holds_no_code_no_link_and_no_secret(tmp_path: Path) -> None:
    """Must never: a secret in the metadata. What the driver hands the VM, key by key."""
    r = _launch(tmp_path, "--session-allow", OWNER, "--session-env", "validation")
    assert r.returncode == 0, r.stderr
    md = tmp_path / "runs" / RUN / "md"
    text = "".join(f.read_text() for f in md.iterdir())
    assert not re.search(r"enrol#|&c=|password|BEGIN |PRIVATE|code:", text, re.I), text
    assert {f.name for f in md.iterdir() if "session" in f.name} == {"tb-session-env", "tb-session-minutes",
                                                                     "tb-session-people", "tb-session-synth",
                                                                     "tb-session-handoff"}  # fmt: skip


def test_the_launch_refuses_a_door_that_does_not_hold(tmp_path: Path) -> None:
    """The old door given a priority before the deny: the launch stops before the VM starts (exit 7)."""
    _env(tmp_path)
    door = tmp_path / "state" / "fw" / "tb-gpu-door.json"
    door.write_text(json.dumps({**json.loads(door.read_text()), "priority": 100}))
    r = _launch(tmp_path, "--session-allow", OWNER, "--session-env", "validation")
    assert r.returncode == 7 and "the door is not proved" in r.stderr
    assert "tb-gpu-door: REACHES the VM" in r.stdout
    assert "instances start" not in _argv(tmp_path)


def test_a_dev_session_is_refused_for_free_while_the_box_would_not_serve_it(tmp_path: Path) -> None:
    """Must never: real data routes or text leaving the box. DEV on this tree routes the session's calls to no served
    model and opens a model host to the gateway: the launch is refused before any cloud call (exit 9)."""
    r = _launch(tmp_path, "--session-allow", OWNER)  # --session-env dev, the default (the integrator's ruling)
    assert r.returncode == 9 and "would not be served as ruled" in r.stderr
    assert "class_not_allowed_in_env" in r.stderr or "ceiling D0" in r.stderr
    assert "openrouter" in r.stderr  # the egress table's way out in DEV
    assert "firewall-rules create" not in _argv(tmp_path) and "instances start" not in _argv(tmp_path)


def test_the_session_check_keeps_every_call_on_the_box_in_validation() -> None:
    sc = box_run.session_check("VALIDATION")
    assert sc["can_run"] and sc["egress_allows"] == []
    for call in sc["calls"].values():
        assert all(c["zone"] == "perimeter" and c["alias"] in box_run.SERVED for c in call["candidates"]), call
    dev = box_run.session_check("DEV")
    assert not dev["can_run"] and any("dev_public" in b for b in dev["blockers"])


@pytest.mark.parametrize("raw", ["0.0.0.0/0", "any", "8.0.0.0/8", ""])
def test_the_driver_refuses_a_wide_range_before_anything(tmp_path: Path, raw: str) -> None:
    r = _launch(tmp_path, "--session-allow", raw, "--session-env", "validation")
    assert r.returncode == 2 and "refused (no VM started)" in r.stderr
    assert _argv(tmp_path) == ""  # not one gcloud call


def test_stop_takes_the_door_away_once_the_accounts_are_closed(tmp_path: Path) -> None:
    _door(tmp_path)
    _closed(tmp_path)
    (tmp_path / "state" / "status").write_text("RUNNING\n")
    r = _run(tmp_path, "--stop", RUN)
    assert r.returncode == 0, r.stderr
    assert not (tmp_path / "state" / "fw" / "tb-session-https.json").exists()
    assert not (tmp_path / "state" / "fw" / "tb-session-deny.json").exists()
    assert "tb-session" not in (tmp_path / "state" / "tags").read_text().split()
    assert (tmp_path / "state" / "fw" / "default-allow-ssh.json").exists()  # the project's own rules stay


def test_stop_keeps_the_deny_while_the_accounts_are_not_confirmed_closed(tmp_path: Path) -> None:
    """The review's finding 6: a session cut before its close (a pre-emption, the cap) leaves accounts open on the
    kept disk; the next boot serves them before its close runs. Until the VM's CLOSED marker is there, --stop takes
    only the allow away: the deny-all and the tag stay, so nothing (not the old door, not SSH) reaches the VM."""
    _door(tmp_path)
    (tmp_path / "state" / "status").write_text("RUNNING\n")
    r = _run(tmp_path, "--stop", RUN)
    assert r.returncode == 0, r.stderr
    assert "accounts not confirmed closed" in r.stdout
    assert not (tmp_path / "state" / "fw" / "tb-session-https.json").exists()
    assert (tmp_path / "state" / "fw" / "tb-session-deny.json").exists()
    assert "tb-session" in (tmp_path / "state" / "tags").read_text().split()
    _closed(tmp_path)  # the next boot of any run closed them: a second --stop takes the rest away
    assert _run(tmp_path, "--stop", RUN).returncode == 0
    assert not (tmp_path / "state" / "fw" / "tb-session-deny.json").exists()
    assert "tb-session" not in (tmp_path / "state" / "tags").read_text().split()


def test_status_counts_only_this_boots_ready_line(tmp_path: Path) -> None:
    _door(tmp_path)
    (tmp_path / "state" / "status").write_text("RUNNING\n")
    a, b = "a" * 16, "b" * 16
    (tmp_path / "state" / "serial").write_text(
        f"TB-SESSION-BOOT boot={a} started=2026-11-17T10:00:00Z\n"
        f"TB-SESSION-READY boot={a} at=2026-11-17T10:40:00Z stop=2026-11-17T13:40:00Z\n"
        f"TB-SESSION-BOOT boot={b} started=2026-11-17T14:00:05Z\n"
    )  # fmt: skip
    r = _run(tmp_path, "--session-status", RUN)
    assert r.returncode == 0, r.stderr
    assert "session: not ready yet" in r.stdout  # an earlier boot's ready line does not count (D-1120)
    r = _run(tmp_path, "--session-status", RUN, "--boot-id", a)
    assert "session: TB-SESSION-READY" in r.stdout
    assert _run(tmp_path, "--session-status", RUN, "--boot-id", "xyz").returncode == 2


def test_the_session_launchs_cap_bounds_its_hours() -> None:
    """Must never: the session outliving its stop. The cap of a session launch is the bring-up plus its hours, and the
    launch sets the cloud's max-run-duration to it (test_the_launch_makes_the_door_and_proves_it_before_the_vm_starts).
    The VM's own window, closed before the cap fires, is held by the rehearsal case session-stop; that no code is
    printed or kept, by every session case (each code looked for in every log, result and the serial output)."""
    assert box_run.launch_cap_hours(["dev", "session"], None, 3) == 4
    assert box_run.launch_cap_hours(["dev", "session"], None, 1) == 2
    est = box_run.estimate(["dev", "session"], "validation", "", 3)["launches"][0]
    assert est["cap_hours"] == 4 and est["usd_cap_spot"] == 10.96
    assert not any(r["step"].startswith("08 ") for r in est["rows"])


def test_a_session_launch_takes_no_other_group_and_no_accuracy_option() -> None:
    vals = {"tb-session-env": "DEV", "tb-session-people": "owner:coordinator+admin", "tb-session-minutes": "180"}
    assert box_run.session_values(["dev", "session"], vals, "validation") == []
    assert any("--steps dev,session" in x for x in box_run.session_values(["dev", "session", "acc"], vals))
    assert any("never PRODUCTION" in x for x in box_run.session_values(["dev", "session"],
                                                                      {**vals, "tb-session-env": "PRODUCTION"}))  # fmt: skip
    assert any("no accuracy option" in x for x in box_run.session_values(["dev", "session"],
                                                                         {**vals, "tb-acc-protocols": "tcga:G1"}))  # fmt: skip
    assert any("--mode validation" in x for x in box_run.session_values(["dev", "session"], vals, "production"))


# ---------------------------------------------------------------- the security review's findings 1, 2, 4, 7, 9
def test_a_session_run_is_never_resumed(tmp_path: Path) -> None:
    """Finding 2: a resume would boot the session's steps with no door, no bucket check and no session-check."""
    _door(tmp_path)
    md = tmp_path / "runs" / RUN / "md"
    md.mkdir(parents=True)
    (md / "tb-steps").write_text("dev session")
    (tmp_path / "runs" / RUN / "session").unlink()  # even with the door's file gone (an earlier --stop took it)
    r = _run(tmp_path, "--resume", RUN)
    assert r.returncode == 2 and "never resumed" in r.stderr
    assert "instances start" not in _argv(tmp_path) and "add-metadata" not in _argv(tmp_path)


@pytest.mark.parametrize(
    "extra, why",
    [(["--skip", "55-session-egress"], "--skip 55-session-egress"),
     (["--skip", "08-qualify 58-session-close"], "--skip 08-qualify 58-session-close"),
     (["--only", "jmed"], "--only"),
     (["--redo", "55-session-egress"], "--redo")],
    ids=["skip-egress", "skip-close", "only", "redo"],
)  # fmt: skip
def test_a_session_takes_no_skip_redo_or_only_of_its_own(tmp_path: Path, extra: list[str], why: str) -> None:
    """Finding 1 (reproduced by the review): a skip of 55 marked the egress proof done and the run handed out links.
    Now refused before any cloud call; the VM's preflight refuses it too (rehearsal case session-skip)."""
    r = _launch(tmp_path, "--session-allow", OWNER, "--session-env", "validation", *extra)
    assert r.returncode == 6 and why in r.stderr, r.stderr
    assert "instances start" not in _argv(tmp_path) and "firewall-rules create" not in _argv(tmp_path)
    vals = {"tb-session-env": "VALIDATION", "tb-session-people": "owner-crc:coordinator", "tb-session-minutes": "60"}
    assert box_run.session_values(["dev", "session"], {**vals, "tb-skip": box_run.SESSION_SKIP}) == []
    assert box_run.metadata(["dev", "session"], {**vals, "tb-src": "s", "tb-commit": "c", "tb-acc-tools": "t",
                                                 "tb-session-handoff": "gs://b/s"}, tmp_path / "md",
                            "validation") and (tmp_path / "md" / "tb-skip").read_text() == box_run.SESSION_SKIP  # fmt: skip


def test_steps_in_any_order_take_the_direct_route(tmp_path: Path) -> None:
    """Finding 9: `--steps session,dev` passed the checks but took the bundle branch on the VM."""
    r = _launch(tmp_path, "--session-allow", OWNER, "--session-env", "validation", "--steps", "session,dev")
    assert r.returncode == 0, r.stderr
    md = tmp_path / "runs" / RUN / "md"
    assert (
        (md / "tb-direct").read_text().strip() == "1" and (md / "tb-src").exists() and not (md / "tb-bundle").exists()
    )


@pytest.mark.parametrize("case", ["no-uniform-access", "versioning", "policy-allow", "ipv6", "allow-source-tags"])
def test_the_launch_refuses_a_bucket_or_a_vm_the_door_cannot_hold(tmp_path: Path, case: str) -> None:
    """Findings 4 and 7: object ACLs or old versions of the links; a firewall policy, an IPv6 address, or an allow
    that also lets other VMs in. Each stops the launch before the VM starts (exit 7)."""
    _env(tmp_path)
    s = tmp_path / "state"
    if case == "no-uniform-access":
        b = json.loads((s / "bucket.json").read_text())
        (s / "bucket.json").write_text(json.dumps({**b, "uniform_bucket_level_access": False}))
    elif case == "versioning":
        b = json.loads((s / "bucket.json").read_text())
        (s / "bucket.json").write_text(json.dumps({**b, "versioning_enabled": True}))
    elif case == "policy-allow":
        (s / "effective.json").write_text(json.dumps({"firewallPolicys": [{"name": "org", "type": "HIERARCHY",
            "rules": [{"priority": 1, "direction": "INGRESS", "action": "allow",
                       "match": {"srcIpRanges": ["0.0.0.0/0"]}}]}]}))  # fmt: skip
    elif case == "ipv6":
        (s / "nics.json").write_text(json.dumps([{"network": NET, "stackType": "IPV4_IPV6",
                                                   "ipv6AccessConfigs": [{"externalIpv6": "2001:db8::5"}]}]))  # fmt: skip
    if case == "allow-source-tags":  # an allow left with a source tag is deleted and made again: the launch passes
        _door(tmp_path, **{"tb-session-https": {"sourceTags": ["tb-other"]}})
        (tmp_path / "runs" / RUN / "session").unlink()
        r = _launch(tmp_path, "--session-allow", OWNER, "--session-env", "validation")
        assert r.returncode == 0, r.stdout + r.stderr
        allow = json.loads((s / "fw" / "tb-session-https.json").read_text())
        assert "sourceTags" not in allow and "firewall-rules delete tb-session-https" in _argv(tmp_path)
        return
    r = _launch(tmp_path, "--session-allow", OWNER, "--session-env", "validation")
    assert r.returncode == 7, r.stdout + r.stderr
    assert "instances start" not in _argv(tmp_path)


def test_links_delete_every_version(tmp_path: Path) -> None:
    _door(tmp_path)
    _links_object(tmp_path)
    assert _run(tmp_path, "--links", RUN).returncode == 0
    assert (tmp_path / "state" / "rm-flags").read_text().split() == ["all-versions"]
