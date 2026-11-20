"""Where does this box stand: in a locked server room, or under a desk? (plan 10 row 10G-11, D-1342). Stdlib only.

    python3 deploy/hardening/host_tier.py --env deploy/.env [--tiers-dir DIR]

The box's tier is the one the installer wrote: ``TB_PROFILE`` in the env file (``deploy/install.sh``), read through
the tier reader ``libs/tb_common/tier_value.py`` (which never raises), field ``desk_side`` of
``models/tiers/<profile>.json``. Review 16 section 2.8 names the desk-side boxes: the RTX 5090 and RTX PRO 6000
workstations under a desk; their records declare ``desk_side: true``. A record that states ``desk_side: false``
(measured or declared) is a server-room box. Anything else (no ``TB_PROFILE``, a label with no record such as
``P-GB10``, a missing or malformed record, a field not stated) is **unknown** and is treated as desk-side, the
stricter case, and the line says so.

Output, two lines: the class (``desk-side``, ``server-room`` or ``unknown``), then one ``PASS``/``WARN`` line in the
form of ``deploy/check_host.sh``. Exit 0 always: the host check decides what the class means.
``--tiers-dir`` is for the tests (``TB_TEST_TIERS_DIR`` in ``check_host.sh``).
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def _tier_value() -> Any:
    """``libs/tb_common/tier_value.py`` by its path (the host has no package install; the module is stdlib only)."""
    spec = importlib.util.spec_from_file_location("tb_tier_value", ROOT / "libs" / "tb_common" / "tier_value.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # a dataclass looks its module up by name
    spec.loader.exec_module(mod)
    return mod


def env_label(env_file: Path) -> str:
    """The last ``TB_PROFILE=`` of the env file, as ``check_host.sh``'s ``envget`` reads it ("" when none)."""
    try:
        text = env_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    label = ""
    for line in text.splitlines():
        if line.startswith("TB_PROFILE="):
            label = line[len("TB_PROFILE=") :].strip()
    return label


def classify(label: str, tiers_dir: Path | None = None) -> tuple[str, str]:
    """(class, the PASS/WARN line) for one ``TB_PROFILE`` label."""
    tv = _tier_value()
    desk = tv.measured("desk_side", env={"TB_PROFILE": label}, tiers_dir=tiers_dir)
    stated = desk.value if desk.case == "measured" else desk.declared if desk.case == "declared" else None
    name = None
    if desk.profile and desk.case in ("measured", "declared", "not_measured"):
        try:  # the record's own tier name, through the reader's one bounded read
            doc = tv.read_record((tiers_dir or tv.TIERS_DIR) / f"{desk.profile}.json")
            name = doc.get("tier") if isinstance(doc, dict) else None
        except (OSError, ValueError):
            name = None
    shown = f"TB_PROFILE {label} ({desk.profile}" + (f", tier {name}" if isinstance(name, str) else "") + ")"
    if stated is True:
        return "desk-side", (
            f"PASS  tier: {shown}, a desk-side box (models/tiers/{desk.profile}.json): "
            "a TPM-only disk unlock is refused in VALIDATION and PRODUCTION"
        )
    if stated is False:
        return "server-room", f"PASS  tier: {shown}, a server-room box (models/tiers/{desk.profile}.json)"
    why = {
        "unknown_profile": f"TB_PROFILE {label or '(unset)'} has no tier record",
        "no_record": f"TB_PROFILE {label}: {desk.why}",
        "malformed": f"TB_PROFILE {label}: {desk.why}",
    }.get(desk.case, f"{shown}: desk_side not stated")
    return "unknown", (
        f"WARN  tier unknown ({why}): treated as a desk-side box, the stricter case: "
        "a TPM-only disk unlock is refused in VALIDATION and PRODUCTION"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="host_tier.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--env", required=True, help="the env file the installer wrote (deploy/.env)")
    ap.add_argument("--tiers-dir", help="the tier records' folder (the tests only)")
    a = ap.parse_args(argv)
    kind, line = classify(env_label(Path(a.env)), Path(a.tiers_dir) if a.tiers_dir else None)
    print(kind)
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
