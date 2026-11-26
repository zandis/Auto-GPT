"""M9: the machine profile of the 96 GB class, and the Docker Engine's tested range (standard library only).

* ``detect``: the profile a described machine gets, or the named refusal. The card-name rule is
  ``deploy/gpu_profile.sh``'s (one rule); this adds "no card" and "unknown machine" as their own answers: a card the
  rule does not know installs only with an explicit ``--gpu``, never a silent smallest-profile guess.
* ``record``: ``deploy/measured/profile_record.<profile>.json``; ``doctor_checks`` shows it and reports a cap in
  ``deploy/.env`` that is not the measured one (a hand edit).
* ``ENGINE_TESTED``: the one place the Docker Engine range is written (speed consult 10, section 4). The installer
  asks ``python3 -m tools.trialbox.profile_m9 engine`` (exit 0 in range, 2 outside, 3 unreadable); doctor shows it.

Do not import ``platform`` here: ``tools/trialbox/platform.py`` shadows it when this file is run by path.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RECORD = "profile_record.{}.json"
#: lowest and highest (major, minor) Docker Engine the box was tried on
ENGINE_TESTED = ((27, 0), (29, 999))
OVERRIDES = ("rtxpro6000", "gb10", "rtx5090", "rtx4090")
#: a card name that means "none": nvidia-smi's placeholders and its error text (as deploy/gpu_profile.sh)
_NO_NAME = ("[N/A]", "[Unknown", "Unknown", "NVIDIA-SMI has failed", "No devices were found")
_REFUSED = {
    "shared-quota": "a card with MIG on is not served by install.sh (deploy/platform, RUNBOOK 17)",
    "b200-no-mig": "a B200 serves only as two MIG instances: enable MIG (RUNBOOK 17)",
    "gb10-64": "the 64 GB Arm class has no profile (memory below 96 GiB)",
    "arm64-dgpu": "an Arm host with a discrete card that is not a GB10 has no profile",
}


def engine_range_text() -> str:
    (a, b), (c, _) = ENGINE_TESTED
    return f"{a}.{b} to {c}.x"


def engine_row(version: str | None, platform: str = "") -> tuple[str, str, str]:
    """doctor's row for the Engine: PASS inside the tested range, FAIL outside, WARN when it could not be read.
    The version is the Engine's own (``Server.Version``), so Docker Desktop's engine on Windows is judged by the same
    range as a Linux Engine; ``platform`` (``Server.Platform.Name``) only says which one it is."""
    text = (version or "").strip()
    who = "Docker Desktop's engine" if "desktop" in platform.lower() else "Docker Engine"
    m = re.match(r"(\d+)\.(\d+)", text)
    if not m:
        return (
            "docker_engine",
            "WARN",
            f"cannot look: the engine's version was not readable ({version!r}); tested {engine_range_text()}",
        )
    lo, hi = ENGINE_TESTED
    if lo <= (int(m[1]), int(m[2])) <= hi:
        return ("docker_engine", "PASS", f"{who} {text} is in the tested range {engine_range_text()}")
    out = f"{who} {text} is outside the tested range {engine_range_text()}"
    return ("docker_engine", "FAIL", out + ": install a version inside it; nothing was changed")


def server_info() -> tuple[str | None, str]:
    """(Engine version, platform name) as ``docker version`` says them, here or through Docker Desktop's WSL link."""
    try:
        r = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}|{{.Server.Platform.Name}}"],
                           capture_output=True, text=True, timeout=15, check=False)  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return None, ""
    if r.returncode != 0:
        return None, ""
    version, _, platform = r.stdout.strip().partition("|")
    return version, platform


def record(profile: str = "rtxpro6000", root: Path = ROOT) -> dict[str, Any] | None:
    f = root / "deploy" / "measured" / RECORD.format(profile)
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None


def detect(
    arch: str, card: str, mig: str = "", mem_kib: str = "", override: str = "", root: Path = ROOT
) -> dict[str, Any]:
    """``{"profile", "ok", "line", "seen"}``: ``ok`` False is a refusal and ``line`` names why (nothing is changed)."""
    seen = f"arch={arch or '?'}, card={card.strip() or 'none'}, mig={mig.strip() or '?'}, memory_kib={mem_kib or '?'}"
    name = "" if any(t in card for t in _NO_NAME) else card.strip()
    if override:
        ok = override in OVERRIDES
        line = f"profile {override} (chosen by --gpu)" if ok else "--gpu must be one of " + ", ".join(OVERRIDES)
        return {"profile": override if ok else "", "ok": ok, "seen": seen, "line": line}
    script = str(root / "deploy" / "gpu_profile.sh")
    got = subprocess.run(["sh", script, arch, name, mig, mem_kib], capture_output=True, text=True, check=True)
    word = got.stdout.strip()
    if word in _REFUSED:
        return {"profile": word, "ok": False, "seen": seen, "line": f"refused, {word}: {_REFUSED[word]}"}
    if word == "default" and not name:
        return {"profile": "stub", "ok": True, "seen": seen, "line": "no card: stub models; every answer is simulated"}
    if word == "default":
        return {"profile": "", "ok": False, "seen": seen,
                "line": f"unknown machine ({seen}): install only with --gpu {'|'.join(OVERRIDES)}"}  # fmt: skip
    rec = record(word, root)
    if rec:
        c = rec["concurrency"]
        m = rec["measured"]["patients_per_night"]
        return {
            "profile": word,
            "ok": True,
            "seen": seen,
            "line": f"profile {word} ({rec['class']} class): {c['judge_max_seqs']} concurrent judge calls and "
            f"{c['verifier_max_seqs']} verifier calls, patients a night: {m or 'not yet measured'}",
        }
    return {"profile": word, "ok": True, "seen": seen, "line": f"profile {word} (another class: no record here)"}


def caps_row(env: dict[str, str] | Any, rec: dict[str, Any]) -> tuple[str, str, str]:
    """A cap or serving value in the box's .env that is not the measured one is a hand edit: FAIL, naming it."""
    bad = [f"{k}={env[k]} (measured {v})" for k, v in rec["caps"].items() if k in env and str(env[k]) != v]
    if bad:
        return ("profile_caps", "FAIL", "hand-edited, not the measured values: " + "; ".join(bad))
    return ("profile_caps", "PASS", "memory caps, card split and concurrency are the measured ones")


def context_row(profile: str, inp: Any) -> list[tuple[str, str, str]]:
    """The profile pair's pinned context against the length its servers run with (``pin_model.context_problems``):
    FAIL before the night, where the gateway would refuse every call ``model_mismatch``. Pins that do not load are a
    FAIL too: the gateway screens with them."""
    from tools import pin_model
    from tools.trialbox import doctor

    if profile not in pin_model.PROFILE_PAIRS:
        return []
    try:
        bad = pin_model.context_problems(profile, doctor._override(inp), inp.env, deploy=inp.deploy)
    except Exception as e:  # the pins unreadable here (a bad site pin, no YAML module): said, the other rows stay
        return [("profile_context", "FAIL", f"cannot look: the pins did not load ({type(e).__name__}: {e})")]
    if bad:
        return [("profile_context", "FAIL", "; ".join(bad))]
    return [("profile_context", "PASS", f"the {profile} pair's pinned context is the length its servers run with")]


def _card(inp: Any) -> str | None:
    if inp.gpu_query is not None:
        got = inp.gpu_query()
        return got[0] if got else None
    smi = shutil.which("nvidia-smi") or "/usr/lib/wsl/lib/nvidia-smi"  # WSL2: the Windows driver's copy lives there
    try:
        r = subprocess.run([smi, "--query-gpu=name", "--format=csv,noheader"], capture_output=True, text=True,
                           timeout=15, check=False)  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.splitlines()[0].strip() if r.returncode == 0 and r.stdout.strip() else None


def _mig(inp: Any) -> str:
    if inp.gpu_query is not None:
        return ""
    smi = shutil.which("nvidia-smi") or "/usr/lib/wsl/lib/nvidia-smi"
    try:
        r = subprocess.run([smi, "--query-gpu=mig.mode.current", "--format=csv,noheader"], capture_output=True,
                           text=True, timeout=15, check=False)  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.splitlines()[0].strip() if r.returncode == 0 and r.stdout.strip() else ""


def doctor_checks(inp: Any) -> list[tuple[str, str, str]]:
    if inp.deploy is None:  # not a box's own files (as M1's rows): nothing to look at
        return []
    rows = [engine_row(*server_info())]
    if inp.env.get("TB_LLM_MODE") != "gpu":
        return rows
    card = _card(inp)
    if card is None:
        return [*rows, ("profile", "WARN", "cannot look: the card was not readable here")]
    kib = ""
    with contextlib.suppress(OSError, StopIteration, IndexError):
        kib = next(
            ln.split()[1] for ln in (inp.proc / "meminfo").read_text().splitlines() if ln.startswith("MemTotal:")
        )
    d = detect(os.uname().machine, card, _mig(inp), kib)
    rows += context_row(d["profile"], inp) if d["ok"] else []
    rec = record(d["profile"]) if d["ok"] else None
    if rec is None:
        return [*rows, ("profile", "PASS" if d["ok"] else "FAIL", d["line"])]
    rows.append(
        ("profile", "PASS", f"{d['line']}; prefix cache {rec['serving']['prefix_cache']}; record of {rec['date']}")
    )
    return [*rows, caps_row(inp.env, rec)]


def main(argv: list[str]) -> int:
    if argv[:1] == ["engine"]:
        v, plat = (argv[1], argv[2] if len(argv) > 2 else "") if len(argv) > 1 else server_info()
        _, state, text = engine_row(v, plat)
        print(text)
        return {"PASS": 0, "FAIL": 2}.get(state, 3)
    if argv[:1] == ["detect"]:  # arch card [mig] [mem_kib] [--gpu NAME]
        a = [x for x in argv[1:] if not x.startswith("--gpu=")]
        ov = next((x[6:] for x in argv[1:] if x.startswith("--gpu=")), "")
        a += [""] * (4 - len(a))
        d = detect(a[0], a[1], a[2], a[3], ov)
        print(d["line"])
        return 0 if d["ok"] else 2
    print(
        "usage: profile_m9 engine [VERSION [PLATFORM]] | detect ARCH CARD [MIG] [MEM_KIB] [--gpu=NAME]", file=sys.stderr
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
