# TrialBox: simple build plan

| Field | Value |
| --- | --- |
| Document ID | TB-PLAN-02 |
| Version | 1.0 |
| Date | 2026-11-07 |
| Owner | Changfu Kuo (Aimedics) |
| Status | Living; listed in TB-DS-00R |

This plan replaces the gated pilot plan (TB-PLAN-01) for the development stage. The TB-DS documents stay as internal reference only; nothing in them is a gate for building.

**What each step contains, its screens and when it is done:** [`20-build-map.md`](20-build-map.md) (the one living page). **The synthetic hospital:** [`21-synthetic-hospital-spec.md`](21-synthetic-hospital-spec.md).

## Why it can be simple

TrialBox is software. While it is being built and tested on synthetic and public data, no patient is involved, so nothing needs an ethics committee, a hospital rule, or hospital staff time.

How the Japan and Taiwan study lifecycle works, and where TrialBox sits in it:

| Kind of study | Japan | Taiwan | Who submits |
| --- | --- | --- | --- |
| Drug/device trial (治験) | GCP省令, PMDA, hospital IRB | TFDA, hospital IRB | Sponsor / PI |
| Specified clinical research | 臨床研究法, CRB, jRCT | 人體研究法, IRB | PI |
| Observational / registry | 生命科学・医学系研究倫理指針, hospital ethics committee | 人體研究法, IRB | PI |

In every case the ethics review is of the **study**, and the PI submits it. TrialBox is a tool the study team uses, like Excel or REDCap. It never needs its own approval. The only question that comes up later is local: when a hospital wants to run TrialBox on its **own real records**, its PI mentions the tool in their study paperwork, or the hospital's IT approves it as internal software. That happens only when you choose to install at a hospital, and we hand them a two-page description.

## What gets built (Claude, end to end)

1. **Feasibility.** You type or paste criteria. You get a report with a funnel: how many patients pass each criterion.
2. **Patient list and mail before clinic.** You approve the criteria on one page. You get a list of likely patients, with the reason each one fits and their next clinic visit. The PI gets the list by e-mail on the morning of each clinic day (or every Monday if the clinic schedule isn't known), and the CRC gets a short daily summary. For a registry or observational study the list is a cohort list (new members, no contact step).
3. **REDCap link.** TrialBox reads screening and consent status from REDCap (a built-in simulator for testing; a real REDCap when available).
4. **Simple web home per role.** PI, CRC, admin. One screen each (the work list), with a command box in the header of every page for simple commands and search.
5. **Japanese, Chinese and English** throughout (built with step 4).

These are the five steps below, in the same order.

## How it is tested

- Synthetic hospital of 500,000 patients (Japanese and Taiwanese style records, notes in each language).
- Public matching benchmarks (the TrialGPT sets): must stay no worse than TrialGPT.
- One end-to-end test (`e2e_simple`) that runs criteria → report → list → mail → REDCap status, every build. It is the only build gate.
- A demo you can click through on the cloud VM (started only when you ask).

## Steps

| Step | Result you can see |
| --- | --- |
| 1 | Feasibility page and report with funnel, on the synthetic hospital |
| 2 | Approved criteria give the patient list and the PI mail before each clinic day |
| 3 | REDCap simulator and status read-back |
| 4 | Role homes, header command box, three languages |
| 5 | Full end-to-end test and the demo link |

Each step is a pull request you can merge or not.

## Only when you decide to use real patient data

- The hospital installs the box. One RTX 5090 is the **target**; it is not yet measured that both models fit its 32 GB, so step 5 measures it on a real card (options if not: shorter context, a smaller second model, or two cards).
- The PI adds a short paragraph about TrialBox to their study paperwork, if the hospital asks for one.
- A short check on real records before anyone relies on the list.

Nothing else is required.
