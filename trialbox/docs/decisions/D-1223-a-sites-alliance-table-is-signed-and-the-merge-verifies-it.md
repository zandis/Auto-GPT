# D-1320 A site's alliance count table is signed, and the merge verifies the signature against the site's registered key

- **Task:** card 10D-1 of plan 10 (`docs/plan/47-plan-10-2026-11-18.md`, Track D; review card M14-20, defect (d) of
  root review 14, `docs/reviews/2026-11-root/14-multicentre-lifecycle.md` section 1)
- **Date:** 2026-11-18
- **Status:** accepted (number taken as the next free one above the lanes' ranges; the integrator may renumber)
- **Builds on:** D-73 (the alliance exchange and merge), D-144 (owner: "counts travel as signed files"), D-467 (the
  opportunity feed's signature and site key register), D-555 (an answer names no value of the request), D-648 (the
  store's record; item 7, the address check), D-666 and D-670 (a re-run gives what the first run gave)

## Context

The specification says inbound alliance aggregates "are verified (Ed25519 signature, schema, suppression flags)"
(`spec/v4/05_data_platform_model_privacy.md` §5.6.7) and D-144 says counts travel as signed files. The merge checked
the schema and bound a site to the mail address that first sent its table (D-648 item 7); it verified no signature.
Whoever could mail `COHORT MERGE` from that address, or first, decided a site's counts.

## Decision

1. **The member box signs its table.** `COHORT` on a member box with `TB_ALLIANCE_SIGNING_KEY_FILE` (the site's
   Ed25519 key, a file that stays on the box) publishes `cohort_table_<…>.sig.json` beside the CSV and mails both to
   the root. The CSV is unchanged. Without a key the box mails nothing to the root and its summary says why.
2. **What is signed** (`tb_common.alliance`): the canonical JSON (keys sorted, no spaces) of the site id; the table's
   scope (its definitions `<ruleset>@<version>`, i.e. the study's rule set and version, its diseases, its quarters);
   the SHA-256 of the table's rows as the root parses them (the formula of the store's record, the order of the rows
   left out); the number of rows; a sequence and its time (`seq`, the job's receipt time in milliseconds, so a re-run
   of the same job signs the same bytes and a later run signs a higher number); the key's fingerprint and the public
   key. Ed25519 through `tb_common.crypto`, as the update bundle and the opportunity feed.
3. **The root verifies before it stores.** `COHORT MERGE` reads the register `TB_ALLIANCE_SITE_KEYS_FILE` (the
   opportunity feed's register form, `{"sites": {site_id: {"name", "key_sha256"}}}`, read by the same
   `opportunity.load_register` with the site ids `settings.yaml` allows). A table is stored only when a signature file
   covers it and that signature holds, made by the key whose fingerprint the register holds for the table's site,
   for this site, these definitions, diseases and quarters, and these rows. Each refusal is one sentence that names
   the site and never an address: unsigned; no readable register; signed for another site; signed for another
   study, version or time window; the site not in the register; a key not registered for the site; the table changed
   since it was signed; a signature that does not verify.
4. **An older table is not taken again.** The store keeps each table's signed sequence and hash
   (`cohort_tables.signed_seq`, `signed_sha256`) and asks, in the transaction that stores and under its lock, whether
   the new table is newer than what it holds for each (site, disease, quarter, definition) it replaces. Newer
   replaces; the very same signed table sent again is taken and changes nothing (so a re-run of a merge stores what
   its first run stored); an older table, or another table under the same sequence, is refused.
5. **The address check stays as an additional check, not as the proof of origin.** D-648 item 7 is a decision and
   is kept: a site's table is still refused from another address than the one its stored tables came from, and the
   root's own site is never taken from mail (asked first now, so its sentence comes before the signature's). The
   proof of origin is the signature.
6. **Tables already stored.** Schema version 6 of the store adds `verified_by` (the signing key's fingerprint; `own`
   for the root's own table, made in the box and never mailed; empty for a table stored before signatures were
   required). Such a table is kept, marked unverified, and left out of every merge; the merge's summary names the
   sites left out ("Not merged: … kept, marked unverified; each is merged again once its site sends it signed"). The
   site's next signed table replaces it. The store's record (`cohort_stored`) keeps the same three values, so a
   replay rebuilds them (D-648). A merge that read before this version and is re-run now refuses the unsigned files
   it was sent, as any merge does now; its re-run says so and does not give the old output.
7. **How a site's key reaches the register.** The opportunity feed's path: the site runs
   `python -m tools.opportunity_feed keygen` on its box (the key stays there; the command prints the register line),
   gives the line to the root's operator by a channel the two sites trust, and the operator adds it to the register
   file. The runbook's steps: `docs/runbook/23-key-inventory-and-the-lost-box-list.md`, "Alliance site keys".

## Where the specification and the decisions differ

They do not differ on the signature: spec §5.6.7 and D-144 both say the counts are signed and verified. The address
check of D-648 item 7 is not in the specification; it is a decision and is kept (item 5). D-73 says each stored table
"replaces the previous one"; item 4 narrows that to a newer one.

## What is not done here

- Revoking or rotating a site's key is an edit of the register file (the old line removed, the new one added); there
  is no list of revoked keys and no expiry.
- The suppression flags of spec §5.6.7 are checked as before (the schema; small cells were suppressed by the sending
  site); the signature does not add a check of them.
- The opportunity hub's own register and this one are two files in one form; one box that is both reads two files.
