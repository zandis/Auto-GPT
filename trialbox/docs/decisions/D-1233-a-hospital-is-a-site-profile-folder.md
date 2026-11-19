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
2. **One loader refuses with the line and the reason** (`tb_common.site_profile.load`): schema errors and unknown
   keys, tables outside the folder, missing columns, patient columns, empty or repeated keys, empty targets, a state
   word that is not `verified` or `verify` (legacy `yes`/`confirmed` read as verified, `local` as verify).
3. **A table says where it is read** (`used_by`): `mapping.<look-up>` replaces the mapping's look-up file (the YAML
   and its version are unchanged); `ssmix2.diagnosis`, `ssmix2.drug`, `ssmix2.lab` are given to the SS-MIX2
   reader at the call site. Adding a row needs no code; adding a kind of table adds one `used_by` word.
4. **Versions and audit.** A new digest is recorded (who, when, old and new version, both digests, direction) in
   `site_profile.json` in the lake folder and as one `site_profile.load` audit event; the same id and version with
   other content is refused. Every night read with a profile writes `site_profile.json` beside its snapshot and
   carries the stamp in `ingest.done`.
5. **The state travels.** Coverage lines and the work list count and list `verify` rows; a site set-up suggestion
   from a `verify` row is `lookup_verify` at 0.80, never shown as certain.
6. **Coverage lines and the work list** come from the night's own files, counts only; the night's data-operations
   page shows them; `python -m adapter.site_profile worklist` writes the CSV. The work list's page waits for 10B-19.
7. **Synthetic profiles may name a shipped table** (`shipped:<path>`) rather than copy it; a site's own may not.

## Consequences

- The goldens' synthetic Taiwan (`synthetic-tw-a`) and Japanese (`ssmix2-jp`) sites are read through their
  profiles; `make goldens-check` is identical from both lake sources. A second profile with renamed local codes
  reads the same coded facts (`tests/unit/test_site_profile.py`).
- What is not yet in the profile is listed with the card that moves it in `docs/data/15-the-site-profile.md`.
- `services/datacore/dataops.py` keeps `site_profile` in a night's row (`DETAIL_KEYS`), counts and type names only.
