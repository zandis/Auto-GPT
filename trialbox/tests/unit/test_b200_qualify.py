"""G1b on the owner's B200 (T-114, D-428): the offline bundle, the owner's script, the host fingerprint, the two MIG
layouts, the G1b record and its schema, and `doctor --platform`'s `host_match` warning.

No GPU and no docker: the script runs against stand-in `nvidia-smi` and `docker` (tests/rehearsal/b200/), whose
answers are the fixtures of a B200 there. A stand-in run's record is `standin`, never `passed`."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from tools import b200_qualify as bq
from tools import serving_config as sc
from tools.trialbox import platform as pf

ROOT = Path(__file__).resolve().parents[2]
SHIMS = ROOT / "tests" / "rehearsal" / "b200"
FIX = SHIMS / "fixtures"
SCHEMA = json.loads((ROOT / "schemas" / "b200_qualification_record.schema.json").read_text(encoding="utf-8"))
DIGEST = "vllm/vllm-openai@sha256:befccf0e7e4089aa23926bb6f887a85c0d46c2a99e6de5c5ffdf5cb7957c5b34"


def _raw(mig: str = "Enabled", listing: str = "list-small.txt") -> dict[str, str]:
    return {
        "query": (FIX / "query.txt").read_text(encoding="utf-8").replace("@MIG@", mig),
        "banner": (FIX / "banner.txt").read_text(encoding="utf-8"),
        "list": (FIX / listing).read_text(encoding="utf-8"),
        "kernel": "6.8.0-48-generic\n",
        "toolkit": "NVIDIA Container Toolkit CLI version 1.17.8\ncommit: x\n",
        "docker": "27.3.1\n",
        "os_release": (FIX / "os-release").read_text(encoding="utf-8"),
    }


def test_the_fingerprint_from_the_fixtures() -> None:
    fp = bq.fingerprint(_raw(), vllm_digests=[DIGEST], at="2026-11-11T00:00:00+00:00")
    assert fp["gpu_name"] == "NVIDIA B200" and fp["gpu_count"] == 1 and fp["memory_total_mib"] == 183359
    assert (fp["driver"], fp["cuda"], fp["vbios"]) == ("580.95.05", "13.0", "97.00.B5.00.21")
    assert fp["mig_mode"] == "enabled" and fp["mig_layout"] == ["1g.23gb", "2g.45gb"]
    assert (fp["kernel"], fp["os"], fp["container_toolkit"]) == ("6.8.0-48-generic", "Ubuntu 24.04.1 LTS", "1.17.8")
    assert len(fp["host_id"]) == 16 and "GPU-" not in fp["host_id"]  # a hash of the UUIDs, never a hostname
    assert fp["fingerprint_sha256"] == bq.fingerprint_sha256(fp)
    other = bq.fingerprint(_raw(), vllm_digests=[DIGEST], at="2027-01-01T00:00:00+00:00")
    assert other["fingerprint_sha256"] == fp["fingerprint_sha256"]  # the time is not part of the host
    assert bq.fingerprint(_raw(mig="Disabled"), vllm_digests=[DIGEST])["fingerprint_sha256"] != fp["fingerprint_sha256"]


def test_compare_lists_the_differences_and_skips_what_one_side_lacks() -> None:
    fp = bq.fingerprint(_raw(), vllm_digests=[DIGEST])
    assert bq.compare(fp, fp)[0] == []
    there = {**fp, "driver": "570.86.15", "mig_layout": ["3g.90gb", "3g.90gb"], "vbios": ""}
    diffs, seen = bq.compare(fp, there)
    assert [d.split(":")[0] for d in diffs] == ["driver", "mig_layout"] and "vbios" not in seen
    other_build = {"vllm_image_digests": ["vllm/vllm-openai@sha256:" + "1" * 64]}
    assert bq.compare(fp, other_build)[0][0].startswith("vllm_image_digests")


def test_the_node_labels_give_a_comparable_fingerprint() -> None:
    node = json.loads((FIX / "node-b200.json").read_text(encoding="utf-8"))
    here = bq.fingerprint_from_node(node, [DIGEST])
    assert here["driver"] == "580.95.05" and here["cuda"] == "13.0" and here["mig_layout"] == ["1g.23gb", "2g.45gb"]
    diffs, seen = bq.compare(bq.fingerprint(_raw(), vllm_digests=[DIGEST]), here)
    assert diffs == [] and {"gpu_name", "driver", "cuda", "mig_layout", "kernel", "vllm_image_digests"} <= set(seen)


def test_two_layouts_each_server_on_its_own_instance() -> None:
    lays = bq.load_layouts()
    assert [x["name"] for x in lays] == ["small", "large"]
    small = bq.layout("small")
    devs = bq.assign_devices((FIX / "list-small.txt").read_text(encoding="utf-8"), small)
    assert devs["judge"] != devs["verifier"] and all(d.startswith("MIG-") for d in devs.values())
    env = bq.serve_env(small, devs)
    assert env["TB_MIG_PROFILE"] == "judge=2g.45gb,verifier=1g.23gb" and sc.mig_layout(env["TB_MIG_PROFILE"])
    for lay in lays:  # the context each server gets reaches the shared-quota rule on its instance
        for role in sc.ROLES:
            assert lay[role]["max_len"] >= sc.MIG_MIN_LEN[sc.mig_base(lay[role]["mig_profile"])]
    with pytest.raises(ValueError, match="no free MIG instance"):  # one slice: refused with the reason
        bq.assign_devices((FIX / "list-one-slice.txt").read_text(encoding="utf-8"), small)


def test_a_third_layout_or_a_profile_without_a_rule_is_refused(tmp_path: Path) -> None:
    doc = json.loads(bq.LAYOUTS.read_text(encoding="utf-8"))
    bad = tmp_path / "l.json"
    bad.write_text(json.dumps({**doc, "layouts": doc["layouts"] + [dict(doc["layouts"][0], name="x")]}))
    with pytest.raises(ValueError, match="exactly two"):
        bq.load_layouts(bad)
    doc["layouts"][0]["judge"]["mig_profile"] = "5g.99gb"
    bad.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="no rule"):
        bq.load_layouts(bad)


def _code(tmp: Path) -> Path:
    """The parts of the code the host run needs (a stand-in for `git archive`)."""
    code = tmp / "code"
    for rel in (
        "tools/__init__.py",
        "tools/b200_qualify.py",
        "tools/serving_config.py",
        "eval/qualification/b200-layouts.json",
    ):
        (code / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, code / rel)
    return code


def _bundle(tmp: Path) -> Path:
    for role in ("judge", "verifier"):
        w = tmp / f"{role}-w"
        w.mkdir(parents=True, exist_ok=True)
        (w / "config.json").write_text(json.dumps({"synthetic": role}))
    img = tmp / "vllm.tar"
    img.write_bytes(b"stand-in image tarball")
    out = tmp / "usb" / "tb-b200.tar.gz"
    bq.build(
        out,
        code=_code(tmp),
        images=[("vllm", img)],
        weights=[("judge-w", tmp / "judge-w"), ("verifier-w", tmp / "verifier-w")],
    )
    return out


def test_the_bundle_verifies_and_a_changed_or_added_file_is_refused(tmp_path: Path) -> None:
    out = _bundle(tmp_path)
    sha = Path(f"{out}.sha256").read_text(encoding="utf-8").split()[0]
    assert len(sha) == 64
    d = tmp_path / "unpacked"
    with tarfile.open(out) as t:
        t.extractall(d, filter="data")
    man = json.loads((d / bq.MANIFEST).read_text(encoding="utf-8"))
    assert man["commit"] is None and "never a G1b pass" in man["code_source"]
    assert {"weights/judge-w/config.json", "images/vllm.tar", "layouts.json"} <= set(man["files"])
    assert bq.verify(d) == []
    (d / "weights" / "judge-w" / "config.json").write_text("{}")
    (d / "code" / "extra.py").write_text("x = 1\n")
    bad = bq.verify(d)
    assert any("judge-w/config.json: sha256" in b for b in bad) and any(
        "extra.py: not in the manifest" in b for b in bad
    )


def _run(tmp: Path, *, standin: str = "1", extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    bundle = _bundle(tmp)
    envf = tmp / "site.env"
    envf.write_text("VLLM_IMAGE=vllm/vllm-openai:v0.32.0\n")
    env = {
        **{k: v for k, v in os.environ.items() if k in ("HOME", "LANG", "TMPDIR")},
        "PATH": f"{SHIMS}:{Path(sys.executable).parent}:/usr/bin:/bin",
        "TB_B200_SHIM_STATE": str(tmp / "state"),
        "TB_B200_STANDIN": standin,
        "TB_B200_QUALIFY_CMD": str(SHIMS / "qualify-standin"),
        **(extra or {}),
    }
    cmd = ["bash", str(ROOT / "tools" / "b200_qualify.sh"), "--bundle", str(bundle), "--operator", "operator-a",
           "--env-file", str(envf), "--out", str(tmp / "run"), "--yes"]  # fmt: skip
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300, check=False)


def test_the_owners_script_end_to_end_on_stand_ins(tmp_path: Path) -> None:
    res = _run(tmp_path)
    assert res.returncode == 1, res.stdout + res.stderr  # a stand-in run is never a pass
    run = tmp_path / "run"
    rec = json.loads((run / "g1b-record.json").read_text(encoding="utf-8"))
    jsonschema.validate(rec, SCHEMA)
    assert bq.problems(rec) == [] and rec["status"] == "standin"
    assert rec["host"]["site_host"] is False and "not CGMH" in rec["host"]["statement"]
    assert rec["fingerprint"]["mig_mode"] == "disabled" and rec["fingerprint"]["vllm_image_digests"] == [DIGEST]
    by = {r["name"]: r for r in rec["layouts"]}
    assert by["small"]["fingerprint"]["mig_layout"] == ["1g.23gb", "2g.45gb"]
    assert by["large"]["fingerprint"]["mig_layout"] == ["3g.90gb", "3g.90gb"]
    for name, row in by.items():
        assert row["serving_record"]["measured"], row["serving_record"]["why"]
        assert row["qualification"]["status"] == "passed" and row["status"] == "passed"
        serving = json.loads((run / name / "serving_config.json").read_text(encoding="utf-8"))
        assert serving["host_fingerprint"]["fingerprint_sha256"] == row["fingerprint"]["fingerprint_sha256"]
        assert sc.measured_for(serving, "shared-quota") == []
    assert rec["failed"] == ["the bundle's code is not a commit (git archive)"]
    calls = (tmp_path / "state" / "nvidia-smi.calls").read_text(encoding="utf-8")
    assert "mig -i 0 -cgi 2g.45gb,1g.23gb -C" in calls and "mig -i 0 -cgi 3g.90gb,3g.90gb -C" in calls
    assert "gcloud" not in res.stdout + res.stderr
    assert "standin" in (run / "G1b.md").read_text(encoding="utf-8")
    with tarfile.open(run / "g1b-results.tar.gz") as t:
        names = t.getnames()
    assert "./g1b-record.json" in names and not any(n.startswith("./bundle/") for n in names)


def test_the_record_passes_only_from_a_commit_without_stand_ins(tmp_path: Path) -> None:
    _run(tmp_path)
    run = tmp_path / "run"
    man = json.loads((run / "bundle" / bq.MANIFEST).read_text(encoding="utf-8"))
    (run / "bundle" / bq.MANIFEST).write_text(json.dumps({**man, "commit": "0" * 40}))
    rec = bq.make_record(run, operator="operator-a", standin=False)
    jsonschema.validate(rec, SCHEMA)
    assert rec["status"] == "passed" and bq.problems(rec) == []
    (run / "large" / "qualification.json").unlink()
    rec = bq.make_record(run, operator="operator-a", standin=False)
    assert rec["status"] == "failed" and "large: qualification absent" in rec["failed"]
    forged = {**rec, "status": "passed"}
    assert any("status passed" in p for p in bq.problems(forged))
    tampered = json.loads(json.dumps(rec))
    tampered["layouts"][0]["fingerprint"]["driver"] = "999"
    assert any("fingerprint_sha256" in p for p in bq.problems(tampered))


def test_the_script_refuses_a_stand_in_qualify_on_a_real_run_and_a_wrong_sha(tmp_path: Path) -> None:
    res = _run(tmp_path, standin="0")
    assert res.returncode == 2 and "refused without TB_B200_STANDIN=1" in res.stderr
    out = _bundle(tmp_path / "b")
    Path(f"{out}.sha256").write_text("0" * 64 + "  x\n")
    envf = tmp_path / "site.env"
    env = {"PATH": f"{SHIMS}:{Path(sys.executable).parent}:/usr/bin:/bin", "TB_B200_STANDIN": "1",
           "TB_B200_SHIM_STATE": str(tmp_path / "state")}  # fmt: skip
    res = subprocess.run(
        ["bash", str(ROOT / "tools/b200_qualify.sh"), "--bundle", str(out), "--operator", "o", "--env-file", str(envf),
         "--out", str(tmp_path / "r"), "--yes"],
        env=env, capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip
    assert res.returncode == 2 and "do not run it" in res.stderr


# ---------------------------------------------------------------- doctor --platform: host_match
def _inputs(tmp: Path, recorded: dict[str, Any] | None, **env: str) -> pf.PlatformInputs:
    rec_path = tmp / "serving.json"
    rec_path.write_text(json.dumps({"schema": sc.SCHEMA, **({"host_fingerprint": recorded} if recorded else {})}))
    state = pf.PlatformState(source="manifests", namespace="trialbox", objects=[])
    release = pf.Release(images={}, release_id="t", sha256="0" * 64)
    return pf.PlatformInputs(
        state=state, release=release, env={"TB_ENV": "TEST", "TB_SERVING_RECORD": str(rec_path), **env}
    )


def test_doctor_platform_warns_when_the_host_differs_from_the_record(tmp_path: Path) -> None:
    fp = bq.fingerprint(_raw(), vllm_digests=[DIGEST])
    same = tmp_path / "here.json"
    same.write_text(json.dumps(fp))
    ok = pf.check_host_match(_inputs(tmp_path, fp, TB_PLATFORM_HOST_FINGERPRINT=str(same)))
    assert ok.status == "PASS" and "driver" in ok.detail
    site = tmp_path / "site.json"
    site.write_text(json.dumps({**fp, "driver": "570.86.15", "mig_layout": ["3g.90gb", "3g.90gb"]}))
    warn = pf.check_host_match(_inputs(tmp_path, fp, TB_PLATFORM_HOST_FINGERPRINT=str(site)))
    assert warn.status == "WARN" and "driver: recorded 580.95.05, here 570.86.15" in warn.detail
    assert "mig_layout" in warn.detail and "re-measure" in warn.detail
    none = pf.check_host_match(_inputs(tmp_path, None, TB_PLATFORM_HOST_FINGERPRINT=str(same)))
    assert none.status == "WARN" and "no host fingerprint" in none.detail
    unknown = pf.check_host_match(_inputs(tmp_path, fp))
    assert unknown.status == "WARN" and "unknown" in unknown.detail


def test_doctor_platform_reads_the_gpu_node_and_skips_without_a_gpu(tmp_path: Path) -> None:
    fp = bq.fingerprint(_raw(), vllm_digests=[DIGEST])
    inp = _inputs(tmp_path, {**fp, "driver": "575.1.1"})
    inp.state.objects.append(json.loads((FIX / "node-b200.json").read_text(encoding="utf-8")))
    got = pf.check_host_match(inp)
    assert got.status == "WARN" and "node gpu-node-1 labels" in got.detail and "driver" in got.detail
    inp.no_gpu = True
    assert pf.check_host_match(inp).status == "SKIP"
    assert "host_match" in {f.__name__.removeprefix("check_") for f in pf.PLATFORM_CHECKS}
