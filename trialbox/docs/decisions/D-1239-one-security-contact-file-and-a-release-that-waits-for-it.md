# D-1239 One security contact file, a disclosure policy in three languages, and a release that waits for the contact

- **Task:** card 10G-9 of plan 10 (`docs/plan/47-plan-10-2026-11-18.md`, track G); review item 16-8 of root review 16
  (`docs/reviews/2026-11-root/16-security-certification-customisation.md`, row J11: "no public security contact, no
  `SECURITY` disclosure policy")
- **Date:** 2026-11-19
- **Status:** accepted for the files and the check; the contact address, private reporting and a PGP key wait for the
  owner (decision 87 named the security officer outside this repository). Number from lane J's block D-1220 to D-1319
- **Builds on:** D-311 B26 (no counsel reading on file), D-390 (the patch policy, RUNBOOK §24), D-411 (the incident
  plan and its §A.7), D-631 (a dirty build is not a release), D-726 (a rehearsal bundle), D-77 and D-210 (the signed
  offline update)

## Context

A hospital's IT asks a vendor three things first: the threat model, the signed audit head and a security contact
(plan 10, section 1). TrialBox had a two-line promise in the incident plan (§A.7: confirm within 2 working days) but no
public policy, no address, no `security.txt`, and no registration in Japan's 情報セキュリティ早期警戒パートナーシップ.
Choosing the address is the owner's decision; this card may not invent one.

## Decision

1. **The policy** is section 12 of SECURITY (`docs/security/12-vulnerability-disclosure.md`), with two parts in
   Japanese (polite register) and Traditional Chinese. It follows ISO/IEC 29147 and 30111, CISA's VDP template, RFC
   9116 and the IPA/JPCERT/CC guideline (2026 edition): scope, how to report, what to include, what not to do (no
   real patient data, no test against a hospital's box), target times until the owner confirms them (acknowledge 2 working days, as §A.7 already
   promised; first assessment 10; updates every 14 days; fixes by severity, Critical as RUNBOOK §24's 14 days; publication by default
   within 90 days), credit, safe harbour (marked: counsel has not read it), supported versions (the newest release;
   an older box takes the newest bundle, since anti-rollback leaves no other path) and the signed offline update.
2. **The Japan route both ways.** (a) A finder reports to IPA; JPCERT/CC contacts Aimedics: the developer duties of
   the guideline's part IV section 5, with the 45-day publication target from the 起算日. (b) Aimedics finds or
   receives a weakness directly: part IV section 6; Aimedics notifies JPCERT/CC for every High and Critical even
   though telling every site directly would make it optional, so that the advisory is on JVN. The owner's once-only
   steps (O-1 to O-8, O-8 being the confirmation of the response times) are a table in the policy.
3. **Where the files go.** GitHub reads a security policy from the repository root, `docs/` or `.github/`. The root
   and its `docs/` belong to the upstream project's layout, so the policy GitHub shows is `.github/SECURITY.md`: one
   added file, no upstream file edited, beside the TrialBox-owned `CODEOWNERS` and workflows. The full policy is a
   numbered SECURITY section, section 12 (section 11 is taken by #1133, announced first, so the two cards never claim one number). The website serves `/.well-known/security.txt`, rendered by
   `tools/build_site.py` at each build (Expires 180 days ahead).
4. **One place for the contact.** `deploy/security/contact.json` holds it; every other file points there and repeats
   no address. It counts as set only when it is a `mailto:` or `https:` URI, so the placeholder string exists in that
   one file and nothing else needs an edit when the owner fills it.
5. **The release waits for it.** The repository had no mechanism for "must be filled before release", so the check is
   a release gate: `python -m tools.security_contact release-check`, the first prerequisite of `make release-bundle`.
   It refuses a release while the contact is not set; a `--rehearsal` or `--allow-dirty` bundle (not a release,
   D-726, D-631) passes with a warning, so the P-0 media and the rehearsals keep working. `tools/make_bundle.sh`
   itself is not changed: the cloud validation builds call it directly. No pull-request job runs the gate; the unit
   test checks the gate and the files, not the address, so master stays green. The site build publishes no
   `security.txt` while the contact is not set.

## Not done

- The contact answering (the card's exit): it needs the owner's address and a test report (O-1, O-6).
- JPCERT/CC registration, private vulnerability reporting, a PGP key (O-2 to O-4): the owner's, outside the repository.
- CSAF and VEX advisories: card 10G-8.
- A counsel reading of the safe-harbour wording.

## Tests

`tests/unit/test_security_contact.py`: the file reads; the placeholder is in one file only; each policy file points
to the contact file and writes no address; each language says the no-patient-data and no-live-box rules and how a fix
reaches a box; only a `mailto:` or `https:` URI counts as set; the release check refuses a release and passes a
rehearsal or dirty bundle; `make release-bundle` runs the check first; `security.txt` has RFC 9116's fields.
