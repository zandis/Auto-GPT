"""T-632 (D-382; review OPS-012): every command RUNBOOK §1 names runs in a test.

``test_every_command_of_section_1_has_a_runner`` reads the section file and fails on a command no runner below
covers, so a new command in §1 needs a test. Each runner runs the command as written, with the placeholders filled
in and ``sudo`` dropped, against temporary folders. Where the command needs what a test machine lacks, the runner
says so and runs as far as it can:

* the installer needs a Docker engine and a signed bundle: it runs through its argument and tier steps to the host
  step, where a stand-in ``docker`` reports the engine down (the whole install is the box rehearsal, RUNBOOK §16);
* ``serving_config.py capture`` runs against stand-ins of ``nvidia-smi`` and ``docker inspect``;
* ``make`` targets run as ``make -n`` (the build itself is CI's images job); ``docker compose ... up`` runs as
  ``docker compose ... config`` when the Docker CLI is there; ``network.sh apply`` runs as ``print`` (``apply``
  needs root and nftables); the adapter's first ingest is ``test_site_inputs``'s drill.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SECTION = ROOT / "docs/runbook/01-install-a-new-site.md"
ANSWERS_C = ROOT / "tests/fixtures/onboarding/site_c_answers.yaml"
PRO6000 = "NVIDIA RTX PRO 6000 Blackwell Server Edition"
EXEC = ("sudo ", "python", "deploy/", "tools/", "make ", "docker ", "cd ", "TB_", "--", "systemctl ")


def commands() -> list[str]:
    """Every command-like code span of §1, whitespace folded (a span may wrap a line)."""
    out = []
    for span in re.findall(r"`([^`]+)`", SECTION.read_text(encoding="utf-8")):
        cmd = " ".join(span.split())
        if cmd.startswith(EXEC) and (" " in cmd or cmd.endswith((".py", ".sh"))):
            out.append(cmd)
    return out


def _env(**extra: str) -> dict[str, str]:
    path = f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}"
    return {**os.environ, "PATH": path, "PYTHONPATH": f"{ROOT}/libs:{ROOT}/services:{ROOT}", "TB_ENV": "DEV",
            "TB_TZ": "Asia/Taipei", **extra}  # fmt: skip


def _run(
    args: list[str], *, cwd: Path = ROOT, stdin: str | None = None, **env: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, input=stdin, capture_output=True, text=True, env=_env(**env), check=False,
                          timeout=300)  # fmt: skip


def _stand_in(bin_dir: Path, name: str, body: str) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    f = bin_dir / name
    f.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    f.chmod(0o755)


# ------------------------------------------------------------------------------------------------ runners


def run_serving_measured(tmp: Path) -> None:
    out = _run([sys.executable, "tools/serving_config.py", "measured", "rtxpro6000",
                "deploy/measured/serving_config.rtxpro6000.json"])  # fmt: skip
    assert out.returncode == 0 and "measured on rtxpro6000" in out.stdout, out.stderr


def run_tier_check(tmp: Path) -> None:
    out = _run(["bash", "deploy/install.sh", "--tier", "large", "--tier-check"], TB_TIER_TEST_CARD=PRO6000,
               TB_TIER_TEST_ARCH="x86_64")  # fmt: skip
    assert out.returncode == 0 and "tier large: rtxpro6000 profile" in out.stdout, out.stderr


def _install_to_the_host_step(tmp: Path, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    """install.sh as §1 writes it, with a stand-in docker whose engine is down: it parses, checks the tier and the
    bundle file, and stops at the host step having changed nothing."""
    bin_dir = tmp / "bin"
    _stand_in(bin_dir, "docker", "import sys\nsys.exit(1)\n")
    bundle = tmp / "trialbox-2026.11-1.tar"
    bundle.write_bytes(b"")
    state = [ROOT / "deploy" / n for n in (".env", "settings.yaml", "updates", "secrets")]
    before = [p.exists() for p in state]
    out = subprocess.run(["bash", "deploy/install.sh", str(bundle), *args], cwd=ROOT, capture_output=True, text=True,
                         env=_env(**{**env, "PATH": f"{bin_dir}{os.pathsep}{_env()['PATH']}"}), check=False,
                         timeout=300)  # fmt: skip
    assert out.returncode == 1 and "Docker is not running" in out.stderr, out.stderr
    assert "==> host" in out.stdout
    assert [p.exists() for p in state] == before  # no setting, secret or update state written
    return out


def run_install_trial_boot(tmp: Path) -> None:
    _install_to_the_host_step(tmp, "--gpu", "rtxpro6000", TB_ACCEPT_UNMEASURED_GPU="1")


def run_install_tier(tmp: Path) -> None:
    out = _install_to_the_host_step(tmp, "--tier", "large", "--answers", str(ANSWERS_C), TB_TIER_TEST_CARD=PRO6000,
                                    TB_TIER_TEST_ARCH="x86_64")  # fmt: skip
    assert "tier large: rtxpro6000 profile" in out.stdout


def run_install_stub(tmp: Path) -> None:
    _install_to_the_host_step(tmp, "--mode", "stub")


def run_capture(tmp: Path) -> None:
    bin_dir = tmp / "bin"
    _stand_in(bin_dir, "nvidia-smi", (
        "import sys\n"
        "if any(a.startswith('--query-gpu') for a in sys.argv): print('" + PRO6000 + ", 97887, 81000, 580.95')\n"
        "else: print('| NVIDIA-SMI 580.95   Driver Version: 580.95   CUDA Version: 13.0 |')\n"))  # fmt: skip
    _stand_in(bin_dir, "docker", (
        "import json, sys\n"
        "a = sys.argv[1:]\n"
        "if a[:1] == ['inspect']:\n"
        "    print(json.dumps([{'Args': ['--model', '/models/judge', '--max-model-len', '32768'],\n"
        "                       'Config': {'Image': 'vllm/vllm-openai:standin'}, 'Image': 'sha256:00'}]))\n"
        "else: sys.exit(1)\n"))  # fmt: skip
    rec = tmp / "deploy/site/serving_config.rtxpro6000.json"
    rec.parent.mkdir(parents=True)
    out = _run([sys.executable, "tools/serving_config.py", "capture", "--container", "judge=trialbox-llm-service-1",
                "--container", "verifier=trialbox-llm-verifier-1", "--models-dir", str(tmp / "models"), "--out",
                str(rec)], PATH=f"{bin_dir}{os.pathsep}{_env()['PATH']}")  # fmt: skip
    # the stand-ins serve no weights, so the record says what it misses (exit 1); the capture itself ran
    assert out.returncode in (0, 1) and out.stdout.startswith(f"wrote {rec}"), out.stderr
    doc = json.loads(rec.read_text(encoding="utf-8"))
    assert [s["role"] for s in doc["servers"]] == ["judge", "verifier"] and doc["card"]["name"] == PRO6000


def run_gpu_sizing(tmp: Path) -> None:
    out = _run([sys.executable, "-m", "tools.gpu_sizing"])
    assert out.returncode == 0 and out.stdout.strip(), out.stderr


def run_make_bundle(tmp: Path) -> None:
    out = _run(["bash", "tools/make_bundle.sh", "--help"])
    assert out.returncode == 0 and "--gates" in out.stdout
    refused = _run(["bash", "tools/make_bundle.sh", "--key", str(tmp / "k"), "--id", "x", "--release-seq", "1",
                    "--out", str(tmp / "b.tar")])  # fmt: skip
    assert refused.returncode != 0 and "gates" in (refused.stderr + refused.stdout)  # never without the gates


def _make_dry(target: str) -> None:
    out = _run(["make", "-n", target])
    assert out.returncode == 0 and out.stdout.strip(), out.stderr


def run_make_release_bundle(tmp: Path) -> None:
    _make_dry("release-bundle")


def run_make_images(tmp: Path) -> None:
    _make_dry("images")


def run_make_images_multiarch(tmp: Path) -> None:
    _make_dry("images-multiarch")


def run_apply_update(tmp: Path) -> None:
    from tests.unit.test_host_tree import _bundle
    from tools.sign_bundle import keygen

    priv, pub = keygen(tmp / "vendor")
    bundle = _bundle(tmp, priv, "2026.11-1", 1, "one")
    out = _run(["sh", "tools/apply_update.sh", str(bundle), "--dry-run"], TB_VENDOR_PUBKEY=str(pub),
               TB_SECRETS_HOST_DIR=str(tmp / "no-secrets"))  # fmt: skip
    assert out.returncode == 0 and "verified:" in out.stdout and "nothing applied" in out.stdout, out.stderr


def run_wizard_questions(tmp: Path) -> None:
    from tools.settings_wizard import QUESTIONS

    replies = {"tz": "Asia/Taipei", "tls_hostname": "trialbox.hospa.test"}
    stdin = "".join(replies.get(k, "") + "\n" for k, *_ in QUESTIONS)
    out = _run([sys.executable, "-m", "tools.settings_wizard", "--out", str(tmp / "deploy/settings.yaml"),
                "--env-out", str(tmp / "deploy/.env")], stdin=stdin, TB_CTGOV_MODE="")  # fmt: skip
    assert out.returncode == 0, out.stderr
    assert "TB_TLS_HOSTNAME=trialbox.hospa.test" in (tmp / "deploy/.env").read_text(encoding="utf-8")


def run_wizard_answers(tmp: Path) -> None:
    settings = tmp / "deploy/settings.yaml"
    out = _run([sys.executable, "-m", "tools.settings_wizard", "--answers", str(ANSWERS_C), "--out", str(settings),
                "--env-out", str(tmp / "deploy/.env")])  # fmt: skip
    assert out.returncode == 0, out.stderr
    check = _run([sys.executable, "-m", "tools.settings_wizard", "--check", str(settings)])
    assert check.returncode == 0 and check.stdout.startswith("OK:"), check.stderr


def run_mapping_check(tmp: Path) -> None:
    """A site mapping in a site mapping folder (the rehearsal's), checked against an export (synthetic site A)."""
    site = tmp / "deploy/site/mapping"
    shutil.copytree(ROOT / "tools/rehearse_box/mapping", site)
    out = _run([sys.executable, "tools/mapping_check.py", "--mapping", str(site / "tw_core/rehearsal_a.yaml"),
                "--source", "csv", "--path", str(ROOT / "tests/fixtures/synthetic_patients/site-a"), "--json"])  # fmt: skip
    assert out.returncode == 0, out.stderr[-2000:]
    assert json.loads(out.stdout[out.stdout.index("{") :])["passed"]


def run_secrets_init(tmp: Path) -> None:
    deploy = tmp / "deploy"
    deploy.mkdir(parents=True, exist_ok=True)
    (deploy / ".env").write_text("TB_ENV=DEV\n", encoding="utf-8")
    out = _run([sys.executable, "-m", "tools.trialbox", "secrets", "init", "--deploy", str(deploy)])
    assert out.returncode == 0, out.stderr
    assert (deploy / "secrets/services/operator.token").is_file()


def run_compose_up(tmp: Path) -> None:
    if shutil.which("docker") is None or _run(["docker", "compose", "version"]).returncode != 0:
        pytest.skip("no Docker CLI with the compose plugin here; CI's images job brings the stack up")
    deploy = tmp / "deploy"  # a copy, with the site's deploy/.env the compose files read
    shutil.copytree(ROOT / "deploy", deploy, ignore=shutil.ignore_patterns("models", ".env"))
    (deploy / ".env").write_text(
        "TB_TLS_HOSTNAME=trialbox.hospa.test\nPOSTGRES_PASSWORD=synthetic-only\n", encoding="utf-8"
    )
    files = ["docker-compose.yml", "docker-compose.secrets.yml", "docker-compose.identity.yml",
             "docker-compose.rtxpro6000.yml"]  # fmt: skip
    for profile in ("gpu", "stub"):
        args = ["docker", "compose", "--project-directory", str(deploy)]
        for f in files:
            args += ["-f", f]
        out = _run([*args, "--profile", profile, "config", "-q"], cwd=deploy)
        assert out.returncode == 0, out.stderr


def run_network_apply(tmp: Path) -> None:
    env = tmp / ".env"
    env.write_text("SMTP_HOST=smtp.hospa.test\nSMTP_PORT=587\nTB_CTGOV_MODE=offline\n", encoding="utf-8")
    bin_dir = tmp / "bin"  # the engine's view of the box: no network yet (apply reads the live one)
    _stand_in(bin_dir, "docker", "")
    out = _run(["sh", "deploy/network.sh", "print", "--env", str(env)], PATH=f"{bin_dir}{os.pathsep}{_env()['PATH']}")
    # the ruleset is rendered; with no container running each allow line is named and skipped
    assert out.returncode == 0 and "table inet trialbox_egress" in out.stdout, out.stderr
    assert "smtp.hospa.test:587" in out.stderr


def run_first_ingest(tmp: Path) -> None:
    """``adapter.cli run`` with the site's mapping and a feed folder: the drill of test_site_inputs.py."""
    from tests.unit import test_site_inputs as drill

    assert callable(drill.test_the_adapter_ingests_from_the_mounted_feed_with_a_mapping_not_in_the_image)


def run_check_host(tmp: Path) -> None:
    env = tmp / ".env"
    env.write_text("TB_ENV=DEV\n", encoding="utf-8")
    out = _run(["sh", "deploy/check_host.sh", "--gb10", "--env", str(env), "--secrets", str(tmp)])
    lines = [ln for ln in out.stdout.splitlines() if ln[:4] in ("PASS", "WARN", "FAIL")]
    assert out.returncode in (0, 1) and lines, out.stderr  # a test machine is not a hardened box: FAIL lines are fine
    assert out.returncode == (1 if any(ln.startswith("FAIL") for ln in lines) else 0)


def run_systemctl_enable(tmp: Path) -> None:
    """``systemctl enable`` needs a booted systemd: the units it names are the ones install.sh copies, with
    ``@TB_ROOT@`` filled in (their content: tests/unit/test_systemd_units.py)."""
    cmd = next(c for c in commands() if c.startswith("systemctl enable "))
    for unit in cmd.split()[2:]:
        text = (ROOT / "deploy/systemd" / unit).read_text(encoding="utf-8")
        assert "[Install]" in text or unit.endswith(".timer"), unit
        filled = text.replace("@TB_ROOT@", str(tmp))
        assert "@TB_ROOT@" not in filled


# command (as §1 writes it, a regular expression) -> its runner
RUNNERS: list[tuple[str, Callable[[Path], None]]] = [
    (r"tools/serving_config\.py measured", run_serving_measured),
    (r"deploy/install\.sh --tier large --tier-check", run_tier_check),
    (r"TB_ACCEPT_UNMEASURED_GPU=1 deploy/install\.sh <bundle> --gpu <profile>", run_install_trial_boot),
    (r"python3 tools/serving_config\.py capture .*", run_capture),
    (r"python -m tools\.gpu_sizing", run_gpu_sizing),
    (r"sudo deploy/install\.sh trialbox-<version>\.tar --tier large --answers site\.yaml", run_install_tier),
    (r"--mode stub", run_install_stub),
    (r"tools/make_bundle\.sh", run_make_bundle),
    (r"make release-bundle", run_make_release_bundle),
    (r"tools/apply_update\.sh trialbox-<version>\.tar", run_apply_update),
    (r"make images", run_make_images),
    (r"make images-multiarch", run_make_images_multiarch),
    (r"python -m tools\.settings_wizard --out deploy/settings\.yaml --env-out deploy/\.env", run_wizard_questions),
    (r"--answers site\.yaml", run_wizard_answers),
    (
        r"python -m tools\.settings_wizard --answers tests/fixtures/onboarding/site_c_answers\.yaml .*",
        run_wizard_answers,
    ),
    (r"--check deploy/settings\.yaml", run_wizard_answers),
    (r"python tools/mapping_check\.py --mapping deploy/site/mapping/.*", run_mapping_check),
    (r"sudo python3 -m tools\.trialbox secrets init", run_secrets_init),
    (r"cd deploy && docker compose .* up -d --wait", run_compose_up),
    (r"--profile stub", run_compose_up),
    (r"deploy/network\.sh apply", run_network_apply),
    (r"docker compose exec adapter python -m adapter\.cli run", run_first_ingest),
    (r"deploy/check_host\.sh \[--gb10\]", run_check_host),
    (r"systemctl enable trialbox-.*", run_systemctl_enable),
]


def _runner(cmd: str) -> Callable[[Path], None] | None:
    hits = [fn for pat, fn in RUNNERS if re.fullmatch(pat, cmd)]
    return hits[0] if hits else None


def test_every_command_of_section_1_has_a_runner() -> None:
    cmds = commands()
    assert len(cmds) >= 20  # the section's commands were found
    missing = [c for c in cmds if _runner(c) is None]
    assert not missing, f"RUNBOOK §1 names commands no test runs; add a runner here: {missing}"
    unused = [pat for pat, _ in RUNNERS if not any(re.fullmatch(pat, c) for c in cmds)]
    assert not unused, f"runners for commands §1 no longer names: {unused}"


@pytest.mark.parametrize("cmd", commands())
def test_the_command_runs(cmd: str, tmp_path: Path) -> None:
    fn = _runner(cmd)
    assert fn is not None, cmd
    fn(tmp_path)
