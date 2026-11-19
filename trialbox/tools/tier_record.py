"""The tier record: one file per GPU profile that says what the box is (plan 10 row 10E-1, commitment C-4, D-1320).

``models/tiers/<profile>.json`` (format ``tb-tier-record/1``, schema ``models/tiers/tier_record.schema.json``) holds
what the gateway, the scheduler, the console, the host check, ``doctor`` and the capability page read about the box:
sequences, context, roles on the box, protocol route, night budget, interactive lane, what the console promises.
Each field says its basis and nothing is filled in:

* ``measured``: the value comes from a measurement record of this profile on its own uncapped card; ``source`` is
  the record's path, and a serving record must pass ``tools/serving_config.py``'s rule (``measured_for``).
* ``declared``: a file of the repository declares it; ``source`` is ``path[:line or lines]`` then free text. The
  path must exist and the lines must be in the file.
* ``not_measured``: ``value`` is null and ``measured_by`` names the run or card that would measure it.

A second kind of measured source (10E-1d, D-1320 amended): ``measured_on.peak_record``, a card-memory peak file
(``{"peak_mib", "total_mib", ...}``) with its origin stated in the tier record. It may be the source of
:data:`PEAK_FIELDS` only, and only when the origin names this profile, an uncapped card whose memory total equals the
serving record's, every origin fact (or "not stated in the file"), and the configuration in force that day equals the
serving record's; the value must be ``total_mib - peak_mib``.

A record made under the ballast stand-in (plan 10 row 10E-28: a larger card held at a 32 GB card's free memory,
captured with ``--capped-to "... by ballast"``) is refused: a stand-in is never a tier record. So is any record whose
serving record was capped. Standard library only, so the host's ``python3`` can run it, as ``tools/tiers.py``.

    python3 tools/tier_record.py check [models/tiers/<profile>.json ...]   # every record when none named
    python3 tools/tier_record.py summary models/tiers/<profile>.json      # counts by basis, then each field
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
if str(ROOT / "libs") not in sys.path:
    sys.path.insert(0, str(ROOT / "libs"))

from tb_common import tier_value  # noqa: E402  (the one bounded read of a tier record, card H-51)

TIERS_DIR = ROOT / "models" / "tiers"
SCHEMA_PATH = TIERS_DIR / "tier_record.schema.json"
FORMAT = "tb-tier-record/1"
BASES = ("measured", "declared", "not_measured")
BALLAST = tier_value.BALLAST  # one pattern for the checker and the services' reader (10E-11)
REFUSED = 3
PEAK_FIELDS = ("free_memory_at_peak_mib",)
PEAK_ORIGIN = ("run", "date", "commit_or_bundle", "card", "driver", "capped", "workload", "sampling")
PEAK_CONFIG = ("context_tokens", "judge_sequences", "verifier_sequences", "gpu_memory_utilization")


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


def _is_file(target: Path) -> bool:
    """``target.is_file()``, False where the name cannot be asked about (too long, a NUL: card H-51)."""
    try:
        return target.is_file()
    except (OSError, ValueError):
        return False


def _short(text: str, n: int = 120) -> str:
    return text if len(text) <= n else text[: n - 3] + "..."


def _bounded(path: Path) -> Any:
    """A record a tier record points to, read the bounded, strict way (``tier_value.read_record``)."""
    return tier_value.read_record(path, constants=False)


def _source_problem(source: str, root: Path) -> str | None:
    """Why ``path[:line or lines] ...`` does not point into the repository; None when it does."""
    head = source.split(maxsplit=1)[0] if source.split() else ""
    path, _, lines = head.partition(":")
    target = root / path
    if not path or not _is_file(target):
        return f"source {_short(source)!r}: no file {_short(path)!r} in the repository"
    if lines:
        m = re.fullmatch(r"(\d{1,9})(?:-(\d{1,9}))?(?:,(\d{1,9})(?:-(\d{1,9}))?)*", lines)
        if not m:
            return (
                f"source {_short(source)!r}: lines {_short(lines)!r} are not n, n-m or a list of them "
                "(n of 1 to 9 digits)"
            )
        count = len(target.read_text(encoding="utf-8", errors="replace").splitlines())
        nums = [int(n) for n in re.findall(r"\d+", lines)]
        if any(n < 1 or n > count for n in nums):
            return f"source {source!r}: {path} has {count} lines"
    return None


def _serving_problems(path: str, profile: str, root: Path) -> list[str]:
    """Why the serving record at ``path`` is not a measurement of ``profile`` on its own card."""
    target = root / path
    try:
        rec = _bounded(target)
    except (OSError, ValueError) as exc:
        return [f"serving record {path} is not readable JSON ({exc})"]
    if not isinstance(rec, dict):
        return [f"serving record {path} is not a JSON object"]
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
    peak: str | None = None
    if (
        not isinstance(on, dict)
        or not {"serving_record", "qualification_record"} <= set(on)
        or not set(on) <= {"serving_record", "qualification_record", "peak_record"}
    ):
        why.append(
            "measured_on must name serving_record and qualification_record (a path, or null), and may name peak_record"
        )
    else:
        for key in ("serving_record", "qualification_record"):
            val = on[key]
            if val is not None and (not isinstance(val, str) or not (root / val).is_file()):
                why.append(f"measured_on.{key} {val!r} is not a file in the repository")
        serving = on["serving_record"]
        if isinstance(serving, str) and (root / serving).is_file() and isinstance(prof, str):
            why += _serving_problems(serving, prof, root)
        if on.get("peak_record") is not None:
            peak_why, peak = _peak_problems(on["peak_record"], prof, serving, root)
            why += peak_why
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
        why += [f"field {name!r}: {w}" for w in _field_problems(f, prof, serving, root, name, peak)]
    return why


def _peak_problems(pr: Any, profile: Any, serving: Any, root: Path) -> tuple[list[str], str | None]:
    """Why ``measured_on.peak_record`` is not a measurement of this profile's card; and its path when it is."""
    if not isinstance(pr, dict) or set(pr) != {"path", "origin"}:
        return ["measured_on.peak_record must be {path, origin}"], None
    path, origin = pr["path"], pr["origin"]
    if not isinstance(path, str) or not _is_file(root / path):
        return [f"measured_on.peak_record.path {path!r} is not a file in the repository"], None
    why: list[str] = []
    try:
        doc = _bounded(root / path)
    except (OSError, ValueError) as exc:
        return [f"peak record {path} is not readable JSON ({exc})"], None
    nums = {k: doc.get(k) if isinstance(doc, dict) else None for k in ("peak_mib", "total_mib")}
    if not all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in nums.values()):
        return [f"peak record {path}: peak_mib and total_mib must be positive integers"], None
    if not isinstance(origin, dict):
        return [f"peak record {path}: origin must be an object (the facts of the run it came from)"], None
    for key in PEAK_ORIGIN:
        val = origin.get(key)
        if not isinstance(val, str) or not val.strip():
            why.append(f"peak record {path}: origin.{key} missing (write 'not stated in the file' if it is not)")
    if origin.get("profile") != profile:
        why.append(f"peak record {path}: origin.profile is {origin.get('profile')!r}, not {profile!r}")
    if str(origin.get("capped", "")).strip() != "uncapped":
        why.append(
            f"peak record {path}: taken on a capped card ({origin.get('capped')!r}): a peak is measured on the "
            "profile's own uncapped card"
        )
    extra = sorted(set(origin) - {*PEAK_ORIGIN, "profile", "configuration", "not"})
    why += [f"peak record {path}: unknown origin key {k!r}" for k in extra]
    if not isinstance(origin.get("not"), str) or not origin["not"].strip():
        why.append(f"peak record {path}: origin.not missing (say what the peak is not)")
    try:
        srec = _bounded(root / serving) if isinstance(serving, str) else None
    except (OSError, ValueError):
        srec = None
    if not isinstance(srec, dict):
        return [*why, f"peak record {path}: needs the record's serving record to compare the card and settings"], None
    total = (srec.get("card") or {}).get("memory_total_mib")
    if nums["total_mib"] != total:
        why.append(
            f"peak record {path}: total_mib {nums['total_mib']} is not the serving record's card ({total} MiB): "
            "another card"
        )
    cfg = origin.get("configuration")
    if not isinstance(cfg, dict) or set(cfg) != {*PEAK_CONFIG, "source"}:
        why.append(f"peak record {path}: origin.configuration must state {', '.join(PEAK_CONFIG)} and its source")
    else:
        srv = {s.get("role"): s for s in srec.get("servers") or [] if isinstance(s, dict)}
        today = {
            "context_tokens": lens.pop() if len(lens := {s.get("max_model_len") for s in srv.values()}) == 1 else None,
            "judge_sequences": (srv.get("judge") or {}).get("max_num_seqs"),
            "verifier_sequences": (srv.get("verifier") or {}).get("max_num_seqs"),
            "gpu_memory_utilization": {r: s.get("gpu_memory_utilization") for r, s in srv.items()},
        }
        that_day = {k: cfg[k] for k in PEAK_CONFIG}
        for k in PEAK_CONFIG:
            if that_day[k] != today[k]:
                why.append(
                    f"peak record {path}: {k} that day was {cfg[k]!r}, the serving record's is {today[k]!r}: the "
                    "peak is of another configuration"
                )
        bad = _source_problem(str(cfg["source"]), root)
        if bad:
            why.append(f"peak record {path}: configuration {bad}")
    return why, (path if not why else None)


def _field_problems(
    f: Any, profile: Any, serving: Any, root: Path, name: str = "", peak: str | None = None
) -> list[str]:
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
        if name in PEAK_FIELDS and peak is not None and path == peak:
            try:  # _peak_problems read it already (positive integers, else no peak); a swapped file is a problem
                doc = _bounded(root / peak)
                free = doc["total_mib"] - doc["peak_mib"]
            except (OSError, ValueError, TypeError, KeyError) as exc:
                return [*out, f"peak record {peak} changed while it was checked ({type(exc).__name__})"]
            if f.get("value") != free:
                out.append(f"measured from {peak}: the value must be total_mib - peak_mib ({free})")
        elif path != serving:
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
    """The record at ``path``, read the same bounded way the services read it (``tier_value.read_record``), but
    strict: ``NaN`` and ``Infinity`` are refused (card H-51)."""
    return tier_value.read_record(path, constants=False)


TOO_DEEP = "nested too deep to check (a tier record is a flat object of fields)"


def check(paths: list[Path]) -> dict[Path, list[str]]:
    """The problems of each record named (the profile is the file's stem); a record that cannot be read or walked is
    a problem, never a traceback (card H-51)."""
    out: dict[Path, list[str]] = {}
    for p in paths:
        try:
            rec = load(p)
        except (OSError, ValueError) as exc:
            out[p] = [f"not readable JSON ({exc})"]
            continue
        try:
            out[p] = problems(rec, p.stem)
        except RecursionError:
            out[p] = [TOO_DEEP]
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
        why = check([a.record])[a.record]
        try:  # read again for the summary: a file swapped since the check is no record, not a traceback
            rec = load(a.record) if why[:1] != [TOO_DEEP] and not (why and why[0].startswith("not readable")) else None
        except (OSError, ValueError) as exc:
            why, rec = [f"not readable JSON ({exc})"], None
        fields = rec.get("fields") if isinstance(rec, dict) else None
        if isinstance(fields, dict):  # a record that is not one is refused below with its problems, unsummarized
            n = counts(rec)  # type: ignore[arg-type]
            print(f"{a.record}: measured {n['measured']}, declared {n['declared']}, not measured {n['not_measured']}")
            for name, field in fields.items():
                f = field if isinstance(field, dict) else {}
                gap = f"(not measured: {f.get('measured_by')})"
                shown = f.get("value") if f.get("basis") != "not_measured" else gap
                print(f"  {name}\t{f.get('basis')}\t{json.dumps(shown, ensure_ascii=False)}")
        for w in why:
            print(f"tier record: refused: {a.record}: {w}", file=sys.stderr)
        return REFUSED if why else 0
    paths = a.records or record_files()
    if not paths:
        print("tier record: refused: no tier record under models/tiers/", file=sys.stderr)
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
