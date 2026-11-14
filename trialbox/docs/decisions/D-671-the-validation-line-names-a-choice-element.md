# D-671 The night's validation line names a choice element as the validator writes it

- **Task:** NEW-B-30 (from lane E's one run of the real HL7 validator, D-682 / #520; placed by the integrator on
  2026-11-13)
- **PR:** this branch (`agent/NEW-B-30-validation-line-names-choice-elements`), cut from lane E's #520
  (`0ba9c49d`), which is cut from #516
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-669 (a line of the night's `validation.messages` is the sample file, the element, the kind of
  problem and the message id; each part only in its own shape), D-682 (lane E's run of the real jar on synthetic
  resources)

## Context

D-669 could not run the HL7 validator (its jar is not on the build machines) and kept an element only as names,
dots and numbered places, anything else as `?`. Lane E ran the real jar once on synthetic resources (D-682): the
night's lines held no value, and three of six lines said `?` for the element. The validator writes a choice
element as `Observation.value[x].value` and as `Observation.value.ofType(Quantity)`. Not a leak: the line said
less than it could, and the element is what tells a steward where to look.

## Decision

1. **An element's shape takes the two forms**: a name may carry the choice mark `[x]` in place of a numbered
   place (`value[x]`), and a name may be followed by `.ofType(<Name>)`, once.
2. **Still only names.** A name and a type's name are one word of the plain letters and digits (A-Z, a-z, 0-9);
   a place is a number in plain digits. At most one bracket per name, before `ofType`. A path starts with a
   name. Any other form is `?`, as before: `where(...)`, `exists()`, a list of types, two `ofType` in a row, a
   slice name after a colon, a bracket with anything but a number or `x`, a bracket after `ofType(...)`, letters
   or digits of another script. A `location` (the validator's other way to say where: a line and column, an
   XPath) is `?` too.
3. **`publish._said` repeats the lake's `detail` only.** With no `detail` in an answer it put the whole body
   before the error's text (found by this card's review by running). Now only a `detail` that is a sentence is
   repeated; the status line stays.

## What was tested, and on what

The six lines of lane E's run are lane E's (D-682 names two in full and the two element forms that read `?`);
the run itself is not repeated here, because the jar is not on this machine. The tests use those two lines and
those two forms as recorded, and further paths built from the same two forms. Whether the pinned validator
writes yet another form is known only from that one run: such a form shows as `?`.

## For the across-services list of places that keep an error's text (lane C2's test, D-700)

After #502 (D-668) and #516 (D-669), in the three adapter files that are this lane's:

- **`adapter/backfill.py`**
  - `lake rebuild failed: <type>: <text>`: **safe words when the lake itself answers.** `cfg.rebuild` from
    `cli.build_config` hands either the lake service's answer (D-664) or, with a local lake, the lake's own
    refusal or `LakeFailed` with the same safe answer (D-669). **One gap, in the lake's client, not here** (found
    by this card's review by running): when something other than the lake answers the rebuild call (a proxy's
    page with a 5xx), `lake/client.py` keeps up to 500 characters of that body in its error, and it arrives in
    this line. Closed by D-672 (NEW-B-31, the lake client's card), which keeps the status and not the body.
    Until both are on one base, keep `backfill.py` and `publish.py` on the list for that one path.
  - the feed-guard line (`[str(exc)]`): a `FeedGuardError`, whose sentence is a setting's name and text.
  - `validation failed to run: ...`: `failure.words` (D-668).
- **`adapter/publish.py`**
  - `night <date> is not published: <text>`: a `FutureNight`, dates only.
  - `lake rebuild failed: <text>` (three places) and `_said`: **safe words**, as for the back-fill; one of them is
    a `SnapshotBuilding`, the lake's own refusal.
  - `fhir-store load failed` / `put-back failed`: `failure.words` (D-668).
- **`adapter/validate/validator.py`**
  - `HL7 validator failed to run: <the jar's last output>`: the text is in the exception. On the night's path it
    reaches the report only through `failure.words`, as the type. **Not safe words in itself**: a caller that
    prints the exception (the claim check, a tool) shows the jar's output, which can quote a value. Keep it on
    the list.
  - the structural validator reads an error's first line only to tell pydantic's count line; it keeps that line
    or the type (D-669).
  - `ValidationResult.per_file` and `unsliced` keep the validator's sentence and its raw element for the claim
    check (TW-PAS); D-682 judged them. Not the night's report.

One limit holds for all "safe words" above: an `AdapterConfig` wired by hand with its own lake callables (tests
do this) is not wrapped; the product makes its lake calls in `build_config` only.

## Tests

`tests/unit/test_validation_line_choice_elements.py`: the two lines of the real run read as recorded; six paths
in the two forms are named whole (all six fail on the base, where they read `?`); fourteen other forms are still
`?`; no line holds the value the validator's sentence quotes. After the review: ten more forms a looser shape
would let through are `?` (another script's letters and digits, an underscore, a bracket after `ofType`, two
brackets, `ofType` without its dot, two `ofType` in a row), and `_said` does not repeat a body that is not the
lake's. No state change is added.
