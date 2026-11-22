# The free cards, sorted (2026-11-22)

**Reader:** the integrator and lanes E, H, J, K. **Written by:** lane R. **Counted at:** master `225100f4`
(train 122), and the pull requests on GitHub at 2026-11-22 10:00 UTC.

A card is **free** when it is in scope, not done, not in review, and every card it waits for is done. In scope means
the 271 cards of D-1068: grade E, the fourteen O cards plan 10 names in section 1.0, and lane J's twelve journey
cards. The owner's ruling of 2026-11-22 (#639, comment 7077918101) defers the second data doors, customisation
beyond what is built, and the multicentre track beyond what the first site uses past the pilot. A free card that
the ruling defers is listed, and it is **not started**.

## The count

| | Cards |
| --- | ---: |
| In scope | 271 |
| Done (a pull request whose head is on master, and no part of the card still open) | 71 |
| In review (an open pull request names the card or a lettered part of it) | 25 |
| Blocked by a card or a decision | 96 |
| Waiting on a run, a person or an outside input | 19 |
| **Free by the plan's columns** | **60** |
| Of these, already built on master | 8 |
| Of these, deferred past the pilot | 9 |
| **Free to start now** | **43** |

**By lane:** lane J 16, lane H 11, lane K 7, lane R 5, lane E 4, lane G 0 (the gates are not plan cards).
**By need:** 5 serve rc1, 19 the pilot core, 19 release 1.0.

The 96 blocked cards wait for a card not started (62), a card in review (13), an owner decision the plan lists as
open (13), or a card the plan does not schedule (8).

## Where this differs from the review's 44

The review (#1327, section 1.1) counts 78 done, 13 in review and 44 free at `3bca0b9d`. This page differs in four
ways:

1. **Lettered parts.** When part of a card is merged and another part is open (10A-1, 10B-2, 10C-1, 10C-3, 10C-5,
   9f-4, 9k-6 and others), this page counts the card as in review, not done. So 71 are done here, not 78, and 25
   are in review, not 13. Cards that wait for one of these (10B-8, 10B-11, 10K-16 wait for 10B-2) are blocked
   here.
2. **The tree.** Eight cards whose waits are all done are already built on master. They are listed below to be
   closed, not started.
3. **The ruling of 11-22.** Nine free cards are deferred past the pilot. The review counted before the ruling.
4. **Decisions.** This page counts a decision as ruled where plan 10's section 8 says "Ruled" (and decision 123 as
   ruled by D-1068). A decision ruled on #639 after 11-18 is not seen here. The 13 cards blocked only by an open
   decision should be checked against the integrator's list.

After all four, 43 cards are free to start. That is close to the review's 44, but they are not the same 44.

## How it was counted

- The rows of plan 10's section 4 were parsed. Each carried id takes its row from plan 9 revision 2, or else from
  plan 9. An id merged into another card ("9k-1 (with 9g-17, 9g-18)") is not a card. This gives 427 rows plus
  the 12 journey cards, 439 in all, and 271 in scope, matching the plan and the review.
- A card's pull requests are those whose title or branch names its id, with or without a letter. "On master" means
  the pull request's head commit is an ancestor of `225100f4`. So a pull request taken off a train does not count.
- "Waits for" was read for card ids and decision numbers. Any other text (a run, a person, the site) makes the card
  "waiting on an outside input".
- Each of the 60 was then looked for in the tree (`libs`, `services`, `tools`, `tests`, `docs`, the workflows) by
  its subject and its "proved by". The verdict and the evidence are in the last column. **Not verified:** the
  verdicts come from targeted searches and reading, not from running each card's proof. "Built" means the proof or
  an equivalent test exists. It does not mean the test was run here.

## The free cards, by lane

Order within a lane: rc1's needs first, then the pilot core's, then 1.0's. "Needed by" is lane R's reading of the
review's sections 3.3, 3.4 and 4.1.

**The five lane R takes first:** 9i-1 and 9l-22 (the nightlies, rc1 line 1), 9e-9 (the reimbursement refusal,
beside the refusal table), 9b-15 and 9b-26. The refusal table itself (R22-34) is lane R's first code card. It is not
a plan card, so it is not counted here.

**Cards for the integrator to rule on before they start:** 9c-11, 9f-2, 9f-10 and 10G-44 are high-risk (masking,
accounts, sign-in, permissions). 10E-27 is a run on the bench. 9c-6's open half is review finding R22-18, which
ruling 2 of 11-22 gives to lane E.

### Lane R: 5

| Id | Title | Track | Size | Waited for (all done) | Deferred past the pilot | Needed by | Lane | In the tree today |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 9e-9 | Reimbursement fenced: NAV, TWPAS and SUBMIT behind a setting off by default and refused on PRODUCTION; the … | A | S | decision 8 | no | rc1 | R | partly: TWPAS has a per-ruleset flag (scenarios/twpas.py); no one setting off by default, no PRODUCTION refusal. a PRODUCTION refusal, beside the refusal table |
| 9i-1 | Defect (e). Fix the compose nightly; a same-day card for every red night | I | S | – | no | rc1 | R | not built: compose job red or cancelled every master nightly 11-16 to 11-21. rc1 line 1: the compose nightly |
| 9l-22 | Flaky policy beside the two nightly fixes | I | S | – | no | rc1 | R | not built: no flaky policy, no CPU-saturation test. rc1 line 1 |
| 9b-15 | `IU/L` against `U/L` for enzyme-activity analytes, one rule per LOINC analyte | B | S | – | no | 1.0 | R | not built: libs/tb_common/labunit.py keeps U/L and [IU]/L apart |
| 9b-26 | The interoperability statement of 1.0, in the release record and the intended-use pages, naming what V21 … | B | S | decision 6 | no | 1.0 | R | not built: no interoperability statement |

### Lane E (the engine's decision rule): 4

| Id | Title | Track | Size | Waited for (all done) | Deferred past the pilot | Needed by | Lane | In the tree today |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10C-12 | "Suspected is not present" as the default for ja note questions | C | S | – | no | rc1 | E | not built: structured suspected diagnoses never exclude; no default for ja note questions. "suspected is not present" for ja note questions; rc1 line 2 |
| 9c-6 | A pregnancy or lactation line never compiles to a sex-only atom | A | S | – | no | rc1 | E | partly: exclusions held (postprocess.py qualifier_dropped; tests/unit/test_exclusion_never_on_a_demographic_alone.py); the inclusion form still compiles to sex = female (review R22-18). inclusion half of R22-18; rc1 line 3 |
| 10A-10 | One cue table per language (ja first: なし, 認めず, 否定できない, (+)/(-), family, sections) and a ConText pass, used … | A | L | 10A-3 | no | pilot | E | partly: cue patterns spread over sitesetup/charts.py, ir_extract/negation_scope.py, matching/inferred.py; no one table, no ConText pass. one cue table per language; feeds the D-985 rule |
| 9c-10 | A guard for rules grown by an automated loop (gold per language, a held-out set, a size budget, no … | A | S | – | no | 1.0 | E | not built: no guard for rules grown by an automated loop |

### Lane J (tracks A, C, SS-MIX2, REDCap; identity, masking, access): 16

| Id | Title | Track | Size | Waited for (all done) | Deferred past the pilot | Needed by | Lane | In the tree today |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10B-10 | Diet orders | B | S | 10B-1 | no | pilot | J | not built: OMD not read. SS-MIX2 to the specification |
| 10B-15 | Document-type and template registries (template fields to coded observations) | B | M | 10B-6 | no | pilot | J | not built: templates listed in site_questionnaire.py, no door. SS-MIX2 extended storage |
| 10B-16 | Synthetic Japanese hospital v2: specification-shaped storage, DPC, UKE, sectioned notes, two profiles | B | L | 10B-1, 10B-6 | no | pilot | J | partly: tools/synth_hospital and tools/ssmix2_spec_export.py exist; no DPC, UKE, sectioned notes, two profiles. the SS-MIX2 and notes half; the DPC and UKE half waits with those doors |
| 10B-7 | ADT-61 allergies into AllergyIntolerance | B | S | 10B-1 | no | pilot | J | not built: ADT-61 not in the reader's types (adapter/sources/ssmix2/source.py). SS-MIX2 to the specification |
| 10B-9 | Lab orders, OMG orders, done procedures, physiology results, microbiology | B | L | 10B-1 | no | pilot | J | not built: reader reads OML-11 results only. SS-MIX2 to the specification |
| 10C-10 | "Billing diagnosis?" flag for 保険病名 | C | M | 10B-3 | no | pilot | J | not built: japan_profile.json lists it not built |
| 10C-22 | Older-records boundary per source: a look-back past it says "record incomplete" | C | L | 10B-6 | no | pilot | J | not built: no older-records boundary |
| 10C-23 | Japanese note sections (SOAP, 【】, ＃n, template labels) and their roles scope evidence | C | M | 10B-6 | no | pilot | J | partly: bracket headings and family-history heads; no SOAP or ＃n section roles |
| 10C-9 | MEDIS modifiers as attributes; WHO-only ICD-10 codes kept | C | M | – | no | pilot | J | partly: MEDIS modifiers read for certainty only (tests/unit/test_ssmix2_10b2b_modifiers.py) |
| 9c-11 | One identifier detector: the recognisers on NFKC-normalised text with offsets mapped back, Sudachi and … | G | M | – | no | pilot | J | partly: libs/tb_common/phi_guard.py full-width and katakana; no shared NFKC detector with offset map. high-risk (masking); rc1 line 9 measures it |
| 9f-2 | Each account bound to one staff-register person; a protected-account confirmation between two accounts of … | G | M | decision 10 | no | pilot | J | partly: services/console/account_rules.py second_person; no binding to a staff-register person. high-risk (accounts) |
| 10A-12 | Event alerts: a new result or diagnosis re-evaluates a watched pair and notifies | A | M | 10A-4 | no | 1.0 | J | not built: no event re-evaluation of a watched pair |
| 10A-7 | At-least-k-of-n and "including" nodes | A | M | Decision 54 | no | 1.0 | J | not built: BoolNode is and/or/not only (libs/tb_contracts/criterion_ir.py:373) |
| 10C-21 | UMIN-CTR loader from the hospital's download; jRCT number on the study | C | S | – | no | 1.0 | J | partly: jRCT and UMIN ids read from CT.gov secondary ids; no UMIN-CTR loader |
| 9c-9 | "Ask" without the model: confirm whether `/assist` reaches a model; remove the re-phrasing step, or add … | A | S | – | no | 1.0 | J | partly: /assist still calls the model (orchestrator/setup_api.py); a write-nothing test exists |
| 9f-10 | Passkeys as the re-authentication at signature, beside the password; a Part 11 note | G | M | – | no | 1.0 | J | not built: no passkey or WebAuthn. high-risk (sign-in) |

### Lane H (tracks E, G, H; CI, terminology, connector drivers): 11

| Id | Title | Track | Size | Waited for (all done) | Deferred past the pilot | Needed by | Lane | In the tree today |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10E-33 | The site box's tier record and wording: no protocol reading ("sent to the coordinating box"), first-load … | E | M | 10E-1 | no | pilot | H | partly: tier record fields and wording key exist; no page test, first-load nights not shown |
| 10G-13 | The Japanese vendor pack: サービス仕様適合開示書, MDS/SDS, 責任分界表, SLA in the two-ministry form, the … | G | L | 10G-4 | no | pilot | H | not built: vendor-pack terms only in research and review pages. what a hospital IT asks first |
| 10G-44 | Authorisation matrix columns: a second study, no CSRF token, a foreign session token, a stale session, an … | G | M | – | no | pilot | H | partly: tests/console/test_role_route_matrix.py; second-study, CSRF, foreign, stale, revoked, break-glass columns missing. fourteen O; high-risk (permissions) |
| 9b-1 | A conformance suite: the ten lines as one test harness, one fixture set per connector, in a required job; … | B | M | – | no | pilot | H | not built: no conformance harness. the SS-MIX2 row first |
| 9h-12 | Chart-fact codes checked against the loaded vocabulary; an unknown code is dropped | H | S | – | no | pilot | H | not built: chart-fact codes not checked against the loaded vocabulary |
| 10E-27 | B-4: the judge alone reading protocols at 16k and 32k, now O-7 on the owner's card under ballast, free | E | S | 10E-28 | no | 1.0 | H | partly: planned as O-7 in the ballast stand-in page; no run recorded. a bench run, through the integrator |
| 10G-10 | A dynamic baseline scan (OWASP ZAP) of the running console nightly in the compose job, anonymous and … | G | S | Decision 115 | no | 1.0 | H | not built: no ZAP or DAST job in workflows, Makefile or tools. fourteen O |
| 10G-40 | gitleaks over the git history on trains and weekly; the first full-history triage into a ledger | G | S | Decision 115 | no | 1.0 | H | partly: tools/security_scan.py runs detect-secrets on tracked files; no history scan, no ledger. fourteen O |
| 9b-7 | The 2014 to 2023 ICD-10-CM (TW) edition map in the nightly path | B | S | – | no | 1.0 | H | partly: map in libs/tb_common/refdata_tw.py, used by mapping and vocab load; nightly-path proof not found. Taiwan map |
| 9h-1 | Model-step candidates from the full shipped ICD-10-CM and, when loaded, LOINC, ICD-10-PCS and the NHI … | H | M | – | no | 1.0 | H | not built: terminology/mapper.py reads curated icd10cm_tw only |
| 9h-5 | The allow-list is the licence register; a licensed vocabulary needs its row and its acceptor; SNOMED … | H | S | Decisions 23, 24 | no | 1.0 | H | partly: allow-list from the licence register; no affiliate row or acceptor test per class |

### Lane K (tracks D, F, K; console and ops): 7

| Id | Title | Track | Size | Waited for (all done) | Deferred past the pilot | Needed by | Lane | In the tree today |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10K-14 | One site file: export and import of answers, settings, profile, mapping and network values, encrypted to … | K | M | 10B-6 | no | pilot | K | not built: no site-file export or import |
| 10K-2 | The site seed: one signed file of the network form and the questionnaire answers, made before shipping; … | K | M | 10B-19 | no | pilot | K | not built: no signed site seed |
| 9g-21 | The phone menu as `details`; `scope="col"` on every table; a refresh button and live status in place of … | F | S | – | no | 1.0 | K | partly: phone menu is details; 172 of 486 headers scoped; 5 s reload remains |
| 9k-12 | Bottom action bar on phones, generalised from the patient sheet | F | M | J-3 | no | 1.0 | K | partly: patient sheet's bar only, not generalised |
| 9k-13 | Task line and "Needs you today" | F | S | J-6 | no | 1.0 | K | partly: Needs you today built behind a layout flag, off; no task line |
| 9k-19 | Delete rules no template uses | F | L | – | no | 1.0 | K | not built: console.css about 511 rule blocks; no unused-selector check |
| 9k-8 | Empty, error and "not allowed" states; live status in place of the 5 s refresh (takes 9g-21's live status) | F | S | J-6 | no | 1.0 | K | not built: no empty, error or not-allowed macro; 5 s refresh still in base.html |

### Free but deferred past the pilot by the ruling of 11-22: 9 (not started)

| Id | Title | Track | Size | Waited for (all done) | Deferred past the pilot | Needed by | Lane after the pilot | In the tree today |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10B-12 | DPC 様式1, EF and H readers (stage, ADL, JCS, NYHA, operations, drugs by day) | B | L | 10B-6; decisions 26, 72 | second data door (DPC) | – | H | not built: site_questionnaire.py says DPC has no door yet |
| 10B-13 | Receipt (UKE) reader, no insurer numbers kept | B | M | Decision 26 | second data door (receipts) | – | H | not built: site_questionnaire.py says UKE has no door yet |
| 10B-17 | REDCap per (study, site) with its DAG; a coordinating view across DAGs; screening numbers unique across sites | B | M | Decision 75 | multicentre beyond the first site (DAG coordinating view) | – | J | partly: one DAG per link (rc_bridge/link.py); no coordinating view, no site-unique screening numbers |
| 10C-20 | JP Core 1.2.0 and JP-CLINS documents in the validator; JLAC11 beside JLAC10 | C | L | 10B-1 | second data door (FHIR JP Core) | – | J | not built: JP Core pinned to 1.1.0 (tools/jpcore_rules.py); no JP-CLINS |
| 10D-5 | Allowed adaptations and a site-differences page on the PI's approval | D | M | 10D-2 | multicentre beyond the first site (site differences) | – | K | not built: no adaptation or site-differences code; D-1366 leaves it to 10D-5 |
| 9b-17 | A runbook section: the site's integration engine writes HL7 v2 to a folder; an Open Integration Engine … | B | S | – | second data door (HL7 v2 through an engine) | – | H | not built: no runbook section |
| 9b-2 | Oracle (`python-oracledb`, thin) and SQL Server (`mssql-python` after its companion licence is read, else … | B | S | – | second data doors (Oracle, SQL Server) | – | H | partly: cgrd_sql takes any SQLAlchemy address; no Oracle or SQL Server driver in the image |
| 9b-23 | CDA R2 documents: C-CDA and Japan's referral CDA, into documents and the coded sections | B | M | decision 6 | second data door (CDA) | – | H | not built: no CDA reader |
| 9b-4 | FHIR REST client: SMART Backend Services; `$export` kick-off, polling, download; `_since` deltas | B | M | – | second data door (FHIR REST) | – | H | partly: fhir_bulk reads NDJSON exports; no REST client, no SMART auth |

### Free by the plan's columns but already built on master: 8

These need no build. Each is for its lane to confirm against the card's "proved by" and close with one line on #639.

| Id | Title | Track | Evidence on master |
| --- | --- | --- | --- |
| 10A-21 | Coded screen-failure reasons in three languages | A | datacore/lifecycle.py SCREEN_FAIL_REASONS; labels in three languages (console/i18n_life.py); sponsor export (orchestrator/lifecycle_api.py) |
| 10E-40 | Plan text corrected: the 1.43 figure, the side-by-side arithmetic, the 15-study first load, decision | E | plan 10 section 10 lines 1313-1317 carry the corrections |
| 10G-26 | Plan text: the four gold stages, the release wording by gold kind, the hours (replaces 17-5's 125 h) | G | plan 10 line 416 and 656; D-1326 |
| 9f-8 | One short mail at once when an SAE is saved (pseudonym and link only) | D | tests/console/test_an_sae_is_told_at_once.py |
| 9g-16 | The console's return-address check (where a sign-in or a mail link sends a person back), as lane J f | G | services/console/next_page.py safe_next; tests/unit/test_safe_next_refuses_every_control.py |
| 9h-15 | Licence register rows and NOTICE lines for every code system used | H | tools/licence_register.py; tests/unit/test_licence_register.py, tests/unit/test_notice.py |
| 9h-9 | Re-file a concept by domain before mapping | H | ir_extract/postprocess.py domain_refiled; tests/unit/test_diagnosis_filed_as_procedure.py |
| 9i-2 | Defect (e). Fix the e2e nightly's `pure` set and `public-e2e` | I | pure and public-e2e green on the 11-19 to 11-21 nightlies |

### Not counted as free: the wait names a run, a person or an outside input: 19

| Id | Track | What it waits for | In the tree today |
| --- | --- | --- | --- |
| 10A-9 | A | 10A-3; decision 14's agreement figure | not checked |
| 10B-14 | B | The site's layout | not checked |
| 10B-21 | B | 10B-1 to 10B-6, 10B-19 | not checked |
| 9b-8 | B | The published format read; a site's answer on extracts | not checked |
| 9e-1 | D | area 0's modules (R40) and opening page (R15); decision 9 | partly: three study types of six (sitestore.py STUDY_TYPES); no per-type strip, checklist, forms |
| 10E-14 | E | S-2, S-3 | partly: schema fields exist, both not_measured in the tier records |
| 10E-15 | E | S-4, S-5 | partly: restore timed once on the test stack (132.9 s); RTO and RPO not measured per tier |
| 9f-12 | F | area 0's One Help (R20) | partly: glossary on the help page only; no inline definitions |
| 9f-13 | F | area 0's opening page (R15) | not built: no first-week card |
| 9f-14 | F | area 0's One Help (R20) | built: services/console/command.py header search; tests/console/test_header_search_off_log.py |
| 9i-21 | F | The owner's testers | not built: no usability round protocol or report |
| 10G-49 | G | J-M7's DNS decision | partly: tests/integration/test_egress.py and make test-egress; no packet capture |
| 9h-4 | H | The owner's list file | not checked |
| 9h-14 | H | The integrator's fetch | not checked |
| 10K-17 | K | 10K-1 to 10K-4 | partly: automated runbook follower exists; no stranger's record |
| J-9 | F | as lane J's list | not checked |
| J-10 | F | as lane J's list | not checked |
| J-11 | F | as lane J's list | not checked |
| J-12 | F | as lane J's list | not checked |
