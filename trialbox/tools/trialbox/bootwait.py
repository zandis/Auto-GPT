"""How long a start and a stop of the stack may take, from the compose files themselves (T-695, D-752; F-10, F-24).

The boot waited 900 s for every service healthy, the same as the verifier's own start period on GB10: a cold load
the compose file allows failed the boot, then the update and its rollback. A service is unhealthy only after its
``start_period`` and then ``retries`` failed checks, each up to ``interval`` plus ``timeout`` apart; the wait is the
longest of those over the services of the box's compose files (``COMPOSE_FILE``, later files override). The stop is
the longest ``stop_grace_period``. ``deploy/install.sh`` writes both into the systemd unit and uses the wait;
``trialbox update`` uses the wait unless ``TB_INSTALL_UP_TIMEOUT`` is set.

    python -m tools.trialbox.bootwait --deploy deploy [--stop]
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

# Docker's own defaults for a health check field not given
DOCKER = {"interval": 30, "timeout": 30, "retries": 3, "start_period": 0}
STOP_DEFAULT_S = 10  # docker's stop grace when a service names none
_PART = re.compile(r"(\d+(?:\.\d+)?)(h|ms|m|s|us|ns)")
_UNIT = {"h": 3600, "m": 60, "s": 1, "ms": 1e-3, "us": 1e-6, "ns": 1e-9}


def seconds(value: Any) -> float:
    """A compose duration (``1m30s``, ``600s``, ``90``) in seconds."""
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip()
    if text.replace(".", "", 1).isdigit():
        return float(text)
    parts = _PART.findall(text)
    if not parts or "".join(n + u for n, u in parts) != text:
        raise ValueError(f"not a compose duration: {value!r}")
    return sum(float(n) * _UNIT[u] for n, u in parts)


def files(deploy: Path, env: Mapping[str, str]) -> list[Path]:
    from tools.trialbox.doctor import _compose_file

    return [_compose_file(deploy, e) for e in (env.get("COMPOSE_FILE") or "docker-compose.yml").split(":") if e]


_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::?-([^}]*))?\}")


def _interpolate(value: Any, env: Mapping[str, str]) -> Any:
    """Compose's ``${VAR:-default}`` in a value, from the box's settings (else the default)."""
    if isinstance(value, dict):
        return {k: _interpolate(v, env) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate(v, env) for v in value]
    if isinstance(value, str):
        return _VAR.sub(lambda m: env.get(m.group(1)) or (m.group(2) or ""), value)
    return value


def services(paths: list[Path], env: Mapping[str, str] | None = None) -> dict[str, dict[str, Any]]:
    """Each service's health check and stop grace, the later file's fields over the earlier's, ``${VAR:-x}`` read
    from ``env``."""
    out: dict[str, dict[str, Any]] = {}
    for p in paths:
        doc = _interpolate(yaml.safe_load(p.read_text(encoding="utf-8")) or {}, env or {})
        for name, svc in (doc.get("services") or {}).items():
            cur = out.setdefault(name, {"healthcheck": {}, "stop_grace_period": None})
            hc = (svc or {}).get("healthcheck")
            if isinstance(hc, dict):
                cur["healthcheck"] = {**cur["healthcheck"], **hc}
            if (svc or {}).get("stop_grace_period") is not None:
                cur["stop_grace_period"] = svc["stop_grace_period"]
    return out


def start_wait_s(svcs: Mapping[str, Mapping[str, Any]]) -> int:
    """The longest a service may take to become healthy (0 when none has a health check)."""
    worst = 0.0
    for svc in svcs.values():
        hc = svc["healthcheck"]
        if not hc or hc.get("disable") or hc.get("test") in (["NONE"], "NONE"):
            continue
        f = {k: seconds(hc[k]) if k in hc else float(v) for k, v in DOCKER.items()}
        worst = max(worst, f["start_period"] + f["retries"] * (f["interval"] + f["timeout"]))
    return int(-(-worst // 1))


def stop_wait_s(svcs: Mapping[str, Mapping[str, Any]]) -> int:
    """The longest stop grace of a service."""
    graces = [seconds(s["stop_grace_period"]) for s in svcs.values() if s["stop_grace_period"] is not None]
    return int(-(-max([STOP_DEFAULT_S, *graces]) // 1))


def main(argv: list[str] | None = None) -> int:
    from tools.trialbox.memcaps import _parse_env

    ap = argparse.ArgumentParser(prog="bootwait", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--deploy", type=Path, default=Path("deploy"))
    ap.add_argument("--stop", action="store_true", help="the longest stop grace instead of the start wait")
    a = ap.parse_args(argv)
    env_file = a.deploy / ".env"
    env = _parse_env(env_file.read_text(encoding="utf-8")) if env_file.is_file() else {}
    svcs = services(files(a.deploy, env), env)
    print(stop_wait_s(svcs) if a.stop else start_wait_s(svcs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
