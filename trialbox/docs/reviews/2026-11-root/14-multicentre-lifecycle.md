# Multicentre by design: the study package, the federation and the whole life of a trial (lane J, root review 14, 2026-11-18)

**Reader:** the owner first (the one-page summary). Then the builders (sections 1 to 7) and plan 10 (sections 8 to 11).

**What was analysed:** master `7da6edd38` (train 80). Read: every `CREATE TABLE` in `services/` and `libs/` (a
script, section 12), the permission matrix, the settings example, the rule-set manifests and compiled files, the
ClinicalTrials.gov client and mirror, the alliance cohort exchange (`COHORT MERGE`), the trial-opportunity feed and
its hub page, the REDCap link, the sponsor layout, the SAE clock, the retention rules, the new-study walk and the
life-cycle walk; every mention of multi-site, federation, alliance, consortium, coordinating centre and sponsor in
`trialbox/docs/` and `trialbox/spec/`, decisions included. Plan 9 revision 2 (`origin/agent/B11-plan-9-rev-2`) and
reviews 06, 07, 09 and 10 on their branches. Opened for this page: the ClinicalTrials.gov API v2 (its OpenAPI file and
one record, fetched with `curl`), jRCT's top page and its terms page, e-Gov's text of APPI article 27, Taiwan's PDPA
article 6 and Human Subjects Research Act, 45 CFR 46.114 and 164.512, 21 CFR 312.32, 312.64 and 812.150, FHIR R5
ResearchStudy, the ICH M11 technical specification, the ODM 2.0 `SiteRef` class, MHLW's 2024 paper on 臨床研究中核病院,
and the network pages of OHDSI, PCORnet, SHRINE, EHDEN and MID-NET (section 13). No box was started; no product code
was changed; public and synthetic data only. The EDC's repository was not read (D-1060); what this page says of the
EDC is what plan 9 revision 2 states.

**Starting point and boundary.** Review 02 (`02-journeys.md`, cited **02** with its card ids J-1 to J-31) has the
roles of one site, the surfaces and the study kinds; this page does not repeat them. Review 15 (a sibling) covers
patient finding itself as the central service; this page covers the structure around it: centres, the study package,
roles across centres, the life cycle and the connections outward.

**How every claim is marked:** **[R]** read, file and line follow; **[M n]** measured, row n of section 12; **[S]**
source, opened for this page, link in section 13 by number (S1 to S27); **[O]** opinion; **not verified** where it
could not be checked (section 14).

---

## Summary (one page, plain words)

**The owner is right: TrialBox is built as one hospital's box, and nothing in it knows that the same trial runs in
other hospitals.** [M 1, M 2] Of 157 tables, 4 carry a site; 74 are keyed by the study, and the study's key is the
local rule-set name. The sponsor pack says of itself "aggregate feasibility counts from one hospital's TrialBox"
[R `services/console/app.py:431`]. There is no coordinating centre, no coordinating investigator, no study package and
no word "multicentre" anywhere in the code [M 2].

**That is less bad than it sounds, because a box that stays inside one hospital is the right unit.** A trial is
multicentre by protocol, not by database. The field's networks that never move patient data (OHDSI network studies,
PCORnet, SHRINE, TriNetX, EHDEN, DataSHIELD) all work the same way: one centre writes the definition once and
distributes it; each site runs it on its own data behind its own firewall; only aggregates come back [S5 to S10].
TrialBox already holds three pieces of that pattern, built and tested, but never joined up [R, section 1.3]:

1. **A signed, offline channel in:** the update bundle is Ed25519-signed and carried on media [R `libs/tb_common/refdata.py:35-36`].
2. **Signed aggregates out, to a hub:** the trial-opportunity feed is signed per site and checked at the hub against a
   site key register [R `libs/tb_common/opportunity.py:551,586`]; the alliance cohort tables are merged at a root box
   [R `services/orchestrator/scenarios/cohort.py:439`].
3. **Portable criteria:** each criterion is a structured record over international codes (ATC, LOINC, ICD-10-CM) in
   FHIR ValueSets [R `rulesets/RA-JAK/valuesets/VS_METHOTREXATE.json`], with a content-addressed criterion library
   [R `services/criteria_compiler/library/ddl.py:14-20`]; the hospital's own codes are mapped on the side
   [R `services/sitesetup/store.py:38`].

**What is missing is the thing that joins them: the study package.** Today a study is one hospital's rule-set folder,
whose manifest mixes the protocol (criteria, value sets, title, sponsor) with the hospital (its doctors' IDs, its
departments, its mail addresses, who approved it, which model reads notes) [R `rulesets/RA-JAK/manifest.yaml:36-57`].
A second hospital cannot take it without editing it, and editing it is a fork.

**Five changes that matter most** [O]:

1. **Federation model (b): a coordinating centre signs a versioned study package; each box imports it, adds only
   listed local adaptations, and sends back only signed counts.** Not a hub with site workspaces: that is the EDC's
   job (plan 9 rev 2 describes the owner's EDC as multi-site with site-level rights), and REDCap's (data access
   groups, which the REDCap link already honours [R `services/rc_bridge/link.py:209-250`]).
2. **Split the manifest** into a protocol part (signed, identical at every site) and a site part (scopes, people,
   routing, thresholds that may only be raised). This is the one structural change; the rest builds on it.
3. **A second site adopts a study in under an hour:** import, steward names the PI, the PI approves "the package plus
   these listed differences", the coordinator records the IRB and opens; the package's own synthetic test patients
   prove the compile matches. Today's walk from "protocol in" to "first list reviewed" is 12 steps, about 39 actions and
   5 hand-offs, and it still skips the IRB record and the study type [M 4; life-cycle walk F-04, F-14].
4. **A coordinating view with no patient in it:** feasibility by site, screening funnel by site, screen-failure
   reasons, enrolment against target, built from the opportunity hub page that exists.
5. **Registry intake that is honest about the registries:** ClinicalTrials.gov gives the latest version only, through
   an open API; TrialBox reads 7 of its 13 protocol modules [M 5]. jRCT has no API and its terms forbid crawling and
   any reuse of investigators' names [S3]: intake there must be one record, started by a person.

**What it costs:** 26 cards (8 S, 14 M, 4 L), section 9; no purchase. Eight decisions for the owner (section 10); the
first is the federation model.

---

## 1. How single-centre is the code today? Measured

### 1.1 Where "site" is a thing, and where it is assumed to be one

| Area | What the code does | Single-centre assumption | Evidence |
| --- | --- | --- | --- |
| **Tables** | 157 tables in the product's stores (OMOP DDL excluded) | 4 carry a site column: `site_key` (the pseudonym key's fingerprint) and the three alliance tables. 153 assume "this box is the site" | [M 1] |
| **Study key** | 74 tables keyed by the study; the key is `ruleset`, the local rule-set id | A study *is* one box's rule-set; there is no study id shared across sites. `study_identity` holds sponsor, protocol number, SIV date and registry ids as free fields | [M 1]; [R `services/console/sitestore.py:204`] |
| **Site identity** | `TB_SITE_ID` (default `DEV`) and one `site:` block per box | One site per box; a box cannot hold two sites | [R `libs/tb_common/config.py:95,166`; `deploy/settings.example.yaml:4`] |
| **Settings and flags** | `flag` keyed by name; settings one YAML | Global to the box; correct for model (a) and (b) | [R `libs/tb_common/flags.py:64`] |
| **Roles** | 7 roles, 89 actions; conditions are per study (`pi`, `task:`, `logged_pi`, `logged_tick`, `monitor`) | No role is scoped to a site, and none needs to be inside one box. No sponsor, coordinating investigator or coordinating-centre role | [M 3]; [R `libs/tb_common/authz_matrix.yaml:12-18,30`] |
| **Users** | `users` has no site or institution | One institution's accounts | [R `services/console/auth.py:83`] |
| **Identifiers** | Pseudonym = HMAC of the chart number with the site key | Per site by design: the same patient at two hospitals has two unrelated pseudonyms. Correct | [R `libs/tb_common/crypto.py:38-45`] |
| **Screening number** | `{prefix}{seq:04d}`, prefix default `{ruleset}-` | No site code by default: two sites of one trial both issue `RA-JAK-0001` unless someone types a prefix | [R `services/console/sitestore.py:618`] |
| **Audit chain** | One `journal` per box | One chain per site; correct. The design's "daily chain head countersigned by the hub" (SC-72) is not built | [R `libs/tb_common/audit_writer.py:92`; `docs/plan/design/03-security-privacy.md:367`] |
| **Candidate registry** | `candidates` keyed by (ruleset, pid) | Per site; correct | [R `services/orchestrator/db.py:71`] |
| **Reports** | Sponsor pack: "aggregate feasibility counts from one hospital's TrialBox"; the DL-1 pack carries one `site_id` | One site per pack; no multi-site pack | [R `services/console/app.py:431`; `services/deliverables/pack.py:107`] |
| **Alliance cohorts** | `COHORT MERGE` on a root box merges members' quarterly count tables; different definition versions never summed; suppressed cells merged as ranges | The one multi-site function. Members are trusted by mail sender address, first sender binds | [R `services/orchestrator/scenarios/cohort.py:225-276,341-349,439-480`; D-73] |
| **Opportunity feed** | Monthly signed aggregate per site, verified at a hub against a key register | Built, multi-site, aggregate only | [R `libs/tb_common/opportunity.py:1-35,551,586`; D-467] |
| **EDC link** | REDCap link honours a data access group (DAG); records outside the site's DAG counted, not read | Multi-site aware: a site can be one DAG of a shared project | [R `services/rc_bridge/link.py:43,209-250`]; DECISIONS line 1555 |
| **Sponsor layout** | The screening log in the sponsor's columns; the sponsor's weekly sheet read as step proposals | Per site, typed by hand at each site | [R `services/datacore/sponsor.py:1-25`] |
| **Rule-set manifest** | Criteria, value sets, CQL, title, sponsor, protocol version **and** practitioners, departments, mail routing, approver, the note-reading model | Protocol and site mixed in one file: not portable | [R `rulesets/RA-JAK/manifest.yaml:1-58`] |

**Reading** [O]: inside one box, "one site" is the right assumption, and changing 153 tables to carry a site key
would buy nothing (it is model (c), which section 2 rejects for TrialBox). The single-centre defects are in four
places only: the **study key** (local name, no shared study id), the **manifest** (protocol and site in one file),
the **screening number** (no site component), and the **absence of an inbound package and an outbound status feed**.

### 1.2 Vocabulary, counted

| Word | Code (`services`, `libs`, `tools`) | Docs and spec |
| --- | --- | --- |
| alliance | 13 files, 58 lines | 31 files, 98 lines |
| federat- | 0 | 24 files, 85 lines |
| multi-site | 2 lines, both REDCap labels (`i18n_4b.py:106`, `i18n_step3.py:30`) | 16 files, 19 lines |
| multicentre / multicenter | 0 | 6 files, 10 lines |
| coordinating centre / investigator / site | 0 | 2 files, 2 lines |
| EvidenceVariable, ResearchStudy, ResearchSubject, USDM | 0 | (spec only) |

[M 2, M 6] The design talked about networks; the code built the alliance and the feed and stopped.

### 1.3 What was already decided (do not re-decide)

| Id | What it says | Built? |
| --- | --- | --- |
| D-71 to D-74 | Cohort definitions; consent registry for `n_contactable`; the alliance exchange and merge by mail (v1 columns, `definition_version = ruleset@version`, ranges for suppressed cells); trial simulation from ClinicalTrials.gov | Yes [R `cohort.py`] |
| D-648 | The root keeps every stored table with its hash, so a merge can be re-run as it ran | Yes [R `services/orchestrator/db.py:160-200`] |
| D-140 | ClinicalTrials.gov live, offline (signed pack) or cassette; offline by default | Yes [R `services/criteria_compiler/ctgov.py:1-16`] |
| D-144 (owner, 2026-11-09) | "Consortium: counts and de-identified profiles may leave under IRB approval and a data-sharing agreement; export defaults project pseudonyms, dates shifted ±180 days, k = 5, no quotes, no vectors; a contract may only tighten; counts travel as signed files; the shared code-map registry is hosted at CGMH and shipped by Aimedics"; randomisation not in TrialBox; drug accountability, TMF, invoicing inputs only | Counts: by mail, **unsigned** (below). Profiles, shared code-map registry: not built |
| D-145 (owner) | Two pilot sites, CGMH then Japan; EDC prefill switched on per study only after the sponsor acknowledges TrialBox in its source-data chain | Pilot order since superseded by the round-3 ruling (first site in Japan) |
| D-467 | The opportunity feed: approved studies only, floor 10, multiples of 10, monthly, signed, hub verifies | Yes |
| ADR-02 (`docs/plan/design/02-architecture.md:1414`) | "No blockchain; federated hub with signed envelopes and countersigned audit heads" | Proposed, not built |
| Design SC-25, SC-52, SC-53 | Consortium Bloom-filter GUID, mTLS with a consortium CA, PI approval of each incoming cross-site query | New, not built [R `03-security-privacy.md:308,344-345`] |
| Spec v4 M11 (FR-M11-1 to -6) | Alliance root role; federated feasibility with a privacy accountant, ≥ 3 members, pairwise masks; "Sponsor system (machine recipient): FHIR Group + EvidenceVariable, USDM eligibility … no inbound link" | Not built beyond COHORT [R `spec/v4/01_constraints_product_experience.md:254`; `spec/v4/10b_modules_m6_m11_workflows.md:476-496`] |

**One contradiction found.** The specification says inbound alliance aggregates "are verified (Ed25519 signature,
schema, suppression flags)" [R `spec/v4/05_data_platform_model_privacy.md:234`]; the code checks the schema and binds
a site to the mail address that first sent its table, and verifies no signature [R `cohort.py:341-349`]. D-144 says
"counts travel as signed files". The opportunity feed signs; the alliance tables do not. Card M14-20.

---

## 2. What multicentre means for a box that never sends patient data out

### 2.1 Three federation models

| | (a) Independent boxes, shared protocol only | (b) Coordinating centre with a signed study package | (c) Hub with site workspaces |
| --- | --- | --- | --- |
| **What it is** | Each hospital types the same protocol into its own box | One centre compiles and reviews once, signs a versioned package; each box imports it, adapts only listed fields, returns signed aggregates | One server holds every site's workspace; each site sees its own rows |
| **What crosses the boundary, in** | Nothing (people retype) | The package: criteria, value sets, forms, schedule, texts, tests. No patient data | Everything: the sites' staff log in to the hub |
| **Out** | Nothing, or mails | Counts and status by stage, rounded under the D-467 rules; never a row | Patient-level records |
| **Japan** [O, on S11, S20] | No question | Counts that identify nobody are not personal data (APPI); the package carries none (not verified against the PPC guidelines' text) | 要配慮個人情報: no opt-out route (APPI art. 27(2) proviso); needs consent, a joint-research basis for an academic institution (art. 27(1)(vi), (vii)) or 共同利用 notified in advance (art. 27(5)(iii)) [S11] |
| **Taiwan** [O, on S12, S13] | No question | Aggregates that cannot identify the person (PDPA art. 6(1)(iv)) [S12]; a jointly agreed review board for multi-institution research (HSRA art. 10) [S13] | Medical-record data needs one of PDPA art. 6's exceptions; abroad also HSRA art. 19(3): written consent and the authority's approval [S13] |
| **US** [O, on S14 to S16] | No question | De-identified aggregates; a site's own feasibility look is "preparatory to research" with no PHI removed (164.512(i)(1)(ii)) [S15]; one IRB for cooperative federally funded research (46.114(b)(1)) [S14] | PHI under authorisation, waiver or a limited data set with an agreement (not opened for this page) |
| **Offline, one-way media** | Works | Works: the package travels like the update bundle (signed tar on media); counts go back as one signed file by mail or media | Needs a network path from each hospital |
| **Effort per extra site** | Full redo: hours to days of compile and review | Import, map local gaps, approve differences: under an hour (target) | Accounts only |
| **Who in the field does it** | Most sites today | OHDSI network studies (study package of R or SQL, "only aggregate results are shared", each site's analyst reviews before sending) [S5]; PCORnet (CDM, queries through a coordinating centre, "data stay with each network partner behind its firewall") [S6]; SHRINE (aggregate counts across hospitals) [S7]; TriNetX (aggregate counts per organisation) [S8]; EHDEN (187 data partners in 29 countries on OMOP) [S9]; DataSHIELD (non-disclosive summaries only) [S10] | EDCs (REDCap DAGs; the owner's EDC module per plan 9 rev 2); MID-NET is PMDA-operated with 9 cooperating institutions (where data are held: not stated on the page) [S17] |

### 2.2 Japanese networks the package must fit

- **臨床研究中核病院** (Medical Care Act, in force April 2015): MHLW states their role is to support other institutions'
  clinical research and, in joint research, to run it as the core ("共同研究を行う場合にあっては中核となって臨床研究を
  実施"); 15 hospitals were approved as of September 2024 [S18]. They are the natural coordinating centres of model (b)
  in Japan [O].
- **国立病院機構 (NHO):** a network of about 140 hospitals with one contact window for sponsors and a central IRB
  (search results only; the PDFs exceeded the fetch limit: not verified) [S19].
- **One review per multi-institution study.** The 生命・医学系指針 requires the research representative, in principle, to
  ask one ethics committee for a single review of a multi-institution protocol (一括審査) (MEXT and university material
  found by search; the guideline's own text not opened: not verified) [S20]. The 臨床研究法's certified review board
  is also one per study (not opened). Consequence for the package [O]: one central approval, many local "permissions
  of the head of the institution"; the package carries the central approval's reference; each site records its own
  head's permission date.
- **Taiwan:** HSRA art. 10 allows a jointly agreed review board [S13]; the TFDA joint-review arrangements were not
  opened (not verified).

### 2.3 Recommendation

**Model (b), with TrialBox as the site node and a "coordinating" mode of the same software at the lead institution;
model (c) stays with the EDC.** [O] Reasons:

1. It keeps the product's one rule, "only aggregates ever leave a site" (D-467), true without exception.
2. Every piece it needs exists in part: signed media in, signed aggregates out, a hub page, a key register,
   standard-coded criteria, a content-addressed library, a merge that never sums different definition versions.
3. It works offline and one-way: a package in on media, a counts file out by internal mail or media.
4. It matches what the field proved at scale (OHDSI, PCORnet) and how Japanese multicentre research is already
   organised (a core hospital or a network headquarters coordinates; one central review).
5. Model (c) would turn the box into a cross-hospital data holder: new legal bases in three countries, a network
   path into every hospital, and the security history the EDC is going through now (plan 9 rev 2: "rounds 1 to 4 each
   found ways for a person to read or change another site's data").

**Where the coordinating node runs** [O]: at the lead institution (a 中核病院, the network's headquarters or the
sponsor-investigator's hospital), on its own TrialBox in a coordinating mode that holds no patient data from other
sites. Not hosted by the vendor: D-144 already says Aimedics never holds patient data, and a vendor-hosted node would
also hold the sponsors' study packages (a commercial-confidentiality question). Decision OD-2.

---

## 3. The study package: the unit of multicentre work

### 3.1 What a study is in the code today

| Part | Where it lives | Protocol or site? |
| --- | --- | --- |
| Id, kind, title, sponsor, version, protocol version, language, source documents | `manifest.yaml:1-11` | Protocol |
| Criteria list; one IR file per criterion (logic, window, value set, source reference, review) | `manifest.yaml:13-29`; `ir/*.json` | Protocol, except `review.by` |
| Value sets (FHIR, ATC, LOINC, ICD-10-CM) | `valuesets/*.json` | Protocol |
| CQL library and ELM | `cql/` | Protocol |
| Generated SQL | `sql/RA-JAK.sql` ("never edited by hand or produced by an LLM") | Derived; same at every site given the same IR and expansion |
| Test patients and expected results | `tests/expected.json`, `tests/equivalence.json` | Protocol (synthetic) |
| Labels (zh-TW, ja) | `labels.yaml` | Protocol, with local wording |
| Screening scope: practitioners, departments, windows | `manifest.yaml:30-43`; `screen_scope` table | **Site** |
| Routing (who gets lists and aggregates) | `manifest.yaml:44-49` | **Site** |
| Thresholds (small cell, tier) | `manifest.yaml:50-52` | Protocol floor, site may raise |
| Note-reading model and prompt | `manifest.yaml:53-55` | **Site** (box tier) |
| Review: approved by, at, via, rounds | `manifest.yaml:56-60` | **Site** (each site's PI approves) |
| Study settings (type, cohort kind, consent scope, screening-number format, reasons) | `study_settings` [R `services/orchestrator/studystore.py:20-35`] | Mixed: type and consent model are protocol; prefix is site |
| Study identity, IRB records, ICF versions, delegation log, SIV date | `study_identity`, `irb`, `icf_versions`, `delegation` [R `sitestore.py:204`; `teamstore.py:44,131,165`] | Site records of protocol facts |
| Visit schedule (versioned) | `schedule`, `schedule_version` [R `services/datacore/lifecycle.py:87,105`] | Protocol, with local windows |
| Forms (7 built-in), sponsor layout, EDC item map | `forms.csv`; `sponsor_layout`; `item_map` | Protocol (forms, map), site (link) |
| SAE rule set | named per study on the set-up page [R `services/datacore/lifecycle.py:175-184`] | Country of the site |

[R `rulesets/RA-JAK/`, listed] **Finding** [O]: the protocol half already exists as files that do not depend on the
hospital. The package is mostly a matter of drawing the line, signing the protocol half, and refusing site edits to it.

### 3.2 What the package must contain

| Section | Content | Format (section 7) | Signed by |
| --- | --- | --- | --- |
| Header | Package id = the primary registry id (NCT, jRCT) + protocol version; package version; previous version; the coordinating centre; the central approval (IRB/CRB/ethics committee, reference, date) | JSON | Coordinating centre |
| Study definition | Title, phase, study type, consent model, arms (names only), target enrolment, countries | JSON, exportable as FHIR R5 ResearchStudy | CC |
| Criteria | IR files, value sets, CQL, labels in en, ja, zh-TW; each criterion's source reference into the protocol | TrialBox IR + FHIR ValueSet + CQL; exportable as EvidenceVariable | CC |
| Conformance tests | Synthetic patients and the expected result per criterion | Existing `tests/` layout | CC |
| Forms and schedule | Visit schedule with windows; site forms; the CDASH item map; screen-failure reason list | ODM 2.0 metadata + schedule JSON | CC |
| Screening log | The sponsor's columns (today's sponsor layout) | Existing layout JSON [R `sponsor.py:82`] | CC |
| EDC template | REDCap project link template (fields, DAG naming rule) or the EDC module's study id | JSON | CC |
| Safety | Which SAE rule set per country (e.g. `jp_gcp`, `tw_trial`), the sponsor's safety mailbox | JSON | CC |
| Documents | Protocol, ICF template, IB (by hash and title; the files themselves optional) | Hash list | CC |
| Allowed adaptations | The list of fields a site may set (3.3), and bounds (e.g. visit window ± days) | JSON | CC |
| Signature | Ed25519 over the canonical tar, the CC key fingerprint, the CC's registered name | As the opportunity feed and the update bundle | CC |

### 3.3 Local adaptation without a fork

| A site may set | Bound | Why it does not change the protocol |
| --- | --- | --- |
| Local code maps (its own lab, drug and diagnosis codes to the package's standard codes) | Only into the package's value sets; D-1113 "the site's own code lists win over every shipped table" | The criterion still names the standard concept; the site says which local codes mean it |
| Local wording of labels and patient texts | Meaning unchanged; shown beside the package text on the PI's approval page | Wording, not logic |
| Screening scope, departments, practitioners, routing, people | Free | Who is looked at and who is told, not who is eligible |
| Visit windows | Inside the package's tolerance | The protocol allows it |
| Small-cell floor, rounding | May only raise | Stricter, never looser (D-144 "a contract may only tighten") |
| Note-reading model | The box's tier | Recorded per run; the decision is still the PI's |

Anything else (a criterion's threshold, a window outside tolerance, a dropped criterion) is **a site difference**: the
box refuses it unless the coordinating centre has signed it as a site variant. **How a site difference is reviewed**
[O]: the box computes, per criterion, the compiled SQL hash and the value-set expansion at this site; the PI's approval
page shows "identical to the package" or lists the difference with its reason; the counts sent back carry the
package version and a "differs at this site" flag, and the merge never sums a criterion across sites whose
definitions differ (the rule D-73 already applies to definition versions).

### 3.4 Versioning and amendments across sites

- The package version follows the protocol amendment; the site's approval names the package version, as today's
  approval names the rule-set version and the D-364 amendment record (effective date, IRB reference)
  [R `services/criteria_compiler/service.py:290-310`].
- An amendment package arrives; the box shows the difference (criteria added, removed, changed; forms; schedule);
  the site's PI approves; the effective date is the site's own (its head's permission may come later than the central
  approval).
- An ICF version change raises the re-consent list that exists today [R `services/datacore/lifecycle.py:20`].
- The coordinating view shows which site runs which package version: a site on an old version is visible, not hidden.

### 3.5 Signatures and provenance

The coordinating centre's key is registered at each box (as `load_register` does for site keys at the hub
[R `opportunity.py:586`]); a package signed by an unknown key is refused. Every list, report and count sent back
names the package id, version and hash; the audit records the import. The site's PI approval is still required: under
ICH E6 each site's investigator is accountable at his site [O]; the package removes the work, not the signature.

### 3.6 A second site in an hour

| Step | Who | Today (per site) | With the package |
| --- | --- | --- | --- |
| Protocol in | CRC | Paste or upload, compile, wait | Import the signed file |
| Criteria review | PI | Every criterion from scratch, labels typed on zh-TW and ja pages | Only the differences and the code-coverage report |
| Local codes | Steward | Found when a count looks wrong | A coverage report before approval: each value-set code with no row in this lake |
| Proof the compile is right | – | None at the site | The package's synthetic tests run on this box |
| Forms, schedule, sponsor log, EDC map | CRC | Typed per site | From the package |
| IRB, study type, open | CRC | Not asked by the walk (F-04, F-14) | Asked, prefilled from the package |

---

## 4. Roles across centres

### 4.1 Who sees and does what

| Role | Where they work | Sees across sites | Does | In TrialBox today |
| --- | --- | --- | --- | --- |
| Sponsor (company) | Sponsor systems | Aggregates per site; per-subject data through the EDC | Funds, owns protocol, safety reporting | No account; `cro` reads the sponsor form [R `authz_matrix.yaml:89-96`] |
| Sponsor-investigator (IIT, 医師主導治験) | Lead hospital | As sponsor | As sponsor and as a site PI | Not distinguished (02, 4a) |
| CRO | Sponsor side | As sponsor | Monitoring, project management | `cro` role |
| Coordinating investigator (治験調整医師, 研究代表者) | Lead hospital | Aggregates of all sites | Signs the package, answers eligibility questions | **No** |
| Coordinating-centre data manager | CC | Aggregates; query load from the EDC | Builds and versions the package | **No** |
| Central monitor | CC or CRO | Aggregates, KRIs | Risk-based monitoring | **No** |
| On-site monitor (CRA) | Site, on a visit | One site's enrolled subjects | SDV | `cro` + monitor grant, inside the hospital [R `authz_matrix.yaml:757-783`] |
| Remote source review | Outside the hospital | One site's enrolled subjects | SDV at a distance | **Not possible by design** (the box is reachable only inside the hospital; 02, 2.2) |
| Site PI | Site | Own site | Approves criteria, decides on candidates | `investigator` + `logged_pi` |
| Sub-investigator | Site | Own site | As ticked | `investigator` + `logged_tick` |
| CRC | Site | Own site, every study | Day-to-day | `coordinator` (sees every study: 02) |
| SMO staff | Contracted CRC at the site | One or a few studies | As CRC | Only as `coordinator`, which sees every study [O: too wide] |
| Site pharmacist | Site | Own site | Drug, accountability | **No** (02, 1.2) |
| IRB office, central | CC or network | Its studies | Approves, receives SAEs | Record only (`irb.edit`) |
| IRB office, local / head of institution | Site | Own site | Permission (許可) | Record only |
| Hospital IT | Site | Own box | Operates | `admin` |
| Data steward | Site | Own box | Feeds, opt-outs, PI naming, local code maps | `steward` |

### 4.2 Proposals (lane C2 owns the matrix: these are proposals; no change made)

| # | Proposal | Why |
| --- | --- | --- |
| P-1 | No sponsor, CC or central-monitor account inside a site box | They see aggregates only; aggregates leave as signed files; an account inside would be a door into patient rows |
| P-2 | A coordinating mode with its own small role set: coordinating investigator (signs packages), CC data manager (builds packages, reads feeds), central monitor (reads feeds), CC administrator. No patient role exists in this mode | Model (b) at the lead site; the mode holds no other site's rows |
| P-3 | A study-scoped coordinator condition (`task:` already exists per study): an SMO coordinator or a coordinator from another department sees only the studies the delegation log names | Today every coordinator sees every study [R `authz_matrix.yaml:109`; 02] |
| P-4 | Pharmacist read-only account when a pharmacy module exists | 02 J-D1 and 1.2; not for 1.0 |
| P-5 | Package import as `site.setup`-like right held by steward or coordinator, with the PI's approval still required | Two-person path kept: who imports is not who approves |

### 4.3 Cross-site dashboards with no patient-level data

| View | Built from | Small-cell rule | Exists? |
| --- | --- | --- | --- |
| Feasibility counts by site (draft protocol) | FEAS on a draft package | D-467: floor 10, multiples of 10, steward approval to release | Rules and signing yes; draft package no |
| Screening funnel by site (candidates → reviewed → approached → contacted → consented) | Status feed (new) | Pre-consent stages rounded as D-467 [O] | No |
| Screen-failure reasons by category | Lifecycle reasons | Rounded; categories only | Categories exist [R `services/console/sitestore.py:39-56`] |
| Enrolment against target | Enrolled count and the package's target | Post-consent counts exact [O; decision OD-3] | No |
| Package version per site, differences flagged | Import record | None needed | No |
| Query load | The EDC, not TrialBox | – | Not TrialBox's |
| Cohort counts by quarter | Alliance tables | D-73 ranges | Yes |

**Why post-consent counts may be exact** [O]: a consented, enrolled participant's record is already in the sponsor's
EDC with a subject number; the count tells the CC nothing the EDC does not. Pre-consent counts concern patients who
have agreed to nothing; they follow D-467. Decision OD-3.

---

## 5. The whole life cycle of a multicentre study

"Exists / partial / missing" against the code. JP, TW, US variants where they differ.

| # | Step | TrialBox today | State | Japan | Taiwan | US |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | **Idea and feasibility** (counts before the protocol is final) | FEAS on pasted criteria at one site; alliance COHORT for cohorts; opportunity feed for recruiting registry trials | Partial: no draft package sent to many sites | Counts are not personal data [O] | PDPA 6(1)(iv) [S12] | Preparatory to research [S15] |
| 2 | **Site selection** | Site capability profile (AD and general capabilities) [R `sitestore.py:57-72`] | Partial: one site's answers; no CC view | – | – | – |
| 3 | **Protocol in** (document, structured protocol, registry record) | Protocol page: rule-set id + file or pasted text [R `services/console/templates/protocol.html:11-15`] | Partial: no NCT/jRCT field on the page; no M11 or USDM | jRCT | TW registry (not verified) | ClinicalTrials.gov |
| 4 | **Registry intake** | CT.gov client reads 13 fields from 7 of 13 modules [M 5]; jRCT and UMIN ids validated by pattern only [R `sitestore.py:250-272`] | Partial (5.2) | jRCT: no API; no crawler; names not reusable [S3, S4] | Not verified | API v2, latest version only [M 5] |
| 5 | **Criteria compile and review** | Compiler, IR, approval by the PI after the steward names him (D-540, as the walk cites it) | Exists for one site; no package, no site-difference view | – | – | – |
| 6 | **Start-up** (contract, IRB, delegation log, training, SIV) | IRB record, ICF versions, delegation log with GCP training date, SIV date [R `teamstore.py:44,131,165`; `sitestore.py:204`]; contract: none | Partial | Central review + head's permission (2.2) | Joint board allowed (HSRA 10) | Single IRB (46.114) [S14] |
| 7 | **Pre-screening** | SCREEN, whole hospital or by practitioner (D-146) | Exists | 指針/GCP basis for looking at records: per site (not re-examined here) | – | 164.512(i)(1)(ii) [S15] |
| 8 | **Candidate list and outreach** | Week list, PI marks, referral to treating doctor, contact outcomes, attempt rule (D-407) | Exists | – | – | – |
| 9 | **Consent, eConsent, re-consent** | Consent form, re-consent slots; eConsent stays the site's system [R `services/orchestrator/scenarios/consent.py:17`] | Partial: no eConsent link | – | – | – |
| 10 | **Screening visits, screen failures** | Lifecycle steps, reasons, screening number | Exists (no site code in the number) | – | – | – |
| 11 | **Randomisation, enrolment (IWRS)** | Enrolment records that randomisation happened, its day and number; no arm (D-407) [R `services/datacore/lifecycle.py:138`] | Exists as a record; no IWRS link (by D-144: randomisation not in TrialBox) | – | – | – |
| 12 | **Visits and data capture (EDC)** | Versioned schedule; prefill to REDCap or the EDC; ODM export (`services/edc/odm.py`) | Partial: REDCap DAG yes; the EDC module not shipped (plan 9 rev 2, 9m) | – | – | – |
| 13 | **SDV and monitoring** | Monitor grant and visit record, inside the hospital | Partial: no remote, no central monitoring view | – | – | – |
| 14 | **Queries** | None in TrialBox | Missing (the EDC's) | – | – | – |
| 15 | **Deviations** | Deviation form; "possible deviations" proposed (D-407) | Exists at the site; not counted for the CC | – | – | – |
| 16 | **Safety: SAE clocks, SUSAR** | SAE register; rule sets `jp_gcp`, `jp_gcp_ii`, `jp_crb`, `jp_guideline`, `tw_trial`, `tw_research`; 24 h counted in hours; calendar days [R `lifecycle.py:142-184`; `services/console/saerecord.py:1-44`] | Partial: no US set; no working-day clock; SUSAR is the sponsor's | J-GCP art. 48 etc. (as coded) | As coded | Investigator → sponsor "immediately" (312.64(b)) [S22]; sponsor 7 / 15 calendar days (312.32(c)) [S21]; device UADE: sponsor and IRB within **10 working days** (812.150(a)(1)) [S23] |
| 17 | **Drug accountability** | Capability "pharmacy and drug accountability" as a site answer only | Missing (by D-144: input only) | – | – | – |
| 18 | **Amendments** | D-364 amendment record per approved version; schedule versions; ICF versions | Partial: per site; no package diff | Central amendment, local permission | – | – |
| 19 | **Interim** | None | Missing (sponsor and DSMB; TrialBox gives counts only) | – | – | – |
| 20 | **Close-out** | Study state `closed`, final, PI may take back the same site day (D-763) | Exists at the site | – | – | – |
| 21 | **Archive and retention** | Study files held for the study's period after close, default 5 years [R `libs/tb_common/retention.py:46`]; audit for ever in the archive | Partial: the period is typed per site; the package could carry it | GCP retention (not opened) | Not opened | 21 CFR 312.62(c) (not opened) |
| 22 | **Results reporting** | None | Missing (sponsor's; registry results) | jRCT | – | CT.gov results |
| 23 | **Afterwards: registry, PMS, reimbursement** | NAV and TWPAS fenced (plan 9 decision 8) | Out of 1.0 | 製造販売後調査 (not opened) | NHI renewals (02, 4e) | – |

### 5.1 The life cycle by who acts, multicentre

| Phase | Coordinating centre does | Each site's box does | What crosses |
| --- | --- | --- | --- |
| Feasibility | Writes a draft package (criteria only) | Steward approves the release; FEAS; signed counts | Draft package in; rounded counts out |
| Selection | Reads counts and capability answers | Fills the capability profile | Capability answers out (no patients) |
| Start-up | Signs package v1.0 with the central approval | Imports; maps local codes; PI approves; IRB/permission recorded | Package in |
| Recruiting | Reads the funnel and enrolment by site | Screens, lists, contacts, consents | Weekly signed status counts out |
| Conduct | Amendments as new package versions | Imports the amendment; re-consent list | Package in; counts out |
| Close | Closes the study | Closes; retention from the package | A final count out |

### 5.2 Registry intake: what the importer does and where it is thin

**ClinicalTrials.gov** [M 5; S1, S2]. API version 2.0.5, data of 2026-11-17. The OpenAPI file lists `/studies`,
`/studies/{nctId}`, metadata, search areas, enums, statistics and version; **no endpoint returns earlier versions of a
record**, so an importer sees only the latest, and an amendment is noticed only by `lastUpdatePostDate` (which the
trial cache already keys on [R `services/orchestrator/db.py:124-131`]). A record has 13 protocol modules; TrialBox's
`to_study` reads 13 fields from 7 of them [R `services/criteria_compiler/ctgov.py:44-72`]:

| Read today | Not read, and why it matters for multicentre work |
| --- | --- |
| NCT id, titles, phases, conditions, overall status, last update, enrolment count, lead sponsor, countries of locations, eligibility text, ages, sex | **Locations** (facility, per-site recruitment status, contacts): which sites recruit, the basis for site selection. **secondaryIdInfos**: where a jRCT or EudraCT id sits, the join key between registries. **armsInterventionsModule**, **outcomesModule**, **designModule** beyond phase (allocation, masking): the package's study definition. **oversightModule**. **overallOfficials** (names are public, but they must not become a contact list) |

The live terms page renders by script and could not be read; archived terms of the same site say the data are free
to all, ask for attribution and currency, and note a copyright outside the US (not verified as current) [S2].

**jRCT** [S3, S4]. No API; a CSV download exists on the search page. The top page asks users not to collect in bulk
beyond personal use, and says automated collection by program counts as beyond it. The terms page puts content under
the government's 公共データ利用規約 (PDL 1.0) **except** names and contacts of review-board members and researchers,
whose use is limited to enquiries about the research; comprehensive collection needs a permission from the help desk;
crawlers are refused. **Consequence** [O]: a jRCT intake must be one record at a time, started by a person (a jRCT
number typed, or the CSV the person downloaded), and must never store investigators' names or contacts. TrialBox has
none today; the console even says "TrialBox has no jRCT or ClinicalTrials.gov connection" [R
`services/console/i18n_home.py:218`], which is untrue on a box with CT.gov live or offline. jRCT points to
rctportal.mhlw.go.jp for cross-search with UMIN-CTR [S3]. UMIN-CTR's terms forbid redistribution, so it is a
site-fetch source [R `libs/tb_common/refdata.py:41`].

**Taiwan's registry:** not opened (not verified); today an id is checked only for shape [R `sitestore.py:250-253`].

### 5.3 "Streamlined": steps from "protocol in" to "first candidate list reviewed"

**Today, measured on the walks** [M 4]: steps 2 to 13 of the new-study and life-cycle walks.

| | Count |
| --- | --- |
| Steps | 12 (2 to 13) |
| Actions (rows of the walk's tables, plus the clicks of steps 12 and 13) | about 39 |
| Roles | 3 (coordinator, investigator, steward) |
| Hand-offs (a different role acts next) | 5: CRC→PI (refused, no PI named), PI→steward, steward→PI, PI→CRC, CRC→PI |
| Jobs a person starts by hand | 2 (FEAS, SCREEN) |
| Steps the walk skips that a real study needs | IRB record (F-04), study type and opening (F-14), study identity, consent set-up, visit schedule |

**The shortest honest path, single site** [O]:

1. CRC: protocol in (file, or an NCT/jRCT number), study type and consent model asked on the same page.
2. Steward: names the PI (the D-540 step stays: the two-person rule is worth one hand-off).
3. PI: approves criteria; the same page records the IRB approval reference and date (today's D-364 fields).
4. Open: FEAS and SCREEN start themselves on approval when the study is open (today two manual requests).
5. PI: reviews the first list.

Three hand-offs, about 15 actions, nothing skipped.

**The shortest honest path, a second site of a multicentre study** [O]:

1. Steward: imports the signed package; the box verifies the signature, runs the package's tests, prints the
   code-coverage gaps; the steward maps them and names the PI.
2. PI: approves "package v1.0 plus these differences" and records the head of institution's permission.
3. Open: FEAS and SCREEN start; the first signed count goes to the CC.
4. PI: reviews the first list.

Two hand-offs, about 10 actions. The proving walk is card M14-24.

---

## 6. One engine for every kind of study

What truly differs is **consent, safety and data capture**; the core (find, list, review, track) is one. 02 section 4
gave the per-kind walk; this table adds multicentre and makes the switch explicit.

| Setting | Multicentre industry trial | Single-centre trial | IIT (医師主導治験, 特定臨床研究) | Registry / biomarker | Observational, retrospective | Device | Reimbursement |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `federation` | member | none | member or coordinating | member or none | member (counts) | member | none |
| `study_type` (02 J-12) | trial | trial | iis | biomarker / registry | observational_retrospective | device | (module, not a type) |
| `consent_model` | written (eConsent at site) | written | written | tiered | waiver with legal basis | written | none (care) |
| `safety_rule_set` | per country, sponsor | per country | `jp_gcp_ii` / `jp_crb` / `tw_trial` | none | none | device set (US: 10 working days) | ordinary pharmacovigilance |
| `data_capture` | sponsor EDC (or REDCap DAG) | REDCap or EDC module | EDC module or REDCap | internal forms or REDCap | extraction | sponsor EDC | none |
| `contact` | yes | yes | yes | yes | **no** | yes | treating doctor |
| Package source | CC signs | site makes its own | lead hospital signs | registry office signs | CC signs a cohort definition | CC signs | NHI rule edition |
| Counts out | weekly funnel | none | weekly funnel | quarterly cohort (D-73) | one-off counts | weekly funnel | none |
| Core (find, list, review, track) | ● | ● | ● | ● | ● (cohort, no list review) | ● | ● (fenced) |

[O] One package format serves every column: a single-centre study is a package the site signs for itself. That
makes "single-centre" a special case of multicentre, which is the owner's point.

---

## 7. Connections outward and the standards that carry a study

### 7.1 Systems

| System | What crosses | Today | Proposal |
| --- | --- | --- | --- |
| **REDCap** (multi-site) | Screening number and status out; status read back | Link with DAG; records of other DAGs counted, not read [R `link.py:209-250`]; create mode writes the DAG (DECISIONS line 1555) | The package carries the project link template and the DAG naming rule; the site fills its DAG |
| **The owner's EDC (module)** | As REDCap, by its connector | Plan 9 rev 2: a module of TrialBox, multi-site with site-level rights, not yet good enough as a product (9m); TrialBox signs in as its one client (decision 5) | The package names the EDC study; site = the EDC's site. Nothing here from the EDC's repository (D-1060) |
| **CTMS** | Site status, enrolment counts | None | The status feed is what a CTMS would read; a CSV/JSON export, no inbound |
| **eTMF / ISF** | Documents and versions | ISF index as input only (D-144) | Package carries document hashes; the site's ISF index lists them |
| **IWRS / IRT** | Randomisation number and day | Recorded by hand (D-407) | Keep; no link in 1.0 |
| **eConsent** | Consent date, version | The site's system stays; TrialBox records facts | Keep |
| **Safety database** | SAE reports | The register tracks dates sent; nothing sent by TrialBox | Keep; US rule sets (M14-16) |
| **Registries** | Protocol data in | CT.gov API; jRCT none | 5.2 |

### 7.2 Standards: which the package speaks

| Standard | What it carries | Status (opened) | In TrialBox | Package should |
| --- | --- | --- | --- | --- |
| **ICH M11 (CeSHarP)** | The protocol's structure; technical specification maps template sections to CDISC terms (NCI C-codes) | Adopted at Step 4 on 19 November 2025; copyright ICH, reuse allowed with acknowledgement [S24] | 0 | Read the M11 sections that carry title, design, objectives and the eligibility text; criteria stay TrialBox IR (whether M11 makes criteria computable: not verified) |
| **CDISC USDM** | Study design, schedule of activities, eligibility as data | Version 4 described by secondary sources; CDISC page not opened (not verified) [S25] | 0 | Import later; not 1.0 |
| **CDISC ODM 2.0** | Forms, items, data; `SiteRef` points a subject's data at an `AdminData/Location` | Schema `odm/v2.0` [S26] | ODM export in the EDC path (30 files mention ODM) [M 6] | Forms and schedule of the package; site = Location |
| **FHIR R5 ResearchStudy** | `site` (0..*), `associatedParty`, `recruitment.targetNumber/actualNumber/eligibility` (Group or EvidenceVariable), `progressStatus`, `partOf` | Maturity 0, trial use [S27] | 0 | Export the package header and per-site status as ResearchStudy; eligibility as EvidenceVariable (spec v4 already names this for sponsor systems) |
| **FHIR ValueSet** | Code lists | Normative in R4 (not re-checked) | **Yes**, every rule set | Keep |
| **CQL** | Computable criteria | – | Present in rule sets (`cql/`) | Carry; the IR stays the source |
| **OMOP / OHDSI cohort definition** | Cohort JSON (ATLAS) for network feasibility | OHDSI network-study model [S5] | 0 (OMOP DDL exists; no cohort import) | Accept an ATLAS cohort as a feasibility-only input, later |
| **SMART on FHIR** | Launch from the EHR | Not opened | 0 | Not for 1.0: Japanese and Taiwanese HIS do not offer it to our knowledge (not verified) |

---

## 8. Gap table

| # | What the product does today | What is needed | Evidence |
| --- | --- | --- | --- |
| G-1 | A study is a local rule-set id | A shared study id (registry id + protocol version) on every package-derived study | [M 1]; `sitestore.py:204` |
| G-2 | Manifest mixes protocol and site | Two parts; the protocol part signed and read-only | `manifest.yaml:1-58` |
| G-3 | No import of a study from another box | Signed package import over the update-bundle channel | 0 import paths found [R `criteria_compiler/app.py`, searched] |
| G-4 | No proof at a site that the compile matches | Package tests run at import | `rulesets/*/tests/` exist, unused for this |
| G-5 | Local code gaps found late | Coverage report per package at import | D-1113, D-1116 |
| G-6 | Screening number has no site code | `{site}-{seq}` or a package rule | `sitestore.py:618` |
| G-7 | Alliance tables unsigned; sender address binds | Ed25519 as the opportunity feed | `cohort.py:341-349` vs spec 05:234 |
| G-8 | No status feed per study | Weekly signed funnel and enrolment | – |
| G-9 | Hub page shows registry trials only | Coordinating view: feasibility, funnel, reasons, enrolment, package versions | `services/opportunity_hub/dashboard.py:1-30` |
| G-10 | No coordinating roles | Coordinating mode with its own roles, no patient role | [M 3] |
| G-11 | Every coordinator sees every study | Study-scoped coordinator (SMO) | `authz_matrix.yaml:109` |
| G-12 | CT.gov: 7 of 13 modules | Locations, secondary ids, arms, outcomes, design | [M 5] |
| G-13 | No jRCT intake; text says "no connection" | One-record intake; text fixed | `i18n_home.py:218`; [S3, S4] |
| G-14 | No US SAE clocks; no working days | `us_ind`, `us_ide` rule sets; a working-day clock with a holiday calendar | `lifecycle.py:175-184`; [S21 to S23] |
| G-15 | No amendment diff across versions | Package diff and site re-approval | `service.py:290` |
| G-16 | Walk skips IRB and type; two manual jobs | Asked on the way; FEAS and SCREEN start on open | life-cycle walk F-04, F-14 |
| G-17 | No standard export of a study | ResearchStudy + EvidenceVariable; ODM 2.0 forms | [M 6] |
| G-18 | Draft-protocol feasibility at many sites only by hand | Draft package; counts by D-467 rules | D-467 |

---

## 9. Cards for plan 10

Sizes: S a day or less, M a few days, L a week or more (estimates). Lanes as review 02: A2 screening, C2a journey,
C2b trust and operations, E EDC and terminology, B2 data, D installer, J this lane, R review, Int integrator.

| # | Card | Size | Lane | Waits for | Proved by |
| --- | --- | --- | --- | --- | --- |
| M14-1 | Split the rule-set manifest into `protocol` and `site` parts; the loader merges; site edits to the protocol part refused | M | A2 | OD-1 | One package on two synthetic sites: identical criteria hash; a site edit of a threshold refused with a sentence |
| M14-2 | Package format v1: canonical tar, header (registry id, protocol version, package version, previous, CC, central approval), sha256 list, Ed25519 signature | M | A2, Int | M14-1 | Schema test; a byte changed fails verification |
| M14-3 | Import a package on a box: register of CC keys (as `load_register`), refuse unknown keys, audit the import; the update-bundle media path | M | C2b, D | M14-2 | Import of a signed and an unsigned package on the steps box; audit rows |
| M14-4 | Allowed adaptations: local code maps, labels, scope, routing, windows within tolerance, floors raised; a site-differences page on the PI's approval | M | C2a | M14-1 | Each allowed field accepted; a forbidden one refused; the page lists differences |
| M14-5 | Run the package's synthetic tests at import; result on the approval page | S | A2 | M14-3 | A broken expansion fails the test and blocks approval |
| M14-6 | Code-coverage report per package: each value-set code with no row in this lake, sent to the steward's local code page | M | E | M14-3 | On the synthetic site, a removed LOINC code shows as a gap |
| M14-7 | Amendment: package diff (criteria, forms, schedule, ICF); D-364 record filled from the package; re-consent list on an ICF change | M | A2, C2a | M14-3 | v1.0 → v1.1 on two sites; diff page; re-consent list grows |
| M14-8 | Shared study id on `study_identity` from the package; screening number default `{site}-{seq}` for package studies | S | C2a | M14-3 | Two sites issue distinct numbers for one study |
| M14-9 | Status feed v1: weekly signed counts per study (funnel stages, screen-fail categories, enrolled vs target, package version); pre-consent stages by D-467 | M | A2 | OD-3 | Validator test as `opportunity.validate`; small cells never published |
| M14-10 | Coordinating view: extend the hub page with feasibility by site, funnel, reasons, enrolment against target, package versions | M | C2a | M14-9 | Page from three synthetic feeds; no patient-level field reachable |
| M14-11 | Draft-package feasibility round: a draft package (criteria only) counts under D-467 after the steward's release | S | A2 | M14-3 | Draft counted on two sites, merged without summing different versions |
| M14-12 | Coordinating mode: a box flag that disables patient roles and enables CC roles (P-2); package build and signing there | L | C2b | OD-2 | Mode box refuses every patient-level route (a table test) |
| M14-13 | Proposals P-1 to P-5 handed to lane C2 as matrix rows to decide | S | J → C2b | – | C2's decision record |
| M14-14 | CT.gov intake widened: locations with status, secondary ids, arms, outcomes, design; an NCT field on the protocol page | M | A2 | – | Cassette record round-trips every field; jRCT id found in `secondaryIdInfos` |
| M14-15 | jRCT intake: one record from a typed number or the person's own CSV; names and contacts never stored; no crawler | M | A2, E | OD-6 | Test: a CSV with investigator names stores none of them |
| M14-16 | Fix "TrialBox has no jRCT or ClinicalTrials.gov connection" to state the box's CT.gov mode, in three languages | S | C2a | – | Text test per mode |
| M14-17 | US safety rule sets `us_ind` and `us_ide`; a working-day clock with a site holiday calendar | M | C2a | Plan 9 decision 6 (US in 1.1) | Clock tests: 312.32 7/15 calendar days; 812.150 10 working days across a holiday |
| M14-18 | Package header and site status exported as FHIR R5 ResearchStudy; eligibility as EvidenceVariable | M | E | M14-2 | Validates against the R5 schema; round trip of the header |
| M14-19 | Package forms and schedule as ODM 2.0 metadata; site as `Location`, subjects with `SiteRef` | M | E | M14-2 | ODM 2.0 schema validation |
| M14-20 | Sign the alliance cohort tables (Ed25519, key register) as D-144 and spec 05 say | S | A2 | – | An unsigned or wrongly signed table refused at the root |
| M14-21 | REDCap: the package carries the project link template and DAG rule; the link page fills from it | S | E | M14-2 | Link from template on two synthetic DAGs |
| M14-22 | Single-site shortest path: study type, consent model and IRB on the protocol and approval pages; FEAS and SCREEN start on open | M | C2a | J-12 | New-study walk: 5 steps, 3 hand-offs, nothing skipped |
| M14-23 | Retention years and SAE rule set suggested from the package per country | S | C2a | M14-3 | Prefilled on import |
| M14-24 | Second-site walk: two steps-mode boxes, one in coordinating mode; import, adapt, approve, first list; time and clicks | L | J, R | M14-1 to M14-6, M14-12 | Under 60 minutes and about 10 actions, measured |
| M14-25 | OHDSI ATLAS cohort JSON as a feasibility-only compiler input | L | A2 | OD-1 | One public OHDSI phenotype compiled and counted on the synthetic OMOP |
| M14-26 | Countersigned daily audit head between site and CC (SC-72) | L | C2b | M14-12 | A changed past journal row detected against the countersigned head |

**Count:** 26 cards: 8 S (M14-5, -8, -11, -13, -16, -20, -21, -23), 14 M, 4 L (M14-12, -24, -25, -26).
**Start now without a ruling:** M14-13, M14-14, M14-16, M14-20.

---

## 10. Decisions only the owner can make

| # | Decision | Recommendation | Why now |
| --- | --- | --- | --- |
| OD-1 | Federation model | **(b)**: a coordinating centre signs a study package; boxes return signed aggregates only. (c) stays with the EDC and REDCap | Every card here waits on it; it fixes the product's rule "only aggregates leave" for multicentre work |
| OD-2 | Where a coordinating node runs | **At the lead institution** (a 中核病院, a network headquarters, or the sponsor-investigator's hospital), never vendor-hosted | D-144 (vendor holds no patient data) and sponsors' confidentiality |
| OD-3 | What a site sends the CC each week | **Counts only**: pre-consent stages rounded as D-467; post-consent counts exact; per-subject data only through the EDC | The legal basis stays "statistics" in all three countries |
| OD-4 | Package transport | **Signed file on media or internal mail first**; an online pull later only with the hospital's approval | Offline boxes; one-way transfer |
| OD-5 | Feasibility on a draft protocol at several sites | **Yes**, under D-467 and the steward's release | The owner's "pre-screening from ClinicalTrials.gov" and the sponsor's first question |
| OD-6 | jRCT intake | **One record at a time, started by a person; no bulk copy**; ask the MHLW help desk only if bulk is ever wanted | jRCT's terms [S3, S4] |
| OD-7 | US variant (SAE clocks, single IRB) | **In 1.1 with US Core** (plan 9 decision 6) | Keeps 1.0's claim to Japan and Taiwan honest |
| OD-8 | SMO coordinators | **Study-scoped coordinator** (P-3), decided by lane C2 | Japanese sites use SMO staff widely (not verified for the first site) |

---

## 11. What the owner or the first hospital must supply

1. **One public multicentre protocol registered in jRCT** that the first site took part in (registry number only;
   the public record), to build the first real package from public data.
2. **The list of multicentre studies the first site runs now**: counts by kind (治験, 医師主導治験, 特定臨床研究, 指針
   research), with who coordinates each (a company, a 中核病院, a network). No patient data.
3. **How those studies are reviewed**: central IRB or CRB, or the hospital's own; how the head's permission is
   recorded (a blank form, with synthetic content).
4. **The EDCs in use**: REDCap version and whether multi-site projects use DAGs; a synthetic REDCap project XML with
   two DAGs.
5. **A blank sponsor screening-log template** (columns only) from one current sponsor.
6. **Whether the site uses SMO staff**, and under what contract scope (one sentence).
7. **The research office's contact** for package import and count release (a role, not a name in this repository).
8. **The local code-system facts the package mapping needs** from the HIS export (laboratory and drug code sets).
   Where this depends on the HIS vendor being Software Service, Inc., that reading is **not confirmed**.
9. **From the owner:** which networks he wants first (a 中核病院 network, NHO, a Taiwan alliance) and whether a
   lead institution will run a coordinating node.

---

## 12. Measurement log

| n | Command | Result |
| --- | --- | --- |
| 1 | A 40-line Python script (`/tmp/claude-0/…/scratchpad/b15/tables.py`, not committed) that finds every `CREATE TABLE` in `services/**/*.py` and `libs/**/*.py` (OMOP DDL, tests and generated models excluded), and checks the body for a column named `site`, `site_id`, `site_code`, `centre`, `center`, and for `study`, `study_id`, `ruleset`, `protocol`, `project` | 157 tables; with a site column 4 (`site_key`, `cohort_tables`, `cohort_stored`, `cohort_tables_before`); with a study column 74 |
| 2 | `grep -rli` / `grep -rhi` for alliance, federat, multi-site, multicent, coordinating, over `services libs tools` (`--include=*.py`) and over `docs spec` | Section 1.2 table |
| 3 | `grep -c "^    what:" libs/tb_common/authz_matrix.yaml`; `roles:` line | 89 actions; 7 roles; the conditions list names no site |
| 4 | Rows of the step tables of `docs/handover/new-study-walk.en.md` between its markers (`grep "^| [A-Z]"` minus headers); "Sign in with" rows; the life-cycle walk's table for steps 12 and 13 | Steps 1 to 11: 35 actions, 3 sign-ins; step 1: 2 actions; steps 12 and 13: 2 and 4 clicks. Steps 2 to 13: 33 + 6 = 39 actions, 3 roles, 5 role changes |
| 5 | `curl https://clinicaltrials.gov/api/v2/version`; `curl …/api/oas/v2`; `curl …/api/v2/studies/NCT04368728` (deleted after reading) | apiVersion 2.0.5, dataTimestamp 2026-11-17T10:00:05; paths: studies, studies/{nctId}, metadata, search-areas, enums, stats (3), version; 13 protocol modules; `Location` has facility, status, city, state, zip, country, contacts, geoPoint; `to_study` reads 7 modules |
| 6 | `grep -rli` for EvidenceVariable, ResearchStudy, ResearchSubject, USDM, ODM, Circe/ATLAS over `services libs tools` | 0, 0, 0, 0, 30 files, 5 files (the ATLAS hits are a mail command of another meaning) |
| 7 | `grep -rli` over `services libs` for amend, randomi, econsent, re-consent, accountab, deviation, SDV, retention, archive, "results report" | 17, 11, 9, 8, 1, 18, 6, 32, 11, 0 files |

---

## 13. Sources (opened 2026-11-18 unless said)

| # | Source | Link | Terms or licence |
| --- | --- | --- | --- |
| S1 | ClinicalTrials.gov API v2 (version, OpenAPI file, one record) | https://clinicaltrials.gov/api/v2/version ; https://clinicaltrials.gov/api/oas/v2 | Live terms page renders by script: not read |
| S2 | ClinicalTrials.gov terms (archived versions, via search) | https://webarchive.library.unt.edu/web/20130223220909/http://clinicaltrials.gov/ct2/about-site/terms-conditions | Archived; current text not verified |
| S3 | jRCT top page (notice on data use; rctportal) | https://jrct.mhlw.go.jp/ | © MHLW |
| S4 | jRCT terms of use | https://jrct.mhlw.go.jp/agreement | PDL 1.0, except names and contacts; bulk needs permission |
| S5 | The Book of OHDSI, network research | https://ohdsi.github.io/TheBookOfOhdsi/NetworkResearch.html | CC0 / public (book's licence not re-checked) |
| S6 | PCORnet, data | https://pcornet.org/data/ | Web page |
| S7 | Harvard Catalyst, SHRINE | https://catalyst.harvard.edu/shrine/ | Web page |
| S8 | TriNetX (search results: institutional pages and papers) | https://pmc.ncbi.nlm.nih.gov/articles/PMC6816049 ; https://trinetx.com/data | Not opened directly: summarised from search |
| S9 | EHDEN data partners | https://ehden.eu/datapartners/ | Web page |
| S10 | DataSHIELD (search: Int J Epidemiol 2014, PubMed 25261970) | https://pubmed.ncbi.nlm.nih.gov/25261970/ | Abstract via search; paper not opened |
| S11 | APPI art. 27 (e-Gov API) | https://laws.e-gov.go.jp/api/1/articles;lawId=415AC0000000057;article=27 | Japanese law text |
| S12 | Taiwan PDPA art. 6 | https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=I0050021&flno=6 | Law text |
| S13 | Taiwan Human Subjects Research Act | https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=L0020176 | Law text |
| S14 | 45 CFR 46.114 | https://www.law.cornell.edu/cfr/text/45/46.114 | US regulation |
| S15 | 45 CFR 164.512 | https://www.law.cornell.edu/cfr/text/45/164.512 | US regulation |
| S16 | (limited data set, 164.514(e)) | not opened | – |
| S17 | PMDA, MID-NET | https://www.pmda.go.jp/safety/mid-net/0001.html | Web page |
| S18 | MHLW, 臨床研究中核病院の承認要件見直しについて (2024-09-04) | https://www.mhlw.go.jp/content/10808000/001298506.pdf | Government document |
| S19 | NHO network (search results only) | https://nho.hosp.go.jp/files/000259955.pdf | Not opened (size limit) |
| S20 | 生命・医学系指針, 一括審査 (search: MEXT, Gifu, Tohoku material) | https://www.mext.go.jp/kaigisiryo/content/20201211-mxt_life-000011472_03.pdf | Guideline text not opened |
| S21 | 21 CFR 312.32 | https://www.law.cornell.edu/cfr/text/21/312.32 | US regulation |
| S22 | 21 CFR 312.64 | https://www.law.cornell.edu/cfr/text/21/312.64 | US regulation |
| S23 | 21 CFR 812.150 | https://www.law.cornell.edu/cfr/text/21/812.150 | US regulation |
| S24 | ICH M11 Technical Specification, final, adopted 19 Nov 2025 (PMDA copy) | https://www.pmda.go.jp/files/000278212.pdf | © ICH, reuse with acknowledgement |
| S25 | USDM v4 (secondary sources via search) | https://github.com/data4knowledge/usdm_m11_resources | Not the CDISC page: not verified |
| S26 | CDISC ODM 2.0 LinkML, `SiteRef` | https://cdisc-org.github.io/DataExchange-ODM-LinkML/SiteRef | CDISC |
| S27 | HL7 FHIR R5 ResearchStudy | https://hl7.org/fhir/R5/researchstudy.html | CC0 (FHIR spec) |

---

## 14. What this document did not verify

- **No box was run.** The step counts are from the walk documents' tables and the walk's own findings, not a new run;
  the "under an hour" target for a second site is an opinion until M14-24 measures it.
- **Table inventory:** a regular-expression scan; a table created by a string the regex does not see, or a site
  column with another name, would be missed. The 157 excludes the OMOP DDL and test fixtures.
- **ClinicalTrials.gov's current terms** (the page renders by script); archived terms only.
- **jRCT:** the CSV download's columns and whether it carries investigators' names; how the 2025 law change affects
  records (jRCT itself reports open defects) — not examined.
- **Taiwan's trial registry** (its API, terms, id format) and TFDA's joint-review arrangements: not opened.
- **Japanese law beyond APPI art. 27:** whether aggregate counts are "statistical information" outside APPI per the
  PPC guidelines; the 生命・医学系指針's text on 一括審査 and on providing information to other institutions; the
  臨床研究法 and J-GCP articles on central review; retention periods. Read only through search summaries or not at all.
- **US:** 164.514 (de-identification, limited data set) and 312.62 (retention) not opened; the FDA's single-IRB rule
  for FDA-regulated research not checked.
- **Networks:** TriNetX, DataSHIELD and NHO from search summaries and papers' abstracts, not their own documentation;
  MID-NET's data location and output rules not stated on the page read.
- **Standards:** USDM v4's release and content from secondary sources; whether ICH M11 makes eligibility criteria
  computable or leaves them as text; the ODM 2.0 release date; FHIR ValueSet's normative status was not re-checked.
- **The owner's EDC:** only what plan 9 revision 2 states (D-1060); whether its site model maps one-to-one to a
  TrialBox site is not known.
- **The first site:** its SMO use, its review arrangements and its HIS vendor (Software Service, Inc. is the
  coordinator's reading, **not confirmed**) are unknown; section 11 asks for them.
- **Legal readings** in section 2 are opinions, not legal advice; counsel must read them before a coordinating node
  is offered to a network.
