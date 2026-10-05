"""Export an approved ruleset as a human-readable specification (sponsor / IRB / site file; SPEC §2 tools).

For every criterion: id, kind, class, source text and reference, the computable definition in words (domain,
quantifier, value, window, ValueSet with every code), the fallback / human question, and the review record; plus the
manifest (version, approval, equivalence result) and sha256 of the generated CQL/ELM/SQL so a reader can confirm the
document matches what the box runs. Output: Markdown (and JSON with ``--json``).

    python tools/export_spec.py rulesets/GZQO > GZQO_spec.md
    python tools/export_spec.py rulesets/RA-BIO --json RA-BIO_spec.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libs"))

OPS = {">=": "≥", "<=": "≤", ">": ">", "<": "<", "==": "=", "in": "in"}


def window_text(w: dict[str, Any] | None) -> str:
    if not w:
        return "any time before the index date"
    lo, hi = w.get("from_days"), w.get("to_days")
    if lo is None and hi is not None:
        return f"at least {-hi} days before the index date" if hi < 0 else "up to the index date"
    if lo is not None and (hi or 0) == 0:
        return f"within {-lo} days before the index date"
    return f"between {-lo if lo is not None else '…'} and {-(hi or 0)} days before the index date"


def atom_text(a: dict[str, Any], valuesets: dict[str, Any]) -> str:
    dom = a.get("domain", "")
    if dom == "demographic" and a.get("age"):
        age = a["age"]
        parts = [f"≥ {age['min']:g}" if "min" in age else "", f"≤ {age['max']:g}" if "max" in age else ""]
        return "age " + " and ".join(p for p in parts if p)
    what = a.get("derived") or (valuesets.get(a.get("valueset", ""), {}).get("title") or a.get("valueset", ""))
    q = a.get("quantifier", "any")
    text = {"latest": f"latest {what}", "any": f"any {what}", "count>=": f"≥ {a.get('count')} × {what}"}.get(
        q, f"{q} {what}"
    )
    v = a.get("value") or {}
    if "num" in v:
        text += f" {OPS.get(v.get('op', ''), v.get('op', ''))} {v['num']:g}{(' ' + v['unit']) if v.get('unit') else ''}"
    elif v.get("codes"):
        text += f" result in {', '.join(v['codes'])}"
    if a.get("duration"):
        d = a["duration"]
        text += f" for ≥ {d.get('min_days')} days (gaps ≤ {d.get('gap_days', 0)} days)"
    return f"{text}, {window_text(a.get('window'))}"


def logic_text(node: dict[str, Any], valuesets: dict[str, Any], depth: int = 0) -> str:
    op = node.get("op")
    if op in ("and", "or"):
        inner = f" {op.upper()} ".join(logic_text(x, valuesets, depth + 1) for x in node.get("args", []))
        return f"({inner})" if depth else inner
    if op == "not":
        return "NOT " + logic_text(node["args"][0], valuesets, depth + 1)
    return atom_text(node, valuesets)


def _sha(data: str | bytes) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def export(directory: Path) -> dict[str, Any]:
    from tb_common.ruleset import Ruleset

    rs = Ruleset.load(directory)
    m = rs.manifest
    criteria = []
    for c in rs.ordered():
        vs_used = sorted(
            {str(a) for a in json.dumps(c.logic.model_dump(mode="json")).split('"') if a.startswith("VS_")}
        )
        criteria.append(
            {
                "id": c.id,
                "kind": c.kind,
                "class": c.class_,
                "label": c.label,
                "text": c.text,
                "source_ref": c.source_ref,
                "definition": logic_text(c.logic.model_dump(mode="json", exclude_none=True), rs.valuesets),
                "valuesets": {
                    vs: [
                        f"{x['code']} {x.get('display', '')}".strip()
                        for inc in rs.valuesets.get(vs, {}).get("compose", {}).get("include", [])
                        for x in inc.get("concept", [])
                    ]
                    for vs in vs_used
                },
                "note_question": c.note_question,
                "human_question": c.human_question,
                "fallback": c.fallback,
                "review": c.review.model_dump(mode="json", exclude_none=True) if c.review else None,
            }
        )
    return {
        "ruleset": rs.id,
        "version": rs.version,
        "kind": m.kind,
        "title": m.title,
        "status": m.status,
        "approved": m.review.model_dump(mode="json", exclude_none=True) if m.review else None,
        "equivalence": m.equivalence.model_dump(mode="json", exclude_none=True) if m.equivalence else None,
        "artifacts": {
            **{f"cql/{k}.cql": _sha(v) for k, v in sorted(rs.cql.items())},
            **{f"cql/elm/{k}.json": _sha(v) for k, v in sorted(rs.elm.items())},
            f"sql/{rs.id}.sql": _sha(rs.sql),
        },
        "criteria": criteria,
    }


def markdown(spec: dict[str, Any]) -> str:
    eq = spec.get("equivalence") or {}
    ap = spec.get("approved") or {}
    out = [
        f"# {spec['ruleset']} v{spec['version']} — {spec['title']}",
        "",
        f"Kind: {spec['kind']} · status: {spec['status']} · approved by {ap.get('approved_by', '—')} "
        f"at {ap.get('approved_at', '—')} · CQL≡SQL equivalence {eq.get('overall_pct', '—')} % "
        f"on {eq.get('sample_size', '—')} synthetic patients",
        "",
        "## Criteria",
        "",
    ]
    for c in spec["criteria"]:
        out += [f"### {c['id']} ({c['kind']}, {c['class']}) — {c['label'] or ''}", "", f"> {c['text']}", ""]
        if c["source_ref"]:
            out.append(f"Source: {c['source_ref']}")
        if c["class"] == "structured":
            out.append(f"Definition: {c['definition']}")
        for key, title in (("note_question", "Note question"), ("human_question", "Human question")):
            if c.get(key):
                out.append(f"{title}: {c[key]}")
        if c.get("fallback"):
            out.append(f"Fallback: {c['fallback']}")
        for vs, codes in c["valuesets"].items():
            out.append(f"- {vs}: {'; '.join(codes) if codes else '(derived)'}")
        out.append("")
    out += ["## Artifacts (sha256)", ""] + [f"- `{k}` `{v}`" for k, v in spec["artifacts"].items()]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ruleset_dir", type=Path)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)
    spec = export(args.ruleset_dir)
    if args.json:
        args.json.write_text(json.dumps(spec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    sys.stdout.write(markdown(spec))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
