"""The 48 GB class's measuring run under the ballast (lane H, card H-47; plan 10's 10E-28 and 10E-29's O-8 on a
rented card): lane J's ``tools/dgpu48.py measure`` run unchanged on a larger card that ``tools.ballast`` holds at a
48 GB card's free memory, so its records say "by ballast" and are never a tier record (D-1320 rule 4).

    python3 -m tools.ballast hold --target-mib 49140 &                      # first: the ballast (tools/ballast.py)
    python3 tools/ballast48.py plan                                         # free: the card, the ballast, the utils
    TB_UNMEASURED_DGPU48_MEASURING_RUN=1 python3 tools/ballast48.py measure --option pair-32k [--keep] [--dry-run]
    python3 tools/ballast48.py during --out <file.json> -- <command> ...    # a command's wall time and card peak
    python3 tools/ballast48.py down --out-dir <the measure's folder>        # after --keep: stop the two servers
    python3 tools/ballast48.py verifier-flag --out-dir <folder> [--off]     # after --keep: the verifier alone again,
                                                                            # with (or without) H-49's server flag
    python3 tools/ballast48.py canary-diff <canary.json> <canary.json>      # one role's answers and speed, two runs

Why a wrapper. ``tools/dgpu48.py measure`` refuses a card whose total is outside 44,000 to 52,000 MiB, and vLLM's
utilisations are shares of the card's total. Under the ballast the card still reports its own total, whatever it is
(the rented card's or a larger one's: no total is assumed), so this tool gives ``measure`` a runner that:

* answers its ``nvidia-smi`` questions as a card of ``--target-mib`` (49,140 MiB, the class's ``memory_total_mib``)
  would: the total is the target, and memory used is what has gone from the target's free (the card's used plus
  the driver's reserved memory, minus the card's total less the target), so the class's own arithmetic and range
  check apply unchanged;
* scales ``JUDGE_GPU_MEM_UTIL`` and ``VERIFIER_GPU_MEM_UTIL`` on the start command to the same MiB of the real total
  (``tools.ballast.util_on``: rounded down, never a larger budget than on the 48 GB card);
* adds ``--capped-to "48 GB class (49,140 MiB), by ballast"`` to the serving record's capture, so
  ``tools/serving_config.py measured_for`` refuses the record as a tier record.

The record itself is taken by ``serving_config.py`` from the real card (its name and real total). ``measure.<option>
.json`` gets a ``ballast`` block (the real card, the target, the scaled utilisations, whether the ballast was still
held at the end) and its ``outcome`` starts "BY BALLAST". It refuses when no ``tb-ballast`` container runs or the
card's free memory is not the target within 512 MiB. Free is read by ``tools.ballast.read_card``, the function the
ballast itself converges with: nvidia-smi's ``memory.free``, what a new process is offered. It is never total minus
used: a driver that reserves memory (580: about 636 MiB on the RTX PRO 6000) counts it in neither, and that
difference refused the run of 2026-11-19 at s07 (card H-66). Nothing in lane J's class or switch is changed; the switch
(``TB_UNMEASURED_DGPU48_MEASURING_RUN=1``) is still what ``measure`` checks. Tested on stand-ins only.

The target (H-67, unchanged in meaning): ``memory.free`` on the chosen card equal to ``TARGET_MIB`` (the class's
``memory_total_mib``, 49,140 MiB) within ``TOLERANCE_MIB`` (512, plan 10's rule, not tied to any card): the free a
48 GB card of the class offers before anything starts. The ballast holds the card's own free as read less that
(total - used - reserved - target, ``tools.ballast.hold_mib``); the view counts from the card's own total and the
driver's reserve as read at the check. One card, chosen by ``--gpu-index``: every nvidia-smi question is for that card
only (``-i``), its UUID is taken at the check and checked at every later read (a different card is refused), and the
two model servers are pinned to that UUID by a compose file of the run (``gpu-pin.yml``, device_ids). The pin is
proven before they start (compose's own resolved configuration) and after (each container's device request); a
server that is not proven pinned is stopped and the measure refused.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # `python3 tools/ballast48.py` on the host
    sys.path.insert(0, str(ROOT))

from tools import ballast, dgpu48  # noqa: E402

TARGET_MIB = 49140  # deploy/dgpu48-profile.yaml card.memory_total_mib (the owner's RTX A6000)
TOLERANCE_MIB = ballast.TOLERANCE_MIB
UTIL_KEYS = ballast.UTIL_KEYS
Runner = dgpu48.Runner


def capped_to(target: int = TARGET_MIB) -> str:
    return f"48 GB class ({target:,} MiB), by ballast"


class Refused(RuntimeError):
    pass


PIN_FILE = "gpu-pin.yml"


def pin_text(uuid: str) -> str:
    """The run's compose file that puts both model servers on the one card: compose's ``!override`` replaces the
    overlay's ``count: 1`` (which would take whichever card Docker lists first) by that card's UUID."""
    dev = f'devices: !override [{{driver: nvidia, device_ids: ["{uuid}"], capabilities: [gpu]}}]'
    body = "".join(f"  {svc}:\n    deploy:\n      resources:\n        reservations:\n          {dev}\n"
                   for svc in dgpu48.SERVICE.values())  # fmt: skip
    return (
        "# H-67: the model servers on one card, by UUID (written by tools/ballast48.py; never uploaded)\nservices:\n"
        + body
    )


def _pinned(devs: Any, uuid: str, ids: str = "device_ids", count: str = "count") -> bool:
    """One device request, for exactly that UUID and no count (compose's config: device_ids; Docker's: DeviceIDs)."""
    return (isinstance(devs, list) and len(devs) == 1 and isinstance(devs[0], dict)
            and devs[0].get(ids) == [uuid] and not devs[0].get(count))  # fmt: skip


def prove_config(run: Runner, base: list[str], env: dict[str, str] | None, services: list[str], uuid: str) -> str:
    """Before any server starts: compose's resolved configuration of the very files and environment of the start
    gives each server exactly the one card. "" when proven, else why not."""
    rc, out, err = run([*base, "config", "--format", "json"], 120, env)
    if rc != 0:
        return f"docker compose config failed (exit {rc}): {dgpu48._tail(err, 200)}"
    try:
        doc = json.loads(out)
    except ValueError:
        return "docker compose config gave no JSON"
    bad = []
    for svc in services:
        devs = (((doc.get("services") or {}).get(svc) or {}).get("deploy") or {}).get("resources") or {}
        devs = (devs.get("reservations") or {}).get("devices")
        if not _pinned(devs, uuid):
            bad.append(svc)
    return f"{', '.join(bad)}: not exactly the chosen card by UUID in compose's configuration" if bad else ""


def prove_running(run: Runner, base: list[str], env: dict[str, str] | None, services: list[str], uuid: str) -> str:
    """After the start: each server's container asked Docker for exactly the one card. "" when proven."""
    bad = []
    for svc in services:
        rc, cid, _ = run([*base, "ps", "-aq", svc], 60, env)
        if rc != 0 or not cid.strip():
            continue  # not created: nothing runs anywhere
        for c in cid.split():
            rc, out, _ = run(["docker", "inspect", "--format", "{{json .HostConfig.DeviceRequests}}", c], 60, None)
            try:
                devs = json.loads(out) if rc == 0 else None
            except ValueError:
                devs = None
            if not _pinned(devs, uuid, "DeviceIDs", "Count"):
                bad.append(svc)
    return f"{', '.join(bad)}: the container's device request is not exactly the chosen card" if bad else ""


def _csv_fields(cmd: list[str]) -> list[str]:
    for a in cmd:
        if a.startswith("--query-gpu="):
            return [f.strip() for f in a.split("=", 1)[1].split(",")]
    return []


class BallastView:
    """A runner for ``dgpu48.measure``: the real runner, with the card seen as ``target`` MiB (see the module)."""

    def __init__(self, run: Runner, real_total: int, target: int = TARGET_MIB, reserved: int = 0, *, index: int = 0,
                 uuid: str | None = None, pin_file: Path | None = None) -> None:  # fmt: skip
        self.run, self.real_total, self.target = run, real_total, target
        self.held = real_total - target
        self.reserved = reserved  # the driver's, as read at the check: neither used nor free
        self.index, self.uuid, self.pin_file = index, uuid, pin_file
        self.scaled: dict[str, dict[str, str]] = {}
        self.down: dict[str, Any] | None = None
        self.card_changed = False
        self.pin: dict[str, Any] = {"pinned": pin_file is not None}

    def view_used(self, used: int) -> int:
        """What has gone from the target's free: 0 when the card is at the target, the servers' memory after."""
        return max(0, used + self.reserved - self.held)

    def _rewrite_smi(self, cmd: list[str], out: str) -> str:
        fields = _csv_fields(cmd)
        lines = []
        for line in out.splitlines():
            cells = [c.strip() for c in line.split(",")]
            if len(cells) != len(fields):
                lines.append(line)
                continue
            for i, f in enumerate(fields):
                if f == "memory.total" and cells[i].isdigit():
                    cells[i] = str(self.target)
                elif f == "memory.used" and cells[i].isdigit():
                    cells[i] = str(self.view_used(int(cells[i])))
                elif f == "memory.free" and cells[i].isdigit():
                    cells[i] = str(min(int(cells[i]), self.target))
            lines.append(", ".join(cells))
        return "\n".join(lines) + ("\n" if out.endswith("\n") else "")

    def _smi(self, cmd: list[str], timeout: int, env: dict[str, str] | None) -> tuple[int, str, str]:
        """nvidia-smi about the chosen card only (``-i``), its UUID asked too and checked, then taken off the line."""
        ask = list(cmd)
        if "-i" not in ask and "--id" not in ask and not any(a.startswith("--id=") for a in ask):
            ask += ["-i", str(self.index)]
        if self.uuid is None:
            return self.run(ask, timeout, env)
        ask = [f"{a},uuid" if a.startswith("--query-gpu=") else a for a in ask]
        rc, out, err = self.run(ask, timeout, env)
        if rc != 0:
            return rc, out, err
        lines = []
        for line in out.splitlines():
            if not line.strip():
                continue
            rest, _, got = line.rpartition(",")
            if got.strip() != self.uuid:
                self.card_changed = True
                return 1, "", f"card {self.index} is not the card read at the check (its UUID changed): refused"
            lines.append(rest)
        return rc, "\n".join(lines) + ("\n" if lines else ""), err

    def _pin(self, cmd: list[str]) -> list[str]:
        """The run's pin file after the compose files of a command on the overlay (start, ps, stop)."""
        if self.pin_file is None or "compose" not in cmd or dgpu48.OVERLAY not in cmd or str(self.pin_file) in cmd:
            return cmd
        last = max(i for i, c in enumerate(cmd) if c == "-f")
        return [*cmd[: last + 2], "-f", str(self.pin_file), *cmd[last + 2 :]]

    def __call__(self, cmd: list[str], timeout: int, env: dict[str, str] | None = None,
                 stream: bool = False) -> tuple[int, str, str]:  # fmt: skip
        cmd = list(cmd)
        if cmd[:1] == ["nvidia-smi"] and _csv_fields(cmd):
            rc, out, err = self._smi(cmd, timeout, env)
            return rc, (self._rewrite_smi(cmd, out) if rc == 0 else out), err
        if cmd[:1] == ["nvidia-smi"]:
            return self._smi(cmd, timeout, env)
        cmd = self._pin(cmd)
        if env and "up" in cmd and dgpu48.OVERLAY in cmd:
            env = dict(env)
            for k in UTIL_KEYS:
                if k in env:
                    new = ballast.util_on(self.real_total, float(env[k]), self.target)
                    self.scaled[k] = {"class": env[k], "on_card": str(new)}
                    env[k] = str(new)
            base = cmd[: cmd.index("up")]
            services = [s for s in cmd[cmd.index("up") + 1 :] if s in dgpu48.SERVICE.values()]
            self.down = {"cmd": [*base, "rm", "-sf", *services], "env": env}
            if self.pin_file is not None and self.uuid:
                self.down["pin"] = {"uuid": self.uuid, "file": str(self.pin_file)}
                why = prove_config(self.run, base, env, services, self.uuid)
                self.pin["before_start"] = why or "proven"
                if why:
                    raise Refused(f"the servers' card pin is not proven, nothing was started: {why}")
                rc, out, err = self.run(cmd, timeout, env)
                why = prove_running(self.run, base, env, services, self.uuid)
                self.pin["after_start"] = why or "proven"
                if why:
                    self.run(self.down["cmd"], 600, env)
                    raise Refused(f"the servers' card pin is not proven after the start, they were stopped: {why}")
                return rc, out, err
        if any(str(c).endswith("serving_config.py") for c in cmd) and "capture" in cmd:
            cmd += ["--capped-to", capped_to(self.target)]
        if stream:
            return self.run(cmd, timeout, env, stream=True)
        return self.run(cmd, timeout, env)


def _smi(run: Runner) -> ballast.Run:
    """This tool's runner as ``tools.ballast``'s (stdout, or a refusal)."""

    def call(cmd: Any) -> str:
        rc, out, err = run(list(cmd), 60, None)
        if rc != 0:
            raise ballast.Refused("driver-tool-failed", f"nvidia-smi exited {rc}: {err.strip()[:200]}")
        return out

    return call


def read_card(run: Runner, index: int = 0, uuid: str | None = None) -> dict[str, Any]:
    """Card ``index`` (the ballast's ``--gpu``) read by ``tools.ballast.read_card``: the same free as the holder, that
    card only; ``uuid`` (as read before) is checked. The UUID is kept for the checks and never written to a record."""
    try:
        c = ballast.read_card(index, _smi(run), uuid)
    except ballast.Refused as e:
        raise Refused(f"nvidia-smi finds no card ({e.code}: {e.text})") from None
    return {"name": c.name, "total_mib": c.total, "used_mib": c.used, "free_mib": c.free,
            "reserved_mib": c.reserved, "index": c.index, "uuid": c.uuid}  # fmt: skip


def ballast_running(run: Runner) -> bool:
    rc, out, _ = run(["docker", "ps", "-q", "--filter", f"name=^{ballast.CONTAINER}$"], 60, None)
    return rc == 0 and bool(out.strip())


def check(run: Runner, target: int = TARGET_MIB, index: int = 0, uuid: str | None = None) -> dict[str, Any]:
    """The card and the ballast, before anything starts; Refused names what is wrong."""
    card = read_card(run, index, uuid)
    if card["total_mib"] - target <= TOLERANCE_MIB:
        raise Refused(f"{card['name']} has {card['total_mib']} MiB: not larger than {target}; run tools/dgpu48.py "
                      "itself, without a ballast")  # fmt: skip
    if not ballast_running(run):
        raise Refused(f"no {ballast.CONTAINER} container: start `python3 -m tools.ballast hold --target-mib {target}` "
                      "first and wait for its 'ready' line")  # fmt: skip
    if abs(card["free_mib"] - target) > TOLERANCE_MIB:
        raise Refused(f"{card['free_mib']} MiB free, not {target} +/- {TOLERANCE_MIB} (nvidia-smi memory.free; "
                      f"{card['used_mib']} used, {card['reserved_mib']} reserved by the driver): the ballast is not "
                      "holding the card at the target (or something else holds memory)")  # fmt: skip
    return card


def annotate(summary: dict[str, Any], card: dict[str, Any], view: BallastView, still_held: bool,
             target: int = TARGET_MIB) -> dict[str, Any]:  # fmt: skip
    summary = dict(summary)
    summary["ballast"] = {
        "card": card["name"], "card_total_mib": card["total_mib"], "target_mib": target,
        "held_mib": view.held, "reserved_mib": view.reserved, "capped_to": capped_to(target), "utils": view.scaled,
        "still_held_at_end": still_held, "tier_record": False,
        "rule": "D-1320 rule 4: a record made under the ballast says 'by ballast' and is never a tier record",
        "gpu_index": view.index, "card_checked_by_uuid": view.uuid is not None, "card_changed": view.card_changed,
        "servers_pin": dict(view.pin),
    }  # fmt: skip
    if summary.get("card_peak_mib") is not None:
        summary["ballast"]["card_peak_mib_real"] = summary["card_peak_mib"] + view.held - view.reserved
        summary["ballast"]["free_at_peak_mib"] = target - summary["card_peak_mib"]
    head = "BY BALLAST" if still_held else "BALLAST LOST (records after the loss are not 'by ballast')"
    if view.card_changed:
        head += "; CARD CHANGED (the card's UUID changed during the measure: not a record of one card)"
    summary["outcome"] = f"{head}: {summary.get('outcome', '')}"
    return summary


def measure(run: Runner, oid: str, out_dir: Path, engine: str, keep: bool, dry_run: bool,
            target: int = TARGET_MIB, measure_fn: Callable[..., dict[str, Any]] | None = None,
            say: Callable[[str], None] = print, gpu_index: int = 0, gpu_uuid: str | None = None,
            pin: bool = False) -> dict[str, Any]:  # fmt: skip
    """``pin``: the servers on the chosen card by UUID, proven (the CLI always asks it)."""
    measure_fn = measure_fn or dgpu48.measure
    if dry_run:
        card = read_card(run, gpu_index, gpu_uuid)
    else:
        card = check(run, target, gpu_index, gpu_uuid)
    pin_file = None
    if pin and not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
        pin_file = (out_dir / PIN_FILE).resolve()
        pin_file.write_text(pin_text(card["uuid"]), encoding="utf-8")
    view = BallastView(run, card["total_mib"], target, card["reserved_mib"], index=gpu_index,
                       uuid=card["uuid"] if pin else gpu_uuid, pin_file=pin_file)  # fmt: skip
    say(f"card {gpu_index}, {card['name']}: {card['total_mib']:,} MiB, held at {target:,} MiB free by "
        f"{ballast.CONTAINER}; records say '{capped_to(target)}' (never a tier record)"
        + ("; the servers pinned to this card by UUID" if pin_file else ""))  # fmt: skip
    try:
        s = measure_fn(view, oid, out_dir, None, engine, dry_run, keep, say=say)
    except Refused:
        _mark_refused(out_dir / f"measure.{oid}.json", card, view, target)
        raise
    if view.card_changed and not dry_run:
        _mark_refused(out_dir / f"measure.{oid}.json", card, view, target)
        raise Refused(f"card {gpu_index}'s UUID changed during the measure: the record is not of one card")
    if dry_run:
        for k in UTIL_KEYS:
            v = ((dgpu48.option(dgpu48.load(), oid).get("env")) or {}).get(k)
            if v is not None:
                say(f"on this card: {k}={ballast.util_on(card['total_mib'], float(v), target)} (the class's {v})")
        say(f"record: also --capped-to {json.dumps(capped_to(target))}")
        return s
    s = annotate(s, card, view, ballast_running(run), target)
    (out_dir / f"measure.{oid}.json").write_text(json.dumps(s, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    if keep and view.down:
        (out_dir / "down.json").write_text(json.dumps(view.down, indent=1) + "\n", encoding="utf-8")
    return s


def _mark_refused(f: Path, card: dict[str, Any], view: BallastView, target: int) -> None:
    """Lane J's summary, written before a refusal ended the measure, still says "by ballast" and why it was refused."""
    try:
        s = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    s = annotate(s, card, view, ballast_running(view.run), target)
    s["outcome"] = "REFUSED (the card or its pin, see ballast): " + s["outcome"]
    f.write_text(json.dumps(s, indent=1, sort_keys=True) + "\n", encoding="utf-8")


class CardPeak:
    """nvidia-smi memory used every ``every`` seconds, highest seen, and the lowest free (``read_card``'s); a thread."""

    def __init__(self, run: Runner, every: float = 2.0, index: int = 0, uuid: str | None = None) -> None:
        self.run, self.every, self.index, self.uuid = run, every, index, uuid
        self.changed = False
        self.peak_used = 0
        self.min_free: int | None = None
        self.total = 0
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, daemon=True)

    def sample(self) -> None:
        try:
            card = read_card(self.run, self.index, self.uuid)
        except Refused as e:
            self.changed = self.changed or "card-changed" in str(e)
            return
        self.uuid = card["uuid"]  # the first read's, checked at every later one
        self.total = card["total_mib"]
        self.peak_used = max(self.peak_used, card["used_mib"])
        self.min_free = card["free_mib"] if self.min_free is None else min(self.min_free, card["free_mib"])

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.sample()
            self._stop.wait(self.every)

    def __enter__(self) -> CardPeak:
        self._t.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        self._t.join(timeout=30)
        self.sample()


def during(cmd: list[str], out: Path, run: Runner, target: int = TARGET_MIB, every: float = 2.0,
           popen: Callable[..., Any] = subprocess.run, index: int = 0,
           uuid: str | None = None) -> dict[str, Any]:  # fmt: skip
    """Run ``cmd`` (its output shown), sampling the card; write the wall time, the exit code and the peak."""
    t0 = time.monotonic()
    with CardPeak(run, every, index, uuid) as peak:
        rc = popen(cmd, check=False).returncode
    rec: dict[str, Any] = {
        "schema": "tb-ballast48-during/1", "command": [os.path.basename(cmd[0]), *cmd[1:]], "exit_code": rc,
        "wall_seconds": round(time.monotonic() - t0, 1), "card_total_mib": peak.total,
        "card_peak_used_mib": peak.peak_used, "free_at_peak_mib": peak.min_free if peak.total else None,
        "target_mib": target, "ballast_held_at_end": ballast_running(run), "capped_to": capped_to(target),
        "gpu_index": index, "card_changed": peak.changed,
    }  # fmt: skip
    if peak.total and peak.min_free is not None:
        rec["peak_used_mib_as_48gb"] = max(0, target - peak.min_free)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return rec


def down(out_dir: Path, run: Runner) -> int:
    f = out_dir / "down.json"
    if not f.is_file():
        print(f"no {f}: nothing was kept (measure --keep writes it)", file=sys.stderr)
        return 2
    d = json.loads(f.read_text(encoding="utf-8"))
    rc, _, err = run(d["cmd"], 600, d.get("env"))
    if rc != 0:
        print(dgpu48._tail(err), file=sys.stderr)
    return 0 if rc == 0 else 1


FLAG = '--structured-outputs-config={"backend":"xgrammar","disable_any_whitespace":true}'  # H-49, option 1


def flag_override(out_dir: Path, overlay: Path | None = None) -> Path:
    """A one-off compose file (in the run's folder, never under deploy/) that gives ``llm-verifier`` the overlay's own
    command with H-49's flag added; compose replaces a service's command list, so the whole list is restated."""
    doc = yaml.safe_load((overlay or ROOT / dgpu48.OVERLAY).read_text(encoding="utf-8"))
    cmd = [str(c) for c in doc["services"]["llm-verifier"]["command"]]
    f = out_dir / "verifier-flag.yml"
    f.write_text("# H-47 optional stage: a measurement, not a serving change (written by tools/ballast48.py)\n"
                 + yaml.safe_dump({"services": {"llm-verifier": {"command": [*cmd, FLAG]}}}, sort_keys=False),
                 encoding="utf-8")  # fmt: skip
    return f


def verifier_flag(out_dir: Path, run: Runner, on: bool = True) -> int:
    """Recreate only the verifier of a ``measure --keep`` run, with the flag (or without it), at the same settings."""
    f = out_dir / "down.json"
    if not f.is_file():
        print(f"no {f}: run measure --keep first", file=sys.stderr)
        return 2
    d = json.loads(f.read_text(encoding="utf-8"))
    base = d["cmd"][: d["cmd"].index("rm")]
    if on:
        base = [*base, "-f", str(flag_override(out_dir).resolve())]
    cmd = [*base, "up", "-d", "--wait", "--wait-timeout", str(dgpu48.WAIT_S), "--no-deps", "--force-recreate",
           "llm-verifier"]  # fmt: skip
    uuid = (d.get("pin") or {}).get("uuid")
    if uuid:  # the kept servers were pinned: the recreated verifier is proven on the same card, before and after
        why = prove_config(run, base, d.get("env"), ["llm-verifier"], uuid)
        if why:
            print(f"ballast48: refused: the verifier's card pin is not proven, nothing was recreated: {why}",
                  file=sys.stderr)  # fmt: skip
            return 2
    rc, _, err = run(cmd, dgpu48.WAIT_S + 240, d.get("env"))
    if uuid:
        why = prove_running(run, base, d.get("env"), ["llm-verifier"], uuid)
        if why:
            run([*base, "rm", "-sf", "llm-verifier"], 600, d.get("env"))
            print(f"ballast48: refused: the verifier's card pin is not proven, it was stopped: {why}", file=sys.stderr)
            return 2
    if rc != 0:
        print(dgpu48._tail(err), file=sys.stderr)
    return 0 if rc == 0 else 1


def _canary_model(path: Path, role: str) -> dict[str, Any]:
    rep = json.loads(path.read_text(encoding="utf-8"))
    for m in rep.get("models") or []:
        if isinstance(m, dict) and m.get("role") == role:
            return m
    raise Refused(f"{path}: no {role} in the canary report")


def canary_diff(a: Path, b: Path, role: str = "verifier") -> dict[str, Any]:
    """One role's canary answers in two runs (``tools/canary.py`` reports): the cases whose verdict differs and the
    seconds per call. A report lists at most 10 wrong cases (``selftest.ModelReport.as_dict``) and no right answers:
    a case right in both runs has the same verdict, so the count is exact while each run has at most 10 wrong."""
    out: dict[str, Any] = {"schema": "tb-ballast48-canary-diff/1", "role": role, "runs": {}}
    wrong: list[dict[str, str]] = []
    exact = True
    for label, path in (("a", a), ("b", b)):
        m = _canary_model(path, role)
        cases, answered, correct = int(m.get("cases") or 0), int(m.get("answered") or 0), int(m.get("correct") or 0)
        w = {str(x.get("id")): str(x.get("got")) for x in m.get("wrong") or [] if isinstance(x, dict)}
        exact = exact and answered - correct <= 10 and answered == cases
        wrong.append(w)
        per_call = round(float(m.get("seconds") or 0) / cases, 3) if cases else None
        out["runs"][label] = {"file": path.name, "cases": cases, "answered": answered, "correct": correct,
                              "flips": m.get("flips"), "seconds": m.get("seconds"),
                              "seconds_per_call": per_call}  # fmt: skip
    differ = sorted(i for i in set(wrong[0]) | set(wrong[1]) if wrong[0].get(i) != wrong[1].get(i))
    out["verdicts_differ"] = len(differ)
    out["differ_ids"] = differ
    out["exact"] = exact
    out["note"] = "a measurement, not a serving change; under the ballast: never a tier record"
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 tools/ballast48.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--target-mib", type=int, default=TARGET_MIB)
    one = argparse.ArgumentParser(add_help=False)
    one.add_argument("--gpu-index", type=int, default=0, help="nvidia-smi index of the card (the ballast's --gpu)")
    one.add_argument("--gpu-uuid", default=None, help="the card's UUID as read before: refused if it differs")
    one.add_argument("--ballast-container", type=ballast.container_name, default=ballast.CONTAINER_BASE,
                     help="the ballast's container, as given to tools.ballast hold")  # fmt: skip
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser(
        "plan", parents=[one], help="free: the card, the ballast and each scripted option's utilisations on this card"
    )
    m = sub.add_parser("measure", parents=[one], help=f"tools/dgpu48.py measure under the ballast ({dgpu48.SWITCH}=1)")
    m.add_argument("--option", required=True)
    m.add_argument("--engine", default="pinned", help="the engine form (no probe on a measured card): pinned")
    m.add_argument("--out-dir", type=Path, default=None)
    m.add_argument("--keep", action="store_true", help="leave the servers running (then `down`)")
    m.add_argument("--dry-run", action="store_true")
    d = sub.add_parser("during", parents=[one], help="run a command; its wall time and the card's peak to --out")
    d.add_argument("--out", type=Path, required=True)
    d.add_argument("command", nargs=argparse.REMAINDER)
    w = sub.add_parser("down", help="stop the servers a measure --keep left running")
    w.add_argument("--out-dir", type=Path, required=True)
    v = sub.add_parser("verifier-flag", help="after measure --keep: recreate the verifier with H-49's flag")
    v.add_argument("--out-dir", type=Path, required=True)
    v.add_argument("--off", action="store_true", help="recreate it without the flag (as measured)")
    c = sub.add_parser("canary-diff", help="one role's canary verdicts and seconds per call in two reports")
    c.add_argument("a", type=Path)
    c.add_argument("b", type=Path)
    c.add_argument("--role", default="verifier")
    c.add_argument("--json", type=Path)
    a = ap.parse_args(argv)
    ballast.CONTAINER = getattr(a, "ballast_container", ballast.CONTAINER_BASE)  # plan, measure and during check it
    os.chdir(ROOT)  # compose reads deploy/ relative to the checkout
    run = dgpu48._real_runner
    try:
        if a.cmd == "plan":
            card = check(run, a.target_mib, a.gpu_index, a.gpu_uuid)
            print(f"card {a.gpu_index}, {card['name']}: {card['total_mib']:,} MiB, {card['free_mib']:,} MiB free "
                  f"(target {a.target_mib:,}"
                  f" +/- {TOLERANCE_MIB}; {card['reserved_mib']:,} MiB reserved by the driver); records: --capped-to "
                  f"{json.dumps(capped_to(a.target_mib))}")  # fmt: skip
            doc = dgpu48.load()
            for o in doc["options"]:
                if o.get("scripted"):
                    env = o.get("env") or {}
                    utils = [f"{k}={ballast.util_on(card['total_mib'], float(env[k]), a.target_mib)} (class {env[k]})"
                             for k in UTIL_KEYS if k in env]  # fmt: skip
                    print(f"  {o['id']}: " + ", ".join(utils))
            return 0
        if a.cmd == "measure":
            dgpu48.option(dgpu48.load(), a.option)
            out_dir = a.out_dir or Path.home() / f"tb-dgpu48-{a.option}"
            s = measure(run, a.option, out_dir, a.engine, a.keep, a.dry_run, a.target_mib, gpu_index=a.gpu_index,
                        gpu_uuid=a.gpu_uuid, pin=True)  # fmt: skip
            if not a.dry_run:
                print(json.dumps({k: s.get(k) for k in ("option", "started", "card_peak_mib", "ballast", "outcome")},
                                 indent=1))  # fmt: skip
            return 0 if (a.dry_run or s.get("started")) else 1
        if a.cmd == "during":
            cmd = a.command[1:] if a.command[:1] == ["--"] else a.command
            if not cmd:
                ap.error("during: give the command after --")
            rec = during(cmd, a.out, run, a.target_mib, index=a.gpu_index, uuid=a.gpu_uuid)
            print(json.dumps(rec, indent=1, sort_keys=True))
            if rec["card_changed"]:
                print(f"ballast48: refused: card {a.gpu_index}'s UUID changed during the command", file=sys.stderr)
                return 2
            return int(rec["exit_code"] != 0)
        if a.cmd == "canary-diff":
            res = canary_diff(a.a, a.b, a.role)
            if a.json:
                a.json.write_text(json.dumps(res, indent=1, sort_keys=True) + "\n", encoding="utf-8")
            print(json.dumps(res, indent=1, sort_keys=True))
            return 0
        if a.cmd == "verifier-flag":
            return verifier_flag(a.out_dir, run, on=not a.off)
        return down(a.out_dir, run)
    except (Refused, dgpu48.Refused, KeyError) as exc:
        print(f"ballast48: refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
