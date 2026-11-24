"""H-97, the review of #1429 (F8): the box rehearsal's ``only_the_expected_poc_stops`` passes only the one PoC stop
part D adds on a host with no TPM (``check_host.sh/no-tpm-sealed``, with doctor's line naming its action), and fails
on any other listed stop, on that stop missing, or on doctor's line missing.

The function is taken from ``tools/rehearse_box/box.sh`` as it is and run in bash, with ``fail`` and ``ok`` standing
in for the rehearsal's own and the TPM device paths pointed at the test's folder (the host's own /dev decides nothing
here).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.nodb
ROOT = Path(__file__).resolve().parents[2]
BOX_SH = ROOT / "tools" / "rehearse_box" / "box.sh"
SEALED = "check_host.sh/no-tpm-sealed"
DOCTOR = f"WARN poc_stop {SEALED}: no TPM device; to do: reseal the site keys under a TPM (SECURITY §10)"


def _function(dev: Path) -> str:
    text = BOX_SH.read_text(encoding="utf-8")
    m = re.search(r"^only_the_expected_poc_stops\(\) \{\n.*?^\}\n", text, re.S | re.M)
    assert m, "only_the_expected_poc_stops is not in box.sh"
    body = m.group(0)
    assert body.count("/dev/tpmrm0") == 1 and body.count("/dev/tpm0") == 1
    return body.replace("/dev/tpmrm0", f"{dev}/tpmrm0").replace("/dev/tpm0", f"{dev}/tpm0")


def _run(tmp: Path, keys: list[str], *, tpm: bool, doctor: bool) -> subprocess.CompletedProcess[str]:
    dev = tmp / "dev"
    dev.mkdir(exist_ok=True)
    if tpm:
        (dev / "tpmrm0").touch()
    listed = tmp / "poc-stops.jsonl"
    listed.write_text("".join(json.dumps({"key": k, "what": "synthetic"}) + "\n" for k in keys), encoding="utf-8")
    log = tmp / "install-output.log"
    log.write_text("==> doctor\n" + (DOCTOR + "\n" if doctor else ""), encoding="utf-8")
    script = ('fail() { echo "FAIL: $*"; exit 1; }\nok() { echo "ok: $*"; }\n' + _function(dev) +
              f'only_the_expected_poc_stops "{listed}" install "{log}"\n')  # fmt: skip
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False, timeout=30)


@pytest.mark.parametrize(
    ("keys", "tpm", "doctor", "passes", "said"),
    [
        ([SEALED], False, True, True, "listed only the expected PoC stop"),
        ([], True, False, True, ""),  # a TPM here: nothing of part D's is due
        ([SEALED, "check_host.sh/no-tpm"], False, True, False, "warned and listed the stops above"),
        (["tools.trialbox/doctor-proxy"], True, False, False, "warned and listed the stops above"),
        ([SEALED, SEALED + "-other"], False, True, False, "warned and listed the stops above"),
        ([], False, True, False, "did not list check_host.sh/no-tpm-sealed"),
        ([SEALED], False, False, False, "doctor did not show the PoC stop"),
    ],
    ids=["no-tpm-ok", "tpm-ok", "another-stop", "another-stop-with-tpm", "a-longer-key", "not-listed", "no-doctor"],
)
def test_the_rehearsal_passes_only_the_expected_poc_stop(
    tmp_path: Path, keys: list[str], tpm: bool, doctor: bool, passes: bool, said: str
) -> None:
    r = _run(tmp_path, keys, tpm=tpm, doctor=doctor)
    assert (r.returncode == 0) is passes, r.stdout + r.stderr
    assert said in r.stdout, r.stdout
