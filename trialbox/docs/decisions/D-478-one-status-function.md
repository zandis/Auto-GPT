# D-478 One function where a verdict becomes a status; the verdict carries its basis

- **Task:** T-709 (`docs/plan/31-master-plan-v6.1-addendum.md` §3.1, wave D; TB-PLAN-06.1)
- **PR:** this branch (`agent/T-709-status-of`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Measures:** H2 and M1 (a to d) of `docs/reviews/2026-11-12-architecture/decision.md`, and the rest of H1 (card
  AD-2; root cause R1: a verdict has no owner once it leaves the engine); T-652's open acceptance (the decision
  table is called by no engine, TB-PLAN-06.1 §4.3)
- **Builds on:** D-476 (T-707: `final`), D-477 (T-708: the decision context gives the threshold and the note-block
  decision), T-652 (`services/matching/verdict.py`), D-95/D-97/D-276 (a single model never excludes), T-603 (a
  record that did not fit is flagged), D-441 (contact denial), D-459 and D-460 (the two tests that measure it)

## Context

Three functions turned a patient's verdicts into a status, with four rules that differed: the v1 `tier`
(`orchestrator/scenarios/evaluate.py`), the cascade's own tiers mapped by `verdicts_of`, and NAV's `classify`
with `_ok`; CASE had none and printed one model's "not met" as not met. A low-confidence "met" was `high` on the
cascade and `review` on v1; NAV ignored the run's note-block decision and the over-budget flag, so one model's
answer dropped a patient with no review row.

## Decision

1. **`services/matching/decision.py`** holds the rule once:
   - `answer_of(criterion, verdict, policy)`: what one verdict says for eligibility: `yes`, `no` or `unknown`. A
     note answer says `no` only when it is final, a pair gave it, its confidence reaches the threshold and the run
     may exclude on notes; a "met" below the threshold or with notes left out says `unknown`; an unknown and a
     criterion a person decides say `unknown`.
   - `status_of(ruleset, verdicts, policy)`: `excluded` when an answer is `no`, `review` when one is `unknown`,
     else `high`, with the actions of the open criteria, the number of unknowns and the criteria that excluded.
   - The structured answer itself comes from T-652's table (`matching/verdict.py`): the v1 evaluator's
     `eligibility` is the table's.
2. **The verdict carries its basis.** `criterion_verdict.basis` (schema `candidate_list` 1.4.0): `coded` (the
   records), `pair` (two different models agreed), `single` (one model, or two clients of one model) or `person`.
   Beside `final` (D-476) it is what the rule needs, so a stored row can be read again without the run that wrote
   it.
3. **Every path calls it.** The v1 `tier`, the cascade's published status (`verdicts_of`), MICROBATCH's re-tier
   and NAV's `classify` call `status_of` / `answer_of`; CASE prints `answer_of` per criterion, so one model's "not
   met" is printed as "to check", with the model's reading kept as evidence.
4. **The policy is an argument** (`Policy`: the threshold, whether notes may exclude; from the decision context).
   T-216's "unknown with a reason" rule for counts becomes one more field of it, not a second rule.

5. **What reads a verdict afterwards asks one function too** (review of this card, 2026-11-12).
   `libs/tb_common/verdict_word.py: shown_of(verdict)` gives the word a page, a sheet or a count shows for a
   stored or published verdict, with no criterion and no run policy at hand: a "not met" that one model gave
   (`basis: single`) or that was given while notes could not exclude (`final: false`) is `unknown` with its
   reason (`single_model`, `not_final`), never "not met". `held_back` is the one test; `answer_of` uses it. The
   console's fit line, weekly card and "why" answer, the candidate and NAV workbooks, the NAV draft, the
   "excluded patients and why" document and the feasibility attrition read through it. A test
   (`tests/unit/test_verdict_word.py`) fails when code outside the rule compares a verdict with "fail" or indexes
   a map by a verdict's word; its two lists name every place that may, with the reason.
6. **Safe defaults for a caller that names no policy** (`nav.classify`, the cascade's `DEFAULT_POLICY`): notes
   may not exclude. **Not changed:** a "not met" that states neither `basis` nor `final` is still decided by the
   policy alone (the review asked for it to read as not final). Tried and withdrawn: callers that state no basis
   (the evaluator called by a tool or a test, and the pair's own exclusion tests of other cards) would stop
   excluding altogether; ten tests of other cards say so. The promise the schema makes for a **stored** row is
   kept where stored rows are read: MICROBATCH stamps `final: false` on such a row before it is tiered (D-476
   rule 3). Making every writer state the basis, and then reading "unstated" as not final, is left to the card
   that removes the v1 path.
7. **The hand-off from D-476 is narrowed.** D-476 handed this card "which models answered, on what text". This
   card records the four-value basis per verdict. Which pair (the two build ids), the prompt and the snapshot
   stay per list (`judging`), so a pool row re-tiered week after week cannot name the pair behind a stored
   `basis: pair`. Recording them per row (the build ids and the prompt hash that T-689's kept answers already
   key on) is **not done here and has no card yet**: it belongs with the generations of T-724 or a card of its
   own; the integrator assigns it.
8. **Stated, not changed:** a `mixed` criterion's verdict with no confidence counts as the records' answer and
   excludes whatever the note policy. It is reachable only through the cascade's certified zero-hit (S2), which
   screening does not run (`absence_semantics=False`). Stored lists and reports written before this card are
   left as written and are not flagged; pool rows are derived again at the next re-tier.

## Consequences

- The cascade no longer lists a patient as `high` on a "met" below the confidence threshold: `review`, as v1 did.
- NAV lists a patient whose exclusion one model called present, with a row to confirm, instead of dropping them.
- The expected-failure tables of T-705 and T-706 lose their H2, M1 and H1 lines; what remains is H4 (T-710) and
  FEAS's unknown rule (T-216).

## A criterion a person decides is never silent on the patient (H-10, 2026-11-17)

Lane H's tested walk of a new study under the stub (H-10, #964) listed 4,064 of 4,842 patients as "may meet the
criteria" with nothing open, though three criteria were for a person. The tier is as designed (only criteria a person
decides are open, so the patient stays `high`), but `status_of` put an open item on the row only for a criterion's
`action`, and the compiler makes person criteria with a `human_question` and no action (a line the model gave no
criterion for, D-912; one whose SQL or CQL would not compile). Now each open person criterion leaves an item: its
`action`, else its `human_question`, else "a person decides <id>". Tiers and exclusions are unchanged; only what the
row lists. The committed rulesets' person criteria all carry an action, so their lists do not change.
