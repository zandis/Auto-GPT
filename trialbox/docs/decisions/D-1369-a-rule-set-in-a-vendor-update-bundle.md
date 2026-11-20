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
6. **An approved folder is not criteria and codes only** (the first review of PR #1174, B1). The manifest holds the
   site's `routing` (mail addresses), `scopes` (practitioner and department codes), the approval record `review`
   (who, how, when), `effective_from`, the IRB fields and the site's code tables; each criterion's `review` holds the
   reviewer's address, the time and a free-text comment, and `provenance` the model calls. A first version of this
   card carried them whole; they are now removed at export (decision 1).

## Decision


1. **The part: criteria and codes only, by allow-lists** (the third review: by file and by key, never by folder or
   deny-list). `python -m criteria_compiler.export_part <ID> --out <file> (--installed installed.json | --release
   "<bundle id> [(release_seq N)]") --by "<your name>"` exports the version of the box's own approval tag as a zip of the
   `import_ruleset` form plus `ORIGIN.json` (`tb_common.ruleset_part`), following the protocol/site split of D-1366
   (10D-2; its field lists are imported from `tb_common.study_manifest`, not copied):
   - **files**, exactly master's `study_manifest.PROTOCOL_FILES` that are criteria and codes, one per name:
     `manifest.yaml`, `labels.yaml`, `ir/<criterion id>.json` (named by its own id), `valuesets/<name>.json` (named
     by its `name`), `cql/<library>.cql` and `cql/elm/<library>.json` (the manifest's `library` and `TB_Common` only;
     an ELM file only beside its CQL), `sql/<ID>.sql`. `tests/` is left out. **Any other file refuses the export**
     (a stray `sql/patients.csv`, `cql/notes.md`, `valuesets/README.txt`, a sub-folder), and the import refuses any
     other member, with a correct record and hash too;
   - **the manifest** keeps D-1366's protocol fields and `status`, but `source_documents` and `docx_template` (file
     names someone chose; the docx is not carried) and `population.notes` (free notes); `source_last_update` must be
     a date, else refused. It loses `routing` and `scopes` (left as empty objects, which the schema requires),
     `review`, `effective_from`, `irb_reference`, `irb_approved_on`, `terminology_tables`, `terminology_refused`;
     `models` keeps `judge_prompt` only; `equivalence` keeps `overall_pct`, `sample_size`, `per_criterion`,
     `failing`, and a criterion id is the only text it may hold (else refused). A field placed in neither part
     refuses; the result must pass the manifest schema (no unknown key at any depth) and is written again as YAML,
     so no comment travels;
   - **each criterion** keeps the fields of `ruleset_part.IR_KEYS` only (the criterion schema's, held equal to it by
     a test, but `provenance`); any other key is dropped; `review` keeps its status (no who, when or comment); a flag
     must be one word of the compiler's (`[a-z][a-z0-9_]*`); the result must pass the criterion schema;
   - **value sets** hold the compiler's keys only, at every level (`resourceType id name title url version status
     compose extension`; `compose.include[]`: `system concept`; `concept[]`: `code display`; `extension[]`: the
     code-family `url` and `valueString`), else the export is refused naming file and key; their bytes travel;
   - **ELM**, by allow-lists at both ends (`tb_common.ruleset_part.elm_allowed`; the re-check of #1174): the top
     level holds `library` only; the library holds `identifier schemaIdentifier usings includes parameters
     codeSystems valueSets codes concepts contexts statements` only; every key below them is one of
     `ELM_NODE_KEYS`, the 81 keys the compiler's ELM holds (the union over the repository's compiled ELM fixtures and
     the pinned translator's output for every rule set's CQL, the generator's `ATOMS` snapshot and `TB_Common`; the
     constant's comment says how). Any other key refuses the export, naming its path (`library.statements.def[0].x`);
     the export removes only the translator's bookkeeping, every `annotation` entry (its copy of the CQL source, its
     options and messages; not read by the engine) and the library's `localId`. The receiving box holds each ELM file
     against the same lists as it stands and refuses any key off them, an annotation included, naming its path: it
     never drops one. Its `library.identifier` may hold `id` and `version` only (else refused); written again as
     compact JSON. ELM is not regenerated: the translator's jars are not on every box. The lists hold keys, not values:
     any string value under an allowed key travels as written; it is not checked against the CQL (see "What
     travels"). A refusal names the path of allowed keys and indices and only the offending key's length, never its
     text (on the receiving box that text is the part's);
   - **labels.yaml**: its keys only (`ruleset`, `criteria.<criterion id>.{source, todo_source, en|ja|zh-TW.{label,
     text, todo}}`), text values only, written again as YAML (its comments go);
   - **CQL and SQL** travel as their bytes and are **never stripped** (removing text from code could change what it
     means): every comment is held against what the compiler writes (`criteria_compiler.part_text`: the generated
     header, each criterion's line with that criterion's id, kind and text from the part's own IR, and `TB_Common`'s
     own comments); any other comment refuses the export, naming the file and the line. The scanner knows the
     languages' strings and quoted names.
   - **depth**: a JSON or YAML file nested deeper than 256 is refused before it is parsed (no `RecursionError`).
   The record holds the rule set and version, the file list, what was left out, the approval tag's name, the
   compiling box's release (bundle id, release_seq, commit, from its installed record or from `--release`, which
   takes a bundle id and its required `(release_seq N)`, nothing else; a release_seq of 1 or more is required),
   and the judge prompt and terminology pins,
   **which must equal the manifest's**. It holds **no time**: `part_sha256` (every carried file, path and bytes, and
   every other field of the record) is the same for the same approved version exported again from the same release,
   so the receiving box takes the repeat as the same part. The export refuses a draft, a version with no approval
   tag, an approval that names nobody here (a seeded example, also on a DEV box where it loads), and **any version
   that arrived in an update**. It is audited on the head box, before the part is handed out, as
   **`approve.part_exported`** (who, when, the rule set and version, `part_sha256`, the file count, the release).
   `--by` is required (refused without it): the event names the account the command runs as (`host:<account>`;
   inside the compiler's container that is the service's account) and, as `by_claimed`, the name the operator typed,
   which the box cannot verify (the fifth review). The output line prints the part's full `part_sha256`.
   **Whose approval** (the fourth review): the export takes any approval the compiler recorded on this box at the
   tag; it does not check that the approver was the PI or the study's steward. The product's approval model has no
   such check at the tag (the compiler's approval is the approval), and this card adds none.
   **The approval family** carries both events of this card: the criteria compiler, which runs the export and the
   site-profile command, writes `ai`, `approve`, `compile`, `ctgov` and `llm` (`audit_writer.ROLE_EVENTS`, unchanged);
   a `ruleset` family would be written by a role that may not write it, and the journal would mark each event
   foreign. Exporting an approved version and setting the site's routing and scope for one are acts on an approval;
   no role and no row of `ROLE_EVENTS` changed.
2. **The bundle, vendor key only.** `python -m tools.ruleset_bundle --key <vendor key> --id .. --release-seq ..
   --out .. <part>...` reads each part as the receiving box will and signs with `tools/sign_bundle.py` (Ed25519, the
   vendor key; no new key type, no new payload kind, no schema change). It is valid 30 days by default, at most 90 (a
   release bundle: a year). A rule-set bundle takes one number of the vendor's `release_seq` (runbook §5). Beside a
   release, a part rides in `tools/make_bundle.sh --rulesets DIR` as any rule set zip; that script is unchanged.
   **The bytes signed are the bytes checked** (the fourth review, N1): each part is read once, checked, and handed
   to `sign_bundle.build` as a copy in a private folder of the run; after the build each packed member is read back
   from the bundle, and it and the sha256 the signed manifest records must equal the checked bytes, else the bundle
   is removed and refused. `tools/sign_bundle.py` is unchanged. The command prints each part's full `part_sha256`
   (`part <ID> v<version> part_sha256 <hash>`): the vendor sends that line to the site with the bundle (the vendor's
   release note); it is where the site's operator reads the hash it accepts (item 4). The signed manifest's
   description keeps the first 12 characters only; no other tool prints the hash at the site before the import.
3. **Verify and apply.** `tools/apply_update.sh` unchanged: the signature, release_seq and every payload's sha256
   first; then the update path. Before writing anything, `import_ruleset` checks a part
   (`tb_common.ruleset_part.open_part`): every zip member is in `<ID>/` or is `ORIGIN.json`; every record field has
   its strict form (id and version patterns, each held whole and in ASCII: `re.fullmatch`, `re.ASCII`, so "1.0.1"
   with a line break or another script's digits is no version; the approval tag exactly `<ID>/v<version>`, a bundle id, a 40-hex
   commit, no control character anywhere, no unknown field); its pins are the manifest's; the record lists exactly
   the part's files; `part_sha256` matches; every file is exactly what the export writes (the export's allow-lists run
   again on the part and must give back the same bytes: a site field, an unknown key, an annotation, a comment the
   compiler does not write, a file off the list are refused). **A part never installs without its record**: a member
   named `ORIGIN.json` anywhere but the zip's root is refused, and a rule set zip with no record whose manifest has no
   routing or no screening scope (the form of a part's manifest) is refused on the plain path too; every rule set the
   vendor ships has both. Then: a part older than the box's newest approved version of the id is refused; the same version
   again is a no-op only when its tag holds the same `part_sha256`, else refused (a local approval or a shipped
   example of that version included: the dry run uses a new id or version). Any refusal rolls the update back
   (`update.rolled_back`); nothing is tagged.
4. **The receiving site's own routing and scope, and the one version it accepts.** The part has none, and a rule
   set from another box must never screen and send on another site's people or scope. The import takes `routing` and
   `scopes` only from a profile the receiving site set itself: `python -m criteria_compiler.import_ruleset
   --site-profile <ID> FILE --version <version> [--part-sha256 <hash>]` (FILE `-`: standard input, as the compiler's
   container does not mount the host's files) writes `profiles/<ID>.yaml` (routing and scopes only: any other key is
   refused; checked against the manifest schema) and beside it `profiles/<ID>.site-set.json`, which records that
   file's sha256, the id it is for (a mark naming another id does not count), **the version the site accepts and,
   when the operator gave it, the part's sha256** (as the export prints it and the vendor's release note carries
   it); `--version` is required. The profile is read up to 64 KiB (a larger one, a file or standard input, is
   refused) and parsed strictly: a field the manifest schema's routing and scopes do not name, at any depth, is
   refused with a sentence. The import installs a part only
   when its version is that version, and its hash that hash when one was given (the fourth review, S2): a later
   version of the same id, or another part of the version, is refused, the update rolls back, nothing is tagged, and
   the refusal (en, ja and zh-TW) gives the exact host command that accepts that part: `docker compose exec -T
   criteria-compiler python -m criteria_compiler.import_ruleset --site-profile <ID> - --version <version>
   --part-sha256 <its hash> --by "<your name>" < <profile.yaml>`, after comparing the hash with the vendor's release
   note. **Accepting a version without the hash** accepts that version whoever built the part: any vendor-signed part
   that names this id and version installs. The hash is the normal way (runbook §5 says so); leaving it out is for
   when the vendor sent none. So **every version that can screen
   patients here had one act by a person at the site.** The example `profiles/<ID>.yaml` a box ships with has no
   such record, and a profile changed by hand since no longer matches it: both are refused, as is a missing
   `routing.list_to` or `scopes.screen`, naming the command. **A profile of the first form** (a mark without a
   version, `trialbox-site-profile/1`, written by this card's earlier form) accepts no version: refused, saying so,
   with the command. This is an interim path for the dry run, and no site has such a profile, so nothing is migrated.
   The command writes **`approve.site_profile_set`** (who, when, the rule set, the version, the part's sha256 when
   given, the profile's sha256) **before** the profile: when the audit write fails, nothing is written.
   **What reaches the operator** (the fifth review): the update runs the import in the compiler's container and keeps
   the first line and the last 600 characters of its standard error (`tools/trialbox/update.py` `run_cmd`); the
   terminal shows that failure, and `update.rolled_back` keeps its first 500 characters (unchanged). The import's
   refusal of a part prints, as its first line, a short English sentence that the part (its id and version) was
   refused and that the command follows; then the text in en, ja and zh-TW (1,300 to 1,800 characters, of which the
   terminal shows only the end); and, as its last line, one ASCII line under 400 characters with the exact command
   (a command too long for that line would be printed alone on its own line, said so; the longest id and version fit).
   So the terminal holds the first line and the whole command, and `update.rolled_back` the first line with the id
   and version. Run by hand on a zip, any refusal ends the same way with exit 2, not a traceback.
   The command is a host command (run on the box's host, not through the console) and needs `--by "<your name>"`
   (refused without it, in en, ja and zh-TW, writing nothing): the event names the account and the name the operator
   typed, which the box cannot verify. The account is `host:<user>` from `getpass.getuser()` (the user variable,
   else the passwd entry; inside the container the service's user; `host:unknown` with neither); the name is
   `by_claimed`, a claim, never a verified identity. The installed manifest is the part's with the site's routing and
   scopes.
5. **The tag and the audit.** The tag of an installed part reads `<ID>/v<version> (offline update, update:<bundle>);
   arrived in a vendor bundle (interim): update:<bundle>; compiled and approved on another box, release <bundle id>
   (release_seq N, commit C), its tag <ID>/v<version>; part sha256 <hash>`, built from checked fields only. That tag
   counts as an approval (D-640), which is why the import asks for the site's act on the version first (item 4).
   The step `rulesets` and `update.applied` (field `rulesets`, beside the files it already listed) name each zip's
   rule set, version and result, imported or already present (the same part again: nothing changed), as
   `GZQO v1.0.1: imported (GZQO-1.0.1.part.zip)`, from the import's own output line (the fourth review, N2). This
   changes the text for every bundle: one without a rule-set zip now says `rulesets: 0 imported, 0 already present`
   (it said `0 imported`), and each `update.applied.rulesets` entry reads `<ID> v<version>: imported (<file>)` (it
   was the file name). No tool or test of the repository parses either form (`git grep` over `tools/` and `tests/`;
   two stored evaluation reports under `eval/complete_run/` quote the old step text as a record and are not read).
6. **The box's release stays.** A bundle of rule-set parts only writes `installed.json` with its own bundle id and
   release_seq, and keeps the commit, `dirty`, `rehearsal` and `vuln_mode` of the release it rides on, and that
   release's bundle id as `release_bundle_id` (the code identity, H-19, reads the commit); `apply_update.sh status`
   prints it as `release (code)`. The export reads `release_bundle_id` first.
7. **Not approved here, wherever it shows.** Every version whose tag records an offline update (a part, or a plain
   rule set zip of any update, with or without `ORIGIN.json`) counts as arrived (`tb_common.ruleset_part.arrived`,
   `tb_common.ruleset.arrived_in_bundle`): the console's rule-set lists (overview, administrator pages) add "arrived in
   a vendor bundle (interim): approved elsewhere, not on this box" in en, ja and zh-TW; the sponsor pack README says
   so instead of an "Approved by" line (`GET /rulesets/<id>/detail` carries `arrived_in_vendor_bundle`); the export
   refuses it. The approval mail (`orchestrator/scenarios/approve.py`) is sent only when this box approves a draft it
   compiled; an arrived version has no draft here, and its IRB fields are removed at export, so the mail never prints
   the head box's IRB reference.
8. **Pins and release refused on mismatch** (the second review). `tools/ruleset_bundle.py` writes the bundle's
   `compat.json` from the parts: `vocabulary_release` lists the parts' terminology release when one is pinned (parts
   of two releases cannot share a bundle), and `min_installed_version` is the highest `release_seq` that compiled a
   part, so the existing verifier refuses a box on an older release, or one that records another vocabulary release,
   before anything changes. A box records no vocabulary release today (`compat_check` then only notes it), so the
   import checks again on the box itself (`import_ruleset.box_pins_problem`): the terminology release the part was
   compiled against must be the one the box resolves through, and every prompt it pins must stand in the box's
   registry unchanged (`pin_drift`); otherwise it is refused, with the sentence. The serving model is the site's
   (D-1366), so `model_pin` stays `*`. The full package pins are card 10D-26's.
9. **The cost on a PRODUCTION box, said plainly.** A rule-set-only bundle of a few kilobytes goes through the whole
   update: refused while a job runs, every service stopped, both databases dumped and backed up, the services
   restarted, `doctor --weights` on a GPU box (up to an hour): a full quiet-hour downtime, and one number of the
   vendor's `release_seq`. This card does not skip the backup or the restart (runbook §5 says so).
10. **Who may do it.** No new role, route, console action or matrix row: exporting and writing a site profile are
   commands in the compiler's container (whoever runs host commands there), both audited in the approval family the
   compiler already writes; signing is the vendor's;
   applying is the existing `apply_update.sh` act of the operator. The part holds criteria and codes only; it reads
   no patient data.

## What an arrived rule set can do before anyone at the site acts

Nothing, for a part and for a plain vendor rule-set zip alike (the review of edb77053 closed the plain zip's road).

**The one gate.** `criteria_compiler.import_ruleset.install_outcome` is the one function through which any rule set
from outside the box is written to the rule-set store (every road calls it: the update step, in the compiler's
container on a compose box and in the process on the test box; the hand-run command; a retry after a rollback, which
verifies the bundle again). It writes nothing new unless, in this order:

1. **Evidence of this run's verified bundle.** `Updater.run` writes, after `apply_update.sh` verified the bundle's
   vendor signature into its root-owned stage, `ruleset-evidence.json` (`tools.trialbox.update.ruleset_evidence`):
   the bundle's id and release_seq, the box's installed release_seq before it, the stage, and each staged rule-set
   zip's sha256. `ComposeBox.rulesets` mounts it read-only beside the zip and passes `--verified`; the import holds
   it to its strict form (`Verified.from_record`), requires the file to be root's and writable by root alone, and the
   zip's sha256 to be one the bundle staged. Without it the command line refuses any write (en, ja, zh-TW) and only
   checks (`--check`). The only writes without evidence: a repeat of what the box holds, the D-640 retag of a
   seeded example of exactly the same bytes, and the install of a rule set whose files are exactly those this box's
   own image ships (`tb_common.ruleset.SEED_RULESETS`; runbook 01's synthetic run on a box that seeds none,
   `tools/rehearse_box`), with the example's routing as before this card. That content came with the release the
   vendor signed; it is not from outside. **For the owner:** it needs no act at the site.
2. **The release that compiled a part.** `ORIGIN.json` `compiled_on.release_seq` is required, a whole number of 1 or
   more (the export refuses without it; zero, missing, negative, a boolean or a non-integer is refused by
   `check_origin` at the vendor's tool and at the box). The rule: a box takes a part only on that release or a later
   one. `tools.ruleset_bundle` makes it the bundle's `min_installed_version` (the verifier refuses an older box before
   anything changes, so an importer older than this card never sees the part through it), and the import refuses it
   again when the evidence's box release_seq is lower or unknown (a bundle signed around the part by other means).
3. **The site's acceptance.** The site profile's mark (`--site-profile`) names this id and version (and hash when the
   operator gave it: a part's `part_sha256`, a plain zip's sha256 as the bundle signed it); the site's routing and
   scopes replace the zip's. A plain zip with no acceptance is refused like a part (the vendor's plain path of D-77
   now needs the same act; nothing in the repository ships or applies one but tests, and runbook 01's hand install
   of the shipped example is the retag above). Its tag says `screens inside the site profile it was accepted with`.
4. Every criterion the manifest lists is an `ir/` file and every `ir/` file is listed (both forms; the export and the
   vendor's tool refuse too), so an exclusion cannot drop out while the version keeps its approval.

**Which jobs may run an arrived rule set (the review of f8fcc04e, H1; for the owner).** One check,
`orchestrator.scenarios.review.guard_arrived`, called by `approved_or_none` (through which every scenario that runs a
rule set loads it), decides by job type (`review.ARRIVED_RULE`, held to the scenario registry by a test, so a new job
type that is not placed fails it):

| Job type | A rule set installed through the gate |
|---|---|
| SCREEN, MICROBATCH | runs, narrowed to the site's accepted practitioners and departments (`screen._scope_terms`; MICROBATCH's given pool rows too, `screen.in_arrived_scope`) |
| FEAS, NAV, COHORT, CASE, SUBMIT, CALIBRATION | refused, with a sentence in en, ja and zh-TW and the audited event `job.ruleset_refused` |
| APPROVE, FEEDBACK, STATUS, CANCEL, INGEST, RETENTION, CONSENT, RELEASE | run no rule set over patients |

The narrowing reads the scope at run time (`tb_common.ruleset.arrived_scope`): the lists installed with the version,
each narrowed by the site's current accepted profile for the id (never widened by it). Closed, never open: a profile
that names neither practitioners nor departments is refused by `--site-profile` and by the gate, and a scope with
nobody left refuses every job. A new `--site-profile` for the installed version is applied to it at once (M3); a
repeat through the update applies only a profile accepted for that version (and hash) (L1). Rule sets approved here
are unchanged (their `scopes.screen.departments` is still not read by screening; not this card's).

**The rest of that review.** The release floor counts the release a part rides with when the bundle carries one
(M4). A version has one spelling (no leading zero) and an equal version under another spelling is refused (L2). The
evidence file is opened once without following a link and checked on that descriptor (a regular file, root's,
writable by root alone, one name) and every folder above it is root's and not writable by others (L3). The evidence
carries the signed manifest's sha256 and each rule-set payload's sha256 as that manifest records it; the staged
manifest and each staged zip must still hash to them (L4). A zip with a member beside the rule set's folder is
refused, and runbook 01's hand install of the shipped example is audited first (`approve.ruleset_installed`) (L6).
The first-load text says such a bundle's rule sets are not imported (L7).

**A repeat takes the site's current routing.** The same version again through the update writes the site's current
routing and scopes into `main`'s manifest of that version when the site set them again since; the tag stays.

**The part's zip holds nothing outside its members** (`check_zip_layout`): no archive or member comment, extra
field, data descriptor or byte before, between or after the members; value-set scalar fields are strings, numbers
or true/false only (never a mapping or a list), at both ends.

**Residual: `tools.trialbox update --stage --summary` trusts its caller (L5).** It reads a stage and a summary that
`apply_update.sh` writes after `verify_update` ran; run directly by root on a stage made by hand it writes evidence
for any zip, and `update.applied` then says it was verified. Root-only, like the residual below.

**Residual: who can forge the evidence.** The evidence is a file, not a signature: root on the host, or anyone who
may run containers there (root-equivalent), can write a root-owned evidence file for any zip and mount it, and can
as well write the rule-set store directly. The compiler's service account (a shell in its container) cannot make a
root-owned file. The import does not re-verify the vendor signature itself.

**Residual: who can forge an acceptance.** The mark `profiles/<ID>.site-set.json` lives in the rule-set store, which
the criteria compiler's service account writes. The import does not cross-check the mark against the audit
(`approve.site_profile_set`): whoever can act as that account (a shell in the compiler's container, the host's
root) can write a mark and profile that accept a version, with no audit event. No cross-check is built here.

## What travels (for the owner to rule on)

Everything not in this list stays on the head box. Free text that still leaves it, all of it the protocol's or the
compiler's by purpose, any of it typed or edited by a person on the head box:

- `manifest.yaml`: `title`, `trial_alias`, `sponsor`, `protocol_version`, `protocol_date`, `language`, `nct_id`,
  `source_last_update` (a date only), `population.disease_stage`, `population.study_arm`, `cohort.disease`,
  `cohort.disease_label`, `cohort.ctgov_condition`, `variants` (named sensitivity variants), `twpas` (NHI form
  settings), `library`, `terminology_release`, `models.judge_prompt`, `prompt_pins`, `derived_pins`; the criteria
  ids, thresholds and equivalence numbers.
- each `ir/<id>.json`: `text`, `label`, `source_ref` (the protocol's section and item, as the parser read it),
  `action` (the suggested to-do), `note_question`, `note_question_source`, `human_question`, `fallback`,
  `suggested_order`, `flags` (compiler words only), `review.status`; the logic's value set names and codes.
- `labels.yaml`: per criterion `source`, `todo_source` and their translations (`label`, `text`, `todo` in en, ja,
  zh-TW).
- `valuesets/*.json`: `title` and each concept's `display` (code system names), besides the codes.
- `cql/*.cql` and `sql/*.sql`: the compiler's comments, which repeat each criterion's `text`; **string literals
  are free text typed by the approver and travel as written**: besides the codes, units and code system URLs the
  compiler writes, a CQL or SQL string literal (`define "X": 'any words'`, `SELECT 'any words'`) is not checked
  (comments are; no literal grammar is held against the compiler's), so whatever a person typed into one on the head
  box leaves it; ELM: without annotations, by its key allow-lists (81 keys), **but its values are not checked: the
  ELM is not checked against the CQL and a value is not type-checked, so any string value under an allowed key
  travels as written; it is not checked against the CQL** (26 of the keys hold strings in the shipped files:
  `accessLevel alias asType codeComparator codeProperty context dataType direction id identifier libraryName localId
  localIdentifier locator name path precision resultTypeName scope templateId type unit uri value valueType
  version`), so define and value set names and literals travel with whatever a person put there.
- `ORIGIN.json`: the bundle id, release_seq and commit of the compiling release (no free words: `--release` takes a
  bundle id), the pins, the file names (criterion ids, value set and library names).

Removed or refused, for the record: `source_documents`, `docx_template`, `population.notes`, every site field above,
each criterion's reviewer, time, comment and `provenance`, `tests/`, every comment the compiler does not write, ELM
annotations, any key or file nobody placed.

**Where the 30/90-day cap is enforced.** Only when the bundle is signed, in `tools/ruleset_bundle.py`
(`--valid-days`, 30 by default, at most 90). The import does not see the bundle's manifest, and the verifier
(`tools/verify_update.py`) checks `not_after` but no cap: a rule-set-only bundle signed with `tools/sign_bundle.py`
directly can be valid longer. This predates the card and is not changed by it.

## Not in this card, and what the dry run must know

- **New id or version.** A site box that already holds the version (the shipped example on a DEV box included)
  refuses the part; the head box exports a new id or version.
- **Pins must match.** The site box screens only on the same terminology release (else `RecompileNeeded`, and a
  screen-only box cannot recompile) and asks for approval again on a prompt or score pin drift; the head and site
  boxes run the same release for the dry run. The site's code tables are not carried, so the receiving box cannot
  check that the compiled SQL read the same site tables (D-1366 names the same limit for 10D-5).
- **Not run on a container box.** The tests run the real verifier, `Updater` and import on an in-process box; the
  compose box's steps (backup, dumps, restart, `docker compose exec criteria-compiler ... import_ruleset`) are
  unchanged and were not run. What `run_cmd` keeps of a refused import's standard error (its first line and last 600
  characters) is tested with a real child process, not in a container.
- `tools/trialbox/update.py` `InProcessBox.rulesets` still imports nothing (the update drill's box); unchanged.
- **Not run on a container box (the gate).** The evidence file, its mount and the root-owner check were run with the
  test's own account standing for root; no compose box ran them.

## Held by

- `tests/unit/test_ruleset_in_update_bundle.py`: planted names, addresses, a reviewer's comment, practitioner and
  department codes, an IRB reference, an effective date and a site code table are in no byte of the part or of the
  bundle; the part keeps the protocol fields and is reproducible; a file or field nobody placed refuses the export;
  only the box's own approval is exported and the export is audited; a bundle may carry a rule set alone, valid 30
  days; the PRODUCTION site box installs it with its own routing and scope, tags and lists it as arrived, audits
  `update.applied` with it, keeps its commit, takes the same part again as a no-op; without its own routing and scope
  it refuses; a zip without a record is listed as arrived too; a part older than the newest, the same version with
  another hash, the version of a shipped example, a record of the wrong form (each field), a record changed without
  its hash, a stray member, a site field put back, a changed criterion are refused; a bundle changed after signing is
  rejected; the sponsor pack says it arrived.
  The third review: a file off the per-file list refuses the export (six shapes) and the import (three, resealed); a
  CQL `//` or `/* */`, a `TB_Common` or an SQL `--` comment the compiler does not write refuses the export with file
  and line, and the import; YAML comments and ELM annotations are in no byte of the part; an ELM identifier key, a
  value-set key or a nested one refuses; an ELM key off the allow-lists (an extra library key, a key on a statement
  definition, an extra top-level key) refuses the export naming its path, and a part resealed with one is refused at
  the receiving box naming its path; a free file name refuses; the criterion stripper is an allow-list equal to
  the schema less `provenance`, and a part holding an unknown key is refused; a part without `ORIGIN.json`, or with it
  moved, is refused; the shipped example profile and a hand-edited one do not count; `approve.site_profile_set` is
  written before the profile and a failed audit writes nothing; a re-export is the same part and installs as a
  repeat; the record's pins must be the manifest's; deep JSON and YAML are refused; `--release` takes no free words;
  `population.notes` stays and `source_last_update` is a date.
  The fourth review: a second version of the id without a new act at the site is refused (en, ja, zh-TW, with the
  command), the update rolls back and the first stays; once accepted the same bundle installs it, and
  `approve.site_profile_set` names who, the id, the version and the hash; a hash the site did not accept is refused
  and the accepted one installs; a profile of the first form accepts no version; `--site-profile` needs `--version`
  and reads standard input; a repeat is said and recorded as "already present" with id and version, from the line the
  import prints; a part swapped on disk after its check is not what the bundle holds, and a file changed between the
  check and the signature refuses the build and leaves no bundle.
  Also: the bundle's compatibility table carries the part's terminology release and the compiling release as its
  floor, and the verifier refuses a box on another vocabulary release or an older release; the import refuses a part
  whose terminology release is not the box's.
- `tests/integration/test_ruleset_bundle_two_boxes.py`: two in-process boxes on the same synthetic hospital. The head
  box screens the shipped GZQO v1.0.0, then approves v1.0.1, which is not shipped (GZQO-INC-01 at age 60; the draft
  is written by the test, the approval is the compiler's own, which rebuilds the SQL), and screens it; it exports
  v1.0.1, the vendor signs it alone, a box that never held GZQO applies it and screens v1.0.1 by e-mail with the
  routing and scope its operator set with `--site-profile` (the synthetic site's people). Every listed patient, tier and criterion answer equals the head box's v1.0.1 answers and differs
  from the shipped version's. A mutant import that writes the repository's own shipped GZQO files instead of the
  zip's fails it (run once by hand).
- `tests/console/test_ruleset_arrived_in_bundle.py`: the overview marks such a version in en, ja and zh-TW; the
  administrator's page (`admin.html`) and the administrator's home without step 4 (`home_admin.html`) mark it too.
- The fifth review (`tests/unit/test_ruleset_in_update_bundle.py`, `test_r5_*` and the re-check of finding 3): the
  accept command carries `--by`; `--site-profile` and `export_part` refuse without it and write nothing; their
  events name the account and `by_claimed`; a refused part's first line holds the id and version within 500
  characters and its last line the whole command within the last 600, also through the update's own command runner;
  any other refusal of a hand-run zip ends with exit 2 and no traceback; a version with a line break or other
  digits, an id with a line break are refused; a profile over 64 KiB (on standard input, read no further) or with an
  unknown field is refused, nothing written; a mark for another id accepts nothing; a bundle without a rule set says
  `0 imported, 0 already present`; the vendor tool prints each part's full hash.
- The review of edb77053 (`tests/unit/test_ruleset_part_gate.py`; each test failed on edb77053): a plain zip of a
  version the site did not accept is refused through the update; a part without a release_seq is refused at the
  export, the vendor's tool and the box, and a part of release 3 on a box of release 2 is refused; the standalone
  command writes nothing (en, ja, zh-TW) and only checks; every road with every bypass (no evidence, evidence of
  other bytes, of an older or unknown release, a plain zip, a forged or group-writable evidence file, a version not
  accepted, the same bundle again after its rollback) writes no tag, and the update's own road with the site's
  acceptance installs; a listed exclusion missing from the part is refused at the export and the box; an arrived rule
  set screens only its profile's practitioner and department whatever the job or set-up page asks; a repeat takes the
  corrected routing; a nested object, list or null in a value-set scalar is refused; an archive or member comment, an
  extra field, appended or prepended bytes refuse the part and the bundle.
