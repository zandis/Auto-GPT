# Changelog

What changed in each TrialBox release, newest first. The version is written in one place, `[project] version` in
`pyproject.toml`; `python -m tools.release version` prints it and `python -m tools.release tag` prints its tag
(`trialbox-v<version>`). Every signed bundle carries this file, `NOTICE` and `release.json` (T-110b, D-340), and the
console's about page shows the release a box runs.

A pull request that changes what a site receives adds a line under "Unreleased". A release moves those lines under a
new heading with the version and date, in the same pull request that sets the version.

## Unreleased

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
  role script; after a `trialbox update` run it once by hand (runbook §5, "Secrets"), or a reveal under a grant
  or by an investigator is refused with "cannot be read".
- The acting person (T-715, D-483): the participant, visit-schedule, SAE-rule, contact-rule, deviation and sponsor
  routes of the orchestrator take the person from a signed claim for that action, study and request, never from the
  request body; their records name `console:<username>`. The other changing routes count unsigned calls.
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

## 1.0.0

The first numbered version: the pilot appliance as built through plan v6 waves P and 1 (no site has installed it from
a signed bundle yet).
