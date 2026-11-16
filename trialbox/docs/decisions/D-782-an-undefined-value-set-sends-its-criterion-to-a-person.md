# D-782 A criterion naming a value set no concept candidate defined goes to a person; the protocol compiles

- **Task:** B14 (lane G findings 2026-11-13), under the owner's ruling D-502
- **PR:** #586 (train 16)
- **Date:** 2026-11-14
- **Status:** proposed (merges with train 16)
- **Builds on:** D-98 and stress test #24 (an uncompilable structured criterion goes to a person)

## Decision

`ValueSets.url`, `version` and `codes` raise `criteria_compiler.semantics.UnknownValueSet` for a name no concept
candidate defined. It is a `CompileError`, so `demote_uncompilable` sends the criterion to `human` with `needs_review`
and `compile_error` (a `mixed` one to `note`, keeping its question) and the rest of the protocol compiles; it is still a
`KeyError` for any older caller. Before, the `KeyError` escaped `demote_uncompilable`, `build_artifacts` and `/compile`:
HTTP 500 and every other criterion of the protocol lost (public protocol NCT03887455, the "CDR score" lines).

## Not changed

On approve, a reviewer who sets such a criterion back to structured gets a 422 naming the value set, not the
criterion, and the compile warnings use compiler words: a wording card with lane C2.

## Test

`tests/unit/test_undefined_valueset_demotes.py`.
