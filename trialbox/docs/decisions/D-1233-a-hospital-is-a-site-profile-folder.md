# D-1233 A hospital's habits are one versioned site-profile folder; its code tables carry a state on every row

- **Task:** card 10B-6 of plan 10 (`docs/plan/47-plan-10-2026-11-18.md`, Track B; review card 12-14,
  `docs/reviews/2026-11-root/12-ssi-data.md` section 7), commitment C-6
- **Date:** 2026-11-19
- **Status:** accepted; the number is reserved for this card's pull request (lane J's block D-1220 to D-1319)
- **Builds on:** D-130 (a code nobody reads is unknown, never a "no"), D-135 (site set-up maps a local code once),
  D-137 (licensed Japanese releases), D-367 (the site folder survives updates), D-394 (one audit writer), D-205
  (committed goldens), D-580 (the night's unmapped codes)
- **Design:** `docs/data/15-the-site-profile.md`

## Context

A hospital's local code tables, the data types it stores and the standard versions it writes lived in code (the
SS-MIX2 reader read the image's sample tables with no setting), in mapping files and in settings. Fitting a new
hospital meant changing code or the image. Shipped sample rows marked `verify` were offered in site set-up as
"from TrialBox's code table" at 100 % confidence.

## Decision

1. **One folder per site.** `deploy/site/mapping/profile/` (mounted with the site mapping, kept by every update):
   `profile.yaml` (`libs/tb_common/site_profile.schema.json`, `format: tb-site-profile/1`) and `codes/*.csv`. One box is
   one site: one profile. No folder: the box reads as before.
2. **One loader refuses with the line and the reason** (with one fold of a code, `tb_common.codekey.fold_key`,
   shared with the mapping's look-up; every standard code checked against its system: LOINC with its check digit,
   the product's ICD-10 and ATC shapes, TrialBox scores, ASCII only; any other system refused) (`tb_common.site_profile.load`): schema errors and unknown
   keys, tables outside the folder, missing columns, patient columns, empty or repeated keys, empty targets, a state
   word that is not `verified` or `verify` (legacy `yes`/`confirmed` read as verified, `local` as verify).
3. **A table says where it is read** (`used_by`): `mapping.<look-up>` replaces the mapping's look-up file (the YAML
   and its version are unchanged) and is held to the mapping's look-up key and columns, at night and by
   `check --mapping`; `ssmix2.diagnosis`, `ssmix2.drug`, `ssmix2.lab` are given to the SS-MIX2 reader at the call
   site and held to an allowlist of its columns. Adding a row needs no code; adding a kind of table adds one `used_by`
   word. Empty tables are refused; free text holds no `://`, `@` or token.
4. **Only a version a person loaded is applied.** `load --by` keeps the checked profile in the lake folder; the night
   reads that copy, never the raw files, and checks it again each night (its content hash must be the audited
   one); a folder whose content is not the loaded version is not applied (said each night, audited once); a folder
   taken away is audited and the night reads without one; a delta night after a change reads whole. **A profile that
   cannot be applied stops the night** (a kept copy that is refused, a folder nobody has loaded): a night read
   without the site's codes could miss patients with no sign, so the box keeps serving the night before.
   **Versions and audit.** A new digest is recorded (who, when, old and new version, both digests, direction, and
   every row whose state changed) in `site_profile.json` in the lake folder and as one `terminology.site_profile_load` audit
   event; with no audit destination nothing is activated; an id and version read before (anywhere in the history)
   with other content is refused; the site is the settings' and the country and standard versions must agree with
   them. Every night read with a profile writes `site_profile.json` beside its snapshot and carries the stamp in
   `ingest.done`.
5. **The state travels.** A fact whose standard code comes from a `verify` row (the row the look-up matched) carries D-135's basis tag `verify`:
   it stays coded (only `proposed` is kept out of the coded tables) and is listed in the lake's `site_fact`; the
   coverage lines count such facts and the `verify` rows; the work list lists the rows; a site set-up suggestion from
   a `verify` row is `lookup_verify` at 0.80, never shown as certain. **Whether such a fact may exclude a patient is
   an open question for the owner** (DATA §15); today it may, as before this decision.
6. **Two homes for one lab code.** Where the site set-up store (D-135) and the profile map a lab code differently,
   the store wins (coordinator's ruling) and the work list lists each disagreement. The night does not apply it yet:
   the adapter has no read right on the `sitesetup` schema, which is lane C2's to grant.
7. **Coverage lines and the work list** come from the night's own files, counts only; the night's data-operations
   page shows them; `python -m adapter.site_profile worklist` writes the CSV. The work list's page waits for 10B-19.
8. **Synthetic profiles may name a shipped table** (`shipped:<path>`) rather than copy it; a site's own may not.

## Consequences

- The goldens' synthetic Taiwan (`synthetic-tw-a`) and Japanese (`ssmix2-jp`) sites are read through their
  profiles; without the `verify` tag the goldens were identical from both lake sources, and the tag moves only the
  lake's `site_fact` and the facts' basis (regenerated with the reason). A second profile with renamed local codes
  reads the same coded facts, at the csv and the SS-MIX2 door (`tests/unit/test_site_profile.py`).
- What is not yet in the profile is listed with the card that moves it in `docs/data/15-the-site-profile.md`.
- `services/datacore/dataops.py` keeps `site_profile` in a night's row (`DETAIL_KEYS`), counts and type names only.
