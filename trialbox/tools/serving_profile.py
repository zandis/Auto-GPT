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

  - the box is a TEST box (``TB_ENV`` of ``deploy/.env``; absent is PRODUCTION): the second engine is in no signed
    bundle and not in ``deploy/images.lock``, and it checks no key of its own on ``/v1`` (model-guard still does), so
    a PRODUCTION or VALIDATION box never runs it;
  - the settings file is owned by root or by this user and is neither readable nor writable by group or others
    (0600), in a ``deploy/site`` only root or this user may write; it fills every key of
    ``deploy/serving-second.example.env`` (no ``<...>`` left), the image by digest only
    (``<repository>@sha256:<64 hex>``, never a tag: the rulings on #1459, 7122790579);
  - the judge's chat template is the one the current engine renders on this box (``JUDGE_CHAT_TEMPLATE``, else the
    GPU overlay's default): the two engines are compared like for like;
  - the box's own list defines both llm-service and llm-verifier (a GPU overlay is in it): the second profile changes
    only what runs inside them.

The settings file is read once per command (a file swapped after the check is never used), with a byte order mark
dropped and ``export KEY=`` read as compose reads it; a file that is there but cannot be read is refused, never read
as the switch off. ``compose`` hands compose a private copy of the checked values (0600, removed after), never the
settings file again.

Nothing here reads the caller's environment: the switch, the box's class and the settings come from the two files.
``compose`` runs ``docker compose`` with those files and an environment cleared of every ``COMPOSE_*`` and
``SERVING2_*`` variable, so a variable of the caller's shell cannot replace a setting.

    python3 -m tools.serving_profile files --deploy deploy           # the file list, ':'-joined (COMPOSE_FILE form)
    python3 -m tools.serving_profile check-image --deploy deploy     # the local image has the pinned digest
    python3 -m tools.serving_profile image --deploy deploy           # the engine's image as the switch selects it
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
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import yaml

SWITCH = "SERVING_ENGINE"
ENGINES = ("current", "second")
OVERLAY = "docker-compose.serving-second.yml"
SETTINGS = Path("site") / "serving-second.env"
EXAMPLE = "serving-second.example.env"
MARK = "x-trialbox-bench-serving: true"
# the mark as a line compose still reads as the same key: blanks and a trailing comment allowed (OCR 1459-7)
MARK_LINE = re.compile(r"^x-trialbox-bench-serving:\s*true\s*(?:#.*)?$", re.M)
# TEST only: the second engine checks no key of its own on /v1 (read in its source), and a model server without
# its own key check is a FAIL on a VALIDATION box (D-177, D-450; OCR 1459-5)
ALLOWED_ENVS = frozenset({"TEST"})
SERVICES = ("llm-service", "llm-verifier")
PLACEHOLDER = re.compile(r"<[^>]*>")
IMAGE_KEY = "SERVING2_IMAGE"
TEMPLATE_KEY = "SERVING2_JUDGE_CHAT_TEMPLATE"
# the judge's pinned chat template in the GPU overlays (DEP-007, D-392): the second engine must render the same one
CURRENT_TEMPLATE = re.compile(r"--chat-template=/models/\$\{JUDGE_CHAT_TEMPLATE:-([^}\s]+)\}")
# name@digest: a registry host may carry a port, the name no tag
PINNED = re.compile(r"\A(?:[a-z0-9.-]+(?::[0-9]+)?/)?[a-z0-9._/-]+@(sha256:[0-9a-f]{64})\Z")  # \Z: no final newline
DIGEST_TAIL = re.compile(r"@(sha256:[0-9a-f]{64})\Z")
COMPOSE_TAG = re.compile(r"(?<=[\s:\[,])!(?:reset|override)\b")  # as doctor reads compose files
CLEARED_PREFIXES = ("COMPOSE_", "SERVING2_", "SERVING_ENGINE", "DOCKER_DEFAULT_PLATFORM")

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


class Refused(RuntimeError):
    """The switch is on and the box may not take it, or a setting is missing: nothing was run."""


def parse_env(text: str) -> dict[str, str]:
    """``KEY=value`` lines as compose reads an env file: comments and blank lines skipped, an ``export`` before the
    key dropped, one pair of quotes around a value dropped."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, _, v = line.partition("=")
            k = k.strip()
            k = k[len("export ") :].strip() if k.startswith("export ") else k
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            out[k] = v
    return out


def env_file(path: Path) -> dict[str, str]:
    """A file's ``KEY=value`` lines; ``{}`` when there is no file. A file that is there but cannot be read is
    refused, never read as absent (that would read the switch as off; OCR 1459-2). A byte order mark is dropped."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError) as e:
        raise Refused(f"{path} cannot be read ({type(e).__name__})") from None
    return parse_env(text)


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


def _read_settings(deploy: Path) -> tuple[dict[str, str], os.stat_result] | None:
    """The settings file, read once: its values and the status of the same open file (None: no file)."""
    path = deploy / SETTINGS
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        return None
    except OSError as e:
        raise Refused(f"{path} cannot be read ({type(e).__name__})") from None
    try:
        with os.fdopen(fd, "rb") as fh:
            st = os.fstat(fh.fileno())
            raw = fh.read()
    except OSError as e:
        raise Refused(f"{path} cannot be read ({type(e).__name__})") from None
    try:
        return parse_env(raw.decode("utf-8-sig")), st
    except UnicodeDecodeError:
        raise Refused(f"{path} cannot be read (not UTF-8)") from None


def switch(deploy: Path) -> str:
    """The switch, from the bench host's settings file only (``current`` without the file)."""
    got = _read_settings(deploy)
    return engine_of(got[0] if got else {})


def _file(deploy: Path, entry: str) -> Path:
    p = Path(entry)
    return p if p.is_absolute() else deploy / p


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _services(path: Path) -> set[str]:
    """The services a compose file defines (its compose tags dropped, as doctor reads compose files)."""
    try:
        doc = yaml.safe_load(COMPOSE_TAG.sub("", _text(path)))
    except yaml.YAMLError:
        return set()
    return set((doc or {}).get("services") or {}) if isinstance(doc, dict) else set()


def current_template(deploy: Path, env: Mapping[str, str], own: Sequence[str]) -> str | None:
    """The judge's chat template the current engine renders on this box: the box's ``JUDGE_CHAT_TEMPLATE``, else the
    default its GPU overlay names (the last file that names one); None when no listed file names one."""
    found = [m.group(1) for e in own for m in CURRENT_TEMPLATE.finditer(_text(_file(deploy, e)))]
    if not found:
        return None
    return env.get("JUDGE_CHAT_TEMPLATE") or found[-1]


def settings_problems(
    deploy: Path, got: Mapping[str, str] | None = None, st: os.stat_result | None = None
) -> list[str]:
    """What keeps the bench host's settings file from being used (empty: it may be used)."""
    path = deploy / SETTINGS
    if got is None or st is None:
        read = _read_settings(deploy)
        if read is None:
            return [f"no {path} (copy deploy/{EXAMPLE} there and fill it on the bench host)"]
        got, st = read
    out: list[str] = []
    if st.st_uid not in (0, os.getuid()):
        out.append(f"{path} is not owned by root or this user")
    if st.st_mode & 0o077:
        out.append(f"{path} is readable or writable by group or others (chmod 600)")
    try:
        sd = os.stat(path.parent)
        if sd.st_uid not in (0, os.getuid()) or sd.st_mode & 0o022:
            out.append(f"{path.parent} is not root's or this user's alone (chmod go-w)")
    except OSError:
        out.append(f"{path.parent} cannot be read")
    for key in required_keys(deploy):
        val = got.get(key, "")
        if not val or PLACEHOLDER.search(val):
            out.append(f"{key} is not filled in {path}")
    ref = got.get(IMAGE_KEY, "")
    if ref and not PLACEHOLDER.search(ref) and not PINNED.match(ref):
        out.append(f"{IMAGE_KEY} is not pinned by digest (<repository>@sha256:<64 hex>, never a tag)")
    return out


def checked(deploy: Path) -> tuple[str, list[str], dict[str, str]]:
    """The switch, the compose file list and the settings' values, from ONE read of the settings file (so a file
    swapped after the check is never used: OCR 1459-9); :class:`Refused` when the switch is on and the box may not
    take it. With the switch off the list is the box's own and the values are empty."""
    env = env_file(deploy / ".env")
    own = box_files(env)
    read = _read_settings(deploy)
    got, st = read if read is not None else ({}, None)
    if engine_of(got) == "current":
        return "current", own, {}
    problems: list[str] = []
    box = (env.get("TB_ENV") or "PRODUCTION").strip().strip("\"'").strip().upper()
    if box not in ALLOWED_ENVS:
        problems.append(f"this is a {box} box: the second serving profile is for test boxes and the bench host only "
                        "(not in a signed bundle, not in deploy/images.lock, no key check of its own)")  # fmt: skip
    if any(Path(e).name == OVERLAY for e in own):
        problems.append(f"COMPOSE_FILE already names {OVERLAY}: the switch adds it, deploy/.env must not")
    defined: set[str] = set()
    for e in own:
        defined |= _services(_file(deploy, e))
    missing = [s for s in SERVICES if s not in defined]
    if missing:
        problems.append(f"the box's compose files define no {', '.join(missing)} (a GPU overlay must be in the list)")
    problems += settings_problems(deploy, got, st)
    want = current_template(deploy, env, own)
    if want is not None and got.get(TEMPLATE_KEY) and got.get(TEMPLATE_KEY) != want:
        problems.append(f"{TEMPLATE_KEY} is not the judge's chat template the current engine renders "
                        "(JUDGE_CHAT_TEMPLATE, or the GPU overlay's default): the engines would not be compared "
                        "like for like")  # fmt: skip
    if problems:
        raise Refused("; ".join(problems))
    overlay = deploy / OVERLAY if any(Path(e).is_absolute() for e in own) else Path(OVERLAY)
    return "second", [*own, str(overlay)], dict(got)


def files(deploy: Path) -> list[str]:
    """The compose file list for the switch (see the module text)."""
    return checked(deploy)[1]


def compose_argv(deploy: Path, env_path: Path | None = None) -> list[str]:
    """``docker compose`` with the box's folder, its env file, the checked settings (``env_path``: the private copy
    ``compose`` writes; else the settings file) and the file list of the switch."""
    engine, listed, _ = checked(deploy)
    argv = ["docker", "compose", "--project-directory", str(deploy), "--env-file", str(deploy / ".env")]
    if engine == "second":
        argv += ["--env-file", str(env_path or deploy / SETTINGS)]
    for f in listed:
        argv += ["-f", str(_file(deploy, f))]
    return argv


def clean_environ(environ: Mapping[str, str]) -> dict[str, str]:
    """The caller's environment without what would replace a setting of the two files."""
    return {k: v for k, v in environ.items() if not k.startswith(CLEARED_PREFIXES)}


def _run(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(argv), capture_output=True, text=True, check=False, env=clean_environ(os.environ))


def _check_pin(ref: str, run: Runner) -> str:
    m = PINNED.match(ref)
    if m is None:
        raise Refused(f"{IMAGE_KEY} is not pinned by digest (<repository>@sha256:<64 hex>, never a tag)")
    r = run(["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", ref])
    if r.returncode != 0:
        raise Refused("the pinned image is not on this host (docker image inspect failed): load it from the file "
                      "whose licence the walk read; nothing is pulled")  # fmt: skip
    try:
        digests = [str(d).rsplit("@", 1)[-1] for d in json.loads(r.stdout or "[]") or []]
    except ValueError:
        digests = []
    if m.group(1) not in digests:
        raise Refused("the local image's digest is not the pinned one")
    return m.group(1)


def check_image(deploy: Path, run: Runner = _run) -> str:
    """The bench host's loaded image against its pin: the digest of ``SERVING2_IMAGE`` must be among the local
    image's repository digests. Nothing is pulled and nothing is tagged: compose runs the image by that digest.
    Returns the digest; :class:`Refused` otherwise."""
    engine, _, got = checked(deploy)
    if engine != "second":
        raise Refused(f"{SWITCH} is not 'second' in deploy/{SETTINGS}: there is no second image to check")
    return _check_pin(got[IMAGE_KEY], run)


def compose(
    deploy: Path, rest: Sequence[str], run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run
) -> int:
    """``docker compose`` for the switch. With the switch on, the settings are read and checked once, the local image
    is checked against its pin, and compose gets those checked values in a private copy (mode 0600, removed after),
    never the settings file a second time."""
    engine, listed, got = checked(deploy)
    if engine == "current":
        return run([*compose_argv(deploy), *rest], check=False, env=clean_environ(os.environ)).returncode
    _check_pin(got[IMAGE_KEY], lambda argv: run(list(argv), capture_output=True, text=True, check=False,
                                                env=clean_environ(os.environ)))  # fmt: skip
    with tempfile.TemporaryDirectory(prefix="serving2-") as tmp:
        env_path = Path(tmp) / "checked.env"
        fd = os.open(env_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("".join(f"{k}={v}\n" for k, v in got.items()))
        argv = ["docker", "compose", "--project-directory", str(deploy), "--env-file", str(deploy / ".env"),
                "--env-file", str(env_path), *(x for f in listed for x in ("-f", str(_file(deploy, f))))]  # fmt: skip
        return run([*argv, *rest], check=False, env=clean_environ(os.environ)).returncode


# ${VAR:-default} or ${VAR:?message} (the platform overlay's form: no default, the box must set it)
IMAGE_VAR = re.compile(r"\A\$\{([A-Z][A-Z0-9_]*)(?::-([^}\s]+)|:\?[^}]*)?\}\Z")


def current_image_ref(deploy: Path, env: Mapping[str, str], own: Sequence[str]) -> str:
    """The image the current engine's judge server runs on this box, as compose resolves it: the ``image`` of
    ``llm-service`` in the last of the box's files that sets one; its ``${VAR:-default}`` resolved with the box's
    ``deploy/.env`` (OCR 1459-13: the variable that stack uses, not any variable of the lock entry)."""
    value = ""
    for e in own:
        try:
            doc = yaml.safe_load(COMPOSE_TAG.sub("", _text(_file(deploy, e))))
        except yaml.YAMLError:
            continue
        svc = ((doc or {}).get("services") or {}).get("llm-service") if isinstance(doc, dict) else None
        if isinstance(svc, dict) and svc.get("image"):
            value = str(svc["image"])
    m = IMAGE_VAR.match(value)
    return (env.get(m.group(1)) or m.group(2) or "") if m else value


def image(deploy: Path) -> str:
    """The digest the switch's engine runs: the second engine's pin (checked as ``files`` checks it), or the current
    engine's image as the box's own files and deploy/.env resolve it (:func:`current_image_ref`). Never a tag."""
    engine, listed, got = checked(deploy)
    if engine == "second":
        ref = got[IMAGE_KEY]
    else:
        ref = current_image_ref(deploy, env_file(deploy / ".env"), listed)
    m = PINNED.match(ref) or DIGEST_TAIL.search(ref)  # the lock's own form is repository:tag@digest
    if m is None:
        raise Refused("the engine's image is not pinned by digest")
    return m.group(1)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m tools.serving_profile", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("files", "check-image", "image", "compose"):
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
            print(f"serving_profile: the pinned image is on this host ({check_image(deploy)[:19]}...)")
            return 0
        if a.cmd == "image":
            print(image(deploy))
            return 0
        return compose(deploy, a.rest[1:] if a.rest[:1] == ["--"] else list(a.rest))
    except Refused as e:
        print(f"serving_profile: refused: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
