# Privacy documents per site (プライバシー文書 / 隱私文件)

| Field | Value |
| --- | --- |
| Version | 0.1 (2026-11-11, T-318, D-411) |
| Owner | Aimedics (the drafts); each hospital's privacy office (its own copy) |
| Status | Drafts on synthetic and public facts only. Each hospital adapts its copy; filled copies with names stay at the hospital (TB-PLAN-06 §10.4 Q-21). |
| Source | TB-PLAN-05 WS-13.5, WS-13.6 and §9.3; card T-318 (TB-ASSESS-01, `docs/reviews/2026-11-09-assessment-and-tasks.md`); findings OPS-041, CR-096, REG-007, REG-009 |
| Tested by | `tests/unit/test_privacy_docs.py`, `tests/unit/test_onepager.py` |

The rule over all of them is D-311 (`docs/decisions/D-311-no-development-gates.md`): building, testing and sharing
TrialBox use synthetic or public data only and wait for no sign-off. These documents are what a hospital needs
**before it reads real patient data** (TB-PLAN-06 §0.3 item 1). No counsel, privacy-office or IRB signature is on
file for any of them, and none is waited for.

## The documents

| Id | Document | File | Japan head hospital | CGMH |
| --- | --- | --- | --- | --- |
| TB-SITE-11 | Incident plan: severity, roles, clocks, the six cases, first hour, templates, tabletop | [`../incident-response.md`](../incident-response.md) | §B (日本語) | §C (繁體中文) |
| TB-PRV-01 | Record of processing (classes D0 to D4, tables, retention, who reads what) | [record-of-processing.md](record-of-processing.md) | §3 | §4 |
| TB-PRV-02 | Data-protection impact assessment (profile, vector store, clinician role, steward's note access) | [dpia.md](dpia.md) | §3 | §4 |
| TB-PRV-03 | Legal-basis memo: **slot only**, filed here once counsel signs | [legal-basis-memo.md](legal-basis-memo.md) | empty | empty |
| TB-PRV-04 | IRB pack: protocol text, data-flow figure, FAQ, screening-log columns | [irb-pack.md](irb-pack.md) | §5 | §5 |
| TB-PRV-05 | Opt-out notice, rewritten for the full scope (REG-009) | [opt-out-notice.md](opt-out-notice.md) | §2 (日本語) | §3 (繁體中文) |
| TB-PRV-06 | One-pager "what this system does with charts", rendered from the site's settings | [one-pager.md](one-pager.md); `tools/onepager.py` | `--lang ja` | `--lang zh-TW` |
| TB-PRV-07 | APPI and PDPA mapping (moved from TB-PLAN-05 §9.3) | [appi-pdpa-mapping.md](appi-pdpa-mapping.md) | Japan column | Taiwan column |
| TB-PRV-08 | Data destruction for study-level lists and media (NIST SP 800-88) | [data-destruction.md](data-destruction.md) | both | both |

## What each site does with them

1. The privacy office reads TB-PRV-01, TB-PRV-02 and TB-PRV-05 and writes its comments on its own copy.
2. The PI attaches TB-PRV-04, TB-PRV-05 and the rendered one-pager (TB-PRV-06) to the IRB submission where the
   committee asks for them.
3. The hospital's contract with Aimedics (the data-processing agreement) names TB-SITE-11 for clock C1 and TB-PRV-08
   for the end of the agreement.
4. The tabletop of TB-SITE-11 §A.9 runs once before the first real read; its outcome line may go to Aimedics.

**Japan.** Real Japanese data waits for the partner physician's own committee, which he handles himself (D-311,
owner answer 2). The Japan columns are drafts for that committee; nothing on this plan waits for them.

**CGMH.** The owner's approved IRB for the whole CGRD covers TrialBox reading the data on a machine inside CGMH
(D-311). The CGMH columns are what the hospital's privacy office and CISO's office keep on file.
