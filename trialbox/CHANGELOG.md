# Changelog

What changed in each TrialBox release, newest first. The version is written in one place, `[project] version` in
`pyproject.toml`; `python -m tools.release version` prints it and `python -m tools.release tag` prints its tag
(`trialbox-v<version>`). Every signed bundle carries this file, `NOTICE` and `release.json` (T-110b, D-340), and the
console's about page shows the release a box runs.

A pull request that changes what a site receives adds a line under "Unreleased". A release moves those lines under a
new heading with the version and date, in the same pull request that sets the version.

## Unreleased

- The console and the device (9f-11, 9f-6, 9g-19; D-1370): one minute before the idle lock a page warns, with
  "Stay signed in" (the idle and the absolute limits are unchanged; what was typed stays on the page); a hospital
  sign-in refused because the person's directory groups give two roles names the two groups for the hospital's IT;
  the console's policy now forbids service workers by name (`worker-src 'none'`), written down with the rest of the
  rule that nothing of a clinical page is kept on a device.
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
