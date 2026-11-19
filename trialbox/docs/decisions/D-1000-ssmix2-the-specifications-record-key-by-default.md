# D-1000 The SS-MIX2 reader keys a record the way the specification does, by default (amends D-594)

- **Card:** 10B-2 (plan 10, `docs/plan/47-plan-10-2026-11-18.md` Track B; review 12 card 12-1)
- **PR:** this branch (`agent/10B-ssmix2-reader-to-specification`)
- **Date:** 2026-11-18
- **Status:** proposed. The owner's decision 71 of plan 10 ("the SS-MIX2 default visit key to the specification")
  is still open with the recommendation "yes"; this card implements that recommendation. If the owner rules no,
  revert the default (`DEFAULT_ORDER_KEY` in the reader, the declared default in `tb_common/config.py`) and keep the
  rest.
- **Amends:** D-594 item 1 (which key is the default). D-594 items 2 to 4 stand.

## Context

Review 12 (`docs/reviews/2026-11-root/12-ssi-data.md` §4.4 and §4.10 F1) read the specification's record key as
(patient ID, 診療日, データ種別, オーダNo), the 診療日 part of it (構築ガイドライン Ver.1.2h 3.1.4 (2)⑥, as the
review records it). D-594 made the day part of the key only where a site declares `per_day`, so under the default
three outpatient visits filed as the specification says (order number "ALL9", or the per-day sequence "1") read as
one visit, and of two admissions under "1" only the newest stayed (the review's probe M4).

## Decision

1. **The default is the specification's key**: `TB_SSMIX2_ORDER_NUMBERS` unset means `per_day`.
2. **`unique` stays, as a site's declared exception**: a vendor that files an order's amendments or deletes under
   the day they were sent, not the order's day (D-594's context), declares it after the site check shows it.
3. **Even under `unique`, order number "ALL9" and the ADT types keep their day.** "ALL9" is the specification's
   number for data no order manages, not an order number; an ADT number is a sequence that tells one day's events
   apart. Neither can name the same record on two days.
4. **Ids**: a lab result with no id of its own carries its day under `per_day` (D-594 item 3), and also under
   "ALL9". A storage loaded under the old default gets a one-time new set of such ids at its next full load.
5. "ALL9" is not counted as "order number on several days": it is meant to be on every day.

## Not in this decision

The multi-volume manifest and the delta by file stamp (card 10B-11); the ADT types not read yet (10B-8).
