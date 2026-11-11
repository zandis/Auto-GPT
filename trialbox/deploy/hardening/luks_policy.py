"""Does this LUKS volume open by itself away from the hospital? (T-634, D-408; OPS-043). Standard library only.

    python3 deploy/hardening/luks_policy.py DEVICE                 # runs cryptsetup and clevis on the box
    python3 deploy/hardening/luks_policy.py --dump F [--clevis F]  # from saved output (the tests, a support case)

Every automatic way into the volume is judged; the passphrase key slots are not (they need a person):

* a ``systemd-tpm2`` token without a PIN, a clevis ``tpm2`` binding alone, or a clevis ``sss`` binding whose
  threshold the non-network pins can reach by themselves: the TPM alone opens the disk, so a stolen box boots to a
  running stack anywhere. **FAIL**;
* a clevis binding that needs a ``tang`` server (``tang`` alone, or ``sss`` where every way to the threshold
  includes a Tang pin), or a ``systemd-tpm2`` token with a PIN: the disk opens only in the hospital, or only with a
  person. **PASS**;
* no automatic way at all: safe, but the box does not come back alone after a power cut. **WARN**.

Output: one ``PASS``/``WARN``/``FAIL`` line per finding (the format of ``deploy/check_host.sh``); exit 1 on a FAIL.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Any

NETWORK_PINS = ("tang",)  # pins that need the hospital network
_CLEVIS_LINE = re.compile(r"^\s*(\d+):\s+(\w+)\s+'(.*)'\s*$")


def _needs_network(pin: str, cfg: Any) -> bool:
    """True when every way through this pin needs a Tang server (or a person)."""
    if pin in NETWORK_PINS:
        return True
    if pin != "sss":
        return False  # tpm2 and anything unknown: no network needed
    if not isinstance(cfg, dict):
        return False
    t = int(cfg.get("t", 1))
    pins = cfg.get("pins") or {}
    # each entry of a pin list is one share; count the shares that do not need the network
    free = 0
    for name, sub in pins.items():
        subs = sub if isinstance(sub, list) else [sub]
        for one in subs:
            if not _needs_network(name, one):
                free += 1
    return free < t


def clevis_bindings(text: str) -> list[tuple[str, str, Any]]:
    """``clevis luks list -d DEV`` lines: (slot, pin, config)."""
    out = []
    for line in text.splitlines():
        m = _CLEVIS_LINE.match(line)
        if not m:
            continue
        try:
            cfg = json.loads(m.group(3))
        except ValueError:
            cfg = None
        out.append((m.group(1), m.group(2), cfg))
    return out


def judge(dump: dict[str, Any] | None, clevis_text: str = "") -> list[str]:
    """The PASS/WARN/FAIL lines for one volume, from ``cryptsetup luksDump --dump-json-metadata`` and clevis."""
    lines: list[str] = []
    auto = 0
    tokens = (dump or {}).get("tokens") or {}
    for tid, tok in sorted(tokens.items()):
        kind = tok.get("type", "?")
        slots = ",".join(tok.get("keyslots") or []) or "-"
        if kind == "systemd-tpm2":
            auto += 1
            if tok.get("tpm2-pin"):
                lines.append(f"PASS  LUKS token {tid} (slot {slots}): TPM2 with a PIN")
            else:
                lines.append(
                    f"FAIL  LUKS token {tid} (slot {slots}): TPM2 without a PIN opens the disk anywhere "
                    "(deploy/hardening/disk-unlock.sh bind)"
                )
        elif kind in ("systemd-fido2", "systemd-pkcs11"):
            auto += 1
            lines.append(f"PASS  LUKS token {tid} (slot {slots}): {kind[8:]} (a person with the token)")
        elif kind == "clevis" and not clevis_text.strip():
            auto += 1
            lines.append(f"FAIL  LUKS token {tid} (slot {slots}): a clevis binding that cannot be read (clevis)")
    for slot, pin, cfg in clevis_bindings(clevis_text):
        auto += 1
        if _needs_network(pin, cfg):
            lines.append(f"PASS  clevis slot {slot}: {pin} needs a Tang server (opens only in the hospital)")
        else:
            lines.append(
                f"FAIL  clevis slot {slot}: {pin} opens the disk without the hospital network "
                "(bind sss t=2 of tang and tpm2: deploy/hardening/disk-unlock.sh bind)"
            )
    if auto == 0:
        lines.append("WARN  LUKS: no automatic unlock: the box waits for the passphrase after every restart")
    return lines


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="luks_policy.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("device", nargs="?", help="the LUKS device (runs cryptsetup and clevis)")
    ap.add_argument("--dump", help="saved `cryptsetup luksDump --dump-json-metadata` output")
    ap.add_argument("--clevis", help="saved `clevis luks list -d DEV` output")
    a = ap.parse_args(argv)
    if a.dump:
        with open(a.dump, encoding="utf-8") as fh:
            dump_text = fh.read()
        clevis_text = open(a.clevis, encoding="utf-8").read() if a.clevis else ""  # noqa: SIM115
    elif a.device:
        dump_text = _run(["cryptsetup", "luksDump", "--dump-json-metadata", a.device])
        clevis_text = _run(["clevis", "luks", "list", "-d", a.device])
    else:
        ap.error("a device or --dump")
    try:
        dump = json.loads(dump_text) if dump_text.strip() else None
    except ValueError:
        dump = None
    if dump is None:
        print(f"FAIL  LUKS: cannot read the LUKS2 header of {a.device or a.dump} (cryptsetup 2.4 or later, as root)")
        return 1
    lines = judge(dump, clevis_text)
    print("\n".join(lines))
    return 1 if any(ln.startswith("FAIL") for ln in lines) else 0


if __name__ == "__main__":
    sys.exit(main())
