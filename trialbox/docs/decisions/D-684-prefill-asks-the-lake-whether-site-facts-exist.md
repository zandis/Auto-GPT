# D-684 The EDC prefill asks the lake whether the site facts exist; the opt-out worker says when it had no snapshot

- **Task:** two findings from lane A2's reviews, sent by the integrator on 2026-11-13: `services/edc/prefill.py`
  decides by an error's text, and the opt-out worker passes over a lake without a snapshot in silence
- **PR:** this branch (`agent/EDC-prefill-site-facts-not-read`), cut from #535's head (D-651)
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-649 and D-650 (`tb_common.lakeprobe`: the lake is asked whether a table is there), D-651 (no code
  decides by the text of an error), D-160 (a draft value always has a citation; unknown never excludes), D-441 (the
  opt-out worker)

## Context

1. `edc.prefill.LakeFacts.site_facts` caught every failure of its query and returned "no site facts" when the
   error's text held the word `site_fact`. The query itself names that table, so nearly any failure of it does. A
   proposed fact then no longer held its draft back (`only_proposed`) and a confirmed fact no longer labelled its
   citation: the coordinator was offered a draft the box should have withheld. Shown by a test with three such
   failures and one real one (a snapshot whose table lacks a column).
2. The opt-out worker's tick reads the hospital registry from the lake's snapshot. With no snapshot name it read
   nothing and said nothing: `registry: None`, `failed: []`. The lake's HTTP client answered "no snapshot" also
   when the lake's health check failed (lane B2 makes it raise).

## Decision

1. **The prefill asks the lake** (`lakeprobe.rows_or_no_table`): only the lake's own answer "this snapshot has no
   table `site_fact`" gives no site facts (a snapshot built before they existed). **Any other failure stops the
   draft**: the caller's error, not a draft without its facts. `services/edc/prefill.py` is off the list of
   `tests/unit/test_no_decision_by_error_text.py`; with it the last decision by an error's text that could hide a
   failure is gone from that list.
2. **A lake that cannot name its snapshot fails the registry step** (`failed: ["registry"]`, held by a test); the
   stores are still cleared by the register in the same tick.
3. **A lake that answers "no snapshot" is said, not passed over**: the tick's result and its `optout.worker`
   audit event carry `registry_not_read: "no snapshot"`. It is **not** counted as failed: a box before its first
   night has no registry to read, and a red health line on every new box would teach people to ignore it. Whether
   a PRODUCTION box should refuse there (as for a snapshot without a consent table) is the owner's question, open
   with the integrator; if yes, this is the one line to change.

## Evidence

`tests/unit/test_edc_prefill_site_facts.py` (six of seven cases failed before); two cases added to
`tests/unit/test_optout_worker.py` (the "no snapshot" one failed before); `tests/unit/test_no_decision_by_error_text.py`
with the line taken off.
