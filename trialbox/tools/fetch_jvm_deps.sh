#!/usr/bin/env bash
# Fetch JVM-side dependencies into .cache/jvm/ (vendor build step; the appliance itself never downloads):
#   - HL7 FHIR validator CLI (pinned version) for adapter sampling and TWPAS bundle validation
#   - cql-to-elm 5.4.0 CLI + dependencies (criteria-compiler)
#   - offline FHIR NPM package cache (R4 core, terminology, extensions, TW Core, TWPAS)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/.cache/jvm}"
# The validator jar is checked against a pinned sha256 (DEP-017): on download and again on every run for a cached
# copy, so a tampered or swapped jar fails the fetch. The sum is of the release asset of tag 6.10.4 of
# hapifhir/org.hl7.fhir.core (downloaded 2026-11-10). To move the version, change both lines together in one pull
# request; another version given in the environment needs its own VALIDATOR_SHA256.
PINNED_VALIDATOR_VERSION="6.10.4"
PINNED_VALIDATOR_SHA256="1106b9d58f9e363e47bea7c4fc065841e5fc91fe9d062775c3bfdd212bd653cc"
VALIDATOR_VERSION="${VALIDATOR_VERSION:-$PINNED_VALIDATOR_VERSION}"
if [ -z "${VALIDATOR_SHA256:-}" ]; then
  if [ "$VALIDATOR_VERSION" != "$PINNED_VALIDATOR_VERSION" ]; then
    echo "fetch_jvm_deps: no pinned sha256 for validator $VALIDATOR_VERSION; set VALIDATOR_SHA256" >&2
    exit 1
  fi
  VALIDATOR_SHA256="$PINNED_VALIDATOR_SHA256"
fi
PY="${PY:-$ROOT/.venv/bin/python}"

# check_sha256 FILE EXPECTED: exit 1 with a plain message when the file's sha256 is not the expected one
check_sha256() {
  local got
  got="$(sha256sum "$1" | cut -d' ' -f1)"
  if [ "$got" != "$2" ]; then
    echo "fetch_jvm_deps: $(basename "$1"): sha256 $got is not the pinned $2; refusing it" >&2
    return 1
  fi
}

mkdir -p "$OUT/cql-translator/lib" "$OUT/fhir-home/.fhir/packages"
if [ ! -s "$OUT/validator_cli.jar" ]; then
  curl -fsSL -o "$OUT/validator_cli.jar.tmp" \
    "https://github.com/hapifhir/org.hl7.fhir.core/releases/download/${VALIDATOR_VERSION}/validator_cli.jar"
  check_sha256 "$OUT/validator_cli.jar.tmp" "$VALIDATOR_SHA256" || { rm -f "$OUT/validator_cli.jar.tmp"; exit 1; }
  mv "$OUT/validator_cli.jar.tmp" "$OUT/validator_cli.jar"
fi
# a cached jar is checked too: delete it and run again to fetch a fresh copy
check_sha256 "$OUT/validator_cli.jar" "$VALIDATOR_SHA256" || exit 1
sha256sum "$OUT/validator_cli.jar" > "$OUT/validator_cli.jar.sha256"
if [ -z "$(ls -A "$OUT/cql-translator/lib")" ]; then
  mvn -q -B -f "$ROOT/services/criteria_compiler/compile_cql/translator/pom.xml" \
    dependency:copy-dependencies -DoutputDirectory="$OUT/cql-translator/lib"
fi
"$PY" "$ROOT/tools/fetch_fhir_packages.py" --cache "$OUT/fhir-home/.fhir/packages"
# TWPAS 1.2.0 (the only version on the npm mirror; settings default 1.2.5, DECISIONS D-63) and its dependencies
"$PY" "$ROOT/tools/fetch_fhir_packages.py" --cache "$OUT/fhir-home/.fhir/packages" "tw.gov.mohw.nhi.pas#1.2.0" \
  "tw.gov.mohw.emr#0.2.0" "tw.gov.mohw.twcore#1.0.0=0.3.2" "hl7.terminology.r4#7.0.1=6.2.0,6.5.0,7.0.0,6.1.0" \
  "hl7.fhir.uv.extensions.r4#5.3.0-ballot-tc1=5.2.0,5.1.0" \
  --subset "hl7.fhir.us.davinci-pas#2.2.0-ballot=2.1.0:StructureDefinition-extension-diagnosisRecordedDate.json"
echo "JVM dependencies ready in $OUT"
