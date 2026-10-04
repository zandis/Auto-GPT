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
"$PY" "$ROOT/tools/fetch_fhir_packages.py" --cache "$OUT/fhir-home/.fhir/packages" "tw.gov.mohw.nhi.pas#1.2.0"
echo "JVM dependencies ready in $OUT"
