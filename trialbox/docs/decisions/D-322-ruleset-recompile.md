# D-322 The shipped rulesets are recompiled offline, and CI checks them against the compiler

- **Task:** T-613a (TB-PLAN-06 §6.2.3, the wave-P half of T-613; T-STD-06 of the deep review)
- **PR:** this branch (`agent/T-613a-recompile`)
- **Date:** 2026-11-10
- **Status:** proposed
- **Closes:** STD-040; STD-001 with PR #70 (the shipped SQL and CQL now carry its unit conversions)

## Context

Five shipped rulesets (GZQO, GOUT-COH, RA-BIO, RA-COH, ONC-OSI) were compiled before the family expansion (D-113,
D-122). Their ValueSets were short exact lists: rheumatoid arthritis had 5 codes where the compiler gives 418 and
the families M05 and M06. A patient coded `M06.09` failed RA-BIO INC-02, and a failed inclusion is a hard exclusion
(STD-040). A recompile through the compile service did not help: an incremental compile reuses the approved
ValueSets. Nothing compared a committed ruleset with what the compiler gives today.

## Decision

1. **Offline recompile.** `python -m tools.build_rulesets --recompile [ID ...]` rebuilds a shipped ruleset with no
   stack and no model. Its concepts come from its extraction cassette (`services/llm_stub/cassettes/ir_extract`),
   the input the full build reads with the stub. The ValueSets come from the compiler's own `postprocess` and the
   terminology the compiler resolves through (`resolver.terminology()`), with status `active`. The SQL, CQL and
   ELM come from `Compiler.build_artifacts` over the committed IR in manifest order. The approved IR, the manifest,
   `tests/expected.json`, `tests/equivalence.json` and `tests/patients.ndjson` are kept.
2. **Drift check.** `python -m tools.build_rulesets --check` fails when any shipped ruleset's ValueSets, SQL or CQL
   source differ from that output. It names each file and prints, per ValueSet, the codes before and after and
   the families. CI runs it in the `contracts` job. ELM is not compared there, because the translator needs the
   JVM; `--recompile` writes it.
3. **The release.** The check runs against the release the compiler resolves through
   (`resolver.current_release()`, `TR-9ec75ee6db36` for the Parquet on master today). A change to the terminology
   that moves a shipped ValueSet fails the check in the same pull request. That pull request recompiles.
4. **No pin in the manifests yet.** The compile service writes `terminology_release` into a manifest it compiles.
   The offline recompile does not. With a pin, the runtime guard refuses the ruleset as soon as the Parquet
   changes, even when no ValueSet moved. Cards in flight change the Parquet (T-614, T-618). The drift check gives
   the same signal in one place, without stopping every run. Pinning the shipped manifests is left to T-613b or
   to the vocabulary cut-over.
5. **Recorded verdicts kept.** No code on synthetic site A is among the codes the recompile added. The recompiled
   SQL agrees 100 % with every recorded CQL verdict in `tests/expected.json` for the five rulesets, as before.
   So the recorded HAPI verdicts stay valid and are not re-recorded.

## Consequences

- A sibling code (`M06.09`, `M05.711`, `C50.912`, ...) now meets the criterion its family stands for.
- The goldens are regenerated once in this pull request: the funnels and SCREEN candidates of the five rulesets
  move where the synthetic hospital uses sibling codes.
- A ruleset with no cassette cannot be recompiled offline. The check says so by name.
