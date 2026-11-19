# 11. Secure development: the SSDF and IEC 81001-5-1 mapping

*Card 10G-19 (review 16, item 16-12), D-1240. The register is `docs/validation/ssdf-iec81001.csv`; this page is
kept in step with it by `tests/unit/test_ssdf_iec81001.py`.*

> **This is a self-assessment, written by the people who build TrialBox.** It is not an audit, and it does not say
> that TrialBox meets NIST SP 800-218 or IEC 81001-5-1, or that it holds any certification. Do not quote it to a
> customer, a hospital or an auditor as a claim. Before any such use, a person who holds the purchased standard
> IEC 81001-5-1:2021 (and any interpretation sheet issued for it) must check the clause list and the titles below
> against the standard's text, and someone independent of the builders must check the statuses.

## What it covers

- **NIST SP 800-218, SSDF version 1.1** (February 2022): all 19 practices and their 42 tasks, under the published
  ids (PO.1.1 and so on). The ids and practice titles come from NIST's own SSDF table; SSDF is a US government work.
- **IEC 81001-5-1:2021**, security activities in the health-software life cycle: the clauses and subclauses of
  clauses 4 to 9 that public summaries name. The standard is copyrighted and was not read, downloaded or quoted. Each
  row carries the clause number and a short title in our own words only, and says in its `source` column that it is
  unverified against the standard's text. Five numbers are implied by the numbering but no public summary gives their
  content (5.4.2, 5.8.4, 5.8.5, 5.8.6, 9.1); they have the status `unverified against the standard's text` and no
  assessment. Two groups that the public summaries give only together are one row each (6.3 for 6.3.1 to 6.3.3, 7.1
  for 7.1.1 and 7.1.2). The list may still miss subclauses.
- TrialBox is not a medical device (`docs/SECURITY.md`). IEC 81001-5-1 is mapped because hospitals and regulators
  name it for health software in general (review 16, row I4).

**Public summaries used for the IEC 81001-5-1 rows** (the `source` column names them):

- S1: Kelsey QMS, "IEC 81001-5-1 crosswalk", the clause list with one-line topics,
  <https://kelseyqms.com/crosswalk/iec-81001> (read 2026-11-19).
- S2: Kelsey QMS, "IEC 81001-5-1 + FDA cybersecurity guidance", the guide naming the main clauses,
  <https://kelseyqms.com/guides/iec-81001-cybersecurity> (read 2026-11-19).
- The IEC catalogue entry for the standard's title and scope, <https://webstore.iec.ch/publication/33615>.

## How to read a row

| Column | Meaning |
| --- | --- |
| `status` | `met`: the cited files do it on `master` today. `partly`: some of it is done, or only a plan or design says it. `not met`: nothing does it yet. `not applicable`: with the reason. For IEC rows only, `unverified against the standard's text`: content not known, not assessed |
| `evidence` | repository paths (from `trialbox/` or the repository root), separated by `;`. `path::name` names a test function, a Makefile target or a CI job in that file |
| `gap`, `weight`, `size`, `card` | for `partly` and `not met`: what is missing in one sentence; its weight (high, medium, low); the rough size to close it (plan 8's sizes: S a day or less, M a few days, L a week or more; estimates); the plan-10 card that would close it, or `no card` |
| practice rows | an SSDF practice's status is derived from its tasks (their common status, or `partly` when they differ); the test holds it |

A plan or a design document is never enough for `met`: at most `partly`.

## Summary by group

Counts of task rows (SSDF) and clause rows (IEC 81001-5-1); practice rows are left out because they repeat their tasks.

<!-- summary -->

| Framework | Group | Rows | met | partly | not met | not applicable | unverified |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SSDF | PO | 13 | 4 | 6 | 3 | 0 | 0 |
| SSDF | PS | 4 | 1 | 3 | 0 | 0 | 0 |
| SSDF | PW | 16 | 8 | 8 | 0 | 0 | 0 |
| SSDF | RV | 9 | 2 | 6 | 1 | 0 | 0 |
| IEC 81001-5-1 | 4 | 11 | 0 | 10 | 1 | 0 | 0 |
| IEC 81001-5-1 | 5 | 27 | 5 | 17 | 1 | 0 | 4 |
| IEC 81001-5-1 | 6 | 4 | 2 | 2 | 0 | 0 | 0 |
| IEC 81001-5-1 | 7 | 5 | 0 | 5 | 0 | 0 | 0 |
| IEC 81001-5-1 | 8 | 1 | 1 | 0 | 0 | 0 | 0 |
| IEC 81001-5-1 | 9 | 5 | 0 | 3 | 1 | 0 | 1 |

In words: of the 42 SSDF tasks, 15 are met, 23 partly and 4 not met. Of the 53 IEC 81001-5-1 rows, 8 are met, 37
partly, 3 not met and 5 not assessed. What is strongest today is the supply chain (hashed locks, pinned tools,
dependency and image scans, SBOMs, signed offline updates), the secure defaults, and the tests that hold a control as a
class. What is weakest is the organisation around the code: no named security owner, no disclosure route, no
security training record, no kept threat model, and no outside testing.

## The gaps, by weight

Every `partly` and `not met` row, heaviest first; within a weight, in the register's order. **High**: a buyer's or
auditor's first question, or a gap that leaves a whole kind of weakness unseen. **Medium**: a control or record that
is partly there. **Low**: a written rule or record for what is already done in practice.

<!-- gaps -->

| Weight | Row | Gap | Size | Card |
| --- | --- | --- | --- | --- |
| high | SSDF PO.2.1 | No security owner is named at Aimedics (soa.csv 5.2, REG-031) and no role is written for each security activity of the development life cycle. | S | no card |
| high | SSDF PW.1.1 | The threat model lives in a design document and a review, not in one file reviewed at each release. | S | 10G-4 |
| high | SSDF PW.7.2 | Bandit runs at medium severity and confidence and honours inline nosec lines outside the reviewed ledger, and no person reviews code before it merges. | S | 10G-39; 10G-42 |
| high | SSDF PW.8.2 | There is no dynamic scan of the running console, no fuzzing of the parsers and no penetration test yet. | M | 10G-10; 10G-43; 10G-16 |
| high | SSDF RV.1.1 | Advisories are read weekly through pip-audit and Trivy, but there is no channel for users or researchers to report a vulnerability. | S | 10G-9; 10G-46 |
| high | SSDF RV.1.3 | There is no vulnerability disclosure policy and no public security contact. | S | 10G-9 |
| high | IEC 81001-5-1 4.1.2 | No security owner is named at Aimedics (soa.csv 5.2, REG-031). | S | no card |
| high | IEC 81001-5-1 4.1.7 | There is no disclosure policy and no public security contact. | S | 10G-9 |
| high | IEC 81001-5-1 4.2 | Security hazards (PHI leak, prompt injection) are in the risk file, but there is no security risk process with its own review per release. | M | 10G-4 |
| high | IEC 81001-5-1 5.5.1 | Code is analysed by ruff and bandit and class B changes get one automated adversarial review, but no person reviews code before merge and inline nosec lines are not in the ledger. | S | 10G-39; 10G-42 |
| high | IEC 81001-5-1 5.7.3 | Static and dependency scans run, but there is no dynamic scan and no fuzzing. | M | 10G-10; 10G-43 |
| high | IEC 81001-5-1 5.7.4 | No penetration test has been done. | L | 10G-16 |
| high | IEC 81001-5-1 5.8.3 | Bundles are Ed25519-signed and verified before use, but the signing key is a file, not a hardware token with two-person signing. | L | 10G-7 |
| high | IEC 81001-5-1 7.2 | STRIDE tables exist in the design and in review 16, not as one kept threat model. | S | 10G-4 |
| high | IEC 81001-5-1 9.2 | There is no channel for anyone outside to report a vulnerability. | S | 10G-9 |
| high | IEC 81001-5-1 9.5 | Incidents and fixes have a plan and timelines, but there is no coordinated disclosure. | S | 10G-9 |
| medium | SSDF PO.2.2 | No secure-development training exists or is recorded; a builder's training is its card and brief (QMS-lite section 3). | M | no card |
| medium | SSDF PO.3.3 | The secret and static security scans leave only a CI log: no SARIF or JSON result is kept per run or per release. | M | 10G-50 |
| medium | SSDF PO.4.2 | The release gates write a record per build, but the results of each pull request's scans expire with the CI artefacts and there is no one security record per release. | M | 10G-50 |
| medium | SSDF PO.5.2 | Nothing sets or checks the hardening of the machines and agent sessions that develop, build or sign TrialBox. | M | no card |
| medium | SSDF PS.1.1 | The code lives on GitHub with branch protection the owner sets outside the repository; no person's approval is needed to merge (D-311) and commits are not signed. | M | no card |
| medium | SSDF PS.3.1 | No release is archived yet: the release-record layout exists but no record does, and CI artefacts expire. | M | 10G-50 |
| medium | SSDF PS.3.2 | CycloneDX SBOMs are made per image and for the Python lock and ride in the signed bundle, but there is no signed build-provenance attestation. | L | 10G-7 |
| medium | SSDF PW.2.1 | Designs are reviewed by independent review sessions from time to time, not against the threat model for each change that adds a data flow. | S | 10G-4 |
| medium | SSDF PW.5.1 | Ruff's S rules and bandit enforce part of secure coding, but there is no written secure-coding standard and ruff's S rules are off for tools/ and tests/. | S | 10G-42 |
| medium | SSDF PW.9.2 | The containers run without dropped capabilities, no-new-privileges or read-only file systems. | M | 10G-1 |
| medium | SSDF RV.1.2 | Reviews sample the code for vulnerabilities from time to time; deeper analysis (own Semgrep rules, a secret scan of the git history) is not run. | M | 10G-40; 10G-42; 10G-54 |
| medium | SSDF RV.2.1 | Each accepted finding has a reason and a review date but no owner and no exploitability statement (VEX). | M | 10G-8 |
| medium | IEC 81001-5-1 4.1.1 | QMS-lite and the development plan say how changes are made and recorded but name no security activity of the life cycle. | S | no card |
| medium | IEC 81001-5-1 4.1.4 | Training is recorded for site users and update operators, but not the security competence of the people who build and review TrialBox. | S | no card |
| medium | IEC 81001-5-1 4.1.8 | The six-monthly review is written down but starts only after the first site goes live, and the release mode of the findings check is not in CI. | S | no card |
| medium | IEC 81001-5-1 5.1.1 | The development plan lists the CI checks but not the security activities per phase; design section 9 is a plan, partly built. | S | no card |
| medium | IEC 81001-5-1 5.1.2 | CI holds a read-only token and pinned actions and the tree is scanned for secrets and real data, but developer machines and sessions have no hardening rule. | M | no card |
| medium | IEC 81001-5-1 5.1.3 | Ruff's S rules are configured, but no written secure-coding standard exists. | S | 10G-42 |
| medium | IEC 81001-5-1 5.3.2 | Access is deny-by-default and per service, but the containers do not yet run with least privilege. | M | 10G-1 |
| medium | IEC 81001-5-1 5.3.3 | The architecture is reviewed in occasional reviews, not at each release against a kept threat model. | S | 10G-4 |
| medium | IEC 81001-5-1 5.4.3 | Every TrialBox service checks its caller's token, but HAPI and PostgreSQL have no per-caller token, only network isolation and a password (D-138). | M | no card |
| medium | IEC 81001-5-1 5.7.1 | Many controls have tests, but the ASVS level 2 self-assessment still has chapters not assessed. | M | 10G-5; 10G-56 |
| medium | IEC 81001-5-1 5.7.2 | Some threats have tests (injection, egress), but there is no test per entry of a kept threat model. | M | 10G-4; 10G-44 |
| medium | IEC 81001-5-1 5.7.5 | Reviews are run by sessions apart from the builders, but no independent tester has tested the product. | L | 10G-16 |
| medium | IEC 81001-5-1 5.8.1 | Scanner findings block the bundle (make_bundle --gates), but the findings register's release check is run by hand, not by the release step. | S | no card |
| medium | IEC 81001-5-1 5.8.2 | The release-record layout exists but has no security section and no record has been written. | M | 10G-50 |
| medium | IEC 81001-5-1 6.2.1 | Advisories are checked weekly, not daily, and the watching leaves no record of what was read. | S | 10G-46 |
| medium | IEC 81001-5-1 6.3 | Updates are delivered as signed offline bundles and notices reach sites in 2 working days, but no security release note or advisory format exists. | S | 10G-50 |
| medium | IEC 81001-5-1 7.1 | Assets, zones and assumptions are written in the design, but not kept as a context reviewed with the risk file. | S | 10G-4 |
| medium | IEC 81001-5-1 7.3 | The risk file rates two security hazards with its criteria; the threats of the threat model are not each rated. | S | 10G-4 |
| medium | IEC 81001-5-1 7.4 | Most controls are built and tested, but several planned ones are not (least-privilege containers, signed provenance, penetration test). | L | 10G-1; 10G-7; 10G-16 |
| medium | IEC 81001-5-1 7.5 | Doctor, the nightly drills and the audit check watch the controls, but unusual activity raises no line yet. | M | 10G-12 |
| medium | IEC 81001-5-1 9.3 | Scanner findings are reviewed with a reason and a date, but not with an owner, and outside reports have no route in. | M | 10G-8 |
| medium | IEC 81001-5-1 9.4 | Findings get a severity, but no exploitability statement (VEX) is written per release. | M | 10G-8 |
| low | SSDF PO.1.1 | The security rules of the build and CI infrastructure (read-only token, pinned actions, hashed tools) are in the workflows but not written down as requirements. | S | no card |
| low | SSDF PO.1.3 | No security requirements are sent to the suppliers of models, hardware or services; open-source components are taken as published and gated by the scans. | S | no card |
| low | SSDF PO.2.3 | No written commitment of the company's management to secure development exists in the repository. | S | no card |
| low | SSDF PO.5.1 | Building uses synthetic data only and CI runs on fresh hosted runners, but how the development, build and test environments are kept apart and protected is not written down or checked. | S | no card |
| low | SSDF PW.6.1 | The interpreter and base images are pinned by digest and every install is hash-checked, but no one has decided which interpreter or JVM security features to use. | S | no card |
| low | SSDF PW.6.2 | Dockerfile settings are checked by hadolint on 3 of the 6 Dockerfiles only. | S | 10G-41 |
| low | SSDF RV.3.1 | Root causes are written when a review looks for them; the findings register has no root-cause field. | S | no card |
| low | SSDF RV.3.2 | Patterns across findings are looked for only in occasional reviews, not on a schedule. | S | no card |
| low | SSDF RV.3.4 | The process changes with each plan and review, but the six-monthly review of QMS-lite section 7 starts only after the first site goes live. | S | no card |
| low | IEC 81001-5-1 4.1.3 | The standards position covers IEC 62304, 82304-1 and ISO 13485; which IEC 81001-5-1 activities apply is decided only in this self-assessment, not by the owner. | S | no card |
| low | IEC 81001-5-1 4.1.5 | Components are gated by scans, but no security requirement is agreed with any supplier. | S | no card |
| low | IEC 81001-5-1 4.1.6 | Improvement follows reviews and plans; no periodic review of the security activities has happened yet. | S | no card |
| low | IEC 81001-5-1 4.1.9 | The security pages are kept in step with code by convention and doclint checks their paths, but they are not reviewed for security content at each release (10G-3 had to correct a stale page). | S | no card |
| low | IEC 81001-5-1 4.3 | Components are listed with a safety class, not with the maintained, supported or required split the public summaries describe. | S | no card |
| low | IEC 81001-5-1 5.2.2 | Requirements were reviewed in design reviews, not at each release. | S | no card |
| low | IEC 81001-5-1 5.2.3 | Known problems are listed for the components on the screening path only, not for every component the box runs. | S | no card |
| low | IEC 81001-5-1 5.4.4 | Controls are held by tests, but no record shows the detailed design checked against the threat model. | S | 10G-4 |

## What closing them costs

The 67 open rows share far fewer pieces of work, because one card closes several rows:

| Work | Rows it closes (all or the main part) | Size | Card |
| --- | --- | --- | --- |
| A public security contact and disclosure policy | RV.1.3, RV.1.1 (part), 4.1.7, 9.2, 9.5 | S | 10G-9 |
| Name a security owner at Aimedics, with the security role of each life-cycle activity | PO.2.1, 4.1.2, 4.1.1 (part) | S | no card |
| One threat-model file, reviewed at each release | PW.1.1, PW.2.1, 4.2, 5.3.3, 5.4.4, 7.1, 7.2, 7.3, 5.7.2 (part) | S | 10G-4 |
| Bandit with no filter and a ledger for every `nosec`; own Semgrep rules | PW.7.2, PW.5.1, 5.5.1, 5.1.3, RV.1.2 (part) | S and M | 10G-39, 10G-42 |
| Dynamic scan of the console and fuzzing of the parsers | PW.8.2 (part), 5.7.3 | S and M | 10G-10, 10G-43 |
| Outside penetration test | PW.8.2 (part), 5.7.4, 5.7.5, 7.4 (part) | L | 10G-16 |
| Signing key in a hardware token, two-person signing, signed provenance | 5.8.3, PS.3.2, 7.4 (part) | L | 10G-7 |
| Least-privilege containers | PW.9.2, 5.3.2, 7.4 (part) | M | 10G-1 |
| One security record per release, scan results kept | PO.3.3, PO.4.2, PS.3.1, 5.8.2, 6.3 | M | 10G-50 |
| VEX per release; every waiver with an owner | RV.2.1, 9.3, 9.4 | M | 10G-8 |
| Secure-development training and its record; hardening rules for development machines and sessions | PO.2.2, 4.1.4, PO.5.2, 5.1.2 | M | no card |
| A per-caller identity for HAPI and PostgreSQL | 5.4.3 | M | no card |
| Written rules for what is done in practice (CI requirements, environments, supplier requirements, root-cause field, periodic review, management commitment) | the low rows with `no card` | S each | no card |

Roughly: the high rows need about ten small pieces of work and two large ones (the penetration test and the signing
key). The rows marked `no card` have no plan-10 card yet; the owner decides whether they get one.

## Keeping it current

A pull request that changes what a row cites, or closes a gap, changes the row in `docs/validation/ssdf-iec81001.csv`
and this page together. `tests/unit/test_ssdf_iec81001.py` fails when a cited file, test, Makefile target or CI job
is gone, when a status is not one of the allowed words, when an SSDF task is missing or doubled, when a practice
claims more than its tasks, when a card is not a plan-10 card, and when the two tables above differ from the
register. Rewrite the tables from the register with the test's own functions (`summary_lines`, `gap_lines`).
