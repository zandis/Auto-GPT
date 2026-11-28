"""The analysis battery over run ledgers (INVEST-1 §2): failures classified and grouped, the data-gap map, unstable
criteria, retrieval ranks, the drift join, cost, accuracy against gold. Every output is a count table.

The same code runs on synthetic and real ledgers; only the export differs: ``suppress`` blanks every count below
``export.MIN_CELL`` and ``refuse`` raises unless the result holds nothing but closed identifiers and counts.
Nothing here prints a row.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from bench.invest import export, ledger
from bench.invest.analysis import taxonomy

#: deterministic grouping key (INVEST-1 §2, plus the code the key's rows were classified as)
GROUP_KEY = ("side", "stage", "family", "reason_code", "unknown_kind", "card_id", "code")
TOP = 20


def open_runs(run_dirs: Iterable[Path]) -> Any:
    """One DuckDB over several published runs (each a directory with ``MANIFEST.json``): a view per ledger table over
    the union of the files the manifests list. A table no run has is an empty view with the right columns."""
    import duckdb

    con = duckdb.connect(":memory:")
    files: dict[str, list[str]] = defaultdict(list)
    for d in run_dirs:
        manifest = Path(d) / "MANIFEST.json"
        if manifest.exists():
            for rel in sorted(json.loads(manifest.read_text("utf-8"))["files"]):
                files[rel.split("/", 1)[0]].append((Path(d) / rel).as_posix())
    for table, cols in {**ledger.TABLES, "run": ledger.RUN_COLS}.items():
        if files.get(table):
            con.register(table, con.read_parquet(files[table], union_by_name=True))
        else:
            con.register(table, ledger.schema_of(cols).empty_table())
    return con


def runs_under(root: Path) -> list[Path]:
    """Every published run directly under ``root``, or ``root`` itself when it is one."""
    root = Path(root)
    if (root / "MANIFEST.json").exists():
        return [root]
    return sorted(p.parent for p in root.glob("*/MANIFEST.json"))


def criteria_meta(protocol_ids: Iterable[str]) -> dict[tuple[str, str], dict[str, Any]]:
    """(protocol, criterion) -> kind, class and text, from the product's rulesets; ids that are not a ruleset (a note
    set's own name) are skipped."""
    from tools.cascade_e2e import RULESET_DIRS, load_trial

    out: dict[tuple[str, str], dict[str, Any]] = {}
    for pid in sorted(set(protocol_ids)):
        if not any((d / pid / "manifest.yaml").exists() for d in RULESET_DIRS):
            continue
        for c in load_trial(pid).active():
            text = c.text.model_dump(mode="json") if hasattr(c.text, "model_dump") else c.text
            out[(pid, c.id)] = {"kind": c.kind, "class": c.class_, "text": text}
    return out


def _field_of(atoms_json: str | None) -> str:
    try:
        atoms = json.loads(atoms_json) if atoms_json else []
    except ValueError:
        return "none"
    for a in atoms if isinstance(atoms, list) else []:
        if isinstance(a, dict) and a.get("valueset"):
            return str(a["valueset"])
    return "none"


def failure_rows(con: Any, meta: Mapping[tuple[str, str], Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Every failing ``match_stage`` group (one per protocol x criterion x stage x verdict x reason x gold) and every
    failing ``trial_stage`` group, classified."""
    out: list[dict[str, Any]] = []
    rows = con.execute(
        "SELECT protocol_id, criterion_id, stage, verdict, reason_code, unknown_kind, gold, card_id, "
        "any_value(atoms_json), count(*) FROM match_stage WHERE criterion_id <> '' GROUP BY ALL ORDER BY ALL"
    ).fetchall()
    for proto, cid, stage, verdict, reason, kind, gold, card, atoms, n in rows:
        m = meta.get((proto, cid), {})
        gv = taxonomy.gold_verdict(gold, m.get("kind"))
        hit = taxonomy.classify_match(stage, verdict, reason, kind, gv)
        if hit is None:
            continue
        out.append(
            {
                "side": "patient",
                "protocol_id": proto,
                "criterion_id": cid,
                "stage": stage,
                "verdict": verdict,
                "gold": gv,
                "family": taxonomy.family_of(atoms, m.get("class")),
                "field": _field_of(atoms),
                "reason_code": reason,
                "unknown_kind": kind,
                "card_id": card,
                "code": hit[0],
                "preventable": hit[1],
                "n": int(n),
            }
        )
    trial = con.execute(
        "SELECT stage, status, reason_code, count(*), count(DISTINCT nct) FROM trial_stage GROUP BY ALL ORDER BY ALL"
    ).fetchall()
    for stage, status, reason, n, _ncts in trial:
        hit = taxonomy.classify_trial(stage, status, reason)
        if hit is None:
            continue
        out.append(
            {"side": "trial", "protocol_id": None, "criterion_id": None, "stage": stage, "verdict": status,
             "gold": None, "family": "trial", "field": "none", "reason_code": reason, "unknown_kind": None,
             "card_id": None, "code": hit[0], "preventable": hit[1], "n": int(n)}
        )  # fmt: skip
    return out


def group(failures: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic clusters over ``GROUP_KEY``, largest first, each with its preventable share, the instrument a fix
    moves, and the protocols and criteria inside it (largest first)."""
    acc: dict[tuple[Any, ...], dict[str, Any]] = {}
    for f in failures:
        key = tuple(f[k] for k in GROUP_KEY)
        g = acc.setdefault(
            key,
            {**dict(zip(GROUP_KEY, key, strict=True)), "n": 0, "preventable_n": 0, "undetermined_n": 0,
             "protocols": defaultdict(int), "criteria": defaultdict(int)},
        )  # fmt: skip
        g["n"] += f["n"]
        g["preventable_n"] += f["n"] if f["preventable"] == "preventable" else 0
        g["undetermined_n"] += f["n"] if f["preventable"] == "undetermined" else 0
        if f["protocol_id"]:
            g["protocols"][f["protocol_id"]] += f["n"]
            g["criteria"][f"{f['protocol_id']}/{f['criterion_id']}"] += f["n"]
    out = []
    for g in acc.values():
        g["label"] = taxonomy.CODES[g["code"]]
        g["instrument"] = taxonomy.INSTRUMENT[g["code"]]
        g["preventable_share"] = round(g["preventable_n"] / g["n"], 3) if g["n"] else None
        g["protocols"] = dict(sorted(g["protocols"].items(), key=lambda kv: (-kv[1], kv[0])))
        g["criteria"] = dict(sorted(g["criteria"].items(), key=lambda kv: (-kv[1], kv[0]))[:10])
        out.append(g)
    out.sort(key=lambda g: (-g["n"], tuple(str(g[k]) for k in GROUP_KEY)))
    for i, g in enumerate(out, 1):
        g["cluster_id"] = f"D{i:03d}"
    return out


def by_code(failures: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = defaultdict(lambda: {"n": 0, "preventable_n": 0, "undetermined_n": 0})
    for f in failures:
        c = out[f["code"]]
        c["n"] += f["n"]
        c["preventable_n"] += f["n"] if f["preventable"] == "preventable" else 0
        c["undetermined_n"] += f["n"] if f["preventable"] == "undetermined" else 0
    return dict(sorted(out.items()))


def data_gap_map(failures: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Unknowns of the site-data codes (P1-P4) by the view and field their criterion reads: rows, criteria and
    protocols touched, largest first. This is what tells a site which views unlock the most protocols."""
    acc: dict[tuple[str, str, str], dict[str, Any]] = {}
    for f in failures:
        if f["side"] != "patient" or f["code"] not in ("P1", "P2", "P3", "P4") or f["verdict"] != "U":
            continue
        key = (taxonomy.view_of(f["family"]), f["field"], f["reason_code"] or "none")
        g = acc.setdefault(key, {"n": 0, "criteria": set(), "protocols": set()})
        g["n"] += f["n"]
        g["criteria"].add(f"{f['protocol_id']}/{f['criterion_id']}")
        g["protocols"].add(f["protocol_id"])
    out = [
        {"view": v, "field": fld, "reason_code": r, "n": g["n"], "criteria": len(g["criteria"]),
         "protocols": len(g["protocols"])}
        for (v, fld, r), g in acc.items()
    ]  # fmt: skip
    return sorted(out, key=lambda x: (-x["n"], x["view"], x["field"], x["reason_code"]))


def diff_runs(a: Any, b: Any) -> list[dict[str, Any]]:
    """The unstable-criteria table, and the drift join: two ledgers of the same patients (a repeat, another
    concurrency, another model pin) joined on (patient, protocol, criterion); per criterion and basis, how many
    answers were compared and how many changed verdict. A change on a coded criterion is a product bug."""
    import duckdb

    con = duckdb.connect(":memory:")
    for name, src in (("a", a), ("b", b)):
        # the n-th identical repeat of a (patient, criterion, stage, attempt) is paired with the n-th of the other run
        tbl = src.execute(
            "SELECT pid, protocol_id, criterion_id, verdict, basis, coalesce(stage, '') AS stage, "
            "coalesce(attempt, 0) AS attempt, row_number() OVER (PARTITION BY pid, protocol_id, criterion_id, "
            "coalesce(stage, ''), coalesce(attempt, 0) ORDER BY verdict NULLS FIRST, basis NULLS FIRST) AS rep "
            "FROM match_stage WHERE criterion_id <> '' AND stage NOT IN ('S0', 'tier')"
        ).to_arrow_table()
        con.register(name, tbl)
    rows = con.execute(
        "SELECT a.protocol_id, a.criterion_id, coalesce(a.basis, b.basis, 'none') AS basis, count(*) AS n, "
        "count(*) FILTER (WHERE a.verdict IS DISTINCT FROM b.verdict) AS changed "
        "FROM a JOIN b USING (pid, protocol_id, criterion_id, stage, attempt, rep) GROUP BY ALL ORDER BY ALL"
    ).fetchall()
    return [
        {"protocol_id": p, "criterion_id": c, "basis": basis, "n": int(n), "changed": int(ch),
         "rate": round(ch / n, 4) if n else None, "coded_bug": basis == "coded" and ch > 0}
        for p, c, basis, n, ch in rows
    ]  # fmt: skip


def retrieval(con: Any) -> dict[str, Any]:
    """Rank of the gold passage (``gold_quote_rank``): recall at 1, 3 and 5 per protocol; ``no_data`` when no row of
    the ledger carries a rank (the cascade does not keep passage ranks today)."""
    rows = con.execute(
        "SELECT protocol_id, count(*), count(*) FILTER (WHERE gold_quote_rank <= 1), "
        "count(*) FILTER (WHERE gold_quote_rank <= 3), count(*) FILTER (WHERE gold_quote_rank <= 5) "
        "FROM match_stage WHERE gold_quote_rank IS NOT NULL GROUP BY 1 ORDER BY 1"
    ).fetchall()
    if not rows:
        return {"status": "no_data", "rows": []}
    return {
        "status": "ok",
        "rows": [{"protocol_id": p, "n": int(n), "at1": int(r1), "at3": int(r3), "at5": int(r5)}
                 for p, n, r1, r3, r5 in rows],
    }  # fmt: skip


def cost(con: Any) -> list[dict[str, Any]]:
    """Model calls per protocol and stage (from ``model_raw_json``) and wall-clock quantiles where a runner timed
    the stage (``match_timing``)."""
    calls = con.execute(
        "SELECT protocol_id, stage, count(*) AS n, "
        "sum(coalesce(json_array_length(json_extract(model_raw_json, '$.calls')), 0)) AS calls "
        "FROM match_stage WHERE criterion_id <> '' GROUP BY ALL ORDER BY ALL"
    ).fetchall()
    lat = {
        (p, s): (int(n), p50, p99)
        for p, s, n, p50, p99 in con.execute(
            "SELECT m.protocol_id, m.stage, count(*), round(quantile_cont(t.ms_wall, 0.5)), "
            "round(quantile_cont(t.ms_wall, 0.99)) FROM match_stage m JOIN match_timing t USING (row_key) "
            "WHERE t.ms_wall IS NOT NULL GROUP BY ALL"
        ).fetchall()
    }
    out = []
    for p, s, n, c in calls:
        t = lat.get((p, s))
        timed = {"timed": t[0], "p50_ms": t[1], "p99_ms": t[2]} if t else {"timed": 0, "p50_ms": None, "p99_ms": None}
        out.append({"protocol_id": p, "stage": s, "n": int(n), "calls": int(c or 0), **timed})
    return out


def accuracy(con: Any, meta: Mapping[tuple[str, str], Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Per protocol, rows with a gold verdict: correct, wrong decided, decided on unknown, missed (an unknown where
    gold decides)."""
    rows = con.execute(
        "SELECT protocol_id, criterion_id, verdict, gold, count(*) FROM match_stage "
        "WHERE gold IS NOT NULL AND criterion_id <> '' GROUP BY ALL"
    ).fetchall()
    acc: dict[str, dict[str, int]] = defaultdict(
        lambda: {"n": 0, "correct": 0, "wrong_decided": 0, "decided_on_unknown": 0, "missed": 0}
    )
    for proto, cid, verdict, gold, n in rows:
        gv = taxonomy.gold_verdict(gold, meta.get((proto, cid), {}).get("kind"))
        if gv is None or verdict == "not_applicable":
            continue
        a = acc[proto]
        a["n"] += n
        if verdict == gv:
            a["correct"] += n
        elif gv == "U":
            a["decided_on_unknown"] += n
        elif verdict == "U":
            a["missed"] += n
        else:
            a["wrong_decided"] += n
    return [{"protocol_id": p, **v} for p, v in sorted(acc.items())]


def run_battery(
    con: Any, meta: Mapping[tuple[str, str], Mapping[str, Any]], repeat: Any | None = None, name: str = "set"
) -> dict[str, Any]:
    """The whole battery on one ledger handle (``repeat``: a second handle for the unstable table)."""
    fails = failure_rows(con, meta)
    total = con.execute("SELECT count(*) FROM match_stage WHERE criterion_id <> ''").fetchone()[0]
    return {
        "set": name,
        "criterion_rows": int(total),
        "failure_rows": sum(f["n"] for f in fails if f["side"] == "patient"),  # same side as criterion_rows
        "trial_failure_rows": sum(f["n"] for f in fails if f["side"] == "trial"),
        "by_code": by_code(fails),
        "clusters": group(fails),
        "data_gap": data_gap_map(fails),
        "unstable": diff_runs(con, repeat) if repeat is not None else [],
        "retrieval": retrieval(con),
        "cost": cost(con),
        "accuracy": accuracy(con, meta),
    }


# ---- the real-data export -------------------------------------------------------------------------------------------

_COUNT_KEYS = frozenset(
    {"n", "preventable_n", "undetermined_n", "changed", "calls", "timed", "criterion_rows", "failure_rows",
     "correct", "wrong_decided", "decided_on_unknown", "missed", "at1", "at3", "at5", "criteria", "size",
     "protocols", "trial_failure_rows"}
)  # fmt: skip
_SHARE_KEYS = frozenset({"preventable_share", "rate"})
_MS_KEYS = frozenset({"p50_ms", "p99_ms"})
_FREE_TEXT_KEYS = frozenset({"name"})  # cluster names
_CLOSED_TEXT = {"label": frozenset(taxonomy.CODES.values()), "instrument": frozenset(taxonomy.INSTRUMENT.values())}
_CLOSED = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/+\-]{0,95}")
_NAME = re.compile(r"[A-Za-z][A-Za-z ,/()+\-]{0,79}")


#: maps of id -> count: the criteria and protocols of a cluster, the codes and stages of a residual cluster
_COUNT_MAPS = ("protocols", "criteria", "codes", "stages")


def _below(v: Any) -> bool:
    """True for a count that must be blanked: below the minimum cell, or already blanked (``None``)."""
    return v is None or (isinstance(v, int) and not isinstance(v, bool) and v < export.MIN_CELL)


def suppress(b: Any) -> Any:
    """Every count below ``export.MIN_CELL`` blanked, and every share or quantile computed from such a count."""
    if isinstance(b, list):
        return [suppress(x) for x in b]
    if not isinstance(b, dict):
        return b
    out = {k: suppress(v) for k, v in b.items()}
    small = "n" in b and _below(b["n"])
    timed_small = _below(b["timed"] if "timed" in b else b.get("n"))  # a quantile rests on the timed observations
    for k, v in list(out.items()):
        if k in _COUNT_KEYS and isinstance(v, int) and not isinstance(v, bool) and v < export.MIN_CELL:
            out[k] = None
        if (k in _SHARE_KEYS and small) or (k in _MS_KEYS and (small or timed_small)):
            out[k] = None
        if k in _COUNT_MAPS and isinstance(v, dict):
            out[k] = {kk: (None if _below(vv) else vv) for kk, vv in v.items()}
    for share, num in (("preventable_share", "preventable_n"), ("rate", "changed")):
        if share in out and out.get(num) is None and b.get(num):  # share x n would give the blanked numerator back
            out[share] = None
    return out


#: the exporter's own refusal: the battery reuses its checks, so one exception type covers both
Refused = export.Refused


def refuse(b: Any, pids: Collection[str], known_ids: Collection[str]) -> None:
    """Raise unless ``b`` holds only counts, shares, closed identifiers (ruleset ids, codes, stages, value-set names)
    and short cluster names: no patient id, no day-level date, no quote, no unsuppressed small count."""
    pidset, known = set(pids), set(known_ids)
    text = json.dumps(b, ensure_ascii=False)
    if export._DATE.search(text):
        raise Refused("a day-level date is in the export")
    _walk(b, "", pidset, known)


def _walk(v: Any, where: str, pids: set[str], known: set[str]) -> None:
    if isinstance(v, dict):
        for k, x in v.items():
            if not isinstance(k, str) or not _CLOSED.fullmatch(k):
                raise Refused(f"{where}: a key that is not a closed identifier")
            export._check_free(where, k, pids)
            if k in _COUNT_MAPS and isinstance(x, dict):  # id -> count
                for kk, vv in x.items():
                    _walk(kk, f"{where}.{k}", pids, known)
                    if k == "protocols" and kk not in known:
                        raise Refused(f"{where}.{k}: {kk!r} is not a ruleset id")
                    _count(f"{where}.{k}.{kk}", vv)
            elif k in _COUNT_KEYS:
                _count(f"{where}.{k}", x)
            elif k in _SHARE_KEYS:
                if x is not None and not (isinstance(x, int | float) and 0 <= x <= 1):
                    raise Refused(f"{where}.{k}: not a share")
            elif k in _MS_KEYS:
                if x is not None and not isinstance(x, int | float):
                    raise Refused(f"{where}.{k}: not a number")
            elif k in _CLOSED_TEXT:
                if x is not None and x not in _CLOSED_TEXT[k]:
                    raise Refused(f"{where}.{k}: not one of the taxonomy's own words")
            elif k in _FREE_TEXT_KEYS:
                if x is not None and (not isinstance(x, str) or not _NAME.fullmatch(x)):
                    raise Refused(f"{where}.{k}: a name with digits, script or length outside the name rule")
                if isinstance(x, str):
                    export._check_free(f"{where}.{k}", x, pids)
            else:
                _walk(x, f"{where}.{k}", pids, known)
    elif isinstance(v, list):
        for i, x in enumerate(v):
            _walk(x, f"{where}[{i}]", pids, known)
    elif isinstance(v, str):
        if not _CLOSED.fullmatch(v):
            raise Refused(f"{where}: not a closed identifier (a quote, a name or free text)")
        export._check_free(where, v, pids)
        parts = v.split("/")
        if len(parts) == 2 and parts[0] in known and parts[1] not in known:
            raise Refused(f"{where}: {v!r} names a criterion that is not one of the rulesets'")
    elif v is not None and not isinstance(v, bool | int | float):
        raise Refused(f"{where}: a value of type {type(v).__name__}")


def _count(where: str, x: Any) -> None:
    if x is None:
        return
    if isinstance(x, bool) or not isinstance(x, int):
        raise Refused(f"{where}: not a count")
    if 0 < x < export.MIN_CELL:
        raise Refused(f"{where}: count {x} below {export.MIN_CELL} not suppressed")


def protect(b: Mapping[str, Any], pids: Collection[str], known_ids: Collection[str]) -> dict[str, Any]:
    """Suppress, then refuse: the payload that may leave the machine (file or screen)."""
    out: dict[str, Any] = suppress(dict(b))
    refuse(out, pids, known_ids)
    return out


#: a run whose ``sets_json`` names only these (and a ``tag``) is synthetic or public data; any other is real
OPEN_SETS = frozenset({"synthetic", "public"})


def is_open(con: Any) -> bool:
    """True only when the ledger holds runs and every run says it is synthetic or public."""
    rows = con.execute("SELECT sets_json FROM run").fetchall()
    return bool(rows) and all(_open_set(r[0]) for r in rows)


def _open_set(raw: Any) -> bool:
    try:
        d = json.loads(raw)
    except (TypeError, ValueError):
        return False
    return isinstance(d, dict) and bool(set(d) & OPEN_SETS) and set(d) <= OPEN_SETS | {"tag"}


def write_real(path: Path, b: Mapping[str, Any], pids: Collection[str], known_ids: Collection[str]) -> Path:
    """Suppress, refuse, then write: nothing is written when a check fails."""
    out = protect(b, pids, known_ids)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
