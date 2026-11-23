"""A rehearsal box with the real model servers on a card that is not its profile's (card H-89).

    deploy/install.sh <bundle> --rehearsal --rehearsal-real-servers --gpu rtxpro6000 --gpu-index N --engine-probe FILE

The install path refuses three things a hospital box must never get past: a driver below ``gpu.driver_min`` of
deploy/images.lock, a card that is not its profile's, and a serving record taken on another card. The bench host
(whole B200-class cards on a driver below the minimum) can rehearse the install walk with the real model servers only
past all three. This module is the one place that decides it, and only under the rehearsal mark:

* "the mark is present" means: this install was given ``--rehearsal`` and ``--rehearsal-real-servers`` on its command
  line (install.sh refuses the new options without ``--rehearsal``), AND the box may be a rehearsal box
  (:func:`box_problems`: deploy/.env TB_ENV is none, DEV or TEST, or VALIDATION with deploy/site/rehearsal.json and
  TB_REHEARSAL=1; no site install without the mark). A hand-made rehearsal.json opens nothing: without
  ``--rehearsal`` install.sh refuses the box, and on a PRODUCTION box :func:`box_problems` refuses it;
* the driver: :func:`driver_allowance`, H-74's check (``tools/measure48_vm.py`` ``bench_exception``, the one
  implementation) on the engine probe file, for this card, this driver and the pinned image;
* the card: :func:`card_facts`, one whole card named by index, no MIG, free memory at least what the pair needs; or
  (H-89b, the rtx5090 profile only) one slice ``N:M`` of a split card, its own UUID and memory (:func:`slice_query`);
* what the box keeps: deploy/site/rehearsal-real-servers.json (the facts, the probe's digest,
  ``valid_for_a_site: false``) and deploy/site/rehearsal-real-servers.yml (the compose file that pins both model
  servers to that one card by its UUID and gives them the probe's recorded environment, read from the probe file);
* the start: :func:`start_refusal` (tools/trialbox/prestart.py, doctor) refuses a box that carries either rehearsal
  sign with TB_ENV=PRODUCTION, and a box with the real-servers record or file that is not a whole rehearsal box.

Standard library only: the host's own python3 runs it (install.sh, check_host.sh through tools/images_lock.py).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tools import ballast, engine_probe, images_lock, measure48_vm

ROOT = Path(__file__).resolve().parents[1]
PROFILE = "rtxpro6000"  # the default; OPENED holds every profile a rehearsal with real servers takes
PROFILE_CARD = "RTX PRO 6000"  # tools/serving_config.py PROFILES["rtxpro6000"]["card"]
# The owner's ruling (7087798913, 7087828219): every shipped profile on the bench, each held to its OWN card's memory
# on the bench's card: its compose file's utilisations scaled by tools/ballast.py util_on (the 5090 profile's existing
# cap: "0.81 of 32,607 MiB becomes 26,412 MiB / total"), written into deploy/.env, which the compose file reads.
#   budget_mib  what the profile's own card reports (nvidia-smi memory.total)
#   cards       the names of the profile's own cards (tools/serving_config.py PROFILES)
#   sleep       the pair swaps (one server awake at a time): the free memory needed is the larger server's, not both
OPENED: dict[str, dict[str, Any]] = {
    "rtxpro6000": {"compose": "docker-compose.rtxpro6000.yml", "budget_mib": 97887, "cards": ("RTX PRO 6000",),
                   "sleep": False},
    "rtx5090": {"compose": "docker-compose.rtx5090.yml", "budget_mib": 32607, "cards": ("5090", "RTX PRO 4500"),
                "sleep": True},
}  # fmt: skip
MARK = "rehearsal.json"
RECORD = "rehearsal-real-servers.json"
OVERRIDE = "rehearsal-real-servers.yml"
OVERRIDE_MARK = "x-trialbox-rehearsal-real-servers: true"
COMPLETE = "rehearsal-install-complete.json"  # install.sh --rehearsal writes it at its end, and nothing else does
SCHEMA = "tb-rehearsal-real-servers/1"
SERVERS = ("llm-service", "llm-verifier")
NOT_VALID = "not valid for a site"
WORDS = "rehearsal: driver below the minimum, not this profile's card, not valid for a site"
SMI_FIELDS = "name,uuid,driver_version,mig.mode.current,mig.mode.pending,memory.free,memory.total"
UUID = re.compile(r"^GPU-[0-9A-Fa-f-]{8,}$")
# H-89b: one slice of a split card, ``N:M`` (card N, its MIG device M, as --gpus device=N:M names it); its own UUID
MIG_UUID = re.compile(r"^MIG-[0-9A-Fa-f]{8}-[0-9A-Fa-f-]{8,}$")
INDEX = re.compile(r"(\d{1,3})(?::(\d{1,2}))?")
SLICE_PROFILES = ("rtx5090",)  # the integrator's ruling 7088891993: the 32 GB profile on a split card's slice
ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")
UTC0 = timezone(timedelta(0))  # the host's own python3 (3.10 on Ubuntu 22.04) has no datetime.UTC
PROBE_MAX_AGE = timedelta(days=7)  # the bench reloads its driver and probes right before the install
LIB_DIR = re.compile(r"/[A-Za-z0-9_.+/-]+")  # fullmatch: no newline
# after the compatibility folder, only the image's own library folders (never a mounted folder such as /models)
IMAGE_LIB_ROOTS = ("/usr/local/", "/usr/lib/", "/usr/lib64/", "/lib/", "/lib64/")
SIGNS_IN_ENV = ("TB_REHEARSAL", "TB_REHEARSAL_REAL_SERVERS")


def words(driver_below: bool, other_card: bool) -> str:
    """What the box says: the facts that hold, then "not valid for a site" (both hold on the bench host: WORDS)."""
    parts = (["driver below the minimum"] if driver_below else []) + (["not this profile's card"] if other_card else [])
    return "rehearsal: " + ", ".join([*parts, NOT_VALID])


def env_file(path: Path) -> dict[str, str]:
    """deploy/.env as compose reads it, for the names this module judges: a leading ``export`` is the same name, and
    an unquoted value ends at `` #`` (review L1); the last line of a name wins."""
    out: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = re.sub(r"^\s*export\s+", "", line)
        k, sep, v = line.partition("=")
        if sep and not line.lstrip().startswith("#"):
            if not v.lstrip().startswith(("'", '"')):
                v = re.sub(r"\s+#.*$", "", v)
            out[k.strip()] = v
    return out


def _norm(v: str | None) -> str:
    return re.sub(r"[\"' \t\r]", "", v or "").upper()


def box_problems(deploy: Path) -> list[str]:
    """Why this box may not be a rehearsal box (none: it may). The installer's own rule (install.sh REHEARSAL), read
    again here so the driver allowance never holds on a site box, whoever calls it."""
    env = env_file(deploy / ".env")
    tb_env = _norm(env.get("TB_ENV"))
    mark = (deploy / "site" / MARK).is_file()
    flag = (env.get("TB_REHEARSAL") or "").strip() == "1"
    if tb_env == "VALIDATION" and not (mark and flag):
        return ["this box is VALIDATION (deploy/.env TB_ENV) with no rehearsal mark: a site box is never made a "
                "rehearsal box"]  # fmt: skip
    if tb_env not in ("", "DEV", "TEST", "VALIDATION"):
        return [f"this box is {tb_env} (deploy/.env TB_ENV): a site box is never made a rehearsal box"]
    if not mark:
        held = [f for f in ("settings.yaml", "updates/installed.json") if (deploy / f).exists()]
        if held:
            return [f"this box holds a site's install (deploy/{held[0]}) from no rehearsal: a rehearsal starts on an "
                    "empty box"]  # fmt: skip
    return []


def _lock_pin() -> str:
    lock = images_lock.load(images_lock.LOCK)
    return images_lock.pinned(lock["third_party"][images_lock.VLLM])


def _form_env(form: str | None, env: dict[str, Any]) -> list[str]:
    """Why the probe's recorded environment is not exactly its passing form's (engine_probe.TESTS): only those names
    reach the model servers (review M1: nothing else, LD_PRELOAD or any other, ever does)."""
    test = next((t for t in engine_probe.TESTS if t["name"] == form), None)
    if test is None:
        return [f"the probe's form {form!r} is not one of tools/engine_probe.py's"]
    want = {str(k): str(v) for k, v in test["env"].items()}
    got = {str(k): str(v) for k, v in env.items()}
    lib = got.pop("LD_LIBRARY_PATH", None) if test["prefix"] else None
    problems = []
    if got != want:
        libs = " and LD_LIBRARY_PATH" if test["prefix"] else ""
        problems.append(f"the probe's environment {sorted(env)} is not its form's ({form}: {sorted(want)}{libs}): "
                        "refused, nothing else reaches the servers")  # fmt: skip
    if test["prefix"]:
        parts = (lib or "").split(":")
        plain = all(LIB_DIR.fullmatch(p) and ".." not in p.split("/") for p in parts)
        own = all(p.startswith(IMAGE_LIB_ROOTS) for p in parts[1:])
        if not lib or parts[0] != engine_probe.COMPAT_DIR or not plain or not own:
            problems.append(f"the probe's LD_LIBRARY_PATH {lib!r} is not {engine_probe.COMPAT_DIR} followed only "
                            f"by the image's own library folders ({', '.join(IMAGE_LIB_ROOTS)})")  # fmt: skip
    return problems


def read_probe(probe: Path) -> tuple[list[str], bytes]:
    """The probe file, read ONCE (never through a link), and why it may not be trusted: it and its folder are root's
    or the installer's and writable by no one else (review round 2, L2). Every later check uses these bytes."""
    problems: list[str] = []
    try:
        fd = os.open(probe, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        return [f"the engine probe result {probe} cannot be read, or is a link ({type(exc).__name__})"], b""
    with os.fdopen(fd, "rb") as fh:
        st = os.fstat(fh.fileno())
        data = fh.read()
    for what, s in ((str(probe), st), (f"its folder {probe.parent}", probe.parent.stat())):
        if s.st_uid not in (0, os.getuid()):
            problems.append(f"{what} is owned by uid {s.st_uid}, not root or the installer")
        if s.st_mode & 0o022:
            problems.append(f"{what} is writable by group or others (chmod go-w)")
    return problems, data


def _probe_problems(data: bytes, facts: dict[str, Any], now: datetime | None = None) -> list[str]:
    """What H-74's check does not ask and a rehearsal install does (review M2), on the bytes :func:`read_probe` read:
    the probe ran on this card (its one-way id) on this host, against the pinned image's matching digest, within
    PROBE_MAX_AGE."""
    try:
        doc = json.loads(data.decode("utf-8"))
    except ValueError as exc:
        return [f"the engine probe result cannot be read ({type(exc).__name__})"]
    problems: list[str] = []
    if not isinstance(doc, dict):
        return [*problems, "the probe file is not an engine probe result"]
    host = doc.get("host") or {}
    if not facts.get("uuid") or host.get("card_id") != engine_probe.card_id(facts["uuid"]):
        problems.append(f"the probe ran on another card than card {facts.get('index')} (its card id does not match; "
                        f"run tools/engine_probe.py run --gpu-index {facts.get('index')})")  # fmt: skip
    mine = engine_probe.host_id()
    if mine is None or host.get("host_id") != mine:
        problems.append("the probe ran on another host (its host id does not match this host's /etc/machine-id)")
    if ((doc.get("images") or {}).get("pinned") or {}).get("digest_matches") is not True:
        problems.append("the probe does not show the pinned image's digest matched (images.pinned.digest_matches)")
    now = now or datetime.now(UTC0)
    try:
        at = datetime.fromisoformat(str(doc.get("at")))
        at = at if at.tzinfo else at.replace(tzinfo=UTC0)
    except ValueError:
        at = None
    if at is None or not (now - PROBE_MAX_AGE <= at <= now + timedelta(hours=1)):
        problems.append(f"the probe was taken at {doc.get('at')!r}: older than {PROBE_MAX_AGE.days} days or not a "
                        "time; probe again")  # fmt: skip
    return problems


def driver_allowance(probe: Path, index: str, deploy: Path) -> tuple[list[str], dict[str, Any]]:
    """The driver below the minimum, on a rehearsal box only: the box rule, H-74's check of the probe (the one
    implementation, ``measure48_vm.bench_exception``) for the card at ``index``, its driver and the lock's pinned
    image, then this card's own checks of the probe (:func:`_probe_problems`, :func:`_form_env`)."""
    problems = box_problems(deploy)
    _, facts = card_facts(index, smi(index), {})
    if not facts:
        return [*problems, f"nvidia-smi finds no card at index {index}"], {}
    trust, data = read_probe(probe)
    if not data:
        return [*problems, *trust], {}
    with tempfile.TemporaryDirectory() as tmp:  # H-74's check reads a path: the bytes read once, in a private copy
        copy = Path(tmp) / "probe.json"
        copy.write_bytes(data)
        found, rec = measure48_vm.bench_exception(copy, facts["driver"], facts["name"], _lock_pin(), images_lock.LOCK)
    problems += trust + found + _probe_problems(data, facts)
    if not found:
        problems += _form_env(rec.get("engine_form"), rec.get("engine_env") or {})
    rec["probe_sha256"] = hashlib.sha256(data).hexdigest()
    return problems, rec


def smi(index: str) -> str:
    """nvidia-smi's line for the one card at ``index`` (of a slice ``N:M``: card N's; a stand-in in the tests: a
    script on PATH)."""
    card = index.partition(":")[0]
    r = subprocess.run(["nvidia-smi", "-i", card, f"--query-gpu={SMI_FIELDS}", "--format=csv,noheader,nounits"],
                       capture_output=True, text=True, timeout=60, check=False)  # fmt: skip
    return r.stdout.strip() if r.returncode == 0 else ""


def slice_problem(index: str, profile: str) -> str:
    """Why the slice form may not carry this profile (``""``: a whole card, or a slice of a profile that may)."""
    if ":" in (index or "") and profile not in SLICE_PROFILES:
        return (f"--gpu-index {index} is a slice of a split card: opened for the {' and '.join(SLICE_PROFILES)} "
                f"profile only, not {profile}")  # fmt: skip
    return ""


def slice_query(card: str, part: str) -> tuple[str, str, str]:
    """The slice ``part`` of card ``card`` (H-89b): its UUID from ``nvidia-smi -L`` and its own memory, free and
    total in MiB, from ``nvidia-smi -q -x -i card`` (the MIG device's ``fb_memory_usage``). Read as text: the form is
    nvidia-smi's documented one, not yet seen on the bench's card. ``""`` for what is not found."""
    uuid = free = total = ""
    r = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True, timeout=60, check=False)
    on = None
    for line in r.stdout.splitlines() if r.returncode == 0 else []:
        gpu = re.match(r"GPU (\d+):", line)
        if gpu:
            on = gpu.group(1)
            continue
        dev = re.match(r"\s+MIG \S+\s+Device\s+(\d+): \(UUID: (MIG-[0-9A-Fa-f-]+)\)\s*$", line)
        if dev and on == card and dev.group(1) == part:
            uuid = dev.group(2)
    r = subprocess.run(["nvidia-smi", "-q", "-x", "-i", card], capture_output=True, text=True, timeout=60, check=False)
    for block in re.findall(r"<mig_device>(.*?)</mig_device>", r.stdout if r.returncode == 0 else "", re.S):
        at = re.search(r"<index>\s*(\d+)\s*</index>", block)
        if at and at.group(1) == part:
            fb = re.search(r"<fb_memory_usage>(.*?)</fb_memory_usage>", block, re.S)
            fb_text = fb.group(1) if fb else ""
            got = {k: re.search(rf"<{k}>\s*(\d+)\s*MiB\s*</{k}>", fb_text) for k in ("total", "free")}
            total = got["total"].group(1) if got["total"] else ""
            free = got["free"].group(1) if got["free"] else ""
    return uuid, free, total


def caps(profile: str, total_mib: int) -> dict[str, float]:
    """The profile's own memory cap on a card of ``total_mib``: each utilisation of its compose file, scaled so the
    server gets the MiB it gets on the profile's own card (tools/ballast.py util_on, rounded down)."""
    rule = OPENED[profile]
    utils = ballast.profile_utils(ROOT / "deploy" / rule["compose"])
    return {k: ballast.util_on(total_mib, u, rule["budget_mib"]) for k, u in utils.items()}


def record_need(record: dict[str, Any], total_mib: int, profile: str = PROFILE) -> tuple[int, int, float]:
    """MiB the pair needs free on a card of ``total_mib`` under the profile's cap: the larger of the record's measured
    use (a profile with a record) and the capped utilisations (vLLM's fractions are of the whole card it is given),
    summed, or the larger one for a pair that swaps."""
    used = int(record.get("memory_used_mib") or 0)
    got = caps(profile, total_mib).values()
    frac = round(max(got) if OPENED[profile]["sleep"] else sum(got), 4)
    return max(used, math.ceil(frac * total_mib)), used, frac


def card_facts(
    index: str, line: str, record: dict[str, Any], profile: str = PROFILE
) -> tuple[list[str], dict[str, Any]]:
    """The one whole card at ``index``, or (H-89b) the one slice ``N:M`` of a split card: its facts, and why it may
    not carry the pair (none: it may). A slice's UUID and memory are its own (:func:`slice_query`)."""
    form = INDEX.fullmatch(index or "")
    if not form:
        return [f"--gpu-index {index!r} is not a card index (0, 1, ...) or a slice of one (N:M): one card or one "
                "slice is named, never all"], {}  # fmt: skip
    card, part = form.groups()
    cells = [c.strip() for c in line.splitlines()[0].split(",")] if line.strip() else []
    if len(cells) != len(SMI_FIELDS.split(",")):
        return [f"nvidia-smi finds no card at index {card} (nvidia-smi -i {card})"], {}
    name, uuid, driver, mig_now, mig_next, free, total = cells
    facts: dict[str, Any] = {"index": int(index) if part is None else index, "name": name, "uuid": uuid,
                             "driver": driver}  # fmt: skip
    problems = []
    if not UUID.match(uuid):
        problems.append(f"card {card}: nvidia-smi gives no card UUID ({uuid!r}): the servers cannot be pinned to it")
    if part is not None:
        if not (mig_now.lower() == mig_next.lower() == "enabled"):
            return [*problems, f"card {card} ({name}) is not split (MIG current {mig_now}, pending {mig_next}): "
                    f"there is no slice {index}; name the whole card (--gpu-index {card})"], facts  # fmt: skip
        s_uuid, free, total = slice_query(card, part)
        if not MIG_UUID.match(s_uuid):
            return [*problems, f"card {card} has no slice {part} (nvidia-smi -L): name a slice it lists"], facts
        facts.update(uuid=s_uuid, card_uuid=uuid, slice=int(part))
        name = f"{name} slice {index}"
    elif "enabled" in (mig_now.lower(), mig_next.lower()):
        problems.append(f"card {index} ({name}) has MIG on (current {mig_now}, pending {mig_next}): the rehearsal "
                        "runs on one whole card; turn MIG off on it, or name another card")  # fmt: skip
    if not (free.isdigit() and total.isdigit()):
        problems.append(f"card {index}: nvidia-smi gives no memory figures ({free!r}, {total!r})")
        return problems, facts
    need, used, frac = record_need(record, int(total), profile)
    facts.update(memory_free_mib=int(free), memory_total_mib=int(total), need_mib=need)
    if int(free) < need:
        problems.append(f"card {index} ({name}) has {free} MiB free; the pair needs {need} MiB (the record's "
                        f"{used} MiB measured, and {frac} of this card's {total} MiB as the servers ask vLLM for): "
                        "free the card (reload the driver), or name another card")  # fmt: skip
    return problems, facts


def override_text(uuid: str, env: dict[str, str]) -> str:
    """The compose file that pins both model servers to the one card and gives them the probe's environment."""
    if not (UUID.match(uuid) or MIG_UUID.match(uuid)):
        raise ValueError(f"not a card or slice UUID: {uuid!r}")
    bad = [k for k, v in env.items() if not ENV_NAME.match(str(k)) or "\n" in str(v) or "\r" in str(v)]
    if bad:
        raise ValueError(f"the probe's environment has names or values a compose file cannot carry: {bad}")
    dev = f"!override [{{driver: nvidia, device_ids: [{json.dumps(uuid)}], capabilities: [gpu]}}]"
    lines = [
        "# Written by deploy/install.sh --rehearsal --rehearsal-real-servers (card H-89): a rehearsal box only, not",
        "# valid for a site. Both model servers on the one card named by --gpu-index (by its UUID, never all), with",
        "# the environment the engine probe passed with (read from the probe file). tools/rehearsal_real.py",
        OVERRIDE_MARK,
        "services:",
    ]
    for svc in SERVERS:
        lines += [f"  {svc}:", "    deploy:", "      resources:", "        reservations:", f"          devices: {dev}"]
        if env:
            lines.append("    environment:")
            lines += [f"      {k}: {json.dumps(str(v))}" for k, v in sorted(env.items())]
    return "\n".join(lines) + "\n"


def _record(path: Path) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"{path} is not a serving record")
    return doc


def write(
    deploy: Path, index: str, probe: Path, record_path: Path | None, profile: str = PROFILE
) -> tuple[list[str], dict[str, Any]]:
    """Check the card and the driver again and write the record and the compose file (deploy/site). Nothing is
    written when a check fails."""
    problems = box_problems(deploy)
    if not (deploy / "site" / MARK).is_file():
        problems.append(f"no rehearsal mark (deploy/site/{MARK}): written by install.sh --rehearsal only")
    if profile not in OPENED:
        return [*problems, f"the {profile} profile is not opened for a rehearsal with real servers"], {}
    if slice_problem(index, profile):
        return [*problems, slice_problem(index, profile)], {}
    record = _record(record_path) if record_path else {}
    card_problems, facts = card_facts(index, smi(index), record, profile)
    problems += card_problems
    if problems:
        return problems, {}
    lock = images_lock.load(images_lock.LOCK)
    need = str(lock["third_party"][images_lock.VLLM]["gpu"]["driver_min"])
    below = measure48_vm._ver(facts["driver"]) < measure48_vm._ver(need)
    env: dict[str, str] = {}
    form = None
    if below:
        found, allowance = driver_allowance(probe, index, deploy)
        if found:
            return found, {}
        env = {str(k): str(v) for k, v in (allowance.get("engine_env") or {}).items()}
        form = allowance.get("engine_form")
        probe_sha = str(allowance["probe_sha256"])
    else:
        trust, data = read_probe(probe)
        if trust or not data:
            return trust or [f"the engine probe file {probe} is empty"], {}
        probe_sha = hashlib.sha256(data).hexdigest()
    rec_card = str((record.get("card") or {}).get("name") or " or ".join(OPENED[profile]["cards"]))
    other = not any(c in facts["name"] for c in OPENED[profile]["cards"])
    doc = {
        "schema": SCHEMA,
        "made_by": "deploy/install.sh --rehearsal --rehearsal-real-servers",
        "words": words(below, other),
        "valid_for_a_site": False,
        "driver": {"found": facts["driver"], "minimum": need, "below_minimum": below},
        "caps": caps(profile, facts["memory_total_mib"]),
        "card": {"found": facts["name"], "index": facts["index"], "profile": profile, "profile_card": rec_card,
                 "this_profiles_card": not other, "slice_of_a_split_card": "slice" in facts,
                 "memory_free_mib": facts["memory_free_mib"],
                 "memory_total_mib": facts["memory_total_mib"], "need_mib": facts["need_mib"]},
        "engine_probe": {"sha256": probe_sha, "form": form, "env": env},
        "serving_record": record_path.name if record_path else None,
    }  # fmt: skip
    site = deploy / "site"
    (site / OVERRIDE).write_text(override_text(facts["uuid"], env), encoding="utf-8")
    (site / OVERRIDE).chmod(0o644)
    (site / RECORD).write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return [], doc


def _override_in_compose(deploy: Path, env: dict[str, str]) -> str:
    """The first file of COMPOSE_FILE that says it is this card's compose file, or ``""``."""
    files = [deploy / "site" / OVERRIDE]
    files += [Path(e.strip()) for e in (env.get("COMPOSE_FILE") or "").split(":") if e.strip()]
    for f in files:
        f = f if f.is_absolute() else deploy / f
        try:
            if OVERRIDE_MARK in f.read_text(encoding="utf-8").splitlines():
                return str(f)
        except (OSError, UnicodeDecodeError):
            continue
    return ""


def real_servers_sign(deploy: Path, env: dict[str, str]) -> str:
    """What says this box ran the real servers as a rehearsal (the record, or the compose file), or ``""``."""
    if (deploy / "site" / RECORD).is_file():
        return str(deploy / "site" / RECORD)
    if (env.get("TB_REHEARSAL_REAL_SERVERS") or "").strip() == "1":
        return "TB_REHEARSAL_REAL_SERVERS=1 (deploy/.env)"
    return _override_in_compose(deploy, env)


def start_refusal(deploy: Path, env: dict[str, str]) -> str:
    """Why this box may not start (``""``: it may). A box that carries a rehearsal sign never starts as PRODUCTION
    (a hand edit of TB_ENV); a box with the real-servers record or file starts only as a whole VALIDATION rehearsal
    box (the mark, TB_REHEARSAL=1): removing the mark by hand is not enough."""
    tb_env = _norm(env.get("TB_ENV"))
    mark = (deploy / "site" / MARK).is_file()
    flag = (env.get("TB_REHEARSAL") or "").strip() == "1"
    real = real_servers_sign(deploy, env)
    complete = (deploy / "site" / COMPLETE).is_file()
    signs = [s for s, on in ((f"deploy/site/{MARK}", mark), ("TB_REHEARSAL=1", flag), (real, bool(real))) if on]
    if not signs:
        return ""
    # the integrator's rulings (7087297960, 7087751791): only an explicit TB_ENV=PRODUCTION is refused, and a missing
    # TB_ENV (or no deploy/.env) is a rehearsal only while the install is in progress: until install.sh --rehearsal
    # has written its completion mark (deploy/site/rehearsal-install-complete.json, written by install.sh alone, at
    # its end). After it, a missing TB_ENV is PRODUCTION to the services (D-127) and refused
    in_progress = not tb_env and not complete
    if tb_env == "PRODUCTION" or (not tb_env and complete):
        said = (
            "says TB_ENV=PRODUCTION"
            if tb_env
            else f"has no TB_ENV after the install completed (deploy/site/{COMPLETE}): PRODUCTION"
        )
        return (
            f"this box carries a rehearsal sign ({', '.join(signs)}) and deploy/.env {said}: a rehearsal box never "
            "becomes a PRODUCTION box; install the site's box afresh on an empty box"
        )
    # the real servers' checks, in every case: the mark always, and once installed a whole VALIDATION rehearsal box
    if real and not (mark and (in_progress or (tb_env == "VALIDATION" and flag))):
        return (f"this box ran the real model servers as a rehearsal ({real}; {NOT_VALID}) and is no longer a "
                f"whole rehearsal box (TB_ENV={tb_env or 'none'}, mark {'present' if mark else 'missing'}, "
                f"TB_REHEARSAL={'1' if flag else 'missing'}): install the site's box afresh on an "
                "empty box")  # fmt: skip
    return ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("box", help="may this box be a rehearsal box (install.sh, before the GPU check)")
    b.add_argument("--deploy", type=Path, required=True)
    c = sub.add_parser("card", help="may the card at this index carry the pair (install.sh, before the GPU check)")
    c.add_argument("--profile", choices=sorted(OPENED), default=PROFILE)
    c.add_argument("--gpu-index", required=True)
    c.add_argument("--record", type=Path, default=None)
    w = sub.add_parser("write", help="write deploy/site's record and compose file (install.sh, after the mark)")
    w.add_argument("--deploy", type=Path, required=True)
    w.add_argument("--profile", choices=sorted(OPENED), default=PROFILE)
    w.add_argument("--gpu-index", required=True)
    w.add_argument("--engine-probe", type=Path, required=True)
    w.add_argument("--record", type=Path, default=None)
    s = sub.add_parser("start", help="may this box start (exit 1 with the reason when not)")
    s.add_argument("--deploy", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "box":
        problems = box_problems(a.deploy)
    elif a.cmd == "card" and slice_problem(a.gpu_index, a.profile):
        problems = [slice_problem(a.gpu_index, a.profile)]
    elif a.cmd == "card":
        problems, facts = card_facts(a.gpu_index, smi(a.gpu_index), _record(a.record) if a.record else {}, a.profile)
        if not problems:
            free, total, need = facts["memory_free_mib"], facts["memory_total_mib"], facts["need_mib"]
            print(
                f"card {facts['index']}: {facts['name']}, {free} MiB free of {total} (the pair needs {need}), "
                + ("one slice of a split card" if "slice" in facts else "MIG off: one whole card")
            )
    elif a.cmd == "write":
        problems, doc = write(a.deploy, a.gpu_index, a.engine_probe, a.record, a.profile)
        if not problems:
            drv, card = doc["driver"], doc["card"]
            print(
                f"{doc['words']} (deploy/site/{RECORD}; driver {drv['found']}, minimum {drv['minimum']}; "
                f"card {card['found']}, the profile's {card['profile_card']})"
            )
    else:
        why = start_refusal(a.deploy, env_file(a.deploy / ".env"))
        problems = [why] if why else []
    for p in problems:
        print(f"refused: {p}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
