# Changelog

What changed in each TrialBox release, newest first. The version is written in one place, `[project] version` in
`pyproject.toml`; `python -m tools.release version` prints it and `python -m tools.release tag` prints its tag
(`trialbox-v<version>`). Every signed bundle carries this file, `NOTICE` and `release.json` (T-110b, D-340), and the
console's about page shows the release a box runs.

A pull request that changes what a site receives adds a line under "Unreleased". A release moves those lines under a
new heading with the version and date, in the same pull request that sets the version.

## Unreleased

- The opt-out register (NEW-JRN-2, D-542): a pseudonym must be typed whole (32 characters) or the chart number
  used; the 8 characters a page shows are refused. After the save the page says whether a listed patient
  matched, or that nobody did.
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

## 1.0.0

The first numbered version: the pilot appliance as built through plan v6 waves P and 1 (no site has installed it from
a signed bundle yet).
