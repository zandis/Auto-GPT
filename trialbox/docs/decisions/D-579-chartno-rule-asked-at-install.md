# D-579 The chart-number rule is asked at install and written to the box's settings

- **Task:** NEW-DIN-3, the installer's half (DIN-003; given to lane D by the integrator on 2026-11-12; the opt-out
  desk's half is lane E's, the first-run page's is lane C's)
- **PR:** this branch (`agent/NEW-DIN-3-chartno-rule-at-install`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Builds on:** D-301 (`tb_common.chartno`: one normaliser for chart numbers; the site's rule is
  `TB_CHARTNO_RULE`, default `asis`)

## Context

`tb_common.chartno` says the rule is "set once at installation from the hospital's chart-number format". Nothing
set it: no question in the settings wizard, no line in `deploy/.env`. Every box ran on `asis`, where leading zeros
are significant: a sheet that lost them (`00123456` saved as `123456`) gives a second pseudonym for the same
patient, and an opt-out or a fact filed under one spelling does not meet the record under the other.

## Decision

1. **The question.** The settings wizard has a question `chartno_rule`, right after the MRN pattern:
   `digits:<width>`, `hex:<width>[:lower]` or `asis`. The answer goes to `deploy/.env` as `TB_CHARTNO_RULE`; every
   service that hashes a chart number reads `.env`, so every path to a pseudonym uses the same rule.
2. **An answer is checked against the MRN pattern.** A rule with a width needs a pattern that accepts a number of
   that width with leading zeros and no number of any other width, asked the way the services read the pattern
   (`re.match`): `^\d{8}$` fits `digits:8`; `^\d{8,10}$`, `^\d{6,8}$` and `\d{8}` without its anchors do not,
   because padding or stripping would then make two valid numbers one. A rule without a width needs a pattern
   that accepts no number with a leading zero.
3. **No answer is `asis`**, the rule every box ran on, with a warning that names the question. A rule is never
   read from the MRN pattern.
4. **On the box**, `tools/box/plan.py` passes `chartno_rule` from the owner's first-run answers when they have the
   field (the page that asks is lane C's).
5. **The rule changes only while the box holds no patient.** No rule and `asis` are the same rule. `tools.box
   apply` asks the box's database for the rows of the pid map before it writes anything: with rows, or when the
   database cannot be asked, a different rule is refused. The settings wizard cannot ask the database and writes
   the whole `.env`, so on a box that already has an `.env` it refuses any rule but the one the box runs on.

## Consequences

- Nothing changes on a box until someone answers the question: no answer writes `asis`.
- **Not built:** a tool that moves a box from one rule to another (it would have to re-key the pid map). And one
  gap: the wizard on a box whose `.env` was removed while its data volumes were kept sees a fresh box. The adapter
  could record the rule beside the site key's fingerprint and refuse another; that is lane E's file.
- An existing site box is not asked: `install.sh` runs the wizard only when there is no `settings.yaml`, and an
  update never runs it. It stays on `asis`.
- The two answer files in the repository answer the question: the rehearsal `digits:8`, site C `asis`.

## After the adversarial review (2026-11-12)

The first version read `digits:n` from an MRN pattern of n digits when there was no answer. The review showed
three ways that makes two patients one, and the derivation is gone:

- Pressing Enter at the pattern question made the wizard's placeholder count as the site's answer.
- A pattern without its end anchor (`\d{8}`) accepts `012345678` in the services; under `digits:8` that number
  becomes `12345678`, another patient's.
- **In `tb_common.chartno` itself, not changed here (another lane's file, reported):** a number wider than the
  rule's width still loses its leading zeros, so `012345678` and `12345678` meet under `digits:8` even with a
  correct pattern, when the feed holds a number the pattern does not describe. The module's text says a longer
  number is never cut and two numbers never become one; for leading zeros that is not true.

Also from the review: the answer check accepted rules on patterns of several widths (now refused); the box's apply
would have set a hand-set rule back to `asis` (now kept); a width that is a digit but not an ASCII number raised a
bare error (now a refusal).

## After the review of the normaliser's fix (#389, lane E; 2026-11-12)

That review found that a rule set on a box which has loaded patients changes their pseudonyms and makes the pid
map report a wrong site key. Item 5 is the answer in the installer's tools. This card is stacked on #389 and
lands with it and with lane C's page.

## After the review of the first-run page (#406, lane C; 2026-11-12)

- **On a box every rule but `asis` was refused.** The box's plan carried no MRN pattern, and the wizard turned
  "no pattern" into the text `None` and checked the rule against it. The owner would pick "digits, 8", the
  accounts would be made, and the install would fail. Now the plan passes the pattern that goes with the rule
  (`digits:8` is `^\d{8}$`, `hex:8` is `^[0-9A-F]{8}$`; a rule without a width, `asis` and no answer give no
  pattern), and a rule with no pattern to check against is taken with a warning.
- **`settings.mrn_regex` was the text `None` on every box**, since before this card: the candidate registry
  refused every chart number that does not start with "None" and the scrubber masked the word. No pattern is now
  the empty string, which every reader (the scrubber, the candidate registry, the adapter's column check, site
  set-up) takes as "no pattern".
- **"Holds no patient" also reads the pid map's `pending` table**: a first night that is staged and not yet
  promoted counts.

