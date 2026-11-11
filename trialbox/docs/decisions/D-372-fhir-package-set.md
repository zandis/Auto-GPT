# D-372 The FHIR package set: fetched by the settings version, TWPAS 1.2.5, extensions and terminology aligned

- **Task:** T-676, FHIR package set (`docs/plan/28-master-plan-v6.md` §6.2.5, wave 2 item (j) of T-DEP-5)
- **PR:** this branch (`agent/T-676-fhir-packages`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** DEP-016 (all but CGMH's answer, see Open)
- **Supersedes:** D-63 (TWPAS IG and package set) in `docs/DECISIONS.md`. The frozen log is not edited; this file
  is the rule from now on. D-64 (partial code systems relabelled `fragment`) stays.

## Context

D-63 validated TWPAS bundles against `tw.gov.mohw.nhi.pas#1.2.0` because the npm mirror the fetch used had no other
version. Settings said `1.2.5`, the cache held `1.2.0`, and `twpas.ig_spec` fell back to `1.2.0` without a word.
The deep review (DEP-016) found D-63's premise out of date: packages.fhir.org has TWPAS 1.2.5, 1.2.6, 1.2.7 and
1.3.0. The extensions were a ballot (`5.3.0-ballot-tc1`) although 5.4.0 is released; the terminology was 7.0.1
while 7.5.0 is current.

Which TWPAS version the NHI takes for 2027 submissions is a question for the CGMH NHI contact. That answer is not
available. This decision picks a version now and makes it one setting, so the answer changes one value.

## Decision

1. **The registry.** `tools/fetch_fhir_packages.py` fetches from `https://packages.fhir.org` (its listings have the
   npm shape, so the code is the same). `TB_NPM_REGISTRY` or `--registry` still names a mirror. The pins in
   `tools/fhir-packages.sha256` are of the packages.fhir.org tarballs; a mirror's tarballs have other sums and are
   refused.
2. **TWPAS by the settings version.** `deploy/settings.example.yaml` `profiles.twpas_version` is the one place
   that names the version. `fetch_fhir_packages.py --twpas-settings <file>` reads it and installs the IG with the
   packages that version needs (`TWPAS_SETS`). `tools/fetch_jvm_deps.sh` calls it with the example settings, or with
   `TB_SETTINGS_FILE`. A version with no set in `TWPAS_SETS` stops the fetch. So the version in settings is the
   version in the cache, and `twpas.ig_spec` finds it there. The wizard default and the scenario fallback
   (`DEFAULT_IG`) name the same version. A unit test holds all of these equal.
3. **TWPAS 1.2.5.** This is the version the specification and the settings already named. It is public on
   packages.fhir.org, and the offline box can validate against it: its NHI code systems are inside the package. Its
   set is TW Core 1.0.0 served as the declared `0.3.2` (as in D-63), and a subset package
   `hl7.fhir.us.davinci-pas#2.2.1` that holds only the `diagnosisRecordedDate` extension definition. The emr package
   is no longer needed. The bundle builder changes in one place: the ECOG assessment is `valueQuantity` (invariant
   `pat-ast-value` since 1.2.5), not `valueInteger`.
4. **Why not 1.3.0 now.** 1.3.0 is the latest version. It moves the NHI code systems (`nhi-apply-type`,
   `nhi-supporting-info-type`, `nhi-tmhb-type`, `nhi-medication`, `organization-identifier-tw` and others) to the NHI
   terminology server (`https://fhir.nhi.gov.tw/nhi_tsfhir/`). No published package holds them. Its
   MedicationRequest requires a `nhi-medication` coding slice whose only discriminator is a required binding to that
   server's value set. With `-tx n/a` and no network, the validator cannot match the slice, so every 1.3.0 bundle
   fails offline. The other 1.3.0 changes (code system URLs, the slices for weight and height) are mechanical. If
   CGMH answers 1.3.0, the box needs an offline copy of the NHI terminology value sets first.
5. **One terminology, one extensions.** The cache holds `hl7.terminology(.r4)` 7.5.0 and
   `hl7.fhir.uv.extensions(.r4)` 5.4.0 (released, not a ballot; 5.4.0 declares terminology 7.5.0). Older versions
   that packages declare are aliases of the same content: terminology 7.4.0, 7.3.0, 7.0.1, 7.0.0, 6.5.0, 6.2.0 and
   6.1.0; extensions 5.3.0, 5.2.0 and 5.1.0. The plan row asked for "the terminology version TW Core 1.0.0 declares"
   (7.0.0). That would put two terminology releases in one cache, because TWPAS and the extensions declare newer
   ones. 7.0.0 is served as an alias instead.

## Checked

With the pinned validator 6.10.4 and the cache built by this fetch, the synthetic bundle of
`tests/unit/test_twpas_unit.py` has one remaining validator error against 1.2.5: the route coding. Everything else
passes. D-342 (T-617b) changed the route from SNOMED CT to TW Core `medication-path-tw#PO`. TWPAS's required value
set `medication-path-sct-tw` has no oral code outside SNOMED CT, and the same error occurs against 1.2.0 on master.
With a SNOMED CT oral route (used for the check only, not committed), the bundle has 0 errors.

## Consequences

- `make jvm-deps` fetches about 30 MB from packages.fhir.org. The CI cache key covers the script and the pins, so
  CI fetches the new set once.
- To move TWPAS: add the version's set to `TWPAS_SETS`, its pins to `fhir-packages.sha256`, and change
  `profiles.twpas_version` (both settings examples and the wizard), in one pull request.

## Open

- **CGMH's answer.** Which TWPAS version the NHI accepts for the 2027 submissions (likely 1.3.0). Until then 1.2.5
  stands.
- **The route coding and D-342.** The real validator fails TWPAS bundles on the route until D-342 and the IG's
  required binding are reconciled: a SNOMED CT code for the route, or an NHI or TW Core code the IG accepts. CI's
  unit job runs without the validator jar, so it does not show this. The nightly compose job does.
