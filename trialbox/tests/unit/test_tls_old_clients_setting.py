"""H-48 (finding H10G48-02, D-1328 amended 2026-11-19): the one setting that relaxes the box's 443 for a hospital's
old client, ``TB_TLS_OLD_CLIENTS`` (``off`` by default, or ``cbc``).

Off, the shipped Caddyfile serves what it served before and the per-release TLS check passes. On, the check reports
the named exception (exit 3), never a pass; on with any other weakening it fails (exit 1); a value that is not
documented is refused (exit 2). The installer audits the switch and doctor shows a line while it is on. No Caddy and
no scan run here: the results are the hand-written testssl.sh results of ``tests/fixtures/tls/``.
"""

from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tools import tls_policy
from tools.trialbox import doctor

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures" / "tls"
CADDY = (ROOT / "deploy" / "identity" / "Caddyfile").read_text(encoding="utf-8")
INSTALL = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
COMPOSE = (ROOT / "deploy" / "docker-compose.identity.yml").read_text(encoding="utf-8")

pytestmark = pytest.mark.nodb

CBC_ROWS = [
    ("cipher-tls1_2_xc009", "TLSv1.2   xc009   ECDHE-ECDSA-AES128-SHA   ECDH 253   AES   128   "
     "TLS_ECDHE_ECDSA_WITH_AES_128_CBC_SHA"),
    ("cipher-tls1_2_xc00a", "TLSv1.2   xc00a   ECDHE-ECDSA-AES256-SHA   ECDH 253   AES   256   "
     "TLS_ECDHE_ECDSA_WITH_AES_256_CBC_SHA"),
]  # fmt: skip


@pytest.fixture(scope="module")
def policy() -> dict[str, Any]:
    return tls_policy.load_policy()


def _box() -> list[dict[str, Any]]:
    return list(json.loads((FIX / "box-pass.json").read_text(encoding="utf-8")))


def _set(rows: list[dict[str, Any]], fid: str, finding: str, severity: str = "INFO") -> list[dict[str, Any]]:
    rows = copy.deepcopy(rows)
    hit = [r for r in rows if r["id"] == fid]
    for r in hit:
        r["finding"], r["severity"] = finding, severity
    if not hit:
        rows.append({"id": fid, "ip": "box.test/192.0.2.10", "port": "443", "severity": severity, "cve": "",
                     "cwe": "", "finding": finding})  # fmt: skip
    return rows


def _with_cbc() -> list[dict[str, Any]]:
    """What an old client's scan of the relaxed box shows: the obsoleted (CBC) category and two ECDHE CBC suites."""
    rows = _set(_box(), "cipherlist_OBSOLETED", "offered", "LOW")
    for fid, finding in CBC_ROWS:
        rows = _set(rows, fid, finding)
    return rows


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "tools.tls_policy", *args], cwd=ROOT, capture_output=True,
                          text=True, timeout=60, check=False)  # fmt: skip


def _snippet(name: str) -> str:
    m = re.search(rf"^\({re.escape(name)}\) \{{\n(.*?)^\}}", CADDY, re.S | re.M)
    assert m, name
    return m.group(1)


# ------------------------------------------------------------------------------------------------ off: as before
def test_off_serves_what_the_box_served_before(policy: dict[str, Any]) -> None:
    # the snippets for off are the ones shipped before H-48: Caddy's own suites (AEAD with ECDHE), no ciphers line
    assert _snippet("suites_internal_off").strip() == "tls internal"
    assert "ciphers" not in _snippet("suites_hospital_off") and "protocols tls1.2 tls1.3" in _snippet(
        "suites_hospital_off"
    )
    assert "\timport tls_{$TB_TLS_MODE:internal}\n" in CADDY  # the edge's import as before H-48
    for mode in ("internal", "hospital"):
        assert _snippet(f"tls_{mode}").strip() == f"import suites_{mode}_{{$TB_TLS_OLD_CLIENTS:off}}"
    assert 'TB_TLS_OLD_CLIENTS: "${TB_TLS_OLD_CLIENTS:-off}"' in COMPOSE  # unset in deploy/.env: off
    assert tls_policy.caddyfile_problems(CADDY, policy) == []
    p = _cli("caddyfile")
    assert (p.returncode, p.stdout.strip()) == (0, "PASS"), p.stdout + p.stderr
    p = _cli("judge", "--target", "box", "--old-clients", "off", str(FIX / "box-pass.json"))
    assert (p.returncode, p.stdout.strip()) == (0, "PASS"), p.stdout + p.stderr


def test_off_still_fails_a_cbc_scan(policy: dict[str, Any], tmp_path: Path) -> None:
    problems = tls_policy.judge(_with_cbc(), "box", policy)
    assert any(p.startswith("cipherlist_OBSOLETED: offered") for p in problems), problems
    assert any(p.startswith("cipher-tls1_2_xc009:") for p in problems), problems
    f = tmp_path / "tls.json"
    f.write_text(json.dumps(_with_cbc()), encoding="utf-8")
    assert _cli("judge", "--target", "box", str(f)).returncode == 1


# ------------------------------------------------------------------------------------- on: the named exception
def test_on_is_the_named_exception_not_a_pass(policy: dict[str, Any], tmp_path: Path) -> None:
    assert tls_policy.caddyfile_problems(CADDY, policy, "cbc") == []
    assert tls_policy.judge(_with_cbc(), "box", policy, "cbc") == []
    want = "EXCEPTION relaxed by setting TB_TLS_OLD_CLIENTS=cbc: "
    p = _cli("caddyfile", "--old-clients", "cbc")
    assert p.returncode == tls_policy.EXIT_EXCEPTION == 3 and p.stdout.startswith(want), p.stdout + p.stderr
    assert "PASS" not in p.stdout
    f = tmp_path / "tls.json"
    f.write_text(json.dumps(_with_cbc()), encoding="utf-8")
    for result in (f, FIX / "box-pass.json"):  # the setting is on: an exception even when no old suite was seen
        p = _cli("judge", "--target", "box", "--old-clients", "cbc", str(result))
        assert p.returncode == 3 and p.stdout.startswith(want), p.stdout + p.stderr


def test_the_relaxed_snippets_add_exactly_the_policys_four_cbc_suites(policy: dict[str, Any]) -> None:
    level = policy["relaxation"]["levels"]["cbc"]
    assert policy["relaxation"]["key"] == "TB_TLS_OLD_CLIENTS" and policy["relaxation"]["default"] == "off"
    assert list(policy["relaxation"]["levels"]) == ["cbc"] and level["targets"] == ["box"]
    iana = {c for c in level["ciphers_allowed"] if c.startswith("TLS_")}
    assert len(iana) == 4 and all(re.fullmatch(r"TLS_ECDHE_(ECDSA|RSA)_WITH_AES_(128|256)_CBC_SHA", c) for c in iana)
    for name in ("suites_internal_cbc", "suites_hospital_cbc"):
        body = _snippet(name)
        assert "protocols tls1.2 tls1.3" in body, name
        suites = set(next(ln for ln in body.splitlines() if "ciphers" in ln).split()[1:])
        assert suites - iana == {s for s in suites if "GCM" in s or "CHACHA20" in s}, name  # the rest: AEAD
        assert iana <= suites, name
        assert all("ECDHE" in s for s in suites), name


# ------------------------------------------------------------------------------ on plus any other weakening: fail
WEAKER_SCANS = {
    "static rsa cbc": ("cipher-tls1_2_x2f", "TLSv1.2   x2f   AES128-SHA   RSA   AES   128   TLS_RSA_WITH_AES_128_CBC_SHA",
                       "INFO", "cipher-tls1_2_x2f:"),
    "ecdhe cbc sha256": ("cipher-tls1_2_xc027", "TLSv1.2   xc027   ECDHE-RSA-AES128-SHA256   ECDH 253   AES   128   "
                         "TLS_ECDHE_RSA_WITH_AES_128_CBC_SHA256", "INFO", "cipher-tls1_2_xc027:"),
    "tls 1.0": ("TLS1", "offered (deprecated)", "LOW", "TLS1:"),
    "tls 1.1": ("TLS1_1", "offered (deprecated)", "LOW", "TLS1_1:"),
    "3des": ("cipherlist_3DES_IDEA", "offered", "MEDIUM", "cipherlist_3DES_IDEA:"),
    "export": ("cipherlist_EXPORT", "offered", "HIGH", "cipherlist_EXPORT:"),
}  # fmt: skip


@pytest.mark.parametrize("name", sorted(WEAKER_SCANS))
def test_on_plus_another_weakening_of_the_scan_fails(name: str, policy: dict[str, Any], tmp_path: Path) -> None:
    fid, finding, severity, expect = WEAKER_SCANS[name]
    rows = _set(_with_cbc(), fid, finding, severity)
    problems = tls_policy.judge(rows, "box", policy, "cbc")
    assert any(p.startswith(expect) for p in problems), problems
    f = tmp_path / "tls.json"
    f.write_text(json.dumps(rows), encoding="utf-8")
    p = _cli("judge", "--target", "box", "--old-clients", "cbc", str(f))
    assert p.returncode == 1 and "EXCEPTION" not in p.stdout, p.stdout + p.stderr


def _cbc_swap(old: str, new: str) -> str:
    """The Caddyfile with ``old`` replaced by ``new`` inside the internal CA's relaxed snippet only."""
    body = _snippet("suites_internal_cbc")
    assert old in body, old
    return CADDY.replace(body, body.replace(old, new, 1), 1)


WEAKER_CADDY = {
    "tls 1.1 in the relaxed snippet": (_cbc_swap("protocols tls1.2 tls1.3", "protocols tls1.1 tls1.3"), "protocols"),
    "static rsa in the relaxed snippet": (
        _cbc_swap("TLS_ECDHE_RSA_WITH_AES_256_CBC_SHA", "TLS_ECDHE_RSA_WITH_AES_256_CBC_SHA TLS_RSA_WITH_AES_128_CBC_SHA"),
        "ciphers",
    ),
    "3des in the relaxed snippet": (
        _cbc_swap("TLS_ECDHE_RSA_WITH_AES_256_CBC_SHA",
                  "TLS_ECDHE_RSA_WITH_AES_256_CBC_SHA TLS_ECDHE_RSA_WITH_3DES_EDE_CBC_SHA"),
        "ciphers",
    ),
    "hsts dropped": (CADDY.replace('\t\tStrict-Transport-Security "max-age=31536000"\n', "", 1), "site"),
    "no relaxed snippet": (CADDY.replace("(suites_internal_cbc) {", "(suites_internal_old) {", 1).replace(
        "(suites_hospital_cbc) {", "(suites_hospital_old) {", 1), "import"),
}  # fmt: skip


@pytest.mark.parametrize("name", sorted(WEAKER_CADDY))
def test_on_plus_another_weakening_of_the_caddyfile_fails(name: str, policy: dict[str, Any], tmp_path: Path) -> None:
    text, expect = WEAKER_CADDY[name]
    problems = tls_policy.caddyfile_problems(text, policy, "cbc")
    assert any(p.startswith(expect) for p in problems), problems
    f = tmp_path / "Caddyfile"
    f.write_text(text, encoding="utf-8")
    p = _cli("caddyfile", "--old-clients", "cbc", str(f))
    assert p.returncode == 1 and "EXCEPTION" not in p.stdout, p.stdout + p.stderr


def test_the_cbc_suites_outside_the_setting_still_fail(policy: dict[str, Any]) -> None:
    # a hand edit that puts the relaxed suites in the snippet served with off is the weakening it always was
    body = _snippet("suites_hospital_off")
    cbc_line = next(ln for ln in _snippet("suites_hospital_cbc").splitlines() if "ciphers" in ln)
    text = CADDY.replace(body, body.replace("protocols tls1.2 tls1.3", "protocols tls1.2 tls1.3\n" + cbc_line), 1)
    assert any(p.startswith("ciphers:") for p in tls_policy.caddyfile_problems(text, policy))


# ------------------------------------------------------------------------------------- another value: refused
@pytest.mark.parametrize("value", ["yes", "on", "1", "CBC", "all", "tls1.0", "off cbc"])
def test_a_value_that_is_not_documented_is_refused(value: str, policy: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="refused"):
        tls_policy.relaxation(policy, value)
    for args in (("caddyfile",), ("judge", "--target", "box", str(FIX / "box-pass.json"))):
        p = _cli(*args[:1], "--old-clients", value, *args[1:])
        assert p.returncode == 2 and "refused" in p.stderr and "PASS" not in p.stdout, p.stdout + p.stderr


def test_the_link_is_never_relaxed(policy: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="link"):
        tls_policy.judge(_box(), "link", policy, "cbc")
    p = _cli("judge", "--target", "link", "--old-clients", "cbc", str(FIX / "link-pass.json"))
    assert p.returncode == 2 and "refused" in p.stderr, p.stdout + p.stderr


# --------------------------------------------------------------------------------------- doctor and the installer
def _doctor(value: str | None, tmp_path: Path, audited: str | None = None) -> list[doctor.Check]:
    env = {"TB_ENV": "DEV", "TB_TOPOLOGY": "A", "TB_TZ": "Asia/Taipei"}
    if value is not None:
        env["TB_TLS_OLD_CLIENTS"] = value
    site = tmp_path / "deploy" / "site"
    site.mkdir(parents=True, exist_ok=True)
    mark = site / tls_policy.OLD_CLIENTS_AUDITED
    mark.unlink(missing_ok=True)
    if audited is not None:
        mark.write_text(audited + "\n", encoding="utf-8")
    inp = doctor.DoctorInputs(env=env, host_tz="Asia/Taipei", deploy=tmp_path / "deploy")
    return doctor.tls_old_clients(inp, [])


def test_doctor_shows_a_line_only_while_it_is_on(tmp_path: Path) -> None:
    assert _doctor(None, tmp_path) == [] and _doctor("off", tmp_path) == [] and _doctor("off", tmp_path, "off") == []
    (line,) = _doctor("cbc", tmp_path, "cbc")
    assert (line.name, line.status) == ("tls_old_clients", "WARN") and "TB_TLS_OLD_CLIENTS=cbc" in line.detail
    (line,) = _doctor('"cbc"', tmp_path, "cbc")  # quoted in deploy/.env: compose reads cbc too
    assert line.status == "WARN"
    (line,) = _doctor("yes", tmp_path)
    assert (line.name, line.status) == ("tls_old_clients", "FAIL")
    assert "tls_old_clients(inp, host_profile(inp, out))" in Path(doctor.__file__).read_text(encoding="utf-8")


@pytest.mark.parametrize(("value", "audited"), [("cbc", None), ("cbc", "off"), ("off", "cbc"), (None, "cbc")])
def test_doctor_fails_a_switch_that_was_not_audited(value: str | None, audited: str | None, tmp_path: Path) -> None:
    # a plain `docker compose up`, an exported variable or a restore: Caddy serves a value the chain does not show
    (line,) = _doctor(value, tmp_path, audited)
    assert (line.name, line.status) == ("tls_old_clients", "FAIL") and "deploy/install.sh" in line.detail


def test_the_effective_value_is_the_one_compose_reads(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    state = tls_policy.old_clients_state
    assert state({}, site, {}) == ("off", "off", "")
    assert state({"TB_TLS_OLD_CLIENTS": "'cbc'"}, site, {})[0] == "cbc"
    # an exported variable wins over deploy/.env, as compose's own precedence; exported empty is off
    assert state({"TB_TLS_OLD_CLIENTS": "off"}, site, {"TB_TLS_OLD_CLIENTS": "cbc"})[0] == "cbc"
    assert state({"TB_TLS_OLD_CLIENTS": "cbc"}, site, {"TB_TLS_OLD_CLIENTS": ""})[0] == "off"
    assert state({"TB_TLS_OLD_CLIENTS": "cbc"}, site, {})[2]  # on, never audited
    (site / tls_policy.OLD_CLIENTS_AUDITED).write_text("cbc\n", encoding="utf-8")
    assert state({"TB_TLS_OLD_CLIENTS": "cbc"}, site, {}) == ("cbc", "cbc", "")


class _Box:
    name = "compose"

    def __init__(self, deploy: Path, env: dict[str, str]) -> None:
        self.deploy, self.env = deploy, env


def test_an_update_refuses_a_setting_that_was_not_audited(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tools.trialbox.update import Updater, UpdateRefused

    monkeypatch.delenv("TB_TLS_OLD_CLIENTS", raising=False)
    (tmp_path / "site").mkdir()
    up = Updater(_Box(tmp_path, {"TB_TLS_OLD_CLIENTS": "cbc"}), tmp_path / "updates")  # type: ignore[arg-type]
    with pytest.raises(UpdateRefused, match="deploy/install.sh"):
        up._tls_old_clients()
    with pytest.raises(UpdateRefused, match="not off or cbc"):
        Updater(_Box(tmp_path, {"TB_TLS_OLD_CLIENTS": "yes"}), tmp_path)._tls_old_clients()  # type: ignore[arg-type]
    (tmp_path / "site" / tls_policy.OLD_CLIENTS_AUDITED).write_text("cbc\n", encoding="utf-8")
    assert up._tls_old_clients() == ["TB_TLS_OLD_CLIENTS=cbc (audited): 443 serves the old-client suites"]
    with pytest.raises(UpdateRefused, match="last audited value is cbc"):  # back to off, never audited
        Updater(_Box(tmp_path, {}), tmp_path)._tls_old_clients()  # type: ignore[arg-type]
    src = Path(Updater.__module__.replace(".", "/") + ".py")
    text = (ROOT / src).read_text(encoding="utf-8")
    assert "notes += self._tls_old_clients()\n        notes += self._from_a_commit(plan)" in text  # first


def _install_value(tmp_path: Path, line: str, exported: str | None) -> str:
    """The installer's own line for the value, run with deploy/.env holding ``line``."""
    start = INSTALL.index('TLS_OLD="${TB_TLS_OLD_CLIENTS-')
    snippet = INSTALL[start : INSTALL.index("\n", start)]
    (tmp_path / "deploy").mkdir(exist_ok=True)
    (tmp_path / "deploy" / ".env").write_text(f"TB_ENV=DEV\n{line}\n", encoding="utf-8")
    envget = 'envget() { sed -n "s/^$1=//p" deploy/.env | tail -1; }'
    env = {"PATH": "/usr/bin:/bin"} | ({"TB_TLS_OLD_CLIENTS": exported} if exported is not None else {})
    p = subprocess.run(["bash", "-c", f'set -u\n{envget}\n{snippet}\nprintf %s "$TLS_OLD"'], cwd=tmp_path, env=env,
                       capture_output=True, text=True, timeout=30, check=True)  # fmt: skip
    return p.stdout


def test_the_installer_reads_the_value_compose_reads(tmp_path: Path) -> None:
    assert _install_value(tmp_path, 'TB_TLS_OLD_CLIENTS="cbc"', None) == "cbc"  # quotes dropped, as doctor does
    assert _install_value(tmp_path, "TB_TLS_OLD_CLIENTS='cbc'", None) == "cbc"
    assert _install_value(tmp_path, "TB_X=1", None) == "off"
    assert _install_value(tmp_path, "TB_TLS_OLD_CLIENTS=off", "cbc") == "cbc"  # exported wins, as in compose
    assert _install_value(tmp_path, "TB_TLS_OLD_CLIENTS=cbc", "") == "off"
    block = INSTALL[INSTALL.index("TLS_OLD_MARK=deploy/site/tls-old-clients.audited") :]
    assert 'if [ "$TLS_OLD" != "$TLS_OLD_WAS" ]; then' in block  # audited with TLS off too: doctor compares


def test_a_restore_drops_the_marker_so_the_event_is_sent_again() -> None:
    main = (ROOT / "tools" / "trialbox" / "__main__.py").read_text(encoding="utf-8")
    after = main[main.index("out = bk.restore(") :]
    assert after.index('joinpath("site", OLD_CLIENTS_AUDITED).unlink(') < after.index("print(json.dumps(out")


def test_ci_validates_the_relaxed_snippets_with_caddy() -> None:
    wf = (ROOT.parent / ".github" / "workflows" / "trialbox-identity.yml").read_text(encoding="utf-8")
    step = wf[wf.index("caddy validate (both modes, TB_TLS_OLD_CLIENTS=cbc") :]
    step = step[: step.index("- name:")]
    assert "for mode in internal hospital" in step and "-e TB_TLS_MODE=$mode -e TB_TLS_OLD_CLIENTS=cbc" in step
    assert "caddy validate --config /etc/caddy/Caddyfile" in step


def test_the_installer_refuses_another_value_and_audits_the_switch() -> None:
    assert re.search(r"case \"\$TLS_OLD\" in\n  off\) ;;\n  cbc\) .*\n  \*\) die \"TB_TLS_OLD_CLIENTS must be off or cbc",
                     INSTALL)  # fmt: skip
    block = INSTALL[INSTALL.index("TLS_OLD_MARK=deploy/site/tls-old-clients.audited") :]
    block = block[: block.index("# ----")]
    assert "TLS_OLD_EVENT=update.tls_relaxed" in block and "TLS_OLD_EVENT=update.tls_strict" in block
    assert '"${COMPOSE[@]}" exec -T orchestrator python -c' in block and "open_audit(" in block
    assert 'FAILS+=("TB_TLS_OLD_CLIENTS=' in block  # an event not sent is a FAIL of the install, and stays due
    # sent from the orchestrator's container, as update.applied is: its family is the orchestrator's (review H1)
    from tb_common import audit_writer

    assert audit_writer.foreign("tb_orchestrator", "update.tls_relaxed") == ""
    assert audit_writer.foreign("tb_orchestrator", "update.tls_strict") == ""
