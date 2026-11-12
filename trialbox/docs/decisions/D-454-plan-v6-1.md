# D-454 Plan v6.1: the box, the capacity rule and five structural repairs

- **Task:** none (the plan itself; `docs/plan/31-master-plan-v6.1-addendum.md`, TB-PLAN-06.1)
- **PR:** this branch (`plan/v6.1-addendum`)
- **Date:** 2026-11-12
- **Status:** accepted; approved by the owner on 2026-11-12
- **Builds on:** D-311 (no development gates), TB-PLAN-06 (`docs/plan/28-master-plan-v6.md`)

## Decision

1. **Capacity (OD-10).** The product's capacity limits are the hardware and the model's measured speed. Every time
   limit, memory cap and count is derived from those or from the size of the data, or is a declared setting with a
   reason, or the work is refused at its start with an estimate. No limit cuts a result silently.
2. **The box (OD-11 to OD-13, OD-16).** A site runs TrialBox on a dedicated box (a GPU workstation or a DGX Spark)
   owned by a research lead who is the data steward. Trial PIs and their teams are users. The audience of the
   set-up and the handbook is the owner, not hospital IT; IT helps with the network address and the data
   connection. The box updates, backs up and checks itself. The shared-host and IT-managed forms stay in the tree
   as a second form.
3. **Data and access (OD-14, OD-15).** Data sources are per site: a research database, a REDCap project, the team's
   own database, an EMR feed, uploaded sheets. Use from outside the hospital and a phone app are offered at a level
   the hospital or the data steward chooses; the default is inside the hospital only.
4. **Structure.** Five root causes found by the reviews of 2026-11-11 and 11-12 are repaired by cards, not finding
   by finding: one decision path (T-705 to T-711), identity and trust (T-712 to T-721), the night as a generation
   and erasure as an obligation (T-722 to T-728), capacity (T-687 to T-704, from the scale review), the box (T-729 to
   T-736).
5. **Tests and merging.** Tests follow paths; a safety property must be able to fail; fakes are made from the real
   service; a card merges when its own CI unit job is green on a head that contains master; safety-core cards get
   one automated adversarial review.

## Evidence

`docs/reviews/2026-11-12-architecture/` (decision, trust, lifecycle); the scale review of PR #279; PR #257 (audit).

## Open

The owner's items of the addendum's §8.
