# The support bundle's scrub: an encoded pseudonym left in part (H-76a, 2026-11-22)

**Reader:** the people who build TrialBox: lane H, the integrator and the reviewer of #1354. Findings for builders,
so in one language.

Card H-76a, the first part of H-76 (the follow-up of H-71, decision D-1354; no new decision), split off to ride alone.
Findings in the register's `--add-from` form: `support-bundle-encoded-pseudonym-gap-2026-11-22/findings.json`
(H76A-01 to H76A-11).

## Pull request body (draft)

- **What was wrong.** On a raw log line, an encoded neighbour (`%2F`, `%22`) joins its hex digit to a pseudonym, so
  the pseudonym rule passed it. The log scrubber's phone pattern then took digits from its middle. The decoded view
  ran after that and saw only fragments, so 8 to 13 hex digits of the pseudonym left the bundle. The invariant test
  `test_the_extended_corpus_still_holds_the_invariant` failed on master about once in 60 runs.
- **What changed.** Two commits (`4cd66786`, `a25a5c18`) and the fix of the review of #1354 (`edcfec47`, then
  this page's commit).
  - Each line's decoded view is read before any raw rule.
  - The line keeps its own (encoded) form only when the raw rules, decoded, give the decoded view mask for mask.
    Otherwise it is written decoded and scrubbed.
  - The bundle's tests draw every random value from a seed of their own test id.
- **What a box sees.**
  - No part of an encoded pseudonym in a support bundle.
  - A few more log lines are written decoded: those whose raw form would not be masked as its decoded form is.
  - Scrubbing a log full of encoded URLs takes about 1.5 times as long.

### Why the encoded form is kept at all (L1)

Two tests on master pin the encoded form of a scrubbed line: `test_query_and_form_secrets_are_replaced` (`x%3D1`)
and `test_url_userinfo_is_replaced_plain_and_encoded` (`%3A%2F%2F[redacted]%40host`). With the decoded view first
and no shortcut, both fail. They pin the form of the output, not its safety. The shortcut keeps them as they are.
Since the review of #1354 it is safe: the raw line is kept only when its masks, decoded, are the decoded view's masks
one for one. Whether those two tests should instead accept a decoded line is the integrator's ruling.

### Review of #1354 (fix first) and the fix

| Finding | Fix | Test (`tests/unit/test_support_bundle_h76.py`) |
| --- | --- | --- |
| H1 (High) the scrub can hang: lining the two lines up by one regex of lazy groups backtracked without end (24 masks on 335 characters: 9.7 s; master 0.04 s) | `_removed` and `_leaks` are gone. The raw line is kept only when `_same_masks(_decode(raw), clean)`: the two are the same text. That is linear and stricter than the review's form with marks normalised; one bundle's tags are the same for one token, so equal marks compare equal. | `test_review_h1_a_line_that_cannot_be_lined_up_does_not_hang_the_scrub` (under 0.5 s); `test_review_the_scrub_of_one_line_is_linear_in_its_masks` (5 shapes, 48 masks under 0.5 s; since round 3, 4,000 masks at most 6 times the time of 1,000, bounds from one helper) |
| M1 (Medium) two raw rules (phone and a chart pattern) cut a pseudonym into pieces under 8 characters, and the shortcut kept them | The same condition: a raw line whose masks differ from the view's is not kept | `test_review_m1_two_raw_rules_that_cut_a_pseudonym_leave_nothing_of_it`; `test_review_m1_class_*`: chart patterns of 5 to 10 digits, bounded as `mrn_pattern` bounds them and by digits only, 150 seeded pseudonyms each (1,800 in all): no run of 5 or more of a pseudonym's characters left |
| L1 the shortcut is there for two form tests | Stated above, for the integrator's ruling | — |
| L2 the seeds fix the draws | The class test above adds 1,800 draws with chart patterns to the 2,400 of the flake's class test | — |
| L3 no page and no findings | This page and its `findings.json` | — |

What the class test admits: a run of 4 characters of a pseudonym can stand in other text of the line by chance (a
marker's letters, `%2F`), so the test fails on 5 or more. Nothing of the pseudonym is left on purpose.

Mutation pass on the fix: 10 mutants of the condition and the order (keep always, keep never, raw not decoded,
raw against the unscrubbed view, keep when they differ, lengths only, either one inside the other, any case, the old
order). 9 were caught on the first run. The tenth (any case) is caught since one more line of
`test_review_the_raw_line_is_kept_only_when_it_is_the_view_mark_for_mark`: 10 of 10.

### Round 3 of #1354 (`6937ec81`)

| Finding | Fix | Test |
| --- | --- | --- |
| H76A-07 (High, H2 of the re-read) the decoded view was scrubbed on its own: an encoded separator inside a secret's value (`--password a%20b`, `\u0022`, `%0A`, `&#10;`) cut the value there and its rest left. Not on master: this line's own | The secret rule runs on the raw line first: `clean = self._rules(_decode(self.secrets(line)))` (the reviewer's form), checked against every earlier probe | `test_review_a_secret_masked_on_the_raw_line_stays_masked_when_the_line_is_written_decoded` (5 forms) |
| H76A-08 (High, the bench's probe) a secret after an unquoted key (`{password: "S"}`, YAML, a JS object) and a key after `/` (`/token: v`) left a bundle, on master too; a secret's name in mixed case (`pAssWord`) was read as other words | The colon rule takes a quoted value and a key after `/`; a secret's name is also read whole, lower case, without separators | `test_the_probes_of_the_re_read_and_the_bench_leave_nothing`; `test_an_unquoted_key_s_neighbours_leave_nothing` (9 forms) |
| The invariant | Never more secret lines than master's scrub: 4,000 seeded lines (12 forms, 9 names, encodings, an identifier after), through `scrub_text` then `redact_secrets`; master 57aeb293 leaves 1,638, frozen in the test; this head leaves 108, all among master's; 7f9534fb left 1,706 (68 more than master) | `tests/unit/test_support_bundle_never_more.py::test_never_more_secret_lines_than_masters_scrub_on_the_same_corpus` |
| H76A-09 (Low) the timing test's 20 ms slack | Bounds in one helper (`BOUNDS`); 1,000 against 4,000 masks, where the time is far above a timer's noise; no slack | `test_review_the_scrub_of_one_line_is_linear_in_its_masks` |
| H76A-10 (Low) three mutants of the mask comparison died only on the direct `_same_masks` test | Two now die through the public path. The third (any case) is equivalent: decoding never changes case and the masks are fixed text; 20,000 generated lines showed no difference | `test_review_an_encoded_flag_value_beside_an_identifier_leaves_nothing`; `test_review_a_secret_inside_a_log_s_own_brackets_is_not_taken_for_a_mask` |
| H76A-11 (Medium) the intermittent `test_a_member_put_in_past_add_is_scrubbed_before_it_is_written`: another gap, not H2 | `Bundle.add` writes the old log scrubber's pass, run on the raw text: its phone pattern takes a run of 10 or more digits inside a pseudonym (`…e04977802419`) before the pseudonym rule, and 21 hex digits of it leave. On master 2 of 200 random runs fail; on this line 2 of 200 seeds; on H-76 (`b3239845`, the pass is counted, not written) 200 of 200 pass. Not fixed on this line: H-76 holds it | 200 runs, one seed each |

Red before: on 7f9534fb, 12 of the round's tests fail; the invariant counts 68 lines more than master. Mutation pass:
10 mutants (secret rule first off, the colon rule's quoted value off, each quote alone, `/` back in its
look-behind, the space around `:` required, the whole-name read off, three of the mask comparison): 9 caught through
the public tests, with the direct `_same_masks` test left out; the tenth is the equivalent one above.

## Not verified

- Not run on a box, and the 64 MB end-to-end build was not timed.
- The invariant compares with master's scrub on one generated corpus, not on every form a log can write.
- The review's "on master, not this card's" list (`%u002F`, entities without `;`, `=2F`, `\057`, five `%25`
  layers, base64, a token split across lines, zero-width characters) is not in this part. H-76 takes it.
