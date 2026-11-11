# Decision number registry

One row per decision number or range. A number belongs to the holder in its row and to nobody else. A pull request
that needs a number takes the next free one and adds its row, or writes "decision number needed" (D-311: no waiting
for the integrator; the old rule "the row is added before the branch is cut" is struck). Rules: D-306, D-311.

`python -m tools.decisions_index --check` (CI job `docs`) holds this table against the text: the frozen log
`docs/DECISIONS.md` (entries D-01 to D-270) and the files `docs/decisions/D-nnn-<slug>.md`. It fails only on a number
written twice; a file with no row, a new log entry or a gap is printed as a note (D-311).
`python -m tools.decisions_index` prints the full index with titles.

States:

| State | Meaning |
| --- | --- |
| `merged` | the text is on master (the log or a file) |
| `reserved` | held by a card, a pull request or a fix group; its file may land (the integrator flips the row to `merged` when convenient) |
| `unused` | never to be used: a gap, or a reservation that was voided |
| `missing` | cited on master, never written: the text is owed |

How to take a number: the integrator writes a `reserved` row naming the card (`T-nnn`) or pull request (`PR #n`). New
numbers start at **D-300** and go up by one. A decision file must name its card in its first lines when the row
names a card.

Collisions settled by TB-PLAN-06 §6.1 rule 3: a number belongs to whoever has it on master. D-201 stays test
isolation (PR #75 takes D-300); D-205 stays committed goldens (PR #82 takes D-301); D-204 is T-104's (merged from
the PR #83 version; PR #82 drops its copy). Reservations D-190 to D-207 of TB-ASSESS-01 are void (the numbers on
master stay); reservations D-208 to D-262 stay valid.

## The frozen log and the first files (D-01 to D-207)

| Number | State | Holder | Note |
| --- | --- | --- | --- |
| D-01..D-98 | merged | phases 0 to 5, clinical review build | `docs/DECISIONS.md` |
| D-99 | missing | — | cited on master (exact counts inside the site, the coordinator's screen, one chart number shown once and audited: `services/orchestrator/scenarios/screen.py`, `services/console/app.py`, `services/console/home.py`, `services/console/backend.py`, `services/orchestrator/app.py`) but never written in the log; the text is owed |
| D-100..D-151 | merged | simple build plan steps 1 to 5 | `docs/DECISIONS.md` |
| D-152..D-159 | unused | — | gap recorded by TB-ASSESS-01 |
| D-160..D-163 | merged | EDC prefill, Study A documents | `docs/DECISIONS.md` |
| D-164..D-169 | unused | — | gap recorded by TB-ASSESS-01 |
| D-170..D-179 | merged | reference data, rehearsal, IT screens (PRs #66, #68, #76 and earlier) | `docs/DECISIONS.md` |
| D-180 | merged | PR #80 | catalogue completion with verified codes (file) |
| D-181 | merged | PR #64 | judge bake-off; `docs/DECISIONS.md` |
| D-182..D-184 | unused | — | held for the sibling session, which was given D-185 to D-193 instead |
| D-185..D-193 | merged | sibling session | supply chain, backups, derived scores, SAE register, identity, TLS; `docs/DECISIONS.md` |
| D-194..D-200 | unused | — | TB-ASSESS-01 reservations for T-006 to T-012, void (T-012 takes D-305) |
| D-201 | merged | T-003 | test isolation and disk (file) |
| D-202 | unused | — | TB-ASSESS-01 reservation for T-102, void (T-102a takes D-302) |
| D-203 | merged | T-005 | data-handling scan (file) |
| D-204 | merged | T-104 | database image and checksummed migrations (file) |
| D-205 | merged | T-006 | committed goldens (file) |
| D-206 | merged | T-007 | CI gate v1 (file) |
| D-207 | merged | T-008 | feature flags (file) |

## Reservations of TB-ASSESS-01 that stay valid (D-208 to D-269)

| Number | State | Holder | Note |
| --- | --- | --- | --- |
| D-208 | reserved | T-108 | Wave-3 operations in code |
| D-209 | reserved | T-110 | Release identity and supply chain |
| D-210 | merged | T-111, PR #83 | update safety (file) |
| D-211 | reserved | T-113 | The shared-quota profile, doctor --platform and the platform manifests |
| D-212 | reserved | T-114 | Cloud B200 qualification record |
| D-213 | reserved | T-115 | EDC prefill follow-ups from TB-REV-EDC-01 (the tracked items) |
| D-214 | reserved | T-117 | Backups: layout, stream hashes, off-box schedule, age alert, … |
| D-215 | merged | T-118 | wave-1 leftovers: unit mismatch, one encoding detector, one dates module |
| D-216 | reserved | T-119 | Cloud hygiene remainder |
| D-217..D-219 | unused | — | no card of TB-ASSESS-01 took them |
| D-220 | reserved | T-103 | One reveal path |
| D-221 | reserved | T-107 | The catalogue loaded as data |
| D-222 | reserved | T-109 | Identity v1: Caddy, Authelia, local TOTP, step-up, forced password … |
| D-223 | reserved | T-112 | The data-operations console v1 |
| D-224 | reserved | T-116 | "Criteria not matched", the forbidden-word check and the intended-use … |
| D-225 | reserved | T-201 | Clinical conflicts and the conflicts page |
| D-226 | reserved | T-202 | The lake exported from OMOP: parity in CI and the flag flip on the … |
| D-227 | reserved | T-203 | pgvector, the chunker and "patients like me" |
| D-228 | reserved | T-204 | The twin |
| D-229 | reserved | T-205 | Second factor at signing and the record lock |
| D-230 | reserved | T-206 | Opt-out worker v1 |
| D-231 | reserved | T-207 | The derived-data framework: stored rows and definitions as data |
| D-232 | reserved | T-208 | Prompt-injection and false-positive suite |
| D-233 | reserved | T-209 | Monitoring, admin screens and the support bundle |
| D-234 | reserved | T-210 | Windows/WSL2 hardening, keys under a KEK, the unseal path |
| D-235 | reserved | T-211 | Audit integrity: signed heads, one writer, NTP as a FAIL, the audit … |
| D-236 | reserved | T-212 | Boundary and egress |
| D-237 | reserved | T-213 | The acceptance environment and the Docker drills |
| D-238 | reserved | T-214 | arm64 builds, the gb10 profile measured, the two-device link |
| D-239 | reserved | T-214 | arm64 builds, the gb10 profile measured, the two-device link (the owner's decision) |
| D-240 | reserved | T-215 | QMS-lite records, change classes, the FS, the risk file, the VMP for … |
| D-241 | reserved | T-216 | Missing data as the normal case |
| D-242 | reserved | T-301 | Wave 5 product completeness, help, card and .ics |
| D-243 | reserved | T-302 | REDCap arms and events, repeating instruments, copy-assist, ODM … |
| D-244 | reserved | T-303 | Monitor SDV |
| D-245 | reserved | T-304 | Statistics page and the export set: EXTRACT, Define-XML, audit CSV, … |
| D-246 | reserved | T-305 | All-history back-fill, content-addressed snapshots, batched publish, … |
| D-247 | reserved | T-306 | HAPI out of the nightly path |
| D-248 | reserved | T-307 | Catalogue gaps and the instrument copyright register |
| D-249 | reserved | T-308 | Specialty templates |
| D-250 | reserved | T-309 | Break-glass |
| D-251 | reserved | T-310 | Weekly "criteria not matched" sample, the per-study IRB-text gate on … |
| D-252 | reserved | T-311 | The cited profile page and the Study C/D protocol drafts |
| D-253 | reserved | T-312 | Physician annotations |
| D-254 | reserved | T-313 | Setpoints and the gap finder, flags off |
| D-255 | reserved | T-314 | The clinician view, restricted |
| D-256 | reserved | T-315 | Test strategy executed: the journeys as the PQ script, IQ/OQ/PQ … |
| D-257 | reserved | T-315 | Test strategy executed: the journeys as the PQ script, IQ/OQ/PQ … (second record) |
| D-258 | reserved | T-316 | Consortium: the shared code-map registry, signed counts, the … |
| D-259 | reserved | T-317 | Documents made true, role guides in ja and zh-TW, the independent … |
| D-260 | reserved | T-318 | Privacy documentation, the incident plan and the one-page "what this … |
| D-261 | reserved | T-319 | Shared-host isolation on the acceptance cluster and the platform KEK … |
| D-262 | reserved | T-320 | Site set-up limits, the EMR launch link, the work log, admin console … |
| D-263..D-269 | unused | — | below the fix-group block; never given |

## The critical-issues fix groups (D-270 to D-289)

| Number | State | Holder | Note |
| --- | --- | --- | --- |
| D-270 | merged | fix group D-270 (PR #86) | the console's "today" is the site's date; `docs/DECISIONS.md` (its last entry) |
| D-271 | merged | fix group D-271 (PR #97) | the data pipeline never promotes nothing; `docs/decisions/D-271-data-pipeline-integrity.md` |
| D-272 | merged | fix group D-272 (FG-C) | audit integrity: no chart number in the audit chain, a head anchor, an archive that never overwrites (file) |
| D-273 | merged | fix group D-273 | console privacy guards: one reveal path, delegation and opt-out on every patient-level reader, signed role and study (file) |
| D-274 | reserved | critical-issues fix groups | TB-REG-01; the fix-group session allocates inside the block |
| D-275 | merged | fix group FG-F (PR #115) | structured criteria: unusable data is unknown, never an exclusion; `docs/decisions/D-275-criteria-unusable-data-unknown.md` |
| D-276 | merged | fix group FG-G (PR #101) | the two-model check needs two different models; `docs/decisions/D-276-two-model-check.md` |
| D-277..D-278 | reserved | critical-issues fix groups | TB-REG-01; the fix-group session allocates inside the block |
| D-279 | merged | fix group D-279 | identity follow-ups: forced first password change, sign-in lock per account and address, OIDC session lifetime, second factor at signing; `docs/decisions/D-279-identity-follow-ups.md` (file) |
| D-280..D-289 | reserved | critical-issues fix groups | TB-REG-01; the fix-group session allocates inside the block |
| D-290..D-299 | unused | — | below the new block; never given |

## New numbers (from D-300)

| Number | State | Holder | Note |
| --- | --- | --- | --- |
| D-300 | merged | T-101 | prompt registry, renumbered from the PR's D-201 (file) |
| D-301 | merged | T-105, PR #82 | vocabulary schema (renumbered from the PR's D-205) (file) |
| D-302 | reserved | T-102a | permission matrix |
| D-303 | reserved | T-106 | OMOP schema name |
| D-304 | reserved | T-106 | dual write |
| D-305 | unused | — | was reserved for T-012a, which took D-313 |
| D-306 | merged | T-002 | decisions as files, one number registry, CODEOWNERS and CONTRIBUTING (file) |
| D-307 | unused | T-508 | was reserved for T-508, which took D-332 (the integrator gave D-332) |
| D-308 | reserved | T-501 | held for T-501 |
| D-309 | merged | T-507 | criterion labels in the site's languages, the label step at approval, the test-model label (file) |
| D-310 | reserved | the integrator | given to other cards and pull requests; their own rows replace this one as they land |
| D-311 | merged | owner rule, branch `agent/no-dev-gates` | no development gates; gates apply only when real patient data is read; CGMH covered by the existing CGRD approval (file) |
| D-312 | merged | T-611 | feed completeness gate before publish (file) |
| D-313 | merged | T-012a | `trialbox eval qualify` and the qualification record (file) |
| D-314 | merged | T-614 | Japan ICD-10 as WHO ICD-10: WHO URI, ICD-10-CM twin only for the same code, WHO-only grouper categories (file) |
| D-315 | merged | T-656 | site time zone as one setting (file) |
| D-316 | reserved | the integrator | given to other cards and pull requests; their own rows replace this one as they land |
| D-317 | merged | T-618 | reference data remainder (file) |
| D-318 | merged | T-101b | the approved ruleset pins its prompt and terminology release; approval needed on a change (file) |
| D-319 | merged | T-655 | the review fixes of PR #71: what changes from D-205 and D-207 (file) |
| D-309..D-319 | reserved | the integrator | given to other cards and pull requests; their own rows replace this one as they land |
| D-320 | merged | T-505a | the API sign-in asks for the second factor; one channel per session (file) |
| D-321 | merged | T-504 | scenario rulesets: SQL checked on planted gold, CQL recorded by a local engine (file) |
| D-322 | merged | T-613a | the shipped rulesets recompiled offline from their cassettes, and the CI drift check (file) |
| D-328 | merged | T-502 | PoC demonstration mode behind the audited flag `demo.mode`: uploads and chart paste refused, banner, `demo.ack`, the scan of stored input (file) |
| D-329 | merged | T-513 | one demo clock: the demo day is the real day in the site's time zone; dates moved, one clock (file) |
| D-330 | merged | T-509 | the PoC host: one VM, the image by digest, Cloudflare Access through a tunnel, kept data on its own disk, daily snapshot, purge (file) |
| D-331 | merged | T-510 | in-product feedback: a flag, a rating and a comment on every page, stored with path, language, role and time; CSV export to issues; the comment in the demo scan (file) |
| D-332 | merged | T-508 | the clinician PoC is product evaluation, not research: no protocol, subject consent or committee step; the acknowledgement only (file) |
| D-333 | merged | T-601 | the gateway never answers one role with another role's model: `fallback: none` unless a route says `any`, one retry on the same build, no fallback on 400/404, build and fallbacks in the response, `tb_llm` raises on an unexpected alias, doctor `judge_route` (file) |
| D-334 | merged | T-613b | lab units read per row: one conversion table in labvalue (engines' factors reused), mapping_check unit pairs and raw values, one presence reader in ja, zh-TW, en (file) |
| D-347 | merged | T-210b | the site keys under a KEK: wrapped files, three back ends, the unseal, the key inventory (file) |
