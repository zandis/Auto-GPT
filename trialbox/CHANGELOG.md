# Changelog

What changed in each TrialBox release, newest first. The version is written in one place, `[project] version` in
`pyproject.toml`; `python -m tools.release version` prints it and `python -m tools.release tag` prints its tag
(`trialbox-v<version>`). Every signed bundle carries this file, `NOTICE` and `release.json` (T-110b, D-340), and the
console's about page shows the release a box runs.

A pull request that changes what a site receives adds a line under "Unreleased". A release moves those lines under a
new heading with the version and date, in the same pull request that sets the version.

## Unreleased

- The PI's cover, the escalation of an unacknowledged SAE and a task's owner (9f-3, 9f-4 (b), 9f-5; D-1383): the PI
  names a sub-investigator of the study's log to cover them for at most 90 days, with the PI's clinical rights in that
  study only (never the delegation log, its monthly check, the study's state or the IRB records); a serious adverse
  event the PI has not acknowledged after `TB_SAE_ESCALATE_HOURS` (default 24) is mailed once to the study's
  sub-investigators and coordinators on its log. **On the first run after the update every unacknowledged serious
  adverse event already older than that is mailed at once, one mail per case and person.** A task on the opening page
  may name its owner from the study's log.
- Silent set-up choices guarded (10K-21): a new PRODUCTION site must answer the chart-number question (choosing
  "as written" is an answer; leaving it empty is not), in the settings wizard and on the box's first-run page. A box
  names the person who opens its health page every working day (its backup alert route); the name is shown with the
  route. With the box's own certificate authority, who in hospital IT confirmed its root is on the clinic PCs, and
  when, is recorded once the root exists (the box's first-run page, or two lines in `deploy/.env`). **An installed
  site is not stopped by the upgrade**: `doctor` warns, with the line to add to `deploy/.env`, for each of the three
  it lacks (D-1365). A typed name holds letters, digits, single spaces and a few marks only, and the wizard writes no
  `deploy/.env` value with a line break, a control character or a byte that is not UTF-8 in it, so a name can never
  add or change a setting; O'Brien and full-width brackets are names. An unknown `--environment` stops the installer
  before it loads or writes anything.
- The one page for hospital IT (10K-18, D-1378) is made from the box's own preflight list, one page per delivered
  form, in en, ja and zh-TW: for a box its supplier prepared it asks IT for six things (name and certificate, clock,
  mail relay, backup share, audit share, data feed) with the words the box shows on a red line, and names the three
  the supplier prepared; for a box IT installs (`it-one-page.it-form.<lang>.md`) it asks for all nine. It no longer
  says "only three things".
- One spelling for each core word (9k-16, D-1371): the console says 候補者 / 候選者 for a candidate everywhere, and in
  Japanese 治験依頼者 (not スポンサー), データ管理責任者 (not データスチュワード) and 治験分担医師・治験協力者リスト
  (not 責任分担表); in Chinese 授權紀錄表, 試驗委託者 and 病人代碼; in English "sub-investigator". The words are a
  data file (`services/console/core_words.yaml`) that `make lint` holds every console text to, and the job mails,
  the PDF titles and the refusal sentences too (the Japanese feasibility mail and report say 実施可能性, not
  フィージビリティ; the zh-TW steward is 資料管理員). No setting changes; no row has yet been read by a native reader.
- The console and the device (9f-11, 9f-6, 9g-19; D-1370): one minute before the idle lock a page warns, with
  "Stay signed in" (the idle and the absolute limits are unchanged; what was typed stays on the page); a hospital
  sign-in refused because the person's directory groups give two roles names the two groups for the hospital's IT;
  the console's policy now forbids service workers by name (`worker-src 'none'`), written down with the rest of the
  rule that nothing of a clinical page is kept on a device.
- Each pull request that changes the console is now compared screen by screen with master on 72 first screens in
  three languages (9k-17, D-1377); a changed screen must be looked at before it passes. The check is not required and
  keeps no picture in git. Nothing changes on the box: no setting, no new file installed.
- The console's buttons are one design (9k-3, D-1375): a filled, an outlined, a text-only and a red-outlined
  variant and one small size, every one at least 44 px; the older second layer of sizes is folded into the first, so
  the pages look as before. Nothing changes on the box: no setting, no new file installed.
- The console's colours and type are named values (9k-1, 9k-2, D-1368): form fields have a darker border that meets
  the 3:1 contrast for controls, the amber "needs attention" row is readable in dark mode (and a little paler in
  light mode), and Japanese and Traditional Chinese pages have a taller line height (1.7) with strict line breaking.
  Nothing else changes in how the pages look; no setting, no new file.
- Operations drills (10K-9): each operations page of the RUNBOOK names a drill only where a test rehearses it (§12
  certificate renewal, §20 close-out, §22 moving the box, §23 lost-box list, §25 leavers); the other pages say that
  no test rehearses them. Two steps corrected: when the host name changes, run `check-tls` with the new values of
  `deploy/.env` (§22); at close-out, write down the head after `--sign-head` (§20).
- Updates from a stick at the box (10K-7, D-1363): the Operations page's update tab lists the bundles on an update
  stick the host mounts read-only (`/media/trialbox-update`, or `TB_UPDATE_STICK`), verifies one after copying it to
  the box, shows its Japanese release note and change-impact sheet (change classes CC1 to CC6, minutes down,
  migration, re-approval), and asks for the apply in the box's quiet hour for exactly the file that was verified (a
  waiting one can be cancelled there). Mount the stick `ro,nodev,nosuid,noexec`. Every bundle now carries
  `RELEASE-NOTE.ja.md` and `CHANGE-IMPACT.json` (`tools/make_bundle.sh` refuses to build one without them); a bundle
  without them is still verified and applied, with a warning. Going back to the previous release is shown on the
  page and stays the older-release path of the runbook at the box.
- A live preflight (10K-3, D-1361): the box's name and certificate, the clock, the backup share, the audit share, the
  data feed (a count of files), the mail relay, the disk, the key protection (the TPM, and Tang where the disk unlock
  uses it) and the graphics card against the tier record, each line with what to do next in English, Japanese and
  Chinese. `trialbox doctor --preflight --lang ja` prints it, the settings wizard prints it with `--preflight`, and
  the box's first-run page shows it, as checked before the owner's answers (a red line says whom to ask: hospital IT
  or the box's supplier). Read-only, bounded in time; plain `doctor` is unchanged.
- ClinicalTrials.gov intake widened (10D-15, D-1367): a study read from the registry (live, offline pack or
  cassette) now carries its sites with their recruitment status, its secondary ids (a jRCT, JapicCTI or UMIN-CTR
  number is recognised as such), arms, interventions, primary and secondary outcomes and the design (allocation,
  masking, model). Contact persons, officials, investigators, a person named as sponsor or collaborator, and
  citations are no longer kept: the reference data store drops them from the records it holds when the box upgrades
  (refdata schema version 4, which rewrites only the records holding one). Free text in a record is not cleaned.
  Nothing to do.
- Dates on printed pages and the fiscal year 年度 (10C-13, 10C-15): a site may print dates in Western form (ISO, as
  before), Japanese era (令和8年11月18日) or both (2026年（令和8年）11月18日) on the feasibility report, the NHI
  navigation summary and application form, the CASE sheet and the released consent page (`site.printed_dates`); the
  research office counts may count by 年度, 1 April to 31 March in the site's time zone, and say which year they count
  in three languages (`site.year_basis`). **A new site** gets its country's default from the set-up wizards, which
  ask both questions: Japan both forms and 年度, any other country Western and the calendar year. **An installed site
  is not changed by the upgrade**: a settings file without the keys prints and counts exactly as before, whatever its
  zone or language. To change it, set the keys in `deploy/settings.yaml` and restart; there is no console page for
  this (D-1229).
- Set-up follows the site's country (10K-1): the settings wizard asks the country first (Japan, Taiwan, United
  States, other) and takes the report language, time zone, retention rules, source type, mapping and the TWPAS
  questions from one table; a Japan site gets Japanese reports, Japan's retention and an SS-MIX2 source (the
  storage's root folder, read-only, and its order-number key). The box's first-run page asks the country first, and
  offers SS-MIX2 for a site in Japan, only with `TB_FIRSTRUN_COUNTRY=1` (off by default: the page is as before). An
  answers file without a country, and an installed box, read exactly as before.
- Exports and typed text (NEW-CSV-1, D-549): a comment or a reason that begins with `=`, `+`, `-` or `@` is no
  longer a formula in the feedback export, the screening log's workbooks or the registry export.
- The candidate registry and the acting person (T-715b, D-550): a status change or a promotion is recorded under
  the signed-in person the orchestrator verified (`console:<username>`), never under a name sent in the request.
- The FHIR store's database sign-in (NEW-TRUST-1, D-541): the FHIR store no longer holds the database
  superuser's password. It signs in as `tb_fhir_store`, which owns the database `hapi` only, with
  `TB_DB_PW_FHIR_STORE`. `install.sh` and `trialbox update` make the password and move the existing tables (an
  update needs the box on a release that has the `db-up` command first); a stack started by hand from an older
  `deploy/.env` needs the variable and one run of the role script.
- The opt-out desk checks the chart number (NEW-DIN-3, D-544): a number that is not a patient of this box is
  refused with that message; the keeper may register it anyway with a written reason. The box's first-run page
  asks how the hospital writes chart numbers, only while the box holds no patient.
- The opt-out register (NEW-JRN-2, D-542): a pseudonym must be typed whole (32 characters) or the chart number
  used; the 8 characters a page shows are refused. After the save the page says whether a listed patient
  matched, or that nobody did.
- Chart numbers typed short (NEW-DIN-3c, D-546): with a rule such as `digits:8`, a chart number typed without its
  leading zeros or in full-width digits is accepted for a registry row, a CASE request and a chart in site set-up.
- Database roles (T-718, D-486): the EDC schema has an owner role no service can become; the orchestrator writes its
  rows and can no longer drop, disable or alter the triggers that make its trail tables append-only. The schema's
  tables are made by the box's admin before the services start (`install.sh`, `trialbox update`, or by hand
  `python3 -m tools.trialbox migrate`); after a restore run the role script, then that command.
- Database roles (NEW-ARCH-18, D-543): the console's role reaches the patient twin's schema (`profile`), so the
  twin read works on a box. `trialbox update` does not run the role script: run it once after the update, from the
  release folder: `docker compose --project-directory deploy exec -T db /docker-entrypoint-initdb.d/30-service-roles.sh`
  (`deploy/install.sh` runs it). Until then the twin read answers 500.
- Chart number to pseudonym (T-719, D-487): the orchestrator gives the pseudonym of a chart number only to a
  signed-in person with the right (the opt-out register, a registry row typed by chart number), at most
  `TB_TO_PID_MAX_PER_HOUR` an hour per person (unset: the value of `TB_REVEAL_MAX_PER_HOUR`), and records each one
  (`screen.to_pid`, with the pseudonym, never the chart number). A service token alone is refused.
- The key that signs people (T-717, D-485): the console signs the acting person with a key of its own
  (`deploy/secrets/services/actor-sign.key`), no longer derived from its service token. `install.sh` and
  `trialbox update` make the file; `trialbox secrets rotate --service actor` rotates it.
- Break-glass (T-716, D-484): the orchestrator reads the grant itself before it gives a chart number (this person,
  this patient or job, open now) and writes the use; an investigator's own right is read from the delegation log
  there too. The orchestrator's database role joins the `breakglass` and `team` schemas: `install.sh` re-runs the
  role script; after a `trialbox update` run it once by hand (runbook §5, "Database roles after a restore"), or a reveal under a grant
  or by an investigator is refused with "cannot be read".
- The audit trail (T-721, D-488): the audit writer marks an event sent by a database role that does not write
  that kind of event, or dated more than `TB_AUDIT_TS_MAX_SKEW_S` (300 s) from when it arrived;
  `python -m tools.audit_verify <audit dir> --foreign` lists the marked events.
- A new study's first approval (NEW-JRN-1, D-540): the data steward can open the delegation log of a study whose
  criteria wait for approval and name its PI; the steward's pages show that task, and the approval page says
  when no PI is named. An account limited to its studies is told why a request for another study is refused.
- The acting person (T-715, D-483): the participant, visit-schedule, SAE-rule, contact-rule, deviation and sponsor
  routes of the orchestrator take the person from a signed claim for that action, study and request, never from the
  request body; their records name `console:<username>`. The other changing routes count unsigned calls
  (audit event `actor.unsigned`, once per route and reason); a participant's step derived from a saved form or a
  REDCap read names the verified person or `unverified`.
- Database passwords (T-712, D-481): every service clears the other roles' and the administrators' passwords in
  the base compose file, so no stack can be started with them; `trialbox doctor` has the check `db_passwords`
  (the box's `.env`, its compose files and its running containers).
- Release identity and bundle gates (T-110b, D-340): `tools/release.py` writes `release.json`
  (`schemas/release.schema.json`) and the release's `images.lock` for each bundle; `tools/make_bundle.sh` needs
  `--gates` and `--release-seq`, carries the SBOMs, the gate record, `NOTICE` and this file, and no longer carries
  the test mail servers.
- The image vulnerability gate blocks for every image a bundle can carry; report mode is left only for the test-only
  mail servers. Open findings of the HAPI FHIR, vLLM and `trialbox-postgres` base images are dated, per-image exceptions in
  `deploy/supply-chain-allowlist.yaml`.
- Build downloads are checked against pinned sha256 sums: the CQL translator jars (`tools/jvm-deps.sha256`), the FHIR
  packages (`tools/fhir-packages.sha256`) and the report fonts (`tools/fetch_fonts.py`).
- One Java version, in `.java-version`, read by CI and checked against the JVM image.

### Known limits

- SCREEN of the whole hospital stops at about 45,000 patients (H23b-01). The orchestrator's memory cap,
  `TB_MEM_ORCH`, is 4 GiB as installed (3 GiB on the two-device workstation), and no installer step or compose
  overlay raises it, whatever the machine's memory. SCREEN needs about 86 KB a patient, so a SCREEN job of a
  hospital of about 45,000 patients or more is killed at the cap. What follows, read from the code (not yet seen
  on an installed box): the orchestrator is killed and restarted, the job is run again from the start, and after
  more restarts than `TB_JOB_MAX_RESTARTS` (3 unless set) it ends `failed` with "This job was interrupted by a
  restart of the box ... times and was not started again ... Check the box's memory and logs (RUNBOOK §4)".
  The basis (`docs/plan/measurements/size-test-2026-11-17.md`, H-23b): measured with the stub model on a 4-vCPU,
  15 GiB container, SCREEN's peak was 2.03 GiB at 20,000 patients, and with the cap lifted 4.37 GiB at 50,000 and
  8.22 GiB at 100,000. On the two-device workstation the limit is lower, not measured. The measurement lifted the
  cap with `TB_MEM_ORCH=10g` (compose reads the same setting from `deploy/.env`); that is a measurement setting,
  not a supported configuration. Sizing the cap from the site's patients and bounding SCREEN's memory are open.

## 1.0.0

The first numbered version: the pilot appliance as built through plan v6 waves P and 1 (no site has installed it from
a signed bundle yet).
