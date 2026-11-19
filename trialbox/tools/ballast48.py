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
utilisations are shares of the card's total. Under the ballast the card still reports its own total (97,887 MiB on
the RTX PRO 6000), so this tool gives ``measure`` a runner that:

* answers its ``nvidia-smi`` questions as a card of ``--target-mib`` (49,140 MiB, the class's ``memory_total_mib``)
  would: the total is the target, and memory used is the card's minus what the ballast holds (the card's total
  minus the target), so the class's own arithmetic and range check apply unchanged;
* scales ``JUDGE_GPU_MEM_UTIL`` and ``VERIFIER_GPU_MEM_UTIL`` on the start command to the same MiB of the real total
  (``tools.ballast.util_on``: rounded down, never a larger budget than on the 48 GB card);
* adds ``--capped-to "48 GB class (49,140 MiB), by ballast"`` to the serving record's capture, so
  ``tools/serving_config.py measured_for`` refuses the record as a tier record.

The record itself is taken by ``serving_config.py`` from the real card (its name and real total). ``measure.<option>
.json`` gets a ``ballast`` block (the real card, the target, the scaled utilisations, whether the ballast was still
held at the end) and its ``outcome`` starts "BY BALLAST". It refuses when no ``tb-ballast`` container runs or the
card's free memory is not the target within 512 MiB. Nothing in lane J's class or switch is changed; the switch
(``TB_UNMEASURED_DGPU48_MEASURING_RUN=1``) is still what ``measure`` checks. Tested on stand-ins only.
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


def _csv_fields(cmd: list[str]) -> list[str]:
    for a in cmd:
        if a.startswith("--query-gpu="):
            return [f.strip() for f in a.split("=", 1)[1].split(",")]
    return []


class BallastView:
    """A runner for ``dgpu48.measure``: the real runner, with the card seen as ``target`` MiB (see the module)."""

    def __init__(self, run: Runner, real_total: int, target: int = TARGET_MIB) -> None:
        self.run, self.real_total, self.target = run, real_total, target
        self.held = real_total - target
        self.scaled: dict[str, dict[str, str]] = {}
        self.down: dict[str, Any] | None = None

    def view_used(self, used: int) -> int:
        return max(0, used - self.held)

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

    def __call__(self, cmd: list[str], timeout: int, env: dict[str, str] | None = None,
                 stream: bool = False) -> tuple[int, str, str]:  # fmt: skip
        cmd = list(cmd)
        if cmd[:1] == ["nvidia-smi"] and _csv_fields(cmd):
            rc, out, err = self.run(cmd, timeout, env)
            return rc, (self._rewrite_smi(cmd, out) if rc == 0 else out), err
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
        if any(str(c).endswith("serving_config.py") for c in cmd) and "capture" in cmd:
            cmd += ["--capped-to", capped_to(self.target)]
        if stream:
            return self.run(cmd, timeout, env, stream=True)
        return self.run(cmd, timeout, env)


def read_card(run: Runner) -> dict[str, Any]:
    rc, out, _ = run(["nvidia-smi", "--query-gpu=name,memory.total,memory.used", "--format=csv,noheader,nounits"],
                     60, None)  # fmt: skip
    cells = [c.strip() for c in out.strip().splitlines()[0].split(",")] if rc == 0 and out.strip() else []
    if len(cells) < 3 or not cells[1].isdigit() or not cells[2].isdigit():
        raise Refused("nvidia-smi finds no card")
    return {"name": cells[0], "total_mib": int(cells[1]), "used_mib": int(cells[2]),
            "free_mib": int(cells[1]) - int(cells[2])}  # fmt: skip


def ballast_running(run: Runner) -> bool:
    rc, out, _ = run(["docker", "ps", "-q", "--filter", f"name=^{ballast.CONTAINER}$"], 60, None)
    return rc == 0 and bool(out.strip())


def check(run: Runner, target: int = TARGET_MIB) -> dict[str, Any]:
    """The card and the ballast, before anything starts; Refused names what is wrong."""
    card = read_card(run)
    if card["total_mib"] - target <= TOLERANCE_MIB:
        raise Refused(f"{card['name']} has {card['total_mib']} MiB: not larger than {target}; run tools/dgpu48.py "
                      "itself, without a ballast")  # fmt: skip
    if not ballast_running(run):
        raise Refused(f"no {ballast.CONTAINER} container: start `python3 -m tools.ballast hold --target-mib {target}` "
                      "first and wait for its 'ready' line")  # fmt: skip
    if abs(card["free_mib"] - target) > TOLERANCE_MIB:
        raise Refused(f"{card['free_mib']} MiB free, not {target} +/- {TOLERANCE_MIB}: the ballast is not holding "
                      "the card at the target (or something else holds memory)")  # fmt: skip
    return card


def annotate(summary: dict[str, Any], card: dict[str, Any], view: BallastView, still_held: bool,
             target: int = TARGET_MIB) -> dict[str, Any]:  # fmt: skip
    summary = dict(summary)
    summary["ballast"] = {
        "card": card["name"], "card_total_mib": card["total_mib"], "target_mib": target,
        "held_mib": view.held, "capped_to": capped_to(target), "utils": view.scaled,
        "still_held_at_end": still_held, "tier_record": False,
        "rule": "D-1320 rule 4: a record made under the ballast says 'by ballast' and is never a tier record",
    }  # fmt: skip
    if summary.get("card_peak_mib") is not None:
        summary["ballast"]["card_peak_mib_real"] = summary["card_peak_mib"] + view.held
        summary["ballast"]["free_at_peak_mib"] = target - summary["card_peak_mib"]
    head = "BY BALLAST" if still_held else "BALLAST LOST (records after the loss are not 'by ballast')"
    summary["outcome"] = f"{head}: {summary.get('outcome', '')}"
    return summary


def measure(run: Runner, oid: str, out_dir: Path, engine: str, keep: bool, dry_run: bool,
            target: int = TARGET_MIB, measure_fn: Callable[..., dict[str, Any]] | None = None,
            say: Callable[[str], None] = print) -> dict[str, Any]:  # fmt: skip
    measure_fn = measure_fn or dgpu48.measure
    if dry_run:
        card = read_card(run)
    else:
        card = check(run, target)
    view = BallastView(run, card["total_mib"], target)
    say(f"{card['name']}: {card['total_mib']:,} MiB, held at {target:,} MiB free by {ballast.CONTAINER}; "
        f"records say '{capped_to(target)}' (never a tier record)")  # fmt: skip
    s = measure_fn(view, oid, out_dir, None, engine, dry_run, keep, say=say)
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


class CardPeak:
    """nvidia-smi memory used every ``every`` seconds, highest seen (a thread)."""

    def __init__(self, run: Runner, every: float = 2.0) -> None:
        self.run, self.every = run, every
        self.peak_used = 0
        self.total = 0
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, daemon=True)

    def sample(self) -> None:
        try:
            card = read_card(self.run)
        except Refused:
            return
        self.total = card["total_mib"]
        self.peak_used = max(self.peak_used, card["used_mib"])

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
           popen: Callable[..., Any] = subprocess.run) -> dict[str, Any]:  # fmt: skip
    """Run ``cmd`` (its output shown), sampling the card; write the wall time, the exit code and the peak."""
    t0 = time.monotonic()
    with CardPeak(run, every) as peak:
        rc = popen(cmd, check=False).returncode
    rec: dict[str, Any] = {
        "schema": "tb-ballast48-during/1", "command": [os.path.basename(cmd[0]), *cmd[1:]], "exit_code": rc,
        "wall_seconds": round(time.monotonic() - t0, 1), "card_total_mib": peak.total,
        "card_peak_used_mib": peak.peak_used, "free_at_peak_mib": peak.total - peak.peak_used if peak.total else None,
        "target_mib": target, "ballast_held_at_end": ballast_running(run), "capped_to": capped_to(target),
    }  # fmt: skip
    if peak.total:
        rec["peak_used_mib_as_48gb"] = max(0, peak.peak_used - (peak.total - target))
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
    rc, _, err = run(cmd, dgpu48.WAIT_S + 240, d.get("env"))
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
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan", help="free: the card, the ballast and each scripted option's utilisations on this card")
    m = sub.add_parser("measure", help=f"tools/dgpu48.py measure under the ballast ({dgpu48.SWITCH}=1)")
    m.add_argument("--option", required=True)
    m.add_argument("--engine", default="pinned", help="the engine form (no probe on a measured card): pinned")
    m.add_argument("--out-dir", type=Path, default=None)
    m.add_argument("--keep", action="store_true", help="leave the servers running (then `down`)")
    m.add_argument("--dry-run", action="store_true")
    d = sub.add_parser("during", help="run a command; its wall time and the card's peak to --out")
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
    os.chdir(ROOT)  # compose reads deploy/ relative to the checkout
    run = dgpu48._real_runner
    try:
        if a.cmd == "plan":
            card = check(run, a.target_mib)
            print(f"{card['name']}: {card['total_mib']:,} MiB, {card['free_mib']:,} MiB free (target {a.target_mib:,}"
                  f" +/- {TOLERANCE_MIB}); records: --capped-to {json.dumps(capped_to(a.target_mib))}")  # fmt: skip
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
            s = measure(run, a.option, out_dir, a.engine, a.keep, a.dry_run, a.target_mib)
            if not a.dry_run:
                print(json.dumps({k: s.get(k) for k in ("option", "started", "card_peak_mib", "ballast", "outcome")},
                                 indent=1))  # fmt: skip
            return 0 if (a.dry_run or s.get("started")) else 1
        if a.cmd == "during":
            cmd = a.command[1:] if a.command[:1] == ["--"] else a.command
            if not cmd:
                ap.error("during: give the command after --")
            rec = during(cmd, a.out, run, a.target_mib)
            print(json.dumps(rec, indent=1, sort_keys=True))
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
