"""Card 10A-1: the approved rulesets on ``main`` with an inclusion whose line may negate what its logic asks.

The compiler now holds such an inclusion for a person, but a ruleset approved before that keeps running as it was
approved (the engine runs ``main``; a reused line is held only on the next compile's draft). This scan lists every
approved ruleset on ``main`` with such an inclusion, by ruleset id, version and criterion id, for a person to act on:
recompile the protocol and approve the draft, where the line comes back held. It is read-only: it changes nothing.

    python -m criteria_compiler.negated_inclusions [--rulesets DIR] [--json]     # make negated-inclusion-scan

``trialbox doctor`` runs it (check ``negated_inclusions``, a WARN that names the hits) and the offline install of a
ruleset (``criteria_compiler.import_ruleset``) reports its hits.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from tb_common.ruleset import Ruleset

from criteria_compiler.ir_extract.postprocess import approved_negated
from criteria_compiler.repo import RulesetRepo


@dataclass(frozen=True)
class Hit:
    ruleset: str
    version: str
    criterion: str
    text: str


def ruleset_hits(rs: Ruleset) -> list[Hit]:
    """The inclusions of one ruleset the rule would hold (criteria a reviewer rejected are left out)."""
    return [Hit(rs.id, rs.version, c.id, c.text) for c in rs.active() if approved_negated(c, rs.valuesets)]


def scan(repo: RulesetRepo, ref: str = "main") -> list[Hit]:
    """Every approved ruleset on ``ref``, read from the repository's objects (the working copy is not trusted)."""
    files = repo.files(ref)
    ids = sorted({p.split("/", 1)[0] for p in files if p.count("/") == 1 and p.endswith("/manifest.yaml")})
    out: list[Hit] = []
    for rid in ids:
        mine = {p[len(rid) + 1 :]: b for p, b in files.items() if p.startswith(f"{rid}/")}
        rs = Ruleset.from_files(mine)
        if rs.manifest.status == "approved":
            out.extend(ruleset_hits(rs))
    return out


def default_dir() -> Path:
    return Path(os.environ.get("TB_RULESETS_DIR") or "/data/rulesets")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rulesets", type=Path, default=None, help="the ruleset repository (default TB_RULESETS_DIR)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    path = a.rulesets or default_dir()
    if not (path / ".git").exists():
        print(f"negated inclusions: no ruleset repository at {path}")
        return 0
    hits = scan(RulesetRepo(path))
    if a.json:
        print(json.dumps([asdict(h) for h in hits], ensure_ascii=False))
        return 0
    for h in hits:
        print(f"{h.ruleset} v{h.version} {h.criterion}: {h.text}")
    print(f"negated inclusions: {len(hits)} approved line(s) to recompile and approve (nothing was changed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
