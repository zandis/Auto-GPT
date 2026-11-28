"""Instantiate the unsigned card proposals of the held-back protocols and compile what the compiler reads today.

    PYTHONPATH=libs:services:. python -m bench.invest_j4.run --proposals proposals.jsonl --cards-dir cards --out OUT

Writes per protocol a bench ruleset (ir/, valuesets/, sql/, cql/) and, in OUT: trial_stage.jsonl (one row per line and
stage, the ledger's columns), lines.tsv, summary.tsv, reasons.tsv, shared_instances.tsv. Nothing here is approved.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from criteria_compiler.compile_cql.generator import CqlGenerator
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.terminology.mapper import Terminology, ValueSets

from bench.invest_j4.instantiate import ALIASES, Uncompiled, atoms_hash, card_version, instantiate, valueset

VERSION = "0.1.0"
LOOKBACK = 36


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _try(render: Any, crits: list[Any]) -> tuple[str | None, str]:
    t = time.perf_counter()
    try:
        render(crits)
        return None, f"{(time.perf_counter() - t) * 1000:.0f}"
    except Exception as e:
        return f"{type(e).__name__}: {e}"[:160], f"{(time.perf_counter() - t) * 1000:.0f}"


def run(proposals: Path, cards_dir: Path, out: Path) -> dict[str, Any]:
    run_id = "j4f-" + _sha(proposals.read_text("utf-8"))[:8]
    by_nct: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for ln in proposals.read_text("utf-8").splitlines():
        r = json.loads(ln)
        by_nct[r["nct"]].append(r)
    term = Terminology()
    rows: list[dict[str, Any]] = []
    lines_tsv = ["nct\tline\tside\tcards\tstatus\treason\tdetail\tcompiled_as\tstrict"]
    summary = ["nct\tlines\tcompiled\tshare\tstrict_share\tcoded_share\tcoded\thuman\tvacuous\tno_card\tuncompiled"]
    reasons: collections.Counter[tuple[str, str]] = collections.Counter()
    shared: dict[str, dict[str, Any]] = {}
    for nct, recs in sorted(by_nct.items()):
        rs = f"J4-{nct}"
        n = 0
        crits: list[Any] = []
        per_line: list[dict[str, Any]] = []
        for r in recs:
            cards = r["proposal"]["cards"]
            info: dict[str, Any] = {"rec": r, "crits": [], "as": [], "fail": [], "cards": []}
            per_line.append(info)
            for e in cards:
                name = e.get("card") if isinstance(e, dict) else None
                info["cards"].append(name or "?")
                try:
                    if not isinstance(name, str):
                        raise Uncompiled("card_outside_29", "malformed entry")
                    ver = (
                        card_version(cards_dir, ALIASES.get(name, name))
                        if (cards_dir / f"{ALIASES.get(name, name)}.yaml").exists()
                        else VERSION
                    )
                    n += 1
                    c, how = instantiate(rs, n, r["side"], r["text"], name, e.get("params") or {}, ver)
                    info["as"].append(how)
                    if c is not None:
                        info["crits"].append(c)
                        crits.append(c)
                        h = shared.setdefault(atoms_hash(c), {"card": name, "ncts": set(), "lines": 0, "how": how})
                        h["ncts"].add(nct)
                        h["lines"] += 1
                except Uncompiled as u:
                    info["fail"].append((u.code, u.detail, name))
        names = sorted({a.valueset for c in crits for a in c.atoms if a.valueset not in (None, "NONE")})
        vsd = {nm: valueset(nm) for nm in names}
        vsi = ValueSets(rs, vsd, term)
        sqlg, cqlg = SqlGenerator(rs, VERSION, vsi), CqlGenerator(rs, VERSION, vsi, LOOKBACK)
        ok: list[Any] = []
        for info in per_line:
            r = info["rec"]
            lid = f"{nct}:{r['line']}"
            tsha = _sha(r["text"])
            base = {"run_id": run_id, "nct": nct, "source": "ctgov", "section_region": r["side"], "line_id": lid,
                    "line_text_sha": tsha, "model_raw_json": None, "gold": None}  # fmt: skip

            def row(
                stage: str,
                status: str,
                reason: str | None,
                out_: dict[str, Any],
                ms: str = "0",
                ih: str = "",
                base: dict[str, Any] = base,
                lid: str = lid,
            ) -> None:
                rows.append({**base, "row_key": _sha(f"{run_id}|{lid}|{stage}")[:16], "stage": stage, "inputs_hash": ih,
                             "output_json": json.dumps(out_, sort_keys=True), "status": status, "reason_code": reason,
                             "ms": int(ms)})  # fmt: skip

            ih = _sha(json.dumps(r["proposal"]["cards"], sort_keys=True))[:16]
            if not r["proposal"]["cards"]:
                row("instantiate", "no_card", "no_card", {}, ih=ih)
                status, reason, detail = "no_card", "no_card", ""
            elif info["fail"]:
                code, detail, name = info["fail"][0]
                row("instantiate", "uncompiled_construct", code, {"failed": [list(f) for f in info["fail"]]}, ih=ih)
                status, reason = "uncompiled_construct", code
                reasons[(code, name)] += 1
            else:
                row("instantiate", "ok", None, {"criteria": [c.id for c in info["crits"]], "as": info["as"]}, ih=ih)
                status, reason, detail = "ok", "", ""
                if info["crits"]:
                    es, ms = _try(sqlg.render, info["crits"])
                    ec, mc = _try(cqlg.render, info["crits"])
                    row(
                        "compile_sql",
                        "ok" if not es else "CompileError",
                        "compile_error" if es else None,
                        {"error": es} if es else {},
                        ms,
                        ih,
                    )
                    row(
                        "compile_cql",
                        "ok" if not ec else "CompileError",
                        "compile_error" if ec else None,
                        {"error": ec} if ec else {},
                        mc,
                        ih,
                    )
                    if es or ec:
                        status, reason, detail = "CompileError", "compile_error", es or ec or ""
                        reasons[("compile_error", info["cards"][0])] += 1
                    else:
                        ok += info["crits"]
            info.update(status=status, reason=reason, detail=detail)
            how = "+".join(sorted(set(info["as"]))) if status == "ok" else ""
            strict = status == "ok" and not any(c in ALIASES for c in info["cards"])
            info["strict"] = strict
            lines_tsv.append(
                "\t".join(
                    [
                        nct,
                        str(r["line"]),
                        r["side"],
                        ",".join(info["cards"]),
                        status,
                        reason,
                        str(detail)[:80],
                        how,
                        str(strict),
                    ]
                )
            )
        pdir = out / "rulesets" / rs
        if ok:
            for sub in ("ir", "valuesets", "sql", "cql"):
                (pdir / sub).mkdir(parents=True, exist_ok=True)
            for c in ok:
                (pdir / "ir" / f"{c.id}.json").write_text(
                    c.model_dump_json(by_alias=True, exclude_none=True, indent=1), "utf-8"
                )
            for nm in sorted({a.valueset for c in ok for a in c.atoms if a.valueset not in (None, "NONE")}):
                (pdir / "valuesets" / f"{nm}.json").write_text(json.dumps(vsd[nm], sort_keys=True), "utf-8")
            (pdir / "sql" / f"{rs}.sql").write_text(sqlg.render(ok), "utf-8")
            (pdir / "cql" / f"{cqlg.library}.cql").write_text(cqlg.render(ok), "utf-8")
        tot = len(per_line)
        cnt = collections.Counter(i["status"] for i in per_line)
        hows = collections.Counter(h for i in per_line if i["status"] == "ok" for h in (set(i["as"]) or {"vacuous"}))
        coded = sum(1 for i in per_line if i["status"] == "ok" and set(i["as"]) <= {"coded", "vacuous"} and i["as"])
        strict_n = sum(1 for i in per_line if i["strict"])
        shares = [cnt["ok"] / tot, strict_n / tot, coded / tot]
        counts = [hows["coded"], hows["human"], hows["vacuous"], cnt["no_card"]]
        counts.append(cnt["uncompiled_construct"] + cnt["CompileError"])
        cells = [nct, str(tot), str(cnt["ok"]), *[f"{x:.3f}" for x in shares], *map(str, counts)]
        summary.append("\t".join(cells))
    out.mkdir(parents=True, exist_ok=True)
    (out / "trial_stage.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), "utf-8")
    (out / "lines.tsv").write_text("\n".join(lines_tsv) + "\n", "utf-8")
    (out / "summary.tsv").write_text("\n".join(summary) + "\n", "utf-8")
    (out / "reasons.tsv").write_text(
        "reason\tcard\tlines\n"
        + "".join(f"{a}\t{b}\t{v}\n" for (a, b), v in sorted(reasons.items(), key=lambda kv: -kv[1])),
        "utf-8",
    )
    (out / "shared_instances.tsv").write_text(
        "atoms_hash\tcard\tcompiled_as\tprotocols\tlines\n"
        + "".join(
            f"{k}\t{v['card']}\t{v['how']}\t{len(v['ncts'])}\t{v['lines']}\n"
            for k, v in sorted(shared.items(), key=lambda kv: -len(kv[1]["ncts"]))
        ),
        "utf-8",
    )
    return {"run_id": run_id, "rows": len(rows), "protocols": len(by_nct)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--proposals", type=Path, required=True)
    ap.add_argument("--cards-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    print(json.dumps(run(a.proposals, a.cards_dir, a.out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
