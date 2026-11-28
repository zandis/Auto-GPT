"""H-94's install bench (used by ``test_poc_stops_h94.py``): the REAL ``deploy/install.sh`` run whole, through the bundle load and the run from the signed
tree, to "TrialBox is running", in a folder laid out as an installer's, with stand-ins for what a test cannot have:
the Docker engine and compose (``bin/docker``), the host's python3 for the steps that would touch a box
(``bin/python3``: the steps named below answer as the box would, every other ``python3`` call is the real
interpreter), ``tools/apply_update.sh`` (a loader that does to the folder what the load does: the release,
``current``, the installer a link into it), nvidia-smi, the host check and ``chown`` (the services' group 10001 is
not the test user's). No GPU, no Docker, no root.

``force`` names the points a run forces to fail: each stand-in answers "no" for the points it serves. The names are
the stop points' keys (``install.sh/<key>`` in the list), so a run that forces a point and ends installed shows that
point warned, went on and was listed.
"""

from __future__ import annotations

import fcntl
import json
import os
import pty
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

pytestmark = [pytest.mark.nodb, pytest.mark.skipif(sys.platform != "linux", reason="bash and GNU tools")]
ROOT = Path(__file__).resolve().parents[2]
SYS_DIRS = ("/usr/local/sbin", "/usr/local/bin", "/usr/sbin", "/usr/bin", "/sbin", "/bin")

DOCKER = r"""#!/bin/sh
F=" ${TB_H94_FORCE:-} "
has() { case "$F" in *" $1 "*) return 0 ;; esac; return 1; }
echo "docker $*" >> "$TB_H94_LOG"
out_dir() {  # the host folder mounted at $1 in a docker run
  prev=""
  for a in "$@"; do
    case "$prev" in -v) case "$a" in *:"$want"|*:"$want":*) echo "${a%%:"$want"*}"; return ;; esac ;; esac
    prev="$a"
  done
}
case "$1 $2" in
  "version --format") echo 27.0; exit 0 ;;
  "info "*|"info") has docker-not-running && exit 1; echo "Runtimes: nvidia runc"; exit 0 ;;
  "image inspect") exit 0 ;;
  "volume ls") exit 0 ;;
  "volume inspect") exit 1 ;;
  "compose version") has compose-missing && exit 1; echo "Docker Compose version v2.29"; exit 0 ;;
  "rm "*) exit 0 ;;
esac
case "$*" in
  *"settings_wizard --check"*) exit 0 ;;
  *"tools.settings_wizard"*)
    want=/out; d="$(out_dir "$@")"
    cp "$TB_H94_WIZARD_ENV" "$d/.env"; echo "site: {}  # stand-in" > "$d/settings.yaml"; exit 0 ;;
  *"pin_model --install-embedder"*) exit 0 ;;
  *"pin_model --install "*) has pin-pair && { echo "pin: no weights (stand-in)" >&2; exit 1; }; exit 0 ;;
  *"pin_model --name-judge"*) echo "judge: j-workhorse (stand-in)"; exit 0 ;;
  *"serving_config measured"*) has serving-record && { echo "FAIL not this card (stand-in)"; exit 1; }; exit 0 ;;
  *"console.cli check-tls"*) has tls-check && { echo "FAIL certificate (stand-in)"; exit 1; }; echo "PASS tls"; exit 0 ;;
  *"--network none -v"*":/anchor:ro"*) has anchor-read && exit 1; exit 0 ;;
  *"tools.network_sheet"*) exit 0 ;;
  *"doctor --serving"*) has serving && { echo "FAIL serving (stand-in)"; exit 1; }; echo "PASS serving"; exit 0 ;;
esac
case "$1" in
  compose)
    case "$*" in
      *"config --images"*) echo trialbox-py:1.0.0; exit 0 ;;
      *"--wait db"*) has db-start && exit 1; exit 0 ;;
      *"--wait --wait-timeout"*) has stack-health && exit 1; exit 0 ;;
      *" down "*|*" down") has project-cleanup-failed && exit 1; exit 0 ;;
      *"keys-init"*) has site-keys && { echo "keys: cannot read (stand-in)" >&2; exit 1; }; echo "keys made"; exit 0 ;;
      *"30-service-roles.sh"*) has db-roles && exit 1; exit 0 ;;
      *"orchestrator.migrate"*) has db-schemas && exit 1; exit 0 ;;
      *"enrol-code"*) echo "enrolment code: 000000 (stand-in)"; exit 0 ;;
      *"refdata status"*) echo "pack_id stand-in"; exit 0 ;;
    esac
    exit 0 ;;
esac
exit 0
"""

PYTHON = r"""#!/bin/sh
F=" ${TB_H94_FORCE:-} "
has() { case "$F" in *" $1 "*) return 0 ;; esac; return 1; }
echo "python3 $*" >> "$TB_H94_LOG"
case "$1" in
  -m) mod="$2"; shift 2 ;;
  */tools/tiers.py)
    has tier-record && { echo "install: refused: tier stand-in: no record" >&2; exit 3; }
    echo "rtxpro6000 deploy/measured/serving_config.rtxpro6000.json"; exit 0 ;;
  -c) case "${2:-}" in "import "*) has host-python-modules && exit 1 ;; esac; exec "$TB_H94_REAL_PY" "$@" ;;
  *) exec "$TB_H94_REAL_PY" "$@" ;;
esac
signed() { [ -n "${TB_INSTALL_SIGNED:-}" ]; }
case "$mod ${1:-}" in
  "tools.trialbox finish-check")
    case " $* " in
      *" --anchor-only "*) k=anchor-gate ;;
      *) if signed; then k=finish-gate; else k=finish-early; fi ;;
    esac
    has "$k" && { echo "  - the backup target is on the box (stand-in)" >&2; exit 1; }
    has "$k-did-not-run" && { echo "finish-check: error (stand-in)" >&2; exit 2; }
    exit 0 ;;
  "tools.trialbox secrets") echo "service tokens: present (stand-in)"; exit 0 ;;
  "tools.trialbox anchors-compose")
    has anchors-compose && { echo "anchor: cannot be mounted (stand-in)" >&2; exit 1; }
    has anchor-read && { printf '%s\n%s\n' "$TB_H94_TMP/anchors.yml" "$TB_H94_TMP/anchor"; exit 0; }
    exit 0 ;;
  "tools.trialbox pre-start") has pre-start && { echo "pre-start: a step failed (stand-in)"; exit 1; }; exit 0 ;;
  "tools.trialbox db-up") has db-up && { echo "db-up: a step failed (stand-in)"; exit 1; }; exit 0 ;;
  "tools.trialbox selftest") exit 0 ;;
  "tools.trialbox backup-install") has backup-schedule && { echo "backup: no alert route (stand-in)"; exit 1; }; exit 0 ;;
  "tools.trialbox audit-sign") exit 0 ;;
  "tools.trialbox.memcaps "*) has memcaps && { echo "memcaps: no record (stand-in)"; exit 1; }; exit 0 ;;
  "tools.trialbox.pgsize "*) has pgsize && { echo "pgsize: no host (stand-in)"; exit 1; }; exit 0 ;;
  "tools.trialbox.bootwait "*) echo 60; exit 0 ;;
  "tools.trialbox.project_check "*)
    has project-cleanup-refused && { echo "refused: not this install's project (stand-in)" >&2; exit 1; }
    has project-cleanup-failed && { echo down; exit 0; }
    echo none; exit 0 ;;
  "tools.images_lock check-compose") exit 0 ;;
  "tools.image_pins resolve") exit 0 ;;
  "tools.rehearsal_real box") exit 0 ;;
  "tools.rehearsal_real card") echo "card 1: stand-in card, 180000 MiB free"; exit 0 ;;
  "tools.rehearsal_real write")
    d="$TB_H94_TMP/deploy/site"
    if has rrs-caps; then caps=''; else caps=', "caps": {"TB_VLLM_GPU_UTIL": "0.4"}'; fi
    printf '{"words": "rehearsal: stand-in", "card": {"profile_card": "P", "index": 1, "found": "stand-in"}%s}\n' "$caps" > "$d/rehearsal-real-servers.json"
    printf 'x-trialbox-rehearsal-real-servers: true\nservices: {}\n' > "$d/rehearsal-real-servers.yml"
    chmod 644 "$d/rehearsal-real-servers.yml"
    echo "driver below the minimum (stand-in)"; exit 0 ;;
esac
exec "$TB_H94_REAL_PY" -m "$mod" "$@"
"""

LOADER = r"""#!/bin/sh
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
[ "${2:-}" = --dry-run ] && exit 0
echo "load $*" >> "$TB_H94_LOG"
rel="$ROOT/releases/r1"
mkdir -p "$rel/deploy"
cp "$ROOT/deploy/install.sh.signed" "$rel/deploy/install.sh"
ln -sfn releases/r1 "$ROOT/current"
ln -sfn ../current/deploy/install.sh "$ROOT/deploy/install.sh"
echo "update r1 loaded"
"""

HOST_CHECK = r"""#!/bin/sh
F=" ${TB_H94_FORCE:-} "
echo "check_host $*" >> "$TB_H94_LOG"
case " $* " in *" --gpu-only "*) echo "PASS  gpu (stand-in)"; exit 0 ;; esac
case "$F" in *" host-check "*) echo "FAIL  disk unlock (stand-in)"; exit 1 ;; esac
case "$F" in *" env-mode "*) echo "FAIL  .env mode 644 (want 600, root-owned) [H-94 (5)]"; exit 1 ;; esac
case "$F" in *" disk-full "*) echo "FAIL  free space on /var/lib/docker: 4% (below 10%) [H-94 (2)]"; exit 1 ;; esac
echo "PASS  host (stand-in)"
"""

ID = r"""#!/bin/sh
real="$(/usr/bin/id "$@")" || exit $?
case "$*:$(/usr/bin/id -u)" in -u:0|-g:0) echo 4242 ;; -un:0) echo installer ;; *) echo "$real" ;; esac
"""

# the user the id stand-in names has a home: the box's own folder (H-96's first sign-in file is written there)
GETENT = r"""#!/bin/sh
case "$*" in "passwd 4242") echo "installer:x:4242:4242::$TB_H94_TMP:/bin/sh" ;; *) exec /usr/bin/getent "$@" ;; esac
"""

SMI = """#!/bin/sh
echo "GPU 0: stand-in card (UUID: GPU-00000000-0000-0000-0000-000000000000)"
"""


@dataclass
class Run:
    rc: int
    out: str
    err: str
    box: Path

    @property
    def text(self) -> str:
        return self.out + self.err

    def listed(self) -> list[dict[str, str]]:
        f = self.box / "deploy" / "site" / "poc-stops.jsonl"
        if not f.exists():
            return []
        return [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]

    def listed_keys(self) -> set[str]:
        return {e["key"] for e in self.listed()}


@dataclass
class Box:
    """An installer's folder under ``tmp``. ``env`` is deploy/.env as the settings wizard writes it."""

    tmp: Path
    env: str = "TB_ENV=TEST\n"
    no: tuple[str, ...] = ()  # host commands this box does not have (python3, flock)
    standins: bool = True  # tools/rehearse_box/standins.yml is there
    prewritten_env: str | None = None  # deploy/.env before the install (a re-run, or an operator's)
    record: bool = False  # deploy/measured/serving_config.rtxpro6000.json
    mark: bool = False  # deploy/site/rehearsal.json: a box that was a rehearsal box
    rrs_record: bool = False  # deploy/site/rehearsal-real-servers.json: one that ran the real servers
    log: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        t = self.tmp
        d = t / "deploy"
        (d / "keys").mkdir(parents=True)
        (d / "keys" / "vendor_ed25519.pub").write_text("stand-in key\n", encoding="utf-8")
        signed = (ROOT / "deploy" / "install.sh").read_bytes()
        (d / "install.sh").write_bytes(signed)
        (d / "install.sh.signed").write_bytes(signed)  # the signed release's installer: the same bytes
        for name, text in (("check_host.sh", HOST_CHECK), ("gpu_profile.sh", "#!/bin/sh\necho rtxpro6000\n")):
            (d / name).write_text(text, encoding="utf-8")
        if self.record:
            (d / "measured").mkdir()
            (d / "measured" / "serving_config.rtxpro6000.json").write_text("{}\n", encoding="utf-8")
        (t / ".env.example").write_text("POSTGRES_PASSWORD=change-me\n", encoding="utf-8")
        tools = t / "tools"
        tools.mkdir()
        for entry in (ROOT / "tools").iterdir():
            if entry.name not in ("apply_update.sh", "rehearse_box", "__pycache__"):
                (tools / entry.name).symlink_to(entry)
        (tools / "rehearse_box").mkdir()
        if self.standins:
            shutil.copy(ROOT / "tools" / "rehearse_box" / "standins.yml", tools / "rehearse_box" / "standins.yml")
        (tools / "apply_update.sh").write_text(LOADER, encoding="utf-8")
        for name in ("libs", "services"):
            (t / name).symlink_to(ROOT / name)
        b = t / "bin"
        b.mkdir()
        # id: the installer runs as a user that is not root (as CI does), whoever runs the test: no step of root's
        # (/usr/local/bin, /etc) is reached; chown: the services' group 10001 is not the test user's
        stand = {
            "docker": DOCKER,
            "nvidia-smi": SMI,
            "chown": "#!/bin/sh\nexit 0\n",
            "id": ID,
            "getent": GETENT,
            # H-110 (M-SC-3): a host whose cron daemon runs, as a site's does (its absence is a stop of its own)
            "pgrep": '#!/bin/sh\ncase " $* " in *" cron "*|*" crond "*) exit 0 ;; esac\nexit 1\n',
        }
        if "python3" not in self.no:
            stand["python3"] = PYTHON
        for name, text in stand.items():
            (b / name).write_text(text, encoding="utf-8")
            (b / name).chmod(0o755)
        sysbin = t / "sysbin"  # the host's commands, less the ones this box does not have
        sysbin.mkdir()
        hide = {"docker", "nvidia-smi", "chown", "id", "python3", "systemd-creds", "pgrep", *self.no}
        for folder in SYS_DIRS:
            if not os.path.isdir(folder):
                continue
            for cmd in os.listdir(folder):
                if cmd in hide or cmd.startswith("python") or (sysbin / cmd).exists():
                    continue
                (sysbin / cmd).symlink_to(os.path.join(folder, cmd))
        (t / "b.tar").write_bytes(b"stand-in bundle\n")
        (t / "wizard.env").write_text(self.env, encoding="utf-8")
        (t / "answers.yaml").write_text("site_name: Site A (synthetic)\n", encoding="utf-8")
        (t / "anchor").mkdir()
        (t / "anchors.yml").write_text("services: {}\n", encoding="utf-8")
        (d / "site").mkdir()
        if self.mark:
            (d / "site" / "rehearsal.json").write_text('{"rehearsal": true}\n', encoding="utf-8")
        if self.rrs_record:
            (d / "site" / "rehearsal-real-servers.json").write_text('{"words": "stand-in"}\n', encoding="utf-8")
        if self.prewritten_env is not None:
            (d / ".env").write_text(self.prewritten_env, encoding="utf-8")
            (d / ".env").chmod(0o600)

    @property
    def deploy(self) -> Path:
        return self.tmp / "deploy"

    def install(self, *args: str, force: tuple[str, ...] = (), tty: str | None = None, answers: bool = True,
                env: dict[str, str] | None = None, hold_lock: bool = False) -> Run:  # fmt: skip
        t = self.tmp
        if answers:
            args = (*args, "--answers", str(t / "answers.yaml"))
        full = {k: v for k, v in os.environ.items() if not k.startswith(("TB_", "COMPOSE_", "PYTHON"))}
        full.update(
            PATH=f"{t / 'bin'}:{t / 'sysbin'}", HOME=str(t), PYTHONPATH=f"{t}:{t / 'libs'}:{t / 'services'}",
            TB_H94_LOG=str(t / "calls.log"), TB_H94_FORCE=" ".join(force), TB_H94_REAL_PY=sys.executable,
            TB_H94_TMP=str(t), TB_H94_WIZARD_ENV=str(t / "wizard.env"), TB_CRON_DIR=str(t / "cron"),
            TB_SYSTEMD="0", TB_INSTALL_URL_TRIES="1", **(env or {}),
        )  # fmt: skip
        (t / "cron").mkdir(exist_ok=True)
        argv = ["bash", str(self.deploy / "install.sh"), str(t / "b.tar"), *args]
        if hold_lock:  # another installer holds the deploy folder's lock for the whole run
            held = os.open(self.deploy, os.O_RDONLY)
            try:
                fcntl.flock(held, fcntl.LOCK_EX)
                return self.install(*args, force=force, tty=tty, answers=False, env=env)
            finally:
                os.close(held)
        if tty is None:
            r = subprocess.run(argv, cwd=t, env=full, capture_output=True, text=True, timeout=300, check=False,
                               stdin=subprocess.DEVNULL)  # fmt: skip
            return Run(r.returncode, r.stdout, r.stderr, t)
        master, slave = pty.openpty()
        try:
            os.write(master, tty.encode())
            r = subprocess.run(argv, cwd=t, env=full, capture_output=True, text=True, timeout=300, check=False,
                               stdin=slave)  # fmt: skip
        finally:
            os.close(slave)
            os.close(master)
        return Run(r.returncode, r.stdout, r.stderr, t)


def test_the_bench_runs_as_a_user_and_writes_nothing_outside(tmp_path: Path) -> None:
    """The bench's own promise: no root step is reached (the installer sees a user), nothing is written outside."""
    box = Box(tmp_path / "b", env="TB_ENV=TEST\n")
    r = box.install("--environment", "TEST", "--mode", "stub", "--yes")
    assert r.rc == 0 and "TrialBox is running." in r.out, r.text[-4000:]
    assert r.listed_keys() == set()  # a clean PoC install lists nothing
    assert not shutil.which("trialbox") or "b/tools" not in os.path.realpath(shutil.which("trialbox") or "")


def stop_prelude(deploy: str = "/nonexistent/h94-no-box", environment: str = "", rehearsal: str = "0",
                 who: str = "install") -> str:  # fmt: skip
    """install.sh's STOP-OR-WARN block and its inputs, for a test that runs a block of install.sh alone (as the
    installer has them by then). The arguments are shell words: a test may pass ``"$ROOT/deploy"`` or
    ``"$ENVIRONMENT"``. The default box is none: nothing speaks, so it is PRODUCTION and every stop stops."""
    text = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    block = text[text.index("# ---- STOP-OR-WARN") : text.index("# ---- end of STOP-OR-WARN")]
    return (
        f"{block}\nTB_STOP_WHO={who}; TB_STOP_FILE={who}.sh; TB_STOP_DEPLOY={deploy}\n"
        f"TB_STOP_ARG_ENV={environment or '""'}; TB_STOP_REHEARSAL={rehearsal}\n"
    )
