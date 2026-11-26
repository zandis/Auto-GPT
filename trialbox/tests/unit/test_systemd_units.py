"""T-108b (D-377; CR-043, OPS-049, OPS-064): the egress table is closed before the first container starts after a
reboot, and the stack starts after a host restart.

The reboot order is held on the unit files themselves: the egress unit runs before Docker (whose restart policies
start containers on their own) and before the compose unit; the compose unit requires it and runs after it. The
table itself is held on ``deploy/egress.py``: ``apply`` saves the box's subnets, ``restore`` loads the closed table
from them with no allow rule. nft and docker are replaced by fakes; no root is needed.
"""

from __future__ import annotations

import configparser
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
UNITS = ROOT / "deploy" / "systemd"
EGRESS_UNIT = "trialbox-egress.service"
STACK_UNIT = "trialbox.service"


def _unit(name: str) -> dict[str, dict[str, list[str]]]:
    """A unit file as section -> key -> every value (a key may repeat; values split on spaces)."""
    out: dict[str, dict[str, list[str]]] = {}
    section = ""
    for raw in (UNITS / name).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            out.setdefault(section, {})
            continue
        key, _, value = line.partition("=")
        out[section].setdefault(key.strip(), []).extend(value.split())
    return out


def _egress() -> ModuleType:
    spec = importlib.util.spec_from_file_location("tb_egress_t108b", ROOT / "deploy" / "egress.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["tb_egress_t108b"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------------------------------- unit ordering


def test_egress_unit_runs_before_docker_and_the_stack() -> None:
    eg = _unit(EGRESS_UNIT)
    before = eg["Unit"]["Before"]
    assert STACK_UNIT in before
    assert "docker.service" in before  # Docker restarts `unless-stopped` containers by itself
    assert eg["Unit"]["DefaultDependencies"] == ["no"]  # early in boot, not after basic.target
    assert eg["Service"]["Type"] == ["oneshot"] and eg["Service"]["RemainAfterExit"] == ["yes"]
    assert eg["Service"]["ExecStart"][-1] == "restore"
    assert "ExecStop" not in eg["Service"]  # stopping the unit never opens the table
    # enabling it makes Docker and the stack need it: no Docker start without the table
    assert {"docker.service", STACK_UNIT} <= set(eg["Install"]["RequiredBy"])


def test_stack_unit_requires_and_follows_egress() -> None:
    st = _unit(STACK_UNIT)
    assert EGRESS_UNIT in st["Unit"]["Requires"]
    assert EGRESS_UNIT in st["Unit"]["After"]
    assert "docker.service" in st["Unit"]["Requires"] and "docker.service" in st["Unit"]["After"]
    start = st["Service"]["ExecStart"]
    assert start[start.index("compose") + 1 :][:3] == ["--project-directory", "@TB_ROOT@/deploy", "up"]
    assert "--pull" in start and start[start.index("--pull") + 1] == "never"  # nothing leaves the host
    assert st["Service"]["ExecStartPost"][-1] == "apply"  # the allowed pairs, for the new addresses
    assert st["Install"]["WantedBy"] == ["multi-user.target"]  # starts after a host restart


def test_timers_and_their_services() -> None:
    names = {p.name for p in UNITS.iterdir()}
    for timer in ("trialbox-egress-refresh", "trialbox-watchdog", "trialbox-ops"):
        assert f"{timer}.timer" in names and f"{timer}.service" in names
        assert _unit(f"{timer}.timer")["Install"]["WantedBy"] == ["timers.target"]
    refresh = _unit("trialbox-egress-refresh.service")
    assert EGRESS_UNIT in refresh["Unit"]["Requires"]
    assert refresh["Service"]["ExecStart"][-2:] == ["apply", "--if-changed"]
    wd = _unit("trialbox-watchdog.service")["Service"]["ExecStart"]
    assert wd[wd.index("-m") + 1 :][:2] == ["tools.trialbox", "watchdog"]


def test_unit_files_are_well_formed() -> None:
    for path in sorted(UNITS.iterdir()):
        cp = configparser.ConfigParser(strict=False, interpolation=None)
        cp.optionxform = str  # type: ignore[assignment,method-assign]
        cp.read_string(path.read_text(encoding="utf-8"))
        assert "Unit" in cp, path.name
        for section in cp.sections():
            for key, value in cp[section].items():
                if key.startswith("Exec"):
                    assert value.split()[0].startswith(("/", "@TB_ROOT@/")), f"{path.name}: {key} not absolute"


def test_install_renders_and_enables_the_units() -> None:
    text = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    enable = text.split("systemctl enable ", 1)[1].split(">/dev/null", 1)[0]
    for unit in (EGRESS_UNIT, STACK_UNIT, "trialbox-egress-refresh.timer", "trialbox-watchdog.timer"):
        assert unit in enable
    assert "trialbox-ops.timer" in enable  # NEW-OPS-8 (D-561): the runner is on, or the health facts are never written
    # OCR 1523-2: every timer the loop copies is enabled and started, or its job never runs (the code-system update)
    start = text.split("systemctl start trialbox-egress-refresh.timer", 1)[1].split(">/dev/null", 1)[0]
    for timer in sorted(t.name for t in UNITS.glob("*.timer")):
        assert timer in enable, timer
        assert timer in start or timer == "trialbox-egress-refresh.timer", timer
    assert "s#@TB_ROOT@#$ROOT#g" in text
    # the units are enabled only once `apply` wrote the state file a boot restores from
    assert text.index("deploy/network.sh apply") < text.index("systemctl enable")


@pytest.mark.skipif(shutil.which("systemd-analyze") is None, reason="systemd-analyze not installed")
def test_systemd_analyze_accepts_the_rendered_units(tmp_path: Path) -> None:
    root = tmp_path / "opt"
    (root / "deploy").mkdir(parents=True)
    (root / "deploy" / "network.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (root / "deploy" / "network.sh").chmod(0o755)
    unit_dir = tmp_path / "units"
    unit_dir.mkdir()
    for path in UNITS.iterdir():
        (unit_dir / path.name).write_text(path.read_text().replace("@TB_ROOT@", str(root)), encoding="utf-8")
    res = subprocess.run(
        ["systemd-analyze", "verify", "--man=no", *sorted(str(p) for p in unit_dir.iterdir())],
        capture_output=True,
        text=True,
        check=False,
        env={"SYSTEMD_UNIT_PATH": f"{unit_dir}:", "PATH": "/usr/bin:/bin"},
    )
    # docker.service is not installed here, and a container has no running manager; only syntax errors fail
    bad = [
        ln
        for ln in res.stderr.splitlines()
        if ("Unknown key" in ln or "Unknown section" in ln or "Invalid" in ln or "bad-setting" in ln)
    ]
    assert not bad, res.stderr


# ------------------------------------------------------------------------------------------------- save and restore


def _no_docker(project: str) -> None:
    raise AssertionError("restore must not need docker")


class _Nft:
    """Records what would be loaded into nft; ``nft list table`` says whether a table is live."""

    def __init__(self) -> None:
        self.loaded: list[str] = []
        self.live = False

    def __call__(self, cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ["nft", "-f"]:
            self.loaded.append(kw["input"])
            self.live = True
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[:3] == ["nft", "list", "table"]:
            return subprocess.CompletedProcess(cmd, 0 if self.live else 1, "", "")
        raise AssertionError(f"unexpected command {cmd}")


@pytest.fixture
def running_box(monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, _Nft]:
    eg = _egress()
    box = eg.Box(
        subnets=["172.30.0.0/16", "172.31.0.0/16", "fd00:7b::/64"],
        addresses={"mail-gateway": ["172.31.0.5"], "gateway": ["172.31.0.6"]},
    )
    nft = _Nft()
    monkeypatch.setattr(eg, "docker_box", lambda project: box)
    monkeypatch.setattr(eg.subprocess, "run", nft)
    for k in list(eg._KEYS):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("SMTP_HOST", "192.0.2.25")  # an address: no name lookup in a test
    return eg, nft


def test_apply_saves_and_restore_loads_the_closed_table(
    running_box: tuple[ModuleType, _Nft], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    eg, nft = running_box
    state = tmp_path / "var" / "egress-state.json"
    env = tmp_path / "none.env"
    assert eg.main(["apply", "--state", str(state), "--env", str(env)]) == 0
    applied = nft.loaded[-1]
    assert "tcp dport 587 accept" in applied  # the mail relay is open while the stack runs
    doc = json.loads(state.read_text(encoding="utf-8"))
    assert doc["table"] == eg.TABLE and doc["script"] == applied
    assert doc["subnets"] == ["172.30.0.0/16", "172.31.0.0/16", "fd00:7b::/64"]

    # the reboot: nothing in nft, no docker; restore loads the table from the file alone
    nft.loaded.clear()
    nft.live = False
    monkeypatch.setattr(eg, "docker_box", _no_docker)
    assert eg.main(["restore", "--state", str(state)]) == 0
    restored = nft.loaded[-1]
    assert restored.startswith(f"table inet {eg.TABLE}\ndelete table inet {eg.TABLE}\n")  # replaces any table
    assert 'ip saddr { 172.30.0.0/16, 172.31.0.0/16 } counter drop comment "trialbox default deny"' in restored
    assert 'ip6 saddr { fd00:7b::/64 } counter drop comment "trialbox default deny"' in restored
    assert "trialbox no access to the host" in restored
    assert "tcp dport" not in restored  # closed: no allow rule until the stack is up and `apply` runs
    assert "172.31.0.5" not in restored  # an old container address may be another container's now


def test_restore_dry_run_and_bad_state(running_box: tuple[ModuleType, _Nft], tmp_path: Path, capsys: Any) -> None:
    eg, nft = running_box
    state = tmp_path / "egress-state.json"
    assert eg.main(["restore", "--state", str(state)]) == 1  # never applied: nothing to restore, said so
    assert "run deploy/network.sh apply once" in capsys.readouterr().err
    state.write_text(json.dumps({"table": eg.TABLE, "subnets": ["10.0.0.0/8; flush ruleset"]}), encoding="utf-8")
    assert eg.main(["restore", "--state", str(state)]) == 1  # a bad subnet never reaches nft
    state.write_text(json.dumps({"table": "other", "subnets": []}), encoding="utf-8")
    assert eg.main(["restore", "--state", str(state)]) == 1
    assert nft.loaded == []
    assert eg.main(["save", "--state", str(state), "--env", str(tmp_path / "none.env")]) == 0
    assert eg.main(["restore", "--dry-run", "--state", str(state)]) == 0
    assert "trialbox default deny" in capsys.readouterr().out and nft.loaded == []


def test_refresh_skips_an_unchanged_table_and_never_opens_a_stopped_box(
    running_box: tuple[ModuleType, _Nft], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    eg, nft = running_box
    state = tmp_path / "egress-state.json"
    args = ["apply", "--if-changed", "--state", str(state), "--env", str(tmp_path / "none.env")]
    assert eg.main(args) == 0 and len(nft.loaded) == 1
    assert eg.main(args) == 0 and len(nft.loaded) == 1  # same table live: nothing reloaded
    nft.live = False  # someone flushed it: loaded again
    assert eg.main(args) == 0 and len(nft.loaded) == 2
    saved = state.read_text(encoding="utf-8")
    # the stack is down (`compose down` removed the networks): the closed table of the state file, never an empty one
    monkeypatch.setattr(eg, "docker_box", lambda project: eg.Box())
    assert eg.main(args) == 0
    assert "trialbox default deny" in nft.loaded[-1] and "tcp dport" not in nft.loaded[-1]
    assert state.read_text(encoding="utf-8") == saved  # the subnets a boot restores are kept
