#!/usr/bin/env bash
# Fetch JVM-side dependencies into .cache/jvm/ (vendor build step; the appliance itself never downloads):
#   - HL7 FHIR validator CLI (pinned version) for adapter sampling and TWPAS bundle validation
#   - cql-to-elm 5.4.0 CLI + dependencies (criteria-compiler)
#   - offline FHIR NPM package cache (R4 core, terminology, extensions, TW Core, TWPAS)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/.cache/jvm}"
VALIDATOR_VERSION="${VALIDATOR_VERSION:-6.10.4}"
PY="${PY:-$ROOT/.venv/bin/python}"
mkdir -p "$OUT/cql-translator/lib" "$OUT/fhir-home/.fhir/packages"
if [ ! -s "$OUT/validator_cli.jar" ]; then
  curl -fsSL -o "$OUT/validator_cli.jar.tmp" \
    "https://github.com/hapifhir/org.hl7.fhir.core/releases/download/${VALIDATOR_VERSION}/validator_cli.jar"
  mv "$OUT/validator_cli.jar.tmp" "$OUT/validator_cli.jar"
fi
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
