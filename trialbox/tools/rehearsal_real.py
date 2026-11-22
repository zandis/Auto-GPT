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
* the card: :func:`card_facts`, one whole card named by index, no MIG, free memory at least what the pair needs;
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
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from tools import images_lock, measure48_vm

PROFILE = "rtxpro6000"
PROFILE_CARD = "RTX PRO 6000"  # tools/serving_config.py PROFILES["rtxpro6000"]["card"]
MARK = "rehearsal.json"
RECORD = "rehearsal-real-servers.json"
OVERRIDE = "rehearsal-real-servers.yml"
OVERRIDE_MARK = "x-trialbox-rehearsal-real-servers: true"
SCHEMA = "tb-rehearsal-real-servers/1"
SERVERS = ("llm-service", "llm-verifier")
NOT_VALID = "not valid for a site"
WORDS = "rehearsal: driver below the minimum, not this profile's card, not valid for a site"
SMI_FIELDS = "name,uuid,driver_version,mig.mode.current,mig.mode.pending,memory.free,memory.total"
UUID = re.compile(r"^GPU-[0-9A-Fa-f-]{8,}$")
ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def words(driver_below: bool, other_card: bool) -> str:
    """What the box says: the facts that hold, then "not valid for a site" (both hold on the bench host: WORDS)."""
    parts = (["driver below the minimum"] if driver_below else []) + (["not this profile's card"] if other_card else [])
    return "rehearsal: " + ", ".join([*parts, NOT_VALID])


def env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        k, sep, v = line.partition("=")
        if sep and not line.lstrip().startswith("#"):
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


def driver_allowance(probe: Path, driver: str, card: str, deploy: Path) -> tuple[list[str], dict[str, Any]]:
    """The driver below the minimum, on a rehearsal box only: the box rule, then H-74's check of the probe (the one
    implementation, ``measure48_vm.bench_exception``) for this card, this driver and the lock's pinned image."""
    problems = box_problems(deploy)
    found, rec = measure48_vm.bench_exception(probe, driver, card, _lock_pin(), images_lock.LOCK)
    return problems + found, rec


def smi(index: str) -> str:
    """nvidia-smi's line for the one card at ``index`` (a stand-in in the tests: a script on PATH)."""
    r = subprocess.run(["nvidia-smi", "-i", index, f"--query-gpu={SMI_FIELDS}", "--format=csv,noheader,nounits"],
                       capture_output=True, text=True, timeout=60, check=False)  # fmt: skip
    return r.stdout.strip() if r.returncode == 0 else ""


def record_need(record: dict[str, Any], total_mib: int) -> tuple[int, int, float]:
    """MiB the pair needs free on a card of ``total_mib``: the larger of the record's measured use and the sum of the
    servers' --gpu-memory-utilization (vLLM's fractions are of the whole card it is given) times this card."""
    used = int(record.get("memory_used_mib") or 0)
    frac = round(sum(float(s.get("gpu_memory_utilization") or 0) for s in record.get("servers") or []), 4)
    return max(used, math.ceil(frac * total_mib)), used, frac


def card_facts(index: str, line: str, record: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    """The one whole card at ``index``: its facts, and why it may not carry the pair (none: it may)."""
    if not re.fullmatch(r"\d{1,3}", index or ""):
        return [f"--gpu-index {index!r} is not a card index (0, 1, ...): one card is named, never all"], {}
    cells = [c.strip() for c in line.splitlines()[0].split(",")] if line.strip() else []
    if len(cells) != len(SMI_FIELDS.split(",")):
        return [f"nvidia-smi finds no card at index {index} (nvidia-smi -i {index})"], {}
    name, uuid, driver, mig_now, mig_next, free, total = cells
    facts: dict[str, Any] = {"index": int(index), "name": name, "uuid": uuid, "driver": driver}
    problems = []
    if not UUID.match(uuid):
        problems.append(f"card {index}: nvidia-smi gives no card UUID ({uuid!r}): the servers cannot be pinned to it")
    if "enabled" in (mig_now.lower(), mig_next.lower()):
        problems.append(f"card {index} ({name}) has MIG on (current {mig_now}, pending {mig_next}): the rehearsal "
                        "runs on one whole card; turn MIG off on it, or name another card")  # fmt: skip
    if not (free.isdigit() and total.isdigit()):
        problems.append(f"card {index}: nvidia-smi gives no memory figures ({free!r}, {total!r})")
        return problems, facts
    need, used, frac = record_need(record, int(total))
    facts.update(memory_free_mib=int(free), memory_total_mib=int(total), need_mib=need)
    if int(free) < need:
        problems.append(f"card {index} ({name}) has {free} MiB free; the pair needs {need} MiB (the record's "
                        f"{used} MiB measured, and {frac} of this card's {total} MiB as the servers ask vLLM for): "
                        "free the card (reload the driver), or name another card")  # fmt: skip
    return problems, facts


def override_text(uuid: str, env: dict[str, str]) -> str:
    """The compose file that pins both model servers to the one card and gives them the probe's environment."""
    if not UUID.match(uuid):
        raise ValueError(f"not a card UUID: {uuid!r}")
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


def write(deploy: Path, index: str, probe: Path, record_path: Path) -> tuple[list[str], dict[str, Any]]:
    """Check the card and the driver again and write the record and the compose file (deploy/site). Nothing is
    written when a check fails."""
    problems = box_problems(deploy)
    if not (deploy / "site" / MARK).is_file():
        problems.append(f"no rehearsal mark (deploy/site/{MARK}): written by install.sh --rehearsal only")
    record = _record(record_path)
    card_problems, facts = card_facts(index, smi(index), record)
    problems += card_problems
    if problems:
        return problems, {}
    lock = images_lock.load(images_lock.LOCK)
    need = str(lock["third_party"][images_lock.VLLM]["gpu"]["driver_min"])
    below = measure48_vm._ver(facts["driver"]) < measure48_vm._ver(need)
    env: dict[str, str] = {}
    form = None
    if below:
        found, allowance = driver_allowance(probe, facts["driver"], facts["name"], deploy)
        if found:
            return found, {}
        env = {str(k): str(v) for k, v in (allowance.get("engine_env") or {}).items()}
        form = allowance.get("engine_form")
    rec_card = str((record.get("card") or {}).get("name") or "?")
    other = PROFILE_CARD not in facts["name"]
    try:
        probe_sha = hashlib.sha256(probe.read_bytes()).hexdigest()
    except OSError as exc:
        return [f"the engine probe file {probe} cannot be read ({type(exc).__name__})"], {}
    doc = {
        "schema": SCHEMA,
        "made_by": "deploy/install.sh --rehearsal --rehearsal-real-servers",
        "words": words(below, other),
        "valid_for_a_site": False,
        "driver": {"found": facts["driver"], "minimum": need, "below_minimum": below},
        "card": {"found": facts["name"], "index": facts["index"], "profile": PROFILE, "profile_card": rec_card,
                 "this_profiles_card": not other, "memory_free_mib": facts["memory_free_mib"],
                 "memory_total_mib": facts["memory_total_mib"], "need_mib": facts["need_mib"]},
        "engine_probe": {"sha256": probe_sha, "form": form, "env": env},
        "serving_record": str(record_path.name),
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
    return _override_in_compose(deploy, env)


def start_refusal(deploy: Path, env: dict[str, str]) -> str:
    """Why this box may not start (``""``: it may). A box that carries a rehearsal sign never starts as PRODUCTION
    (a hand edit of TB_ENV); a box with the real-servers record or file starts only as a whole VALIDATION rehearsal
    box (the mark, TB_REHEARSAL=1): removing the mark by hand is not enough."""
    tb_env = _norm(env.get("TB_ENV")) or "PRODUCTION"
    mark = (deploy / "site" / MARK).is_file()
    flag = (env.get("TB_REHEARSAL") or "").strip() == "1"
    real = real_servers_sign(deploy, env)
    signs = [s for s, on in ((f"deploy/site/{MARK}", mark), ("TB_REHEARSAL=1", flag), (real, bool(real))) if on]
    if signs and tb_env == "PRODUCTION":
        return (
            f"this box carries a rehearsal sign ({', '.join(signs)}) and deploy/.env says TB_ENV=PRODUCTION: a "
            "rehearsal box never becomes a PRODUCTION box; install the site's box afresh on an empty box"
        )
    if real and not (tb_env == "VALIDATION" and mark and flag):
        return (f"this box ran the real model servers as a rehearsal ({real}; {NOT_VALID}) and is no longer a "
                f"whole rehearsal box (TB_ENV={tb_env}, mark {'present' if mark else 'missing'}, TB_REHEARSAL="
                f"{'1' if flag else 'missing'}): install the site's box afresh on an empty box")  # fmt: skip
    return ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("box", help="may this box be a rehearsal box (install.sh, before the GPU check)")
    b.add_argument("--deploy", type=Path, required=True)
    c = sub.add_parser("card", help="may the card at this index carry the pair (install.sh, before the GPU check)")
    c.add_argument("--gpu-index", required=True)
    c.add_argument("--record", type=Path, required=True)
    w = sub.add_parser("write", help="write deploy/site's record and compose file (install.sh, after the mark)")
    w.add_argument("--deploy", type=Path, required=True)
    w.add_argument("--gpu-index", required=True)
    w.add_argument("--engine-probe", type=Path, required=True)
    w.add_argument("--record", type=Path, required=True)
    s = sub.add_parser("start", help="may this box start (exit 1 with the reason when not)")
    s.add_argument("--deploy", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "box":
        problems = box_problems(a.deploy)
    elif a.cmd == "card":
        problems, facts = card_facts(a.gpu_index, smi(a.gpu_index), _record(a.record))
        if not problems:
            free, total, need = facts["memory_free_mib"], facts["memory_total_mib"], facts["need_mib"]
            print(
                f"card {facts['index']}: {facts['name']}, {free} MiB free of {total} (the pair needs {need}), "
                "MIG off: one whole card"
            )
    elif a.cmd == "write":
        problems, doc = write(a.deploy, a.gpu_index, a.engine_probe, a.record)
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
