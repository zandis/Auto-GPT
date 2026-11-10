# D-313 `trialbox eval qualify` and the qualification record

- **Task:** T-012a (TB-PLAN-06 §6.2.4; first half of TB-ASSESS-01 T-012; WS-02.2, URS-ADM-07, RSK-09, TST-MOD-01)
- **PR:** this branch (`agent/T-012a-qualify`)
- **Date:** 2026-11-10
- **Status:** proposed
- **Number:** given by the integrator for this card (the registry's D-305 row for T-012a is then free)
- **Closes:** CR-079 (qualify half), LLM-029, LLM-020, LLM-021, LLM-031, LLM-030

## Context

A build became `champion` when it was installed. Nothing ran the checks that say a model pair is fit to screen
patients on a given card, and nothing wrote down that they had run (LLM-029, CR-079). The deep review of 2026-11-10
named the checks that were missing: schema enforcement on the real server (LLM-020), repeat-run determinism
(LLM-021), prompts longer than the profile's context (LLM-015), prompt text in the model server's log (LLM-042),
the licence file (LLM-012), the judge gate of PR #64 run as a pair through the gateway (LLM-031), and two
throughput numbers per card (LLM-025).

## Decision

1. **One command.** `python -m tools.trialbox eval qualify --profile <p>` (`tools/qualify.py`) runs fourteen steps
   in a fixed order and writes one JSON record. The steps are `pin`, `serving_record`, `licence`, `schema`,
   `longest_prompt`, `log_marker`, `canary`, `pair_gate`, `determinism`, `throughput`, `n12`, `public_e2e`,
   `goldens` and `planted_defect`. The tool's docstring says what each step checks.
2. **Every call goes through the gateway**, as the box sends it. The judge uses alias `j-workhorse` and the verifier
   uses `v-verifier`. The pair gate uses `NoteJudge` with a verifier and `tb_common.pair.combine`, and is scored
   by `tools.judge_bakeoff.metrics`, so the gate is PR #64's gate in pair mode.
3. **The status follows from the steps.** A record is `passed` only when every step of `STEPS` is in it and
   `passed`. A missing step is a failed step. `check_record` recomputes the status and the body's sha256, so a
   record that was edited, or that says `passed` over a failed step, is refused. It also refuses a record of
   another profile or build, and synthetic weights or a stub run for PRODUCTION (`qualifies_production`).
4. **A broken model must be seen.** The `planted_defect` step runs the same pair with every decided verdict
   flipped. The canary and the pair gate must both fail it.
5. **The stub run (`--stub`, profile `ci` only)** uses an in-process gateway in TEST in front of
   `services/llm_stub`, with no response cache. Every step runs, with three stub rules:
   - The stub answers every canary case `unknown` and fails the canary. The `canary` step passes only on exactly
     that known result (`STUB_CANARY`), by build name, so a change in the stub is still caught.
   - The heavy evidence steps (`n12`, `public_e2e`, `goldens`) run in wiring form: the tool answers `--help`. The
     record says `mode: wiring`.
   - The one prompt the stub has no handler for (`profile_summary`) is listed as not probed.

   A stub record can never qualify a PRODUCTION champion.
6. **Evidence steps on a real profile** take a JSON result file (`--evidence step=file`). It must say `passed`
   (or `ok`) and name the git HEAD of the run. Its sha256 goes into the record.
7. **Records** go to `eval/qualification/` (stub runs to `.cache/qualification/`). They hold hashes, counts,
   codes and verdict labels, never note text, prompts or answers.

## Consequences

- Today every real profile fails `pin` and `licence`. The registry has no weight hash for any real build, and no
  licence row is verified. That is correct: those rows are filled from a verified download (T-012b, T-617b).
- `longest_prompt` fails on any profile where the product's longest prompt does not fit. The chart prompt
  (60,000 characters, Japanese) does not fit 32k. Fixing that is the budgets card (T-603), not this one.
- T-012b uses `check_record` for the registry's `champion` rule and the PRODUCTION gateway refusal. The prompt
  registry's per-prompt record (D-300) stays as it is. The `serving_record` step already lists each prompt's text
  and schema sha.
- `tools/bakeoff.py` says it cannot choose a box model, and its dry run no longer calls an unpriced estimate
  "within cap" (LLM-030).
