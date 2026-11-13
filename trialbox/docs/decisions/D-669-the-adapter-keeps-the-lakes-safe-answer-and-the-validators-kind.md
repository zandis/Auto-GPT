# D-669 The adapter keeps the lake's safe answer in its own process too, and the validator's kind of problem, not its sentence

- **Task:** NEW-B-28 (the two points D-668 left open; placed by the integrator on 2026-11-13)
- **PR:** this branch (`agent/NEW-B-28-adapter-keeps-the-lakes-safe-answer`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-668 (the adapter keeps an unexpected error's type, not its text), D-664 (the lake's answers:
  `lake.store.error_answer`), D-462 / D-271 / D-531 (what the publish reads of a lake failure: busy, refused,
  "built again since"), D-557 (answers carry no value)

## Context

1. **The lake in the adapter's process.** With `TB_ADAPTER_LAKE=local` (a declared setting; the deploy sets
   `http`, tests and the CLI use `local`) the adapter calls the lake as a library. An engine error then reached
   `lake rebuild failed: <text>` in the night's report and the publish record raw. Over HTTP the lake service
   answers the same failure with D-664's safe sentence. Confirmed by a test: the engine's `Could not convert
   string '...'` text was in the error the adapter got.
2. **The HL7 validator's sentences.** The night's report keeps up to 200 lines of `validation.messages`, each
   `<file> <element>: <the validator's sentence>`. The validator's sentences quote what they refuse: the repo's
   own fixture has `Unknown Code 'N18.30'`. The validator's jar is not on the build machines, so this was checked
   against the shape of its output (an OperationOutcome per sample file), not by running it.

## Decision

1. **A local lake call answers as the lake service does** (`adapter.failure.local_lake`, used by the two local
   branches of `cli.build_config`: rebuild/build and promote). The lake's own refusals pass as they are, class
   and words (`RebuildError` and its busy classes, `OmopError`, `LakeSaid`, `LakeLimitError`, `LakeSchemaError`,
   `StaleSnapshotError`): the publish reads the class and the words, and the service passes the same ones whole.
   Anything else is logged as its type and where it failed (D-668's `log_failure`) and raised as `LakeFailed`
   with `error_answer(exc, "build")`: the type and the lake's fixed sentence.
2. **The wrap is at the source, not at the lines that format the error.** `publish.py` and `backfill.py` cannot
   tell the lake client's error (which carries the service's safe answer as a plain `RuntimeError`) from a raw
   one by its class. So their lines stay as they are, and both forms now hand them safe words.
3. **A line of `validation.messages` is the sample file, the element, the kind of problem and the validator's
   message id** when it gives one: `r00003-Condition.json Condition.code.coding[1].code: code-invalid
   (Terminology_PassThrough_TX_Message)`. Never `details.text` or `diagnostics`. Each part is kept only in its
   own shape (a sample file's name, an element path, a code token); anything else is `?` or left out.
4. **What the steward loses, said plainly**: the validator's sentence (which value set, which profile) is no
   longer in the night's report. The element and the kind say where to look; the sentence is read by running the
   validator on the box against the held night. An element is kept only as names, dots and numbered places
   (`Bundle.entry[0].resource.code`); any other form is `?`.
5. **The JP Core code checks name the problem, not the code**: "the code is not a valid LOINC code (check
   digit)", not "<code> is not ...". The first such line went into the report's `errors`, all of them into
   `profile_validation.messages`. The element path beside it says which code.
6. **The structural validator's line is pydantic's count line or the error's type.** "1 validation error for
   Patient" holds no value; any other first line (a contained resource of an unknown type quotes it) is replaced
   by the error's type.
7. **Only the lake's call is wrapped.** The adapter's own settings (the embedder, the lake's folder) are read
   before the wrap, so a wrong setting is said in its own words. "no lake snapshot <date>"
   (`FileNotFoundError`) passes as the lake's own words, as the service's 404 does.

## What this does not do

- `ValidationResult.per_file` keeps the validator's sentences. The TW-PAS claim check reads them
  (`orchestrator/scenarios/twpas.py`, another lane) and shows a claim's own errors to the person who prepared it.
  Listed for the integrator, not changed here.
- An `AdapterConfig` wired by hand with other callables (tests do this) is not wrapped: `local_lake` is in
  `build_config`, the only place the product makes a local lake.
- Over HTTP the adapter gets the lake's refusals as the client's classes, locally as the lake's own; the
  publish ends in the same state (busy, refused, failed; held or not) either way.
- Whether the pinned validator writes every element as names, dots and numbered places was not checked (the jar
  is not on the build machines): a form it writes otherwise shows as `?`.

## Tests

`tests/unit/test_adapter_lake_words.py`: an engine error of the local lake (rebuild, build, promote) reaches the
adapter as the lake's safe answer, with the type, without the text, and the log has the type only; the lake's own
refusals pass as the same object; a night run in the test process with a local lake that fails keeps the safe
answer in its report; the validation line for three issue shapes; a kind or message id that is not a plain token
is not kept; a file name or element that is not in its shape is `?`; `per_file` is as before. Review fixes: "no lake snapshot" keeps the lake's words; a wrong
setting of the adapter is not reported as a failed build; an issue of an unexpected shape never fails the
validation step; an element is kept only as names, dots and numbered places; the JP Core code checks and the
structural validator's line hold no value.
