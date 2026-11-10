# Owner-chain tracker

The chains of TB-PLAN-06 §3.1, one row per step, with the latest starts of §3.2 (card T-663). Roles only: no
personal names, no contact details, no patient data. Dates are ISO. "Started" stays empty until the step starts;
then it holds the date and "Evidence" says where the proof is (a sent request, a receipt, a merged PR).
"Latest start" is the §3.2 date where §3.2 names the step, else the P50 latest start of TB-DR-10 §4. Float is
counted from 2026-11-10 at P50 / P90 (TB-PLAN-06 §3.1). `python -m tools.owner_chains` prints every step past its
latest start with no start date.

## Chains

| Chain | Step | Owner role | Started | Evidence | Need by | Latest start | Float P50 / P90 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CGMH-A | IRB approval, then HIS export build, then tier 3 notes, in series | CGMH IRB, CGMH HIS team | 2026-11-10 | amendment filed (receipt to record below) | 2027-03-19 | 2026-11-10 | −0.5 wk / −11 wk |
| CGMH-A′ | HIS work request under the existing approval for the PI's own department (Q-11) | owner | | | 2027-02-12 | 2026-11-13 | +4 wk / 0 |
| CGMH-A′ | Named HIS export owner (role) and the build started | CGMH HIS team | | | 2027-02-12 | 2026-12-11 | +4 wk / 0 |
| CGMH-B | Conflict-of-interest disclosure to CGMH | owner | | | 2027-03-12 | 2026-11-13 | +3.5 wk / −3.5 wk |
| CGMH-B | Contract template requested | owner | | | 2027-03-12 | 2026-11-13 | +3.5 wk / −3.5 wk |
| CGMH-B | Contract draft with CGMH legal | owner, CGMH legal | | | 2027-03-12 | 2026-11-20 | +3.5 wk / −3.5 wk |
| CGMH-B | Conflict-of-interest ruling on file; contract and DPA signed | CGMH legal | | | 2027-03-12 | 2026-12-04 | +3.5 wk / −3.5 wk |
| CGMH-C | First IT meeting requested | owner | | | 2027-02-26 | 2026-11-13 | +6.5 wk / +0.5 wk |
| CGMH-C | IT security review, then namespace, MIG, storage, network policy | CGMH IT | | | 2027-02-26 | 2026-12-25 | +6.5 wk / +0.5 wk |
| CGMH-D | IRB amendment approved | CGMH IRB | 2026-11-10 | amendment filed | 2027-03-12 | 2026-11-10 | +11.5 wk / +4.5 wk |
| CGMH-E | T-012 `qualify` merged | integrator | | | 2027-01-08 | 2026-11-27 | +5.5 wk / +2.5 wk |
| CGMH-E | G1b record on the owner's B200 | owner | | | 2027-01-08 | 2026-12-18 | +5.5 wk / +2.5 wk |
| Japan-A | Spark bought or dropped | owner | | | 2027-03-12 | 2026-11-20 | +3 wk / −2 wk |
| Japan-A | Hardware form decided and ordered | owner, Japan site PI | | | 2027-03-12 | 2026-12-18 | +3 wk / −2 wk |
| Japan-A | Delivery and on site | domestic vendor | | | 2027-03-12 | 2026-12-18 | +3 wk / −2 wk |
| Japan-B | Contract template requested | owner | | | 2027-03-26 | 2026-11-13 | +2.5 wk / −6.5 wk |
| Japan-B | Contract request with the hospital | owner | | | 2027-03-26 | 2026-11-27 | +2.5 wk / −6.5 wk |
| Japan-B | Contract and DPA in force (proposed 2027-04-01, Q-10) | Japan hospital legal | | | 2027-03-26 | 2026-11-27 | +2.5 wk / −6.5 wk |
| Japan-C | IT review and device registration filed | Japan hospital IT | | | 2027-03-12 | 2026-12-18 | +3 wk / −3 wk |
| Japan-D | IRB amendment approved | Japan IRB | 2026-11-10 | amendment filed | 2027-03-26 | 2026-11-10 | +6.5 wk / +0.5 wk |
| Japan-E | Answers on the notes route, the private cloud and who rotates on 04-01 | Japan site PI | | | 2027-03-26 | 2026-11-20 | +10 wk / −0.5 wk |
| Japan-E | Notes tier through the EMR vendor | EMR vendor | | | 2027-03-26 | 2027-01-22 | +10 wk / −0.5 wk |
| People | Safety-core engineer search started | owner | | | 2026-12-04 | 2026-11-13 | +4.5 wk / +0.5 wk |
| People | Safety-core engineer named and working | owner | | | 2026-12-04 | 2026-12-11 | +4.5 wk / +0.5 wk |
| People | Operations-person search started (Q-08) | owner | | | 2026-12-01 | 2026-11-13 | 0 / 0 |
| People | Owner hours: about 14 h a week on the chains until 12-25 | owner | | | 2026-12-25 | 2026-11-13 | 0 / 0 |
| Code to G3 | 170 to 210 sessions against 195 to 290 verified merges | integrator | 2026-11-10 | TB-PLAN-06 §4 | 2027-02-26 | 2026-11-10 | +2 wk / −1 wk |
| Sponsor ack | Choose an investigator-initiated study for the PQ prefill (PLAN-042) | owner | | | 2027-03-29 | 2027-02-01 | +12 wk / 0 |
| The PoC | Each PI's study list confirmed (Q-02) | owner | | | 2026-12-08 | 2026-11-13 | +1 wk / +1 wk |
| The PoC | Testers invited; sessions booked | owner | | | 2026-12-08 | 2026-11-20 | +1 wk / +1 wk |
| Counsel | Counsel engaged (gates the contract annexes, PLAN-043) | owner | | | 2027-03-12 | 2026-11-27 | none stated |
| Pentest | Pentest firm booked for pass 2 (PLAN-043) | owner | | | 2027-03-01 | 2026-12-18 | none stated |
| Insurance | E&O and cyber insurance quotes (PLAN-043) | owner | | | 2027-03-12 | 2027-01-15 | none stated |

## IRB filings

One row per site (PLAN-022). No patient data is involved.

| Site | Filed | Receipt id | Review type | Next meeting | Answer expected |
| --- | --- | --- | --- | --- | --- |
| CGMH | 2026-11-10 | to record | to record | to record | to record |
| Japan | 2026-11-10 | to record | to record | to record | to record |

## Latest starts for the owner's diary

TB-PLAN-06 §3.2, as dates. Each item is a step above.

| By | Steps |
| --- | --- |
| 2026-11-13 | conflict-of-interest disclosure; HIS work request (Q-11); contract templates at both hospitals; first IT meeting at CGMH; engineer and operations-person searches; the PIs' study lists (Q-02) |
| 2026-11-20 | contract drafts with CGMH legal; the Japan site PI's answers on the notes route, the private cloud and the 04-01 rotation; Spark bought or dropped; the supplement to the amendments if needed |
| 2026-11-27 | the Japan contract request; T-012 `qualify` merged; counsel engaged |
| 2026-12-18 | the Japan hardware ordered and its registration filed; the pentest firm booked; G1b done |
