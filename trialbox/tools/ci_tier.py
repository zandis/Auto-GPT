"""Which tier a CI run gets (CI-TIER, D-970; D-564, D-578, D-969 before it).

    python3 trialbox/tools/ci_tier.py < changed-paths     # prints full=<true|false> and scenarios=<true|false>

The `changes` job of ``.github/workflows/trialbox-ci.yml`` runs it with the runner's python3 (standard library only),
reading what it needs from the environment: EVENT, DRAFT, HEAD_REF, PROVED, DOCS_ONLY, LABELS (the pull request's
labels, one per line, read when the job runs) and CARD_TIER. The changed paths (from the repository root) come on
standard input; a push or a run by hand has none.

* A merge train (a branch ``train/*``), a run by hand and a push to master run everything (a push to master at a
  tree a green train already proved runs the fast tier, D-578). Nothing reaches master untested.
* A card's pull request, ``CARD_TIER=fast`` (the trial of E, D-970): the fast tier, unless a changed file is on
  ``FULL_TIER`` (a path that decides about a patient or guards patient data, the contracts, the gate itself) or the
  pull request carries the label ``ci:full``; then the full tier. The integrator reverts the trial by setting
  ``CARD_TIER: touched`` in the workflow, nothing else.
* A card's pull request, ``CARD_TIER=touched`` (D, the rule before the trial): the full tier, except that a card
  whose every change is under ``trialbox/deploy/``, ``trialbox/tools/`` or ``.github/`` (and none on ``FULL_TIER``)
  skips the scenario jobs (goldens, e2e-simple, demo-boot), which run the services those folders do not hold.
* Whatever ``CARD_TIER`` says: a draft and a docs-only card (D-969) run the fast tier unless labelled ``ci:full``.

``scenarios`` is true whenever ``full`` is, except in that one ``touched`` case.

The tiers' jobs are unchanged by D-1119: the fast tier's `checks` job ends with the guard tests (the test files marked
``guard``, static readers of the tree, no database) and the collection check of a pull request's changed test files,
so every tier runs them (``make guard`` locally). The log says so under the tier's reason.
"""

from __future__ import annotations

import fnmatch
import os
import sys
from collections.abc import Iterable, Mapping

LABEL = "ci:full"
CARD_TIERS = ("fast", "touched")
#: D-970: a card's pull request that changes any of these runs the full tier on its own pull request (condition iii,
#: the integrator's list on #639). A pattern ending in ``/**`` is a folder and all below it; any other is matched
#: whole (``*`` as in fnmatch). tests/unit/test_ci_tier.py checks each still matches a file.
FULL_TIER: tuple[str, ...] = (
    # decides about a patient
    "trialbox/services/matching/**",
    "trialbox/services/criteria_compiler/**",
    "trialbox/rulesets/**",
    "trialbox/services/orchestrator/scenarios/**",
    "trialbox/libs/tb_common/ruleset.py",
    "trialbox/libs/tb_common/scores.py",
    "trialbox/libs/tb_common/score_defs.json",
    "trialbox/libs/tb_common/phenotypes.py",
    "trialbox/libs/tb_common/derived.py",
    "trialbox/libs/tb_common/derived_store.py",
    "trialbox/libs/tb_common/recall.py",
    "trialbox/libs/tb_common/notmatched.py",
    "trialbox/libs/tb_common/verdict_word.py",
    "trialbox/libs/tb_common/labvalue.py",
    "trialbox/libs/tb_common/labunit.py",
    # the gateway and the guards
    "trialbox/services/gateway/**",
    "trialbox/services/model_guard/**",
    "trialbox/services/guard/**",
    "trialbox/libs/tb_common/routing.py",
    "trialbox/libs/tb_common/llm.py",
    "trialbox/libs/tb_common/pair.py",
    "trialbox/models/**",
    # guards patient data: masking, small cells, access, identity
    "trialbox/libs/tb_common/phi_guard*",
    "trialbox/libs/tb_common/feedguard.py",
    "trialbox/libs/tb_common/smallcell.py",
    "trialbox/libs/tb_common/authz.py",
    "trialbox/libs/tb_common/authz_matrix.yaml",
    "trialbox/libs/tb_common/service_auth.py",
    "trialbox/libs/tb_common/chartno.py",
    "trialbox/libs/tb_common/subject.py",
    "trialbox/services/doc_parser/**",
    "trialbox/services/adapter/**",  # ingest, chart numbers, pseudonyms: it guards identity
    # which rows a lake query may return: the query guard, the tombstones, the query path
    "trialbox/services/lake/sqlguard.py",
    "trialbox/services/lake/store.py",
    "trialbox/services/lake/source.py",
    "trialbox/services/lake/app.py",
    # erasure, consent and opt-out
    "trialbox/libs/tb_common/erasure.py",
    "trialbox/libs/tb_common/optout.py",
    "trialbox/libs/tb_common/retention.py",
    "trialbox/services/datacore/**",  # the consent and withdrawal state (lifecycle), the opt-out worker
    "trialbox/services/console/templates/site_optouts.html",
    # patient files leave the box: mail, the sponsor's systems
    "trialbox/services/mail_gateway/**",
    "trialbox/services/rc_bridge/**",
    "trialbox/services/edc/**",
    # key sealing and pseudonyms
    "trialbox/libs/tb_common/kek.py",
    "trialbox/libs/tb_common/crypto.py",
    "trialbox/libs/tb_common/objstore.py",
    "trialbox/tools/keys.py",
    "trialbox/tools/key_escrow.py",
    "trialbox/tools/key_ceremony.py",
    "trialbox/deploy/hardening/seal_keys.sh",
    "trialbox/deploy/hardening/trialbox-unseal.service",
    # the contracts the services share
    "trialbox/schemas/**",
    # the gate itself
    ".github/workflows/trialbox-ci.yml",
    "trialbox/tools/ci_tier.py",
    "trialbox/tools/test_shard.py",
    "trialbox/tests/conftest.py",
    "trialbox/Makefile",
)
#: D-1119: wording only, the log's second line; the guard step is a step of `checks`, which every tier runs
GUARD_NOTE = "every tier runs the guard tests and the collection check, the last steps of `checks` (D-1119)"
#: D (CARD_TIER=touched): a card that changes only these skips the scenario jobs
NO_SCENARIOS = ("trialbox/deploy/", "trialbox/tools/", ".github/")


def matches(path: str, pattern: str) -> bool:
    if pattern.endswith("/**"):
        return path.startswith(pattern[:-2])
    return fnmatch.fnmatchcase(path, pattern)


def on_full_tier(paths: Iterable[str]) -> list[str]:
    """The changed paths that are on ``FULL_TIER``."""
    return [p for p in paths if any(matches(p, pat) for pat in FULL_TIER)]


def decide(env: Mapping[str, str], paths: list[str]) -> tuple[bool, bool, str]:
    """``(full, scenarios, why)`` for one run."""
    event, head = env.get("EVENT", ""), env.get("HEAD_REF", "")
    labels = {x.strip() for x in env.get("LABELS", "").splitlines() if x.strip()}
    card_tier = env.get("CARD_TIER", "") or "fast"
    if card_tier not in CARD_TIERS:
        return True, True, f"CARD_TIER={card_tier!r} is not one of {CARD_TIERS}: the full tier"
    if event == "push":
        if env.get("PROVED") == "true":
            return False, False, "master at a tree a green train proved (D-578): the fast tier"
        return True, True, "a push to master: everything"
    if event != "pull_request":
        return True, True, f"{event or 'a run'}: everything"
    if head.startswith("train/"):
        return True, True, "a merge train: everything"
    if LABEL in labels:
        return True, True, f"labelled {LABEL}: the full tier"
    if env.get("DRAFT") == "true":
        return False, False, "a draft: the fast tier (mark it ready, or label it ci:full)"
    if env.get("DOCS_ONLY") == "true":
        return False, False, "documents only (D-969): the fast tier"
    hits = on_full_tier(paths)
    if card_tier == "fast":
        if hits:
            return True, True, f"changes {len(hits)} file(s) on the full-tier list, e.g. {hits[0]}: the full tier"
        return False, False, "a card on no full-tier path (D-970, E): the fast tier; the train runs everything"
    if paths and not hits and all(p.startswith(NO_SCENARIOS) for p in paths):
        return True, False, "only deploy/, tools/, .github/ (D-970, D): the full tier without the scenario jobs"
    return True, True, "a card (CARD_TIER=touched): the full tier"


def main() -> int:
    paths = [ln.strip() for ln in sys.stdin.read().splitlines() if ln.strip()] if not sys.stdin.isatty() else []
    full, scenarios, why = decide(os.environ, paths)
    print(f"full={'true' if full else 'false'}")
    print(f"scenarios={'true' if scenarios else 'false'}")
    print(f"ci_tier: {why}", file=sys.stderr)
    print(f"ci_tier: {GUARD_NOTE}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
