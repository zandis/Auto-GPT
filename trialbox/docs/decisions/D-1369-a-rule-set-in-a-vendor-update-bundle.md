# D-1369 A rule set compiled on the head box reaches a screen-only site box in a vendor-signed update bundle (10D-28)

- **Task:** lane K, plan 10 row 10D-28 (review 19, card 19-9): "interim, for the dry run only: a rule set carried in
  a vendor-signed update bundle (vendor key, not the coordinating investigator's)"; plan 10's third ruling, change 1
  (the owner's workstation card is the head box that reads protocols; the first site's 32 GB box screens).
- **Date:** 2026-11-19
- **Status:** proposed
- **Builds on:** D-77 (the offline update channel), D-210 (release_seq, compat.json), D-640 (a site box runs only a
  study approved at the site, or installed by an offline update), D-1102 (the rule-set zip caps), D-862 (the stored
  equivalence report)
- **Interim:** the long-term route is the study package signed by the coordinating centre (10D-2 to 10D-4); this
  record is replaced when they land. Nothing here is for the first real study.

## What was found (before building)

1. **What an approved rule set is.** A folder `<ID>/` in the criteria compiler's git repository (`rulesets-data`,
   `criteria_compiler/repo.py`): `manifest.yaml` (`status: approved`, the version, the judge and its prompt pin in
   `models`, the terminology release, the score pins `derived_pins`, the equivalence summary, the site's `routing`),
   `ir/` (one criterion each), `valuesets/` (the codes), `cql/` and `cql/elm/`, `sql/`, optionally `labels.yaml`, and
   `tests/`. The approval is the annotated tag `<ID>/v<version>`; its message says who ("approved by <who>", or
   "(offline update, <by>)"); a tag the first start wrote on a shipped example names nobody and is no approval on a
   site box (D-640, `tb_common.ruleset.seeded_approval`). The working copy the services read is materialized from
   `main`. What pins it at run time: the prompt pin and the score pins (`approval_state`: a drift asks for approval
   again), and the terminology release (`load_approved(terminology=...)`: another release refuses the run until a
   recompile).
2. **`tests/` is not criteria.** A box's compile writes `tests/equivalence.json` there: the percentages and one row
   per disagreeing case (a case label, never a pseudonym, no evidence: D-862). The shipped examples also hold
   `tests/patients.ndjson` and `expected.json`, synthetic patients of site A. Neither is needed to screen.
3. **Export today.** None from a box: the compiler offers a draft zip for review (`review.draft_zip`) and the vendor
   builds the shipped rule sets from the checkout (`tools/build_rulesets.py`, `make_bundle.sh --rulesets DIR`, every
   `*.zip` a payload of kind `ruleset`).
4. **What a bundle may hold** (`tools/verify_update.py`, `schemas/update_manifest.schema.json`): payloads of kind
   model, ruleset, image, refdata, other, host; any other kind fails the schema, and a member not in the manifest is
   refused. Nothing requires an image, a release record or a host tree: `release.json` and `images.lock` are needed
   only with images. **So an update bundle may carry a rule set alone** (review 19's open point, now verified by
   `tests/unit/test_ruleset_in_update_bundle.py`): `tools/sign_bundle.py build` signs it, the verifier accepts it,
   and the update path (`tools/trialbox/update.py`) runs every step on it: a PRODUCTION or VALIDATION box notes "no
   release record" and goes on (D-633 refuses only a record that is dirty or names no commit); the step `rulesets`
   imports each `*.zip` with `criteria_compiler.import_ruleset` (approved, equivalence at or above the site's gate,
   an existing tag never moved). `tools/make_bundle.sh` cannot build one alone: it always exports images and needs
   the release gates. A rule-set-only bundle takes a `release_seq` above the box's (D-210), one number of the
   vendor's sequence.
5. **Approval on the receiving box today.** An installed update's tag "(offline update, <by>)" is an approval a site
   box runs (D-640 lets it stand): no local approval step is required by the code, and none is added or removed here.
   What was missing: the box did not say where such a version came from.

## Decision

1. **The part.** `python -m criteria_compiler.export_part <ID> --out <file> (--installed installed.json | --release
   "<words>")` exports the version of the box's own approval tag as a zip of the `import_ruleset` form plus
   `ORIGIN.json` (`tb_common.ruleset_part`): the rule set and version, the sha256 of its content (every file, path and
   bytes), the file list, what was left out, the approval tag's name, the compiling box's release (its installed
   record: bundle id, release_seq, commit), the judge and terminology pins, the time. It carries `manifest.yaml`,
   `labels.yaml`, `ir/`, `valuesets/`, `cql/`, `sql/`; `tests/` is left out; any other file refuses the export. It
   refuses a version that is not approved, an approval that names nobody here (a seeded example), and a version
   that itself arrived in a bundle (only a box's own approval is carried). Who approved at the head box is not copied
   from the tag (the manifest's own `review` block travels as part of the approved rule set).
2. **The bundle, vendor key only.** `python -m tools.ruleset_bundle --key <vendor key> --id .. --release-seq ..
   --out .. <part>...` reads each part as the receiving box will and signs with `tools/sign_bundle.py` (Ed25519, the
   vendor key; no new key type, no new payload kind, no schema change). Beside a release, a part rides in
   `tools/make_bundle.sh --rulesets DIR` as any rule set zip; that script is unchanged.
3. **Verify and apply.** `tools/apply_update.sh` unchanged: the signature, release_seq and every payload's sha256
   first; then the update path. `import_ruleset` checks a part before writing anything: the record names the same rule
   set and version, the folder holds only carried files, the content sha256 is the recorded one; a mismatch refuses
   the import, the update rolls back (`update.rolled_back`), nothing is tagged. The tag of an installed part reads
   `<ID>/v<version> (offline update, update:<bundle>); arrived in a vendor bundle (interim): update:<bundle>; compiled
   and approved on another box, release <bundle id> (release_seq N, commit C), its tag <ID>/v<version>; content
   sha256 <hash>` (`tb_common.ruleset_part.ARRIVED_MARK`). `update.applied` names the rule sets imported (field
   `rulesets`), beside the files it already listed.
4. **The box's release stays.** A bundle of rule-set parts only writes `installed.json` with its own bundle id and
   release_seq, and keeps the commit, `dirty`, `rehearsal` and `vuln_mode` of the release it rides on, and that
   release's bundle id as `release_bundle_id` (the code identity, H-19, reads the commit). The export reads
   `release_bundle_id` first.
5. **Listed as arrived.** The console's rule-set lists (the overview table, the administrator's pages) add "arrived in
   a vendor bundle (interim): approved on another box, not here" to such a version, in en, ja and zh-TW
   (`overview.arrived_in_bundle`; `console.backend.ruleset_infos` sets `RulesetInfo.origin`, read from the tag by
   `tb_common.ruleset.arrived_in_bundle`).
6. **Who may do it.** No new role, route, console action or matrix row: exporting is a command in the compiler's
   container on the head box (whoever runs host commands there), signing is the vendor's, applying is the existing
   `apply_update.sh` act of the operator. The part holds criteria and codes only; it reads no patient data.

## Not in this card, and what the dry run must know

- **Routing travels with the manifest.** The part's `routing` is the head box's. A site box sends a list only to
  internal recipients of its own domains (`tb_common.routing.check`), so a head box at another domain makes the site
  box refuse to send the list (it fails safe). For the dry run the head box compiles with the site's routing; a
  rewrite on arrival would change an approved manifest and is not done.
- **Pins must match.** The site box screens only on the same terminology release (else `RecompileNeeded`, and a
  screen-only box cannot recompile) and asks for approval again on a prompt or score pin drift; the head and site
  boxes run the same release for the dry run.
- **Not audited at export.** The export writes no audit event on the head box (the compiler's container has no audit
  writer of its own here); the receiving box's `update.applied` and tag hold the provenance.
- **Not run on a container box.** The test runs the real verifier, `Updater` and import on an in-process box; the
  compose box's steps (backup, dumps, restart, `docker compose exec criteria-compiler ... import_ruleset`) are
  unchanged and were not run.
- `tools/trialbox/update.py` `InProcessBox.rulesets` still imports nothing (the update drill's box); unchanged.

## Held by

- `tests/unit/test_ruleset_in_update_bundle.py`: the part carries criteria and codes only and is reproducible; only
  the box's own approval is exported; a bundle may carry a rule set alone and the verifier accepts it; the vendor's
  tool refuses a zip that is no part or whose hash is wrong; the PRODUCTION site box installs it, tags and lists it as
  arrived with bundle, release and hash, audits `update.applied` with it, keeps its commit; a part whose hash does
  not match is refused and rolled back; a bundle changed after signing is rejected.
- `tests/integration/test_ruleset_bundle_two_boxes.py`: two in-process boxes on the same synthetic hospital; GZQO
  approved on the head box, exported, signed alone, applied on a box that never held it, screened there by e-mail:
  every listed patient, tier and criterion answer equal to the head box's.
- `tests/console/test_ruleset_arrived_in_bundle.py`: the overview marks such a version in en, ja and zh-TW.
