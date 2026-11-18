"""The tier record: one file per GPU profile that says what the box is (plan 10 row 10E-1, commitment C-4, D-1320).

``deploy/tiers/<profile>.json`` (format ``tb-tier-record/1``, schema ``deploy/tiers/tier_record.schema.json``) holds
what the gateway, the scheduler, the console, the host check, ``doctor`` and the capability page read about the box:
sequences, context, roles on the box, protocol route, night budget, interactive lane, what the console promises.
Each field says its basis and nothing is filled in:

* ``measured``: the value comes from a measurement record of this profile on its own uncapped card; ``source`` is
  the record's path, and a serving record must pass ``tools/serving_config.py``'s rule (``measured_for``).
* ``declared``: a file of the repository declares it; ``source`` is ``path[:line or lines]`` then free text. The
  path must exist and the lines must be in the file.
* ``not_measured``: ``value`` is null and ``measured_by`` names the run or card that would measure it.

A record made under the ballast stand-in (plan 10 row 10E-28: a larger card held at a 32 GB card's free memory,
captured with ``--capped-to "... by ballast"``) is refused: a stand-in is never a tier record. So is any record whose
serving record was capped. Standard library only, so the host's ``python3`` can run it, as ``tools/tiers.py``.

    python3 tools/tier_record.py check [deploy/tiers/<profile>.json ...]   # every record when none named
    python3 tools/tier_record.py summary deploy/tiers/<profile>.json      # counts by basis, then each field
    # exit 0 when every record named is complete and sound, 3 with the reasons on stderr when not
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

try:  # as ``tools.tier_record`` (tests) or as a script (``python3 tools/tier_record.py``)
    from tools import serving_config, tiers
except ImportError:  # pragma: no cover - script mode
    import serving_config  # type: ignore[no-redef,import-not-found]
    import tiers  # type: ignore[no-redef,import-not-found]

ROOT = Path(__file__).resolve().parents[1]
TIERS_DIR = ROOT / "deploy" / "tiers"
SCHEMA_PATH = TIERS_DIR / "tier_record.schema.json"
FORMAT = "tb-tier-record/1"
BASES = ("measured", "declared", "not_measured")
BALLAST = re.compile(r"by\s+ballast", re.IGNORECASE)
REFUSED = 3


def schema() -> dict[str, Any]:
    """The JSON Schema of the record (the one list of required fields)."""
    out: dict[str, Any] = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return out


def required_fields() -> list[str]:
    """The fields every tier record must state, in the schema's order."""
    return list(schema()["properties"]["fields"]["required"])


def record_files(tiers_dir: Path = TIERS_DIR) -> list[Path]:
    """Every tier record on file (the schema is not one)."""
    return sorted(p for p in tiers_dir.glob("*.json") if not p.name.endswith(".schema.json"))


def _strings(node: Any) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for k, v in node.items() for s in (*_strings(k), *_strings(v))]
    if isinstance(node, list):
        return [s for v in node for s in _strings(v)]
    return []


def _source_problem(source: str, root: Path) -> str | None:
    """Why ``path[:line or lines] ...`` does not point into the repository; None when it does."""
    head = source.split(maxsplit=1)[0] if source.split() else ""
    path, _, lines = head.partition(":")
    target = root / path
    if not path or not target.is_file():
        return f"source {source!r}: no file {path!r} in the repository"
    if lines:
        m = re.fullmatch(r"(\d+)(?:-(\d+))?(?:,(\d+)(?:-(\d+))?)*", lines)
        if not m:
            return f"source {source!r}: lines {lines!r} are not n, n-m or a list of them"
        count = len(target.read_text(encoding="utf-8", errors="replace").splitlines())
        nums = [int(n) for n in re.findall(r"\d+", lines)]
        if any(n < 1 or n > count for n in nums):
            return f"source {source!r}: {path} has {count} lines"
    return None


def _serving_problems(path: str, profile: str, root: Path) -> list[str]:
    """Why the serving record at ``path`` is not a measurement of ``profile`` on its own card."""
    target = root / path
    try:
        rec = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"serving record {path} is not readable JSON ({exc})"]
    card = rec.get("card") or {}
    capped = str(card.get("capped_to") or "")
    if BALLAST.search(capped):
        return [
            f"serving record {path} was made under the ballast stand-in ({capped!r}, plan 10 row 10E-28): "
            "a stand-in record is never a tier record"
        ]
    why = serving_config.measured_for(rec, profile)
    return [f"serving record {path}: {w}" for w in why]


def problems(rec: Any, profile: str | None = None, root: Path = ROOT) -> list[str]:
    """Why ``rec`` is not a complete, sound tier record of ``profile``; empty when it is."""
    if not isinstance(rec, dict):
        return ["a tier record is a JSON object"]
    why: list[str] = []
    ballast = sorted({s for s in _strings(rec) if BALLAST.search(s)})
    if ballast:
        why.append(
            f"made under the ballast stand-in (plan 10 row 10E-28; {ballast[0]!r}): a stand-in record is never a "
            "tier record"
        )
    sch = schema()
    extra = sorted(set(rec) - set(sch["properties"]))
    why += [f"unknown key {k!r}" for k in extra]
    why += [f"missing {k!r}" for k in sch["required"] if k not in rec]
    if rec.get("schema") != FORMAT:
        why.append(f"schema is {rec.get('schema')!r}, not {FORMAT!r}")
    prof = rec.get("profile")
    if profile is not None and prof != profile:
        why.append(f"profile is {prof!r}, but the file is the record of {profile!r}")
    known = dict(tiers.TIERS)
    if prof not in known.values():
        why.append(f"profile {prof!r} is not one of the tiers' profiles ({', '.join(sorted(known.values()))})")
    elif known.get(str(rec.get("tier"))) != prof:
        mine = next(t for t, g in known.items() if g == prof)
        why.append(f"tier is {rec.get('tier')!r}, but tools/tiers.py gives profile {prof!r} the tier {mine!r}")
    on = rec.get("measured_on")
    serving = None
    if not isinstance(on, dict) or set(on) != {"serving_record", "qualification_record"}:
        why.append("measured_on must name serving_record and qualification_record (a path, or null)")
    else:
        for key in ("serving_record", "qualification_record"):
            val = on[key]
            if val is not None and (not isinstance(val, str) or not (root / val).is_file()):
                why.append(f"measured_on.{key} {val!r} is not a file in the repository")
        serving = on["serving_record"]
        if isinstance(serving, str) and (root / serving).is_file() and isinstance(prof, str):
            why += _serving_problems(serving, prof, root)
    fields = rec.get("fields")
    if not isinstance(fields, dict):
        return [*why, "fields must be an object of field -> {basis, value, source | measured_by}"]
    need = required_fields()
    why += [f"field {f!r} is missing (every tier record states every field)" for f in need if f not in fields]
    why += [f"field {f!r} is not in the schema" for f in sorted(set(fields) - set(need))]
    for name in need:
        f = fields.get(name)
        if f is None:
            continue
        why += [f"field {name!r}: {w}" for w in _field_problems(f, prof, serving, root)]
    return why


def _field_problems(f: Any, profile: Any, serving: Any, root: Path) -> list[str]:
    if not isinstance(f, dict):
        return ["not an object"]
    basis = f.get("basis")
    if basis not in BASES:
        return [f"basis {basis!r} is not one of {', '.join(BASES)}"]
    if basis == "not_measured":
        out = [f"unknown key {k!r}" for k in sorted(set(f) - {"basis", "value", "measured_by"})]
        if "value" not in f or f["value"] is not None:
            out.append("not measured, so its value is null (a figure not measured is never filled in)")
        if not isinstance(f.get("measured_by"), str) or not f["measured_by"].strip():
            out.append("not measured: name the run or card that would measure it (measured_by)")
        return out
    out = [f"unknown key {k!r}" for k in sorted(set(f) - {"basis", "value", "source"})]
    if f.get("value") is None:
        out.append(f"{basis} with no value: a field with no value is not_measured")
    src = f.get("source")
    if not isinstance(src, str) or not src.strip():
        return [*out, f"{basis} with no source"]
    bad = _source_problem(src, root)
    if bad:
        return [*out, bad]
    if basis == "measured":
        path = src.split()[0].partition(":")[0]
        if path != serving:
            out.append(
                f"measured from {path}, which is not the record's measured_on.serving_record ({serving!r}): a "
                "measured value comes from this profile's own measurement"
            )
    return out


def counts(rec: dict[str, Any]) -> dict[str, int]:
    """How many fields are measured, declared and not measured."""
    fields = rec.get("fields") or {}
    return {b: sum(1 for f in fields.values() if isinstance(f, dict) and f.get("basis") == b) for b in BASES}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def check(paths: list[Path]) -> dict[Path, list[str]]:
    """The problems of each record named (the profile is the file's stem)."""
    out: dict[Path, list[str]] = {}
    for p in paths:
        try:
            rec = load(p)
        except (OSError, ValueError) as exc:
            out[p] = [f"not readable JSON ({exc})"]
            continue
        out[p] = problems(rec, p.stem)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="is every tier record named (default: all) complete and sound")
    c.add_argument("records", nargs="*", type=Path)
    s = sub.add_parser("summary", help="counts by basis, then each field")
    s.add_argument("record", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "summary":
        rec = load(a.record)
        n = counts(rec)
        print(f"{a.record}: measured {n['measured']}, declared {n['declared']}, not measured {n['not_measured']}")
        for name, f in (rec.get("fields") or {}).items():
            shown = f.get("value") if f.get("basis") != "not_measured" else f"(not measured: {f.get('measured_by')})"
            print(f"  {name}\t{f.get('basis')}\t{json.dumps(shown, ensure_ascii=False)}")
        why = problems(rec, a.record.stem)
        for w in why:
            print(f"tier record: refused: {a.record}: {w}", file=sys.stderr)
        return REFUSED if why else 0
    paths = a.records or record_files()
    if not paths:
        print("tier record: refused: no tier record under deploy/tiers/", file=sys.stderr)
        return REFUSED
    bad = 0
    for p, why in check(paths).items():
        for w in why:
            print(f"tier record: refused: {p}: {w}", file=sys.stderr)
        if why:
            bad += 1
        else:
            print(f"{p}: complete")
    return REFUSED if bad else 0


if __name__ == "__main__":
    sys.exit(main())
