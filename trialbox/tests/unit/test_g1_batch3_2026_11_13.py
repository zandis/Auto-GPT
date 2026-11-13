"""Lane G batch 3 (2026-11-13): the serving record says the WSL2 kernel, and a bucket-mode VM powers off once its last
results are in the bucket (defect B7). Each test failed before its change. No cloud: the VM scripts' own functions,
run in bash over temporary files, with ``systemctl`` a stub that writes down a power-off."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GCP = ROOT / "deploy" / "gcp"
VM_SCRIPT = GCP / "complete-run-vm.sh"
BOX_SCRIPT = GCP / "box-install-run.sh"
PY = str(ROOT / ".venv" / "bin" / "python")


def _function(script: Path, name: str) -> str:
    """The shell function ``name`` of ``script``, from ``name() {`` to its closing ``}`` at the start of a line."""
    m = re.search(rf"^{name}\(\) {{.*?^}}\n", script.read_text(encoding="utf-8"), re.M | re.S)
    assert m, f"{script.name}: no function {name}"
    return m.group(0)


# ---------------------------------------------------------------- 3. wsl_kernel in the serving record
def _record(tmp: Path) -> Path:
    rec = tmp / "serving_config.json"
    rec.write_text(json.dumps({"schema": "tb-serving-config/1", "card": {"name": "x"}, "servers": []}), "utf-8")
    return rec


@pytest.mark.parametrize("script", [VM_SCRIPT, BOX_SCRIPT])
@pytest.mark.parametrize(
    ("version", "release", "want"),
    [
        ("Linux version 6.6.87.2-microsoft-standard-WSL2 (root@host) (gcc ...)", "6.6.87.2-microsoft-standard-WSL2",
         "6.6.87.2-microsoft-standard-WSL2"),
        ("Linux version 5.15.0 (builder@x) #1 SMP", "5.15.153.1-microsoft-standard-WSL2",
         "5.15.153.1-microsoft-standard-WSL2"),  # the release alone says WSL2
        ("Linux version 6.8.0-1015-gcp (buildd@lcy02) (gcc 13.2.0)", "6.8.0-1015-gcp", None),  # a GCE VM
    ],
)  # fmt: skip
def test_the_serving_record_holds_the_wsl_kernel(
    tmp_path: Path, script: Path, version: str, release: str, want: str | None
) -> None:
    rec = _record(tmp_path)
    (tmp_path / "version").write_text(version, encoding="utf-8")
    fn = _function(script, "wsl_kernel_into")
    r = subprocess.run(["bash", "-c", f'{fn}\nwsl_kernel_into "$1" "$2" "$3"', "_", str(rec),
                        str(tmp_path / "version"), release], env=dict(os.environ, PY=PY),
                       capture_output=True, text=True, check=False)  # fmt: skip
    assert r.returncode == 0, r.stderr
    doc = json.loads(rec.read_text(encoding="utf-8"))
    assert "wsl_kernel" in doc and doc["wsl_kernel"] == want
    assert doc["schema"] == "tb-serving-config/1" and doc["card"] == {"name": "x"}  # nothing else changes


def test_the_schema_allows_the_field_and_both_scripts_write_it_after_the_capture(tmp_path: Path) -> None:
    from tools import serving_config

    rec = json.loads((ROOT / "deploy" / "measured" / "serving_config.rtxpro6000.json").read_text(encoding="utf-8"))
    assert serving_config.validate({**rec, "wsl_kernel": None}) == serving_config.validate(rec)
    assert _function(VM_SCRIPT, "wsl_kernel_into") == _function(BOX_SCRIPT, "wsl_kernel_into")  # one definition
    vm = VM_SCRIPT.read_text(encoding="utf-8")
    assert vm.index("serving_config.py capture") < vm.index("wsl_kernel_into $REC/serving_config.json")
    box = BOX_SCRIPT.read_text(encoding="utf-8")
    assert box.index('d_capture "$REC/serving_config.json"') < box.index('wsl_kernel_into "$REC/serving_config.json"')
    # no record (the capture failed): nothing is written
    fn = _function(VM_SCRIPT, "wsl_kernel_into")
    r = subprocess.run(["bash", "-c", f'{fn}\nwsl_kernel_into "$1"', "_", str(tmp_path / "none.json")],
                       env=dict(os.environ, PY=PY), capture_output=True, text=True, check=False)  # fmt: skip
    assert r.returncode == 0 and not (tmp_path / "none.json").exists()


# ---------------------------------------------------------------- 4. B7: the bucket-mode VM powers off after its upload
def _bucket_done(tmp: Path, bucket: str, failed: bool, arg: str = "0") -> tuple[int, str, list[str]]:
    tb = tmp / "tb"
    (tb / "out").mkdir(parents=True, exist_ok=True)
    if failed:
        (tb / "out" / "upload-failed").write_text("gs://b/runs/r/results.tgz\n", encoding="utf-8")
    stub = tmp / "bin"
    stub.mkdir(exist_ok=True)
    (stub / "systemctl").write_text(f'#!/bin/sh\necho "$*" >> {tmp / "off"}\n', encoding="utf-8")
    (stub / "systemctl").chmod(0o755)
    fn = _function(VM_SCRIPT, "bucket_done")
    env = dict(os.environ, PATH=f"{stub}:{os.environ['PATH']}")
    r = subprocess.run(["bash", "-c", f'TB={tb}; BUCKET="$1"; RUN={tmp}/runs/R-s1; LOG={tmp}/log\n{fn}\n'
                        f'bucket_done {arg}; echo "returned $?"', "_", bucket], env=env, capture_output=True,
                       text=True, check=False)  # fmt: skip
    offs = (tmp / "off").read_text(encoding="utf-8").split("\n") if (tmp / "off").exists() else []
    return r.returncode, r.stdout, [x for x in offs if x]


def test_b7_a_bucket_vm_powers_off_once_its_last_upload_went_through(tmp_path: Path) -> None:
    rc, out, offs = _bucket_done(tmp_path, "gs://tb-runs", failed=False)
    assert offs == ["poweroff"] and rc == 0 and "returned" not in out  # off now: it does not go on to the grace
    assert "TB-BUCKET-DONE: results.tgz is in gs://tb-runs/runs/R-s1/" in out
    assert (tmp_path / "tb" / "collected").exists()  # the watchdog's own rule agrees, should poweroff not end us
    assert "TB-BUCKET-DONE" in (tmp_path / "log").read_text(encoding="utf-8")  # in vm.log too


def test_b7_a_failed_upload_or_door_mode_keeps_the_old_way(tmp_path: Path) -> None:
    rc, out, offs = _bucket_done(tmp_path / "a", "gs://tb-runs", failed=True)  # the archive is on this disk only
    assert offs == [] and "returned 1" in out and not (tmp_path / "a" / "tb" / "collected").exists()
    rc, out, offs = _bucket_done(tmp_path / "b", "", failed=False)  # door mode: "collected" or the grace, as before
    assert offs == [] and "returned 1" in out
    rc, _, offs = _bucket_done(tmp_path / "c", "gs://tb-runs", failed=False, arg="1")  # after a failure marker
    assert offs == ["poweroff"] and rc == 1


def test_b7_the_run_and_a_failure_end_with_the_bucket_check_after_their_last_pack() -> None:
    text = VM_SCRIPT.read_text(encoding="utf-8")
    tail = text[text.rindex('touch "$TB/run-ended"') :]
    assert tail.index('tb-pack "$RUN" "$BUCKET"') < tail.index("COMPLETE-RUN-DONE") < tail.index("bucket_done 0")
    fin = _function(VM_SCRIPT, "finish")
    assert fin.index('tb-pack "$RUN" "$BUCKET"') < fin.index("COMPLETE-RUN-DONE") < fin.index("bucket_done 1")
    # the rehearsal's poweroff shim names the reason, and its bucket case checks it
    assert "TB-BUCKET-DONE" in (ROOT / "tests" / "rehearsal" / "shims" / "systemctl").read_text(encoding="utf-8")


def _check_module() -> object:
    spec = importlib.util.spec_from_file_location("rehearsal_check", ROOT / "tests" / "rehearsal" / "check.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_b7_the_rehearsals_bucket_check() -> None:
    check = _check_module()
    con = (
        "TB-PHASE run 2026-11-13T10:00:00Z\nTB-PHASE done 2026-11-13T10:05:00Z\nCOMPLETE-RUN-DONE\nTB-BUCKET-DONE: x\n"
    )
    prompt = ["2026-11-13T10:05:03Z poweroff by: /bin/bash | TB-BUCKET-DONE: results.tgz is in gs://b/runs/R-s1/"]
    assert check.bucket_poweroff_problems(con, prompt) == []  # type: ignore[attr-defined]
    late = ["2026-11-13T10:11:00Z poweroff by: /bin/sh | TB-WATCHDOG done, results collected: powering off"]
    why = check.bucket_poweroff_problems(con.replace("TB-BUCKET-DONE: x\n", ""), late)  # type: ignore[attr-defined]
    assert any("not the VM's TB-BUCKET-DONE" in w for w in why) and any("360 s after" in w for w in why)
    assert check.bucket_poweroff_problems(con, []) == ["no power-off recorded"]  # type: ignore[attr-defined]


def test_b7_a_bucket_left_in_the_metadata_by_an_earlier_run_is_not_this_runs(tmp_path: Path) -> None:
    """Metadata stays on a VM between runs: the rehearsal's door-mode case after the bucket case found tb-bucket still
    set and, with B7, powered off as a bucket run. The driver now always sets tb-bucket ("none" in door mode) and the
    VM takes only a gs:// value as its bucket."""
    env = dict(os.environ, TB_COMPLETE_DIR=str(tmp_path / "out"), PY=PY, TB_RUN_ID="R")
    for k in ("TB_ZONES", "TB_BUCKET", "TB_ESTIMATE_LLM_SPEEDUP", "TB_PROVISIONING"):
        env.pop(k, None)
    r = subprocess.run([str(GCP / "complete-run.sh"), "--dry-run", "--patients", "500", "--only", "scenario-it-dump"],
                       cwd=ROOT, env=env, capture_output=True, text=True, check=False, timeout=300)  # fmt: skip
    assert r.returncode == 0, r.stderr[-800:]
    meta = next(ln for ln in r.stdout.splitlines() if "add-metadata" in ln and "tb-run-id=" in ln)
    assert meta.rstrip().endswith("tb-bucket=none")
    vm = VM_SCRIPT.read_text(encoding="utf-8")
    line = next(ln for ln in vm.splitlines() if ln.startswith('case "$BUCKET" in gs://*)'))
    for value, want in (("none", ""), ("", ""), ("gs://tb-runs", "gs://tb-runs")):
        out = subprocess.run(["bash", "-c", f'BUCKET="$1"; {line}; printf %s "$BUCKET"', "_", value],
                             capture_output=True, text=True, check=True).stdout  # fmt: skip
        assert out == want
    assert vm.index("BUCKET=$(md tb-bucket || true)") < vm.index(line)


def test_a_cut_node_download_is_made_again_not_kept_half() -> None:
    vm = VM_SCRIPT.read_text(encoding="utf-8")
    block = vm[vm.index("NODE_V=v") : vm.index("ln -sf /opt/node-$NODE_V")]
    assert "[ ! -e /opt/node-$NODE_V-linux-x64/bin/npm ]" in block and "for _ in 1 2 3" in block
    assert block.index("rm -rf /opt/node-$NODE_V-linux-x64") < block.index("curl -fsSL")
