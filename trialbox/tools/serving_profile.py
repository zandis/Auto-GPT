"""H-112: the serving profile switch, for the serving engine comparison on the bench host (the owner's go, #639
7121371183).

The box serves its two models (llm-service, the judge; llm-verifier, the verifier) with the current serving engine.
A second serving profile, ``deploy/docker-compose.serving-second.yml``, runs the second serving engine in the same
two services instead. The switch is ``SERVING_ENGINE`` in the bench host's own settings file
``deploy/site/serving-second.env`` (``current`` when the file or the line is absent, or ``second``), never in
``deploy/.env``: every service reads ``deploy/.env`` as its env file, so a line there would reach every container.
This module reads the switch and gives the compose file list:

* **off** (``current``): the box's own list (``COMPOSE_FILE`` of ``deploy/.env``, else ``docker-compose.yml``),
  byte for byte, and nothing else is read or checked;
* **on** (``second``): the same list with the second profile's file added last, only when all of these hold, else
  refused with the reason (exit 1):

  - the box is a TEST or VALIDATION box (``TB_ENV`` of ``deploy/.env``; absent is PRODUCTION): the second engine is
    in no signed bundle and not in ``deploy/images.lock``, so a PRODUCTION box never runs it;
  - the settings file is owned by root or by this user, not writable by group or others, and fills every key of
    ``deploy/serving-second.example.env`` (no ``<...>`` left);
  - the box's own list defines both llm-service and llm-verifier (a GPU overlay is in it): the second profile changes
    only what runs inside them.

Nothing here reads the caller's environment: the switch, the box's class and the settings come from the two files.
``compose`` runs ``docker compose`` with those files and an environment cleared of every ``COMPOSE_*`` and
``SERVING2_*`` variable, so a variable of the caller's shell cannot replace a setting.

    python3 -m tools.serving_profile files --deploy deploy           # the file list, ':'-joined (COMPOSE_FILE form)
    python3 -m tools.serving_profile check-image --deploy deploy     # the local image against its pinned digest,
                                                                     # then tagged as SERVING2_IMAGE
    python3 -m tools.serving_profile compose --deploy deploy -- --profile gpu up -d --wait llm-service llm-verifier

Exit 0 done, 1 refused (the reason on stderr), 2 usage. Standard library and the YAML library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import yaml

SWITCH = "SERVING_ENGINE"
ENGINES = ("current", "second")
OVERLAY = "docker-compose.serving-second.yml"
SETTINGS = Path("site") / "serving-second.env"
EXAMPLE = "serving-second.example.env"
MARK = "x-trialbox-bench-serving: true"
ALLOWED_ENVS = frozenset({"TEST", "VALIDATION"})
SERVICES = ("llm-service", "llm-verifier")
PLACEHOLDER = re.compile(r"<[^>]*>")
DIGEST = re.compile(r"@(sha256:[0-9a-f]{64})$")
COMPOSE_TAG = re.compile(r"(?<=[\s:\[,])!(?:reset|override)\b")  # as doctor reads compose files
CLEARED_PREFIXES = ("COMPOSE_", "SERVING2_", "SERVING_ENGINE", "DOCKER_DEFAULT_PLATFORM")

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


class Refused(RuntimeError):
    """The switch is on and the box may not take it, or a setting is missing: nothing was run."""


def env_file(path: Path) -> dict[str, str]:
    """``KEY=value`` lines (comments and blank lines skipped; one pair of quotes around a value dropped)."""
    out: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, _, v = line.partition("=")
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            out[k.strip()] = v
    return out


def engine_of(env: Mapping[str, str]) -> str:
    """The switch's value: ``current`` when absent or empty; an unknown value is refused, never read as off."""
    raw = (env.get(SWITCH) or "").strip().lower() or "current"
    if raw not in ENGINES:
        raise Refused(f"{SWITCH}={raw!r}: not one of {', '.join(ENGINES)}")
    return raw


def box_files(env: Mapping[str, str]) -> list[str]:
    """The box's own compose file list, as compose reads ``COMPOSE_FILE`` (``docker-compose.yml`` when unset)."""
    return [e for e in (env.get("COMPOSE_FILE") or "docker-compose.yml").split(":") if e]


def required_keys(deploy: Path) -> list[str]:
    """The keys of the committed example but the switch: every one must be filled on the bench host."""
    return [k for k in env_file(deploy / EXAMPLE) if k != SWITCH]


def switch(deploy: Path) -> str:
    """The switch, from the bench host's settings file only (``current`` without the file)."""
    return engine_of(env_file(deploy / SETTINGS))


def _file(deploy: Path, entry: str) -> Path:
    p = Path(entry)
    return p if p.is_absolute() else deploy / p


def _services(path: Path) -> set[str]:
    """The services a compose file defines (its compose tags dropped, as doctor reads compose files)."""
    try:
        doc = yaml.safe_load(COMPOSE_TAG.sub("", path.read_text(encoding="utf-8")))
    except (OSError, yaml.YAMLError):
        return set()
    return set((doc or {}).get("services") or {}) if isinstance(doc, dict) else set()


def settings_problems(deploy: Path) -> list[str]:
    """What keeps the bench host's settings file from being used (empty: it may be used)."""
    path = deploy / SETTINGS
    if not path.is_file():
        return [f"no {path} (copy deploy/{EXAMPLE} there and fill it on the bench host)"]
    out: list[str] = []
    st = path.stat()
    if st.st_uid not in (0, os.getuid()):
        out.append(f"{path} is not owned by root or this user")
    if st.st_mode & 0o022:
        out.append(f"{path} is writable by group or others (chmod go-w)")
    got = env_file(path)
    for key in required_keys(deploy):
        val = got.get(key, "")
        if not val or PLACEHOLDER.search(val):
            out.append(f"{key} is not filled in {path}")
    src = got.get("SERVING2_SOURCE_IMAGE", "")
    if src and not PLACEHOLDER.search(src) and not DIGEST.search(src):
        out.append("SERVING2_SOURCE_IMAGE is not pinned by digest (<repository>@sha256:<64 hex>)")
    return out


def files(deploy: Path) -> list[str]:
    """The compose file list for the switch (see the module text); :class:`Refused` when the
    switch is on and the box may not take it."""
    env = env_file(deploy / ".env")
    own = box_files(env)
    if switch(deploy) == "current":
        return own
    problems: list[str] = []
    box = (env.get("TB_ENV") or "PRODUCTION").strip().strip("\"'").strip().upper()
    if box not in ALLOWED_ENVS:
        problems.append(f"this is a {box} box: the second serving profile is for the bench and test boxes only "
                        "(not in a signed bundle, not in deploy/images.lock)")  # fmt: skip
    if any(Path(e).name == OVERLAY for e in own):
        problems.append(f"COMPOSE_FILE already names {OVERLAY}: the switch adds it, deploy/.env must not")
    defined: set[str] = set()
    for e in own:
        defined |= _services(_file(deploy, e))
    missing = [s for s in SERVICES if s not in defined]
    if missing:
        problems.append(f"the box's compose files define no {', '.join(missing)} (a GPU overlay must be in the list)")
    problems += settings_problems(deploy)
    if problems:
        raise Refused("; ".join(problems))
    overlay = deploy / OVERLAY if any(Path(e).is_absolute() for e in own) else Path(OVERLAY)
    return [*own, str(overlay)]


def compose_argv(deploy: Path) -> list[str]:
    """``docker compose`` with the box's folder, its env file(s) and the file list of the switch."""
    argv = ["docker", "compose", "--project-directory", str(deploy), "--env-file", str(deploy / ".env")]
    listed = files(deploy)
    if switch(deploy) == "second":
        argv += ["--env-file", str(deploy / SETTINGS)]
    for f in listed:
        argv += ["-f", str(_file(deploy, f))]
    return argv


def clean_environ(environ: Mapping[str, str]) -> dict[str, str]:
    """The caller's environment without what would replace a setting of the two files."""
    return {k: v for k, v in environ.items() if not k.startswith(CLEARED_PREFIXES)}


def _run(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(argv), capture_output=True, text=True, check=False, env=clean_environ(os.environ))


def check_image(deploy: Path, run: Runner = _run) -> str:
    """The bench host's loaded image against its pin: ``SERVING2_SOURCE_IMAGE``'s digest must be among the
    local image's repository digests; then it is tagged ``SERVING2_IMAGE`` (what compose runs, never pulled).
    Returns the digest checked; :class:`Refused` otherwise."""
    if switch(deploy) != "second":
        raise Refused(f"{SWITCH} is not 'second' in deploy/{SETTINGS}: there is no second image to check")
    files(deploy)  # the same refusals as the switch: class of box, settings, GPU overlay
    got = env_file(deploy / SETTINGS)
    src, tag = got["SERVING2_SOURCE_IMAGE"], got["SERVING2_IMAGE"]
    m = DIGEST.search(src)
    assert m is not None  # settings_problems refused it otherwise
    r = run(["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", src])
    if r.returncode != 0:
        raise Refused("the pinned image is not loaded on this host (docker image inspect failed): load it from the "
                      "file the walk verified; nothing is pulled")  # fmt: skip
    try:
        digests = [str(d).rsplit("@", 1)[-1] for d in json.loads(r.stdout or "[]") or []]
    except ValueError:
        digests = []
    if m.group(1) not in digests:
        raise Refused("the local image's digest is not the pinned one: not tagged")
    t = run(["docker", "tag", src, tag])
    if t.returncode != 0:
        raise Refused("docker tag failed")
    return m.group(1)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m tools.serving_profile", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("files", "check-image", "compose"):
        p = sub.add_parser(name)
        p.add_argument("--deploy", type=Path, default=Path("deploy"))
        if name == "compose":
            p.add_argument("rest", nargs=argparse.REMAINDER)
    a = ap.parse_args(argv)
    deploy = a.deploy.resolve()
    try:
        if a.cmd == "files":
            print(":".join(files(deploy)))
            return 0
        if a.cmd == "check-image":
            print(f"serving_profile: the pinned image is loaded and tagged ({check_image(deploy)[:19]}...)")
            return 0
        rest = a.rest[1:] if a.rest[:1] == ["--"] else list(a.rest)
        cmd = [*compose_argv(deploy), *rest]
        return subprocess.run(cmd, check=False, env=clean_environ(os.environ)).returncode
    except Refused as e:
        print(f"serving_profile: refused: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
