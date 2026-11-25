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
    # a copy of the installer's folder: a rehearsal box is a PoC box (H-94, D-1091), whose warnings are listed in its
    # own deploy/site, never the checkout's
    box = tmp / "box"
    (box / "deploy").mkdir(parents=True, exist_ok=True)
    for name in ("install.sh", "gpu_profile.sh", "check_host.sh"):
        shutil.copy(ROOT / "deploy" / name, box / "deploy" / name)
    if not (box / "tools").exists():
        (box / "tools").symlink_to(ROOT / "tools")
    state = [box / "deploy" / n for n in (".env", "settings.yaml", "updates", "secrets")]
    before = [p.exists() for p in state]
    # H139-12: the host's own graphics tool is not this step's: a card the run's host has (the bench host's) that
    # cannot run the model server's image makes the installer refuse, rightly. The step sees the profile it is given.
    host_path = os.pathsep.join(d for d in _env()["PATH"].split(os.pathsep) if not (Path(d) / "nvidia-smi").exists())
    out = subprocess.run(["bash", "deploy/install.sh", str(bundle), *args], cwd=box, capture_output=True, text=True,
                         env=_env(**{**env, "PATH": f"{bin_dir}{os.pathsep}{host_path}"}), check=False,
                         timeout=300)  # fmt: skip
    assert out.returncode == 1 and "Docker is not running" in out.stderr, out.stderr
    assert "==> host" in out.stdout
    assert [p.exists() for p in state] == before  # no setting, secret or update state written
    if "--rehearsal" in args:  # D-1091: a PoC box warns and goes on, to the vendor key here (kept refusal 1)
        assert "install: warning (PoC box, H-94): Docker is not running" in out.stderr
        assert out.stderr.splitlines()[-1].startswith("install: vendor public key missing"), out.stderr
    else:
        assert out.stderr.splitlines()[-1] == "install: Docker is not running (sudo systemctl start docker)"
    return out


def run_kek_passphrase_file(tmp: Path) -> None:
    """H-96: the hidden input writes the passphrase, exactly as typed, to a file only its owner reads (0600)."""
    span = next(c for c in commands() if c.startswith("sudo bash -c 'umask 077;"))
    inner = span.removeprefix("sudo bash -c ").strip("'").replace("/root/", f"{tmp}/")
    typed = "  synthetic h96 phrase \t "
    out = _run(["bash", "-c", inner], stdin=typed + "\n")
    f = tmp / "trialbox-kek.pass"
    assert out.returncode == 0 and f.read_text(encoding="utf-8") == typed + "\n", out.stderr
    assert f.stat().st_mode & 0o777 == 0o600


def run_install_kek_passphrase_file(tmp: Path) -> None:
    """H-96: install.sh takes --kek-passphrase-file (checked, read) and goes on to its host step."""
    f = tmp / "trialbox-kek.pass"
    f.write_text("synthetic-h96-phrase-for-a-test\n", encoding="utf-8")
    f.chmod(0o600)
    out = _install_to_the_host_step(tmp, "--mode", "stub", "--kek-passphrase-file", str(f), TB_KEK_BACKEND="passphrase")
    assert "synthetic-h96-phrase" not in out.stdout + out.stderr and f.exists()


def run_install_trial_boot(tmp: Path) -> None:
    _install_to_the_host_step(tmp, "--gpu", "rtxpro6000", "--rehearsal", TB_COMPOSE_OVERRIDE="",
                              TB_ACCEPT_UNMEASURED_GPU="1")  # fmt: skip


def run_first_command(tmp: Path) -> None:
    """D-996: the one command from the stick, as written, on a signed bundle of this checkout's host tree (a
    throwaway vendor key): openssl checks the bootstrap's signature, the bootstrap unpacks the tree into an empty
    /opt/trialbox stand-in and places the key, and that tree's installer runs to its host step."""
    from tools import sign_bundle

    priv, pub = sign_bundle.keygen(tmp / "vendor")
    usb, opt = tmp / "usb", tmp / "opt" / "trialbox"
    usb.mkdir()
    host = tmp / "trialbox-host.tar"
    packed = _run([sys.executable, "-m", "tools.host_tree", "pack", "--root", ".", "--out", str(host)])
    assert packed.returncode == 0, packed.stderr
    sign_bundle.build(priv, "2026.11-1", [("host", host, "trialbox-host.tar")], usb / "trialbox-2026.11-1.tar")
    shutil.copy(ROOT / "deploy/bootstrap.sh", usb / "trialbox-bootstrap.sh")
    sign_bundle.sign_file(priv, usb / "trialbox-bootstrap.sh")
    cmd = next(c for c in commands() if c.startswith("cd /media/usb && openssl"))
    cmd = (cmd.replace("/media/usb", str(usb)).replace("/root/vendor_ed25519.pub", str(pub))
           .replace("<version>", "2026.11-1").replace("/root/site/site.yaml", str(ANSWERS_C)).replace("sudo ", ""))  # fmt: skip
    bin_dir = tmp / "bin"
    _stand_in(bin_dir, "docker", "import sys\nsys.exit(1)\n")
    out = _run(["bash", "-c", cmd], TB_BOOTSTRAP_NO_ROOT="1", TB_BOOTSTRAP_ROOT=str(opt), TB_TIER_TEST_CARD=PRO6000,
               TB_TIER_TEST_ARCH="x86_64", PATH=f"{bin_dir}{os.pathsep}{_env()['PATH']}")  # fmt: skip
    assert "Signature Verified Successfully" in out.stdout, out.stderr
    assert (opt / "deploy/keys/vendor_ed25519.pub").read_bytes() == pub.read_bytes()
    assert f"running: {opt}/deploy/install.sh" in out.stdout and "tier large: rtxpro6000 profile" in out.stdout
    assert out.returncode == 1 and "Docker is not running" in out.stderr, out.stderr


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


def run_buildx_check(tmp: Path) -> None:
    """H-70: the build host's buildx check, with a stand-in ``docker``: a version passes, no plugin stops ``make``."""
    for has, rc in ((True, 0), (False, 2)):
        bin_dir = tmp / f"buildx-{has}"
        _stand_in(
            bin_dir, "docker", f"import sys\nsys.exit(0 if {has} and sys.argv[1:] == ['buildx', 'version'] else 1)\n"
        )
        out = _run(["make", "--no-print-directory", "buildx-check"], PATH=f"{bin_dir}{os.pathsep}/usr/bin:/bin")
        assert out.returncode == rc, out.stderr
        assert ("Docker's buildx plugin is missing" in out.stderr) is (not has)


def run_apply_update(tmp: Path) -> None:
    from tests.unit.test_host_tree import _bundle
    from tools.sign_bundle import keygen

    priv, pub = keygen(tmp / "vendor")
    bundle = _bundle(tmp, priv, "2026.11-1", 1, "one")
    out = _run(["sh", "tools/apply_update.sh", str(bundle), "--dry-run"], TB_VENDOR_PUBKEY=str(pub),
               TB_SECRETS_HOST_DIR=str(tmp / "no-secrets"))  # fmt: skip
    assert out.returncode == 0 and "verified:" in out.stdout and "nothing applied" in out.stdout, out.stderr


def run_wizard_questions(tmp: Path) -> None:
    from tb_common import site_country

    from tools.settings_wizard import QUESTIONS, _asked

    # OPS-060: Enter on tls_mode keeps the hospital certificate, the first choice. 10K-1: the country first (no
    # default); a Taiwan site's zone is then the default, and only the questions asked for it take a line
    replies = {"country": "tw", "tls_hostname": "trialbox.hospa.test", "tls_cert_file": "/etc/tb/site.crt",
               "tls_key_file": "/etc/tb/site.key"}  # fmt: skip
    tw = site_country.TABLE["tw"]
    stdin = "".join(
        replies.get(k, "") + "\n" for k, *_ in QUESTIONS if k == "country" or _asked(k, tw, {"data_source_type": "csv"})
    )
    out = _run([sys.executable, "-m", "tools.settings_wizard", "--out", str(tmp / "deploy/settings.yaml"),
                "--env-out", str(tmp / "deploy/.env")], stdin=stdin, TB_CTGOV_MODE="")  # fmt: skip
    assert out.returncode == 0, out.stderr
    env = (tmp / "deploy/.env").read_text(encoding="utf-8")
    assert "TB_TLS_HOSTNAME=trialbox.hospa.test" in env and "TB_TLS_MODE=hospital" in env
    assert "TB_TZ=Asia/Taipei" in env


def run_wizard_answers(tmp: Path) -> None:
    settings = tmp / "deploy/settings.yaml"
    out = _run([sys.executable, "-m", "tools.settings_wizard", "--answers", str(ANSWERS_C), "--out", str(settings),
                "--env-out", str(tmp / "deploy/.env")])  # fmt: skip
    assert out.returncode == 0, out.stderr
    check = _run([sys.executable, "-m", "tools.settings_wizard", "--check", str(settings)])
    assert check.returncode == 0 and check.stdout.startswith("OK:"), check.stderr


def run_mapping_check_in_the_image(tmp: Path) -> None:
    """The same check as the image runs it: its WORKDIR is /app, so the relative --mapping path is the mount. The
    image itself is the CI images job's; here the tool runs with the same arguments against the same layout."""
    df = (ROOT / "deploy/docker/python.Dockerfile").read_text(encoding="utf-8")
    assert "WORKDIR /app" in df and "COPY --chown=tb:tb tools /app/tools" in df
    app = tmp / "app"
    shutil.copytree(ROOT / "tools/rehearse_box/mapping", app / "deploy/site/mapping")
    out = _run([sys.executable, str(ROOT / "tools/mapping_check.py"), "--mapping",
                "deploy/site/mapping/tw_core/rehearsal_a.yaml", "--source", "csv", "--path",
                str(ROOT / "tests/fixtures/synthetic_patients/site-a"), "--json"], cwd=app)  # fmt: skip
    assert out.returncode == 0, out.stderr[-2000:]
    assert json.loads(out.stdout[out.stdout.index("{") :])["passed"]


def run_ingest_report(tmp: Path) -> None:
    """The report is in the lake's volume, which the adapter mounts at /data/lake, under the run's date."""
    import yaml

    class _Compose(yaml.SafeLoader):
        pass

    _Compose.add_multi_constructor("!", lambda loader, suffix, node: None)
    compose = yaml.load((ROOT / "deploy/docker-compose.yml").read_text(encoding="utf-8"), Loader=_Compose)
    assert "lake-data:/data/lake" in compose["services"]["adapter"]["volumes"]
    pipeline = (ROOT / "services/adapter/pipeline.py").read_text(encoding="utf-8")
    assert '(out_dir / "ingest_report.json")' in pipeline


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
    # TB_TEST_MEM_KIB: a 128 GB Spark's MemTotal (synthetic), so the --gb10 memory check never reads this machine's
    out = _run(["sh", "deploy/check_host.sh", "--gb10", "--env", str(env), "--secrets", str(tmp)],
               TB_TEST_MEM_KIB="124000000")  # fmt: skip
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


def run_memcaps_measure(tmp: Path) -> None:
    """The measurement at two small sizes into a temporary record (the shipped one is measured at 5,000 and
    10,000 patients, minutes of work): it gives a fixed part and a part per patient for both services."""
    out = _run([sys.executable, "-m", "tools.trialbox.memcaps", "--measure", "--sizes", "20", "40",
                "--out", str(tmp / "rec.json")])  # fmt: skip
    assert out.returncode == 0, out.stderr
    rec = json.loads((tmp / "rec.json").read_text(encoding="utf-8"))
    assert set(rec["services"]) == {"adapter", "lake"} and all(v["fixed_mb"] > 0 for v in rec["services"].values())


def run_memcaps_write(tmp: Path) -> None:
    """Sizing the caps again in a deploy folder whose .env names the hospital's size."""
    (tmp / "deploy").mkdir()
    (tmp / "deploy/.env").write_text("TB_ENV=DEV\nTB_SITE_PATIENTS=50000\n", encoding="utf-8")
    out = _run([sys.executable, "-m", "tools.trialbox.memcaps", "--env-file", "deploy/.env", "--write"], cwd=tmp)
    assert out.returncode == 0 and "50000 patients" in out.stdout, out.stderr
    env = (tmp / "deploy/.env").read_text(encoding="utf-8")
    assert "TB_MEM_ADAPTER=" in env and "TB_MEM_LAKE=" in env


def run_import_example(tmp: Path) -> None:
    """D-640: the example study an operator installs on a PRODUCTION box for a synthetic run. ``docker compose exec
    criteria-compiler sh -c '...'`` needs the running stack: the shell line inside it runs here as written, with
    the image's ``/app/rulesets`` as this checkout's folder, the zip in a temporary folder and a name for
    ``<who>``, on an empty working copy of a box that says PRODUCTION. Then the study is approved there and its
    tag names the operator."""
    cmd = next(c for c in commands() if "criteria_compiler.import_ruleset" in c)
    inner = re.fullmatch(r"docker compose exec criteria-compiler sh -c '(.+)'", cmd)
    assert inner is not None, cmd
    line = (
        inner.group(1).replace("/app/rulesets", str(ROOT / "rulesets")).replace("/tmp/GZQO.zip", str(tmp / "GZQO.zip"))
    )
    line = line.replace("<who>", "runbook-test")
    data = tmp / "data"
    box = {"TB_ENV": "PRODUCTION", "TB_DATA_DIR": str(data), "TB_RULESETS_DIR": str(data / "rulesets"),
           "TB_DOTENV": str(tmp / "no.env"), "TB_SETTINGS_FILE": str(ROOT / "deploy/settings.example.yaml")}  # fmt: skip
    out = _run(["sh", "-c", line], cwd=ROOT, stdin=None, **box)
    assert out.returncode == 0 and json.loads(out.stdout.strip().splitlines()[-1]) == {"installed": "GZQO/v1.0.0"}, (
        out.stdout + out.stderr
    )
    check = (
        "import sys; from pathlib import Path; from tb_common.ruleset import list_rulesets, load_approved; "
        "from criteria_compiler.repo import RulesetRepo; d = Path(sys.argv[1]); "
        "print(list_rulesets(d), load_approved(d, 'GZQO').version, RulesetRepo(d).tag_message('GZQO/v1.0.0'))"
    )
    seen = _run([sys.executable, "-c", check, str(data / "rulesets")], cwd=ROOT, stdin=None, **box)
    assert seen.returncode == 0, seen.stderr
    assert seen.stdout.strip() == "['GZQO'] 1.0.0 GZQO/v1.0.0 (offline update, synthetic-run:runbook-test)"


def run_holidays_import(tmp: Path) -> None:
    """10C-14: the yearly holiday update. Run as written, with a file in the Cabinet Office's layout made here (CP932,
    its header; nothing is fetched), its sha256 and the years filled in, and ``--out`` in the temporary folder so the
    committed list is not overwritten; a wrong sha256 is refused."""
    import hashlib

    cmd = next(c for c in commands() if c.startswith("python3 -m tools.holidays_import"))
    src = tmp / "syukujitsu.csv"
    src.write_bytes(
        "国民の祝日・休日月日,国民の祝日・休日名称\r\n2028/1/1,元日\r\n2028/1/10,成人の日\r\n".encode("cp932")
    )
    sha = hashlib.sha256(src.read_bytes()).hexdigest()
    line = cmd.replace("syukujitsu.csv", str(src)).replace("<hex>", sha).replace("<first>-<last>", "2028-2028")
    out_file = tmp / "holidays_jp.csv"
    got = _run([*line.replace("python3", sys.executable, 1).split(), "--out", str(out_file)])
    assert got.returncode == 0, got.stderr
    assert (
        out_file.read_text(encoding="utf-8") == "date,name,kind\n2028-01-01,元日,holiday\n2028-01-10,成人の日,holiday\n"
    )
    bad = _run([*line.replace("python3", sys.executable, 1).replace(sha, "0" * 64).split(), "--out", str(out_file)])
    assert bad.returncode == 2 and "not the one recorded" in bad.stderr


def run_preflight(tmp: Path) -> None:
    """10K-3: the live preflight as §1 writes it, on a box folder of its own (an empty .env): it runs, every line of
    the list is there, and a line that is not green has its Japanese action under it."""
    from tb_common import preflight as text

    deploy = tmp / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text("TB_ENV=PRODUCTION\nTB_LLM_MODE=stub\n", encoding="utf-8")
    cmd = next(c for c in commands() if "doctor --preflight" in c).split()
    out = _run([sys.executable if a == "python3" else a for a in cmd], cwd=tmp)
    assert out.returncode in (0, 1), out.stderr
    for cid in text.IDS:
        assert re.search(rf"^(PASS|WARN|FAIL)\s+{cid} ", out.stdout, re.M), (cid, out.stdout)
    assert f"-> {text.action('backup_share', 'ja')}" in out.stdout


# command (as §1 writes it, a regular expression) -> its runner
RUNNERS: list[tuple[str, Callable[[Path], None]]] = [
    (r"tools/serving_config\.py measured", run_serving_measured),
    (r"deploy/install\.sh --tier large --tier-check", run_tier_check),
    (
        r"TB_COMPOSE_OVERRIDE= TB_ACCEPT_UNMEASURED_GPU=1 deploy/install\.sh <bundle> --gpu <profile> --rehearsal",
        run_install_trial_boot,
    ),
    (r"python3 tools/serving_config\.py capture .*", run_capture),
    (r"python -m tools\.gpu_sizing", run_gpu_sizing),
    (r"cd /media/usb && openssl pkeyutl -verify .* -- --tier large --answers /root/site/site\.yaml", run_first_command),
    (r"--mode stub", run_install_stub),
    (r"sudo bash -c 'umask 077; IFS= read -rs p; .*", run_kek_passphrase_file),
    (
        r"-- --tier large --answers /root/site/site\.yaml --kek-passphrase-file /root/trialbox-kek\.pass",
        run_install_kek_passphrase_file,
    ),
    (r"tools/make_bundle\.sh", run_make_bundle),
    (r"make release-bundle", run_make_release_bundle),
    (r"tools/apply_update\.sh trialbox-<version>\.tar", run_apply_update),
    (r"make images", run_make_images),
    (r"make images-multiarch", run_make_images_multiarch),
    (r"docker buildx version", run_buildx_check),
    (r"python -m tools\.settings_wizard --out deploy/settings\.yaml --env-out deploy/\.env", run_wizard_questions),
    (r"--answers site\.yaml", run_wizard_answers),
    (
        r"python -m tools\.settings_wizard --answers tests/fixtures/onboarding/site_c_answers\.yaml .*",
        run_wizard_answers,
    ),
    (r"--check deploy/settings\.yaml", run_wizard_answers),
    (
        r"docker run --rm --network none .* trialbox-py:1\.0\.0 python tools/mapping_check\.py --mapping deploy/site/mapping/.*",
        run_mapping_check_in_the_image,
    ),
    (r"sudo python3 -m tools\.trialbox secrets init", run_secrets_init),
    (r"cd deploy && docker compose .* up -d --wait", run_compose_up),
    (r"--profile stub", run_compose_up),
    (r"deploy/network\.sh apply", run_network_apply),
    (r"docker compose --project-directory deploy exec adapter python -m adapter\.cli run", run_first_ingest),
    (
        r"docker compose --project-directory deploy exec adapter cat /data/lake/ndjson/<date>/ingest_report\.json",
        run_ingest_report,
    ),
    (r"deploy/check_host\.sh \[--gb10\]", run_check_host),
    (r"python3 -m tools\.trialbox doctor --preflight --env-file deploy/\.env --lang ja", run_preflight),
    (r"systemctl enable trialbox-.*", run_systemctl_enable),
    (r"python -m tools\.trialbox\.memcaps --measure", run_memcaps_measure),
    (r"python3 -m tools\.holidays_import syukujitsu\.csv --sha256 <hex> --years <first>-<last>", run_holidays_import),
    (r"python -m tools\.trialbox\.memcaps --env-file deploy/\.env --write", run_memcaps_write),
    (r"docker compose exec criteria-compiler sh -c 'cd /app/rulesets && python -m zipfile .*", run_import_example),
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
