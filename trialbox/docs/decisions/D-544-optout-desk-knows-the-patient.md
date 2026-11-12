# D-544 The opt-out desk is told whether a chart number is a patient of this box; the first-run page asks the chart-number rule

- **Task:** NEW-DIN-3, the console's half (DIN-003 of `docs/reviews/2026-11-12-deep-review/08-data-input.md`; plan
  v7 wave 0). The installer's half is lane D's (D-579, #387); the normaliser's is lane E's (D-591, #389). The three
  land together.
- **PR:** this branch (`agent/NEW-DIN-3-console-knows-the-pid`), stacked on #389's head
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI)
- **Builds on:** D-147 (the opt-out register; a chart number becomes the pseudonym at the door), D-273 (PV-6: the
  lookup is capped and audited, the pseudonym is never given back), D-301 (`tb_common.chartno`), D-466 (the box's
  first-run page), D-579, D-591

## The problem

The research office types a chart number at the opt-out desk. The box hashes whatever is typed into a pseudonym
and the console registers it. A slip of the hand, a number of another hospital, or a number written another way
than the feed writes it gives a pseudonym no record carries: the register then says "opted out", the desk says
"recorded", and the patient who asked is still screened. Since D-591 a number wider than the rule keeps its zeros,
so more mistyped numbers end as a new pseudonym instead of meeting a real one. And the rule itself
(`TB_CHARTNO_RULE`) was asked nowhere on a box: its owner is not at a shell.

## The decision

1. **The box answers "known".** `POST /setup/pseudonym` returns `{"pid", "known"}`. `known` is true when the pid
   map holds a row for that pseudonym, false when it holds none, and null when the map cannot be asked (no map key
   yet, the database away). The orchestrator asks the map through `orchestrator.candidates.known_pid`; the set-up
   service gets it as a callable and has no import of the map.
2. **Only true is "known".** The console (`console.team.to_pid`) treats false, null and an answer without the field
   (an orchestrator of an earlier release) the same way: not known.
3. **The desk refuses, with one way on.** An opt-out typed by chart number for a pseudonym that is not known is
   refused with "this chart number is not a patient of this box: check the number", in three languages, on the
   page and on `/api/v1/site/opt-outs`. The keeper may register it anyway with a written reason of 10 characters
   or more (`unknown_reason`): a patient who is not loaded yet has the right to opt out before the first night.
   The reason and what the box said (`known`: `yes`, `no`, `cannot_say`) are in the `console.opt_out` event; the
   `console.chart_lookup` event, written for every lookup whether registered or not, carries `known` too.
4. **Not asked:** a lift (what is on the register can always be taken off), and a pseudonym typed by the steward
   (no chart number was typed, so there is nothing to mistype into a new pseudonym; #394, D-542, tells the steward
   whether a whole pseudonym is on a list).
5. **The first-run page asks the rule.** The box's first-run form has one more group: the kind (kept as written,
   digits, hexadecimal) and the length when all numbers have one. `tb_common.box_answers` reads it into
   `chartno_rule`, written the way `tb_common.chartno` writes a rule, and the answers file carries it to the
   installer (`tools.box.plan`, D-579). No answer is an empty string: the installer keeps the rule the box runs on.
6. **Only while the box holds no patient.** The page shows the group only when the pid map has no row
   (`console.firstrun.box_holds_patients`), and a rule posted when it has one, or when the map cannot be asked,
   is refused and makes no account. The installer's apply step refuses it too (D-579 item 5); this is the page's
   own check, so the owner is told on the page and not by a failed install.

## What it does not do

- **"Known" is "in the pid map"** (a row, or a merged number). A patient loaded by a path that writes no pid-map
  row is "not known": the FHIR feed (DIN-002), and a patient made in site set-up from a pasted chart or a sheet.
  The desk then asks for the reason; it does not refuse the opt-out.
- **The answer tells the keeper whether a chart number is a patient of the box.** That is the purpose. It is one
  bit per lookup, to an account that keeps the register, under the lookup cap of D-273 (per person and hour) and
  one audit event per lookup.
- **The page does not check the rule against the site's chart-number pattern.** A box's owner is not asked a
  pattern; the installer's wizard checks the two against each other (D-579 item 2) and may refuse at apply.
- **The other caller of the route** (`console.app`: an opted-out patient behind a CASE job) reads `pid` only.

## What the adversarial review changed

One review by a fresh reviewer. Verdict: fix first. No path registered an unknown chart number without a reason
(page, API, `lift` and `known` in odd spellings), and nothing gives the pseudonym or the number back.

- **H1, in lane D's installer, reported and not fixed here:** on a box, `tools.box apply` refuses every rule but
  `asis`: the box's plan carries no chart-number pattern, and the wizard checks the rule against the pattern (the
  text "None"). Until lane D's fix lands, an owner who picks digits or hexadecimal gets a failed install after the
  accounts are made. **The three cards must not land together before that.**
- **H2, "cannot say" was worded "not a patient".** With the map away, the key locked or an orchestrator of an
  earlier release, the keeper was told to doubt a correct number. The desk now says "TrialBox cannot check this
  chart number now" for that, and "not a patient of this box" only when the box said no. A reason is asked in both.
- **M1, a chart number merged into another patient was "not a patient"**, though the register hides the surviving
  patient for it. `known_pid` now also reads the map's aliases.
- **M2, a first night that is staged and not committed** was an empty box to the first-run page.
  `box_holds_patients` reads the staging table too.
- **M3, a width such as a superscript two was a 500.** The rule must now match its written form exactly (ASCII
  digits, one width, nothing cut at a length, never both `chartno_rule` and the form's fields).
- **L3, asking made the schema `pidmap`** on a box that had none: the schema is now looked up, never opened.
- **L5:** the map is asked only when the caller sends `ask_known` (the CASE page's call pays no lookup); a map
  that cannot be opened or read writes one log line with the error's type.
- **Not changed:** the reason is checked for length only, as a lift's reason is (L1); a pseudonym typed in the
  other field skips the check (L2, item 4); a refused lookup counts against the hourly cap, so an unknown number
  registered with a reason costs two (L7); the page offers no lower-case hexadecimal (a file may give it).

## Reuse check

Nothing fits: the question is asked of this box's own pid map through its own route, and the form is one group
on an existing page.

## Dropped (D-311)

No sign-off step.
