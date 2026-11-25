"""H-77 (install-test F-22): the box records which KEK back end sealed its site keys, as the seal step ran it.

After an install nothing on the box said which back end sealed the keys: seal_keys.sh chose it (tpm, then
hardening.conf's KEK_BACKEND, then TB_KEK_BACKEND) and said it only in a log line, and under tpm the key tool's own
kek.json says ``file``. seal_keys.sh --record FILE now writes the word once its last step has passed (install.sh: deploy/site/kek-backend,
which the settings wizard's rewrite of deploy/.env leaves alone), and install.sh copies it into deploy/.env (TB_KEK_BACKEND, where the host check reads it); it never works the back
end out itself. A dry run, a TPM that cannot seal and a box whose KEK exists already write no record."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from tb_common.audit import AuditLog
from tb_common import kek as K

ROOT = Path(__file__).resolve().parents[2]
SEAL = ROOT / "deploy" / "hardening" / "seal_keys.sh"
INSTALL = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
PHRASE = "synthetic-h77-phrase-not-real"
SEAL_OK = 'case "$1" in has-tpm2) exit 0 ;; encrypt) cp "$4" "$5" ;; esac\n'
SEAL_FAILS = 'case "$1" in has-tpm2) exit 0 ;; encrypt) echo "TPM2 operation failed" >&2; exit 1 ;; esac\n'

pytestmark = pytest.mark.nodb


def _host(tmp: Path, creds: str | None = SEAL_OK, tpm: bool = True) -> dict[str, str]:
    """A host root of its own (the layout test_seal_keys_order.py uses): two plain keys, /dev/tpmrm0 when ``tpm``,
    a stand-in systemd-creds whose shell body is ``creds`` (None: not installed)."""
    hr = tmp / "host"
    (hr / "dev").mkdir(parents=True)
    if tpm:
        (hr / "dev" / "tpmrm0").write_text("")
    sec = tmp / "secrets"
    sec.mkdir()
    for name in ("site_hmac.key", "pid_map.key"):
        (sec / name).write_bytes(os.urandom(32))
    bindir = tmp / "bin"
    bindir.mkdir()
    if creds is not None:
        f = bindir / "systemd-creds"
        f.write_text("#!/bin/sh\n" + creds, encoding="utf-8")
        f.chmod(0o755)
    return {
        **{k: v for k, v in os.environ.items() if not k.startswith("TB_")},
        "PATH": f"{bindir}:{Path(sys.executable).parent}:/usr/bin:/bin",
        "TB_HOST_ROOT": str(hr),
        "TB_SYSTEMD": "0",
        "TB_KEK_FILE": str(tmp / "kek.runtime"),
        "TB_KEK_PASSPHRASE": PHRASE,
    }


def _conf(tmp: Path, backend: str) -> Path:
    shares = tmp / "media"
    shares.mkdir(exist_ok=True)
    conf = tmp / "hardening.conf"
    conf.write_text(f"KEK_BACKEND={backend}\nKEK_SHARES_OUT={shares}\n", encoding="utf-8")
    return conf


def _seal(tmp: Path, env: dict[str, str], conf: Path | None = None, *extra: str) -> subprocess.CompletedProcess[str]:
    args = ["sh", str(SEAL), "--secrets", str(tmp / "secrets"), "--conf", str(conf or tmp / "no-such.conf")]
    args += ["--record", str(_record(tmp)), *extra]
    return _run_seal(args, env, conf)


def _run_seal(args: list[str], env: dict[str, str], conf: Path | None = None) -> subprocess.CompletedProcess[str]:
    """H-96: the passphrase goes by stdin, never the environment, and only to the back end that takes one."""
    env, phrase = _apart(env)
    backend = env.get("TB_KEK_BACKEND") or (conf.read_text(encoding="utf-8") if conf and conf.is_file() else "")
    if "passphrase" in backend:
        return subprocess.run([*args, "--kek-passphrase-stdin"], input=phrase + "\n", capture_output=True, text=True,
                              env=env, check=False)  # fmt: skip
    return subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env, check=False)


def _apart(env: dict[str, str]) -> tuple[dict[str, str], str]:
    return {k: v for k, v in env.items() if k != "TB_KEK_PASSPHRASE"}, env.get("TB_KEK_PASSPHRASE", "")


def _record(tmp: Path) -> Path:
    return tmp / "deploy" / "site" / "kek-backend"


def _no_record(tmp: Path) -> None:
    assert not _record(tmp).exists()
    assert not _record(tmp).with_name("kek-backend.tmp").exists()


@pytest.mark.parametrize("backend", ["tpm", "shamir", "passphrase"])
def test_each_back_end_records_its_own_name(tmp_path: Path, backend: str) -> None:
    res = _seal(tmp_path, _host(tmp_path), _conf(tmp_path, backend))
    assert res.returncode == 0, res.stderr
    rec = _record(tmp_path)
    assert rec.read_text(encoding="utf-8") == backend + "\n"
    assert rec.stat().st_mode & 0o777 == 0o600  # no wider than the keys
    assert not rec.with_name("kek-backend.tmp").exists()
    assert sorted(p.name for p in rec.parent.iterdir()) == ["kek-backend"]
    assert f"the KEK back end is recorded: {backend}" in res.stdout


def test_a_tpm_that_cannot_seal_records_nothing_and_keeps_an_earlier_record(tmp_path: Path) -> None:
    env = _host(tmp_path, SEAL_FAILS)
    _record(tmp_path).parent.mkdir(parents=True)
    _record(tmp_path).write_text("shamir\n", encoding="utf-8")  # an earlier record, whatever it said
    res = _seal(tmp_path, {**env, "TB_KEK_BACKEND": "tpm"})
    assert res.returncode != 0 and "nothing was changed" in res.stderr
    assert not (tmp_path / "secrets" / K.META_FILE).exists()
    assert (tmp_path / "secrets" / "site_hmac.key").is_file()  # still plain
    assert _record(tmp_path).read_text(encoding="utf-8") == "shamir\n"
    assert not _record(tmp_path).with_name("kek-backend.tmp").exists()


@pytest.mark.parametrize("creds", ['case "$1" in has-tpm2) echo partial; exit 1 ;; esac\n', None])
def test_an_unusable_or_missing_tpm_records_nothing(tmp_path: Path, creds: str | None) -> None:
    res = _seal(tmp_path, _host(tmp_path, creds), _conf(tmp_path, "tpm"))
    assert res.returncode != 0
    _no_record(tmp_path)


def test_the_environment_overrides_hardening_conf_and_the_record_says_what_ran(tmp_path: Path) -> None:
    res = _seal(tmp_path, {**_host(tmp_path), "TB_KEK_BACKEND": "passphrase"}, _conf(tmp_path, "shamir"))
    assert res.returncode == 0, res.stderr
    meta = K.read_meta(tmp_path / "secrets")
    assert meta is not None and meta["backend"] == "passphrase"
    assert _record(tmp_path).read_text(encoding="utf-8") == "passphrase\n"
    assert not list((tmp_path / "media").iterdir())  # shamir never ran


def test_the_environment_overrides_the_other_way_too(tmp_path: Path) -> None:
    res = _seal(tmp_path, {**_host(tmp_path), "TB_KEK_BACKEND": "tpm"}, _conf(tmp_path, "passphrase"))
    assert res.returncode == 0, res.stderr
    assert _record(tmp_path).read_text(encoding="utf-8") == "tpm\n"
    assert (tmp_path / "host" / "etc" / "credstore.encrypted" / "trialbox-kek").is_file()


@pytest.mark.parametrize("backend", ["tpm", "shamir", "passphrase"])
def test_a_dry_run_records_nothing(tmp_path: Path, backend: str) -> None:
    res = _seal(tmp_path, _host(tmp_path), _conf(tmp_path, backend), "--dry-run")
    assert res.returncode == 0, res.stderr
    _no_record(tmp_path)
    assert not (tmp_path / "secrets" / K.META_FILE).exists()


def test_a_box_with_a_kek_already_records_the_back_end_kek_json_names(tmp_path: Path) -> None:
    """A re-run (the KEK exists, the keys are only wrapped): the record follows the seal in place as kek.json names it,
    whatever the environment or the conf ask now; tpm's kek.json says file (the integrator's ruling on the review of
    #1336: this test asserted no record before)."""
    env = _host(tmp_path)
    assert _seal(tmp_path, {**env, "TB_KEK_BACKEND": "passphrase"}).returncode == 0
    _record(tmp_path).unlink()
    res = _seal(tmp_path, {**env, "TB_KEK_BACKEND": "tpm"}, _conf(tmp_path, "shamir"))
    assert res.returncode == 0, res.stderr
    assert "the KEK exists" in res.stdout
    assert _record(tmp_path).read_text(encoding="utf-8") == "passphrase\n"
    _record(tmp_path).unlink()
    res = _seal(tmp_path, {**env, "TB_KEK_BACKEND": "tpm"}, None, "--dry-run")
    assert res.returncode == 0, res.stderr
    _no_record(tmp_path)  # a dry run on the re-run path writes none either


def test_a_tpm_box_re_run_records_tpm_from_kek_json_s_file(tmp_path: Path) -> None:
    env = _host(tmp_path)
    assert _seal(tmp_path, {**env, "TB_KEK_BACKEND": "tpm"}).returncode == 0
    assert K.read_meta(tmp_path / "secrets")["backend"] == "file"  # type: ignore[index]
    _record(tmp_path).write_text("passphrase\n", encoding="utf-8")  # stale
    res = _seal(tmp_path, {**env, "TB_KEK_BACKEND": "passphrase"})
    assert res.returncode == 0, res.stderr
    assert _record(tmp_path).read_text(encoding="utf-8") == "tpm\n"


def test_a_seal_whose_closing_check_failed_is_recorded_on_the_re_run(tmp_path: Path) -> None:
    """The review's second Medium: the keys were sealed, `tools.keys check` failed once; the clean re-run records."""
    env = {**_host(tmp_path), "TB_KEK_BACKEND": "passphrase"}
    fake = tmp_path / "bin" / "python3"
    fake.write_text(
        '#!/bin/sh\ncase " $* " in *" tools.keys check "*) echo "check failed" >&2; exit 1 ;; esac\n'
        f'exec "{sys.executable}" "$@"\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    assert _seal(tmp_path, env).returncode != 0
    _no_record(tmp_path)
    fake.unlink()
    res = _seal(tmp_path, env)
    assert res.returncode == 0, res.stderr
    assert _record(tmp_path).read_text(encoding="utf-8") == "passphrase\n"


# ---- install.sh: the seal block as it stands, run with the real seal_keys.sh in a folder laid out as an installer's
SEAL_BLOCK = INSTALL[
    INSTALL.index('HB_CONF="$ROOT/deploy/site/hardening.conf"') : INSTALL.index("# D-378: the services")
]


def _install(
    tmp: Path, env: dict[str, str], conf_text: str | None, profile: str = "standard", site: str = "VALIDATION"
) -> subprocess.CompletedProcess[str]:
    (tmp / "deploy" / "site").mkdir(parents=True, exist_ok=True)
    if not (tmp / "tools").exists():  # a second run (a re-install) keeps the folder as the first left it
        (tmp / "deploy" / "hardening").symlink_to(ROOT / "deploy" / "hardening")
        (tmp / "tools").symlink_to(ROOT / "tools")
        (tmp / "libs").symlink_to(ROOT / "libs")
        (tmp / "deploy" / ".env").write_text("TB_ENV=VALIDATION\n", encoding="utf-8")
    if conf_text is not None:
        (tmp / "deploy" / "site" / "hardening.conf").write_text(conf_text, encoding="utf-8")
    script = (
        "set -euo pipefail\n"
        f'ROOT="{tmp}"\ncd "$ROOT"\nHOST_PROFILE={profile}\nTB_ENV_SITE={site}\nIMAGE_PY=unused\n'
        'say() { echo "==> $*"; }\n'
        'die() { echo "install: $*" >&2; exit 1; }\n'
        "id() { echo 0; }\n"  # the block's root check; CI runs non-root
        'envset() { sed -i "/^$1=/d" deploy/.env && printf \'%s=%s\\n\' "$1" "$2" >> deploy/.env; }\n'
        # what install.sh has set before the block (H-94, H-96): the keys made, the passphrase read from stdin
        'KEYS_OK=1\nPP_KEEP=0\nKP_FILE=""\nstop_or_warn() { shift 2; die "$*"; }\n'
        'KP_VALUE=""; IFS= read -r KP_VALUE || :\n'
        f"{SEAL_BLOCK}\n"
    )
    env, phrase = _apart(env)
    backend = env.get("TB_KEK_BACKEND") or conf_text or ""
    return subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, check=False,
        input=phrase + "\n" if "passphrase" in backend else "",
        env={**env, "TB_SECRETS_HOST_DIR": str(tmp / "secrets")},
    )  # fmt: skip


def _env_value(tmp: Path) -> list[str]:
    lines = (tmp / "deploy" / ".env").read_text(encoding="utf-8").splitlines()
    return [ln.removeprefix("TB_KEK_BACKEND=") for ln in lines if ln.startswith("TB_KEK_BACKEND=")]


@pytest.mark.parametrize(("conf", "asked"), [("tpm", "passphrase"), ("passphrase", "tpm"), ("shamir", None)])
def test_install_copies_the_back_end_seal_keys_recorded(tmp_path: Path, conf: str, asked: str | None) -> None:
    """THE INVARIANT: the back end deploy/.env names is the one the sealing step ran, never one worked out again.
    hardening.conf says one, the environment another; the installer's line and deploy/.env equal seal_keys.sh's
    record, which equals what sealed the keys."""
    env = _host(tmp_path)
    if asked:
        env["TB_KEK_BACKEND"] = asked
    (tmp_path / "media").mkdir()
    res = _install(tmp_path, env, f"KEK_BACKEND={conf}\nKEK_SHARES_OUT={tmp_path / 'media'}\n")
    assert res.returncode == 0, res.stderr
    ran = asked or conf
    recorded = _record(tmp_path).read_text(encoding="utf-8").strip()
    assert recorded == ran
    assert _env_value(tmp_path) == [recorded]
    assert f"the KEK back end that sealed the keys: {recorded} " in res.stdout
    cred = tmp_path / "host" / "etc" / "credstore.encrypted" / "trialbox-kek"
    meta = K.read_meta(tmp_path / "secrets")
    assert meta is not None
    assert cred.is_file() == (ran == "tpm")  # what sealed the keys is what the record says
    assert meta["backend"] == ("file" if ran == "tpm" else ran)


def test_a_rotation_moves_the_record_and_deploy_env(tmp_path: Path) -> None:
    """The review's first Medium: after `tools.keys rotate-kek --backend shamir` the next install records shamir and
    deploy/.env follows (it copied the stale word back before)."""
    env = {**_host(tmp_path), "TB_KEK_BACKEND": "passphrase"}
    assert _install(tmp_path, env, None).returncode == 0
    assert _env_value(tmp_path) == ["passphrase"]
    (tmp_path / "media").mkdir()
    AuditLog(tmp_path / "audit").append("test.start", actor="test")  # a rotation is an audit event (H-133)
    kek = tmp_path / "host" / "run" / "trialbox" / "kek"  # where the seal left it (H-118)
    rot = subprocess.run(
        [sys.executable, "-m", "tools.keys", "rotate-kek", "--backend", "shamir", "--shares-out", str(tmp_path / "media"),
         "--secrets", str(tmp_path / "secrets"), "--out", str(kek),
         "--audit-dir", str(tmp_path / "audit")],
        capture_output=True, text=True, check=False, cwd=ROOT, env={**_apart(env)[0], "TB_ENV": "VALIDATION", "TB_KEK_FILE": str(kek), "PYTHONPATH": f"{ROOT / 'libs'}:{ROOT}"},
    )  # fmt: skip
    assert rot.returncode == 0, rot.stderr
    assert K.read_meta(tmp_path / "secrets")["backend"] == "shamir"  # type: ignore[index]
    res = _install(tmp_path, env, None)  # the installer's environment still says passphrase
    assert res.returncode == 0, res.stderr
    assert _record(tmp_path).read_text(encoding="utf-8") == "shamir\n"
    assert _env_value(tmp_path) == ["shamir"]
    assert "the KEK back end that sealed the keys: shamir " in res.stdout


def test_install_on_a_poc_host_without_a_tpm_records_nothing(tmp_path: Path) -> None:
    res = _install(tmp_path, _host(tmp_path, None, tpm=False), None, profile="poc", site="TEST")
    assert res.returncode == 0, res.stderr
    assert "not sealed (host profile poc" in res.stdout
    assert _env_value(tmp_path) == []
    _no_record(tmp_path)


def test_install_fails_and_records_nothing_when_the_tpm_cannot_seal(tmp_path: Path) -> None:
    res = _install(tmp_path, _host(tmp_path, SEAL_FAILS), "KEK_BACKEND=tpm\n")
    assert res.returncode != 0 and "the site keys are not sealed" in res.stderr
    assert _env_value(tmp_path) == []
    _no_record(tmp_path)


def test_install_does_not_work_the_back_end_out_itself() -> None:
    """Only seal_keys.sh decides: after the seal the installer reads the record and nothing else."""
    after = SEAL_BLOCK[SEAL_BLOCK.index("sh deploy/hardening/seal_keys.sh") :]
    after = after[after.index("\n", after.index("|| stop_or_warn seal-keys")) :]  # the lines after the seal's own refusal
    assert "< deploy/site/kek-backend)" in after and 'echo "TB_KEK_BACKEND=$KEK_USED" >> deploy/.env' in after
    assert "--record deploy/site/kek-backend" in SEAL_BLOCK
    for blk in (after, _copy_block(BOX_INSTALL)):
        for guess in (
            "has-tpm2",
            "hb_load_conf",
            "^KEK_BACKEND",
            "${TB_KEK_BACKEND",
            "$HB_CONF",
            "hardening.conf",
            "/dev/tpm",
        ):
            assert guess not in blk, guess


@pytest.mark.parametrize("backend", ["passphrase", "shamir"])
def test_no_secret_in_the_record_or_any_output(tmp_path: Path, backend: str) -> None:
    env = _host(tmp_path)
    (tmp_path / "media").mkdir()
    res = _install(tmp_path, env, f"KEK_BACKEND={backend}\nKEK_SHARES_OUT={tmp_path / 'media'}\n")
    assert res.returncode == 0, res.stderr
    rec = _record(tmp_path).read_text(encoding="utf-8")
    assert rec == backend + "\n"  # the name only: no passphrase, no share, no path
    seen = rec + res.stdout + res.stderr + (tmp_path / "deploy" / ".env").read_text(encoding="utf-8")
    assert PHRASE not in seen
    for share in (tmp_path / "media").glob("share-*.txt"):
        body = share.read_text(encoding="utf-8").strip()
        assert body and body not in seen


@pytest.mark.parametrize(("backend", "step"), [("tpm", "init"), ("passphrase", "check"), ("tpm", "check")])
def test_a_later_step_that_fails_records_nothing(tmp_path: Path, backend: str, step: str) -> None:
    """The record is the seal's last word: a wrap or the closing `tools.keys check` that fails leaves none."""
    env = _host(tmp_path)
    fake = tmp_path / "bin" / "python3"  # the host's python3, but `tools.keys <step>` fails
    fake.write_text(
        f'#!/bin/sh\ncase " $* " in *" tools.keys {step} "*) echo "{step} failed" >&2; exit 1 ;; esac\n'
        f'exec "{sys.executable}" "$@"\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    _record(tmp_path).parent.mkdir(parents=True)
    _record(tmp_path).write_text("shamir\n", encoding="utf-8")
    res = _seal(tmp_path, {**env, "TB_KEK_BACKEND": backend})
    assert res.returncode != 0
    assert _record(tmp_path).read_text(encoding="utf-8") == "shamir\n"  # the earlier record, untouched
    assert not _record(tmp_path).with_name("kek-backend.tmp").exists()


def _copy(
    tmp: Path, record: str | None, env_text: str | None, *, link: bool = False, runs: int = 1
) -> subprocess.CompletedProcess[str]:
    """install.sh's copy block alone (box-install.sh holds the same), on a planted record and deploy/.env."""
    (tmp / "deploy" / "site").mkdir(parents=True, exist_ok=True)
    if record is not None:
        _record(tmp).write_text(record, encoding="utf-8")
    if env_text is not None:
        target = tmp / "real.env" if link else tmp / "deploy" / ".env"
        target.write_text(env_text, encoding="utf-8")
        if link:
            (tmp / "deploy" / ".env").symlink_to(target)
    script = (
        f'set -euo pipefail\ncd "{tmp}"\ndie() {{ echo "install: $*" >&2; exit 1; }}\n' + _copy_block(INSTALL) * runs
    )
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)


@pytest.mark.parametrize("record", [None, "tpm; echo x\n", "windows\n", ""])
def test_the_copy_leaves_deploy_env_alone_without_a_back_end_name(tmp_path: Path, record: str | None) -> None:
    res = _copy(tmp_path, record, "TB_ENV=TEST\nTB_KEK_BACKEND=shamir\n")
    assert res.returncode == 0, res.stderr
    assert (tmp_path / "deploy" / ".env").read_text(encoding="utf-8") == "TB_ENV=TEST\nTB_KEK_BACKEND=shamir\n"
    assert "no record of the KEK back end" in res.stderr and "sealed the keys" not in res.stdout


def test_the_copy_twice_leaves_one_line_and_the_others_as_they_were(tmp_path: Path) -> None:
    env_text = "TB_ENV=TEST\nTB_KEK_BACKEND=tpm\nTB_TZ=UTC\nexport TB_KEK_BACKEND=shamir\n  TB_KEK_BACKEND=tpm\n"
    res = _copy(tmp_path, "passphrase\n", env_text, runs=2)
    assert res.returncode == 0, res.stderr
    lines = (tmp_path / "deploy" / ".env").read_text(encoding="utf-8").splitlines()
    assert lines == ["TB_ENV=TEST", "TB_TZ=UTC", "TB_KEK_BACKEND=passphrase"]


def test_the_copy_does_not_join_a_last_line_without_its_newline(tmp_path: Path) -> None:
    res = _copy(tmp_path, "tpm\n", "TB_ENV=TEST\nTB_TZ=UTC")
    assert res.returncode == 0, res.stderr
    lines = (tmp_path / "deploy" / ".env").read_text(encoding="utf-8").splitlines()
    assert lines == ["TB_ENV=TEST", "TB_TZ=UTC", "TB_KEK_BACKEND=tpm"]


def test_the_copy_stops_on_a_missing_deploy_env(tmp_path: Path) -> None:
    res = _copy(tmp_path, "tpm\n", None)
    assert res.returncode != 0
    assert "deploy/.env is missing or a link" in res.stderr and "sealed the keys" not in res.stdout
    assert not (tmp_path / "deploy" / ".env").exists()


def test_the_copy_stops_on_a_linked_deploy_env(tmp_path: Path) -> None:
    res = _copy(tmp_path, "tpm\n", "TB_ENV=TEST\nTB_KEK_BACKEND=shamir\n", link=True)
    assert res.returncode != 0
    assert "deploy/.env is missing or a link" in res.stderr and "sealed the keys" not in res.stdout
    assert (tmp_path / "deploy" / ".env").is_symlink()  # not replaced by a file
    assert (tmp_path / "real.env").read_text(encoding="utf-8") == "TB_ENV=TEST\nTB_KEK_BACKEND=shamir\n"


def test_the_record_is_written_whole_then_renamed() -> None:
    """A reader never sees half a record: written to kek-backend.tmp, then renamed over kek-backend."""
    seal = SEAL.read_text(encoding="utf-8")
    tail = seal[seal.index("record() {") : seal.index("\n}\n", seal.index("record() {"))]
    assert '> "$REC.tmp"' in tail and 'mv -f "$REC.tmp" "$REC"' in tail
    assert '> "$REC"' not in tail and '>> "$REC' not in tail


def test_without_record_nothing_is_written(tmp_path: Path) -> None:
    """The callers of before (box-install.sh's deferred seal, the rehearsal) pass no --record: nothing new appears."""
    env = {**_host(tmp_path), "TB_KEK_BACKEND": "passphrase"}
    before = {p.name for p in tmp_path.iterdir()}
    res = _run_seal(["sh", str(SEAL), "--secrets", str(tmp_path / "secrets"), "--conf", str(tmp_path / "no-such.conf")],
                    env)  # fmt: skip
    assert res.returncode == 0, res.stderr
    assert {p.name for p in tmp_path.iterdir()} == before
    assert "kek-backend" not in {p.name for p in (tmp_path / "secrets").iterdir()}


# ---- box-install.sh: the deferred seal (TB_BOX_DEFER_SEAL=1; the owner's passphrase at the apply step), as it stands
BOX_INSTALL = (ROOT / "deploy" / "box-install.sh").read_text(encoding="utf-8")
BOX_BLOCK = BOX_INSTALL[
    BOX_INSTALL.index(
        "if [ -f \"$ROOT/deploy/site/hardening.conf\" ] && grep -q '^KEK_BACKEND=passphrase'"
    ) : BOX_INSTALL.index("TZ_NEW=")
]
COPY_START = "  # H-77 (F-22): the back end is the one seal_keys.sh recorded"


def _copy_block(text: str) -> str:
    start = text.index(COPY_START)
    return text[start : text.index("  esac\n", start) + len("  esac\n")]


def _box(tmp: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """The box's apply-step seal: hardening.conf says passphrase (the plan's, D-898), the owner's answers hold it."""
    for d in ("hardening",):
        (tmp / "deploy").mkdir(exist_ok=True)
        (tmp / "deploy" / d).symlink_to(ROOT / "deploy" / d)
    (tmp / "deploy" / "site").mkdir()
    (tmp / "tools").symlink_to(ROOT / "tools")
    (tmp / "libs").symlink_to(ROOT / "libs")
    (tmp / "deploy" / ".env").write_text("TB_ENV=PRODUCTION\n", encoding="utf-8")
    (tmp / "deploy" / "site" / "hardening.conf").write_text("KEK_BACKEND=passphrase\n", encoding="utf-8")
    script = (
        "set -euo pipefail\n"
        f'ROOT="{tmp}"\ncd "$ROOT"\nFR=unused\nIMAGE_PY=unused\n'
        'die() { echo "box-install: $*" >&2; exit 1; }\n'
        "id() { echo 0; }\n"  # the block's root check; CI runs non-root
        f'json_get() {{ echo "{PHRASE}"; }}\n'  # the owner's answers: the passphrase the owner set
        f"{BOX_BLOCK}\n"
    )
    full = {k: v for k, v in env.items() if k != "TB_KEK_PASSPHRASE"}  # only from the owner's answers
    return subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, check=False,
        env={**full, "TB_SECRETS_HOST_DIR": str(tmp / "secrets")},
    )  # fmt: skip


@pytest.mark.parametrize("asked", [None, "tpm"])
def test_the_box_deferred_seal_copies_the_back_end_seal_keys_recorded(tmp_path: Path, asked: str | None) -> None:
    """The invariant on box-install.sh's door: hardening.conf says passphrase, the environment may say tpm; the line,
    deploy/.env and the record name what sealed the keys, and no passphrase shows anywhere."""
    env = _host(tmp_path)
    if asked:
        env["TB_KEK_BACKEND"] = asked
    res = _box(tmp_path, env)
    assert res.returncode == 0, res.stderr
    ran = asked or "passphrase"
    recorded = _record(tmp_path).read_text(encoding="utf-8").strip()
    assert recorded == ran and _env_value(tmp_path) == [ran]
    assert f"the KEK back end that sealed the keys: {ran} " in res.stdout
    meta = K.read_meta(tmp_path / "secrets")
    assert meta is not None and meta["backend"] == ("file" if ran == "tpm" else ran)
    cred = tmp_path / "host" / "etc" / "credstore.encrypted" / "trialbox-kek"
    assert cred.is_file() == (ran == "tpm")
    seen = res.stdout + res.stderr + (tmp_path / "deploy" / ".env").read_text(encoding="utf-8") + recorded
    assert PHRASE not in seen


def test_a_failed_deferred_seal_records_nothing(tmp_path: Path) -> None:
    res = _box(tmp_path, {**_host(tmp_path, SEAL_FAILS), "TB_KEK_BACKEND": "tpm"})
    assert res.returncode != 0 and "the site keys could not be sealed" in res.stderr
    _no_record(tmp_path)
    assert _env_value(tmp_path) == []
    assert not (tmp_path / "secrets" / K.META_FILE).exists()


def test_the_two_installers_copy_the_record_with_one_block() -> None:
    """install.sh and box-install.sh share no sourced file: the copy is the same block in both, byte for byte, and
    each passes the same record file to seal_keys.sh."""
    assert _copy_block(INSTALL) == _copy_block(BOX_INSTALL)
    assert _copy_block(BOX_INSTALL) in BOX_BLOCK
    assert "--record deploy/site/kek-backend" in SEAL_BLOCK and "--record deploy/site/kek-backend" in BOX_BLOCK
