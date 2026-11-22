# The support bundle's scrub: an encoded pseudonym left in part (H-76a, 2026-11-22)

**Reader:** the people who build TrialBox: lane H, the integrator and the reviewer of #1354. Findings for builders,
so in one language.

Card H-76a, the first part of H-76 (the follow-up of H-71, decision D-1354; no new decision), split off to ride alone.
Findings in the register's `--add-from` form: `support-bundle-encoded-pseudonym-gap-2026-11-22/findings.json`
(H76A-01 to H76A-06).

## Pull request body (draft)

- **What was wrong.** On a raw log line, an encoded neighbour (`%2F`, `%22`) joins its hex digit to a pseudonym, so
  the pseudonym rule passed it. The log scrubber's phone pattern then took digits from its middle. The decoded view
  ran after that and saw only fragments, so 8 to 13 hex digits of the pseudonym left the bundle. The invariant test
  `test_the_extended_corpus_still_holds_the_invariant` failed on master about once in 60 runs.
- **What changed.**
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
| H1 (High) the scrub can hang: lining the two lines up by one regex of lazy groups backtracked without end (24 masks on 335 characters: 9.7 s; master 0.04 s) | `_removed` and `_leaks` are gone. The condition is `_MARK.sub("[]", _decode(raw)) == _MARK.sub("[]", clean)`, which is linear. | `test_review_h1_a_line_that_cannot_be_lined_up_does_not_hang_the_scrub` (under 0.5 s); `test_review_the_scrub_of_one_line_is_linear_in_its_masks` (5 shapes, 48 masks under 0.5 s, doubling the masks at most 2.5 times the time) |
| M1 (Medium) two raw rules (phone and a chart pattern) cut a pseudonym into pieces under 8 characters, and the shortcut kept them | The same condition: a raw line whose masks differ from the view's is not kept | `test_review_m1_two_raw_rules_that_cut_a_pseudonym_leave_nothing_of_it`; `test_review_m1_class_*`: chart patterns of 5 to 10 digits, bounded as `mrn_pattern` bounds them and by digits only, 150 seeded pseudonyms each (1,800 in all): no run of 5 or more of a pseudonym's characters left |
| L1 the shortcut is there for two form tests | Stated above, for the integrator's ruling | — |
| L2 the seeds fix the draws | The class test above adds 1,800 draws with chart patterns to the 2,400 of the flake's class test | — |
| L3 no page and no findings | This page and its `findings.json` | — |

What the class test admits: a run of 4 characters of a pseudonym can stand in other text of the line by chance (a
marker's letters, `%2F`), so the test fails on 5 or more. Nothing of the pseudonym is left on purpose.

## Not verified

- Not run on a box, and the 64 MB end-to-end build was not timed.
- The review's "on master, not this card's" list (`%u002F`, entities without `;`, `=2F`, `\057`, five `%25`
  layers, base64, a token split across lines, zero-width characters) is not in this part. H-76 takes it.
