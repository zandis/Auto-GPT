#!/usr/bin/env bash
# Fetch JVM-side dependencies into .cache/jvm/ (vendor build step; the appliance itself never downloads):
#   - HL7 FHIR validator CLI (pinned version) for adapter sampling and TWPAS bundle validation
#   - cql-to-elm 5.4.0 CLI + dependencies (criteria-compiler)
#   - offline FHIR NPM package cache (R4 core, terminology, extensions, TW Core, TWPAS at the settings version)
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
# The translator jars are checked against tools/jvm-deps.sha256 (ENG-013, T-110b): Maven fetches with strict checksums
# (-C: a jar that does not match the repository's sum fails), then every jar in the directory must have the pinned
# sha256, and no jar may be missing or extra. A cached directory is checked too, so a stale or tampered cache fails.
# After a pom change: UPDATE_LIB_SUMS=1 tools/fetch_jvm_deps.sh (on an empty lib directory) rewrites the list.
LIB_SUMS="${JVM_LIB_SUMS:-$ROOT/tools/jvm-deps.sha256}"

# check_sha256 FILE EXPECTED: exit 1 with a plain message when the file's sha256 is not the expected one
check_sha256() {
  local got
  got="$(sha256sum "$1" | cut -d' ' -f1)"
  if [ "$got" != "$2" ]; then
    echo "fetch_jvm_deps: $(basename "$1"): sha256 $got is not the pinned $2; refusing it" >&2
    return 1
  fi
}

# check_lib DIR: every jar in DIR has the sha256 tools/jvm-deps.sha256 pins, and the two lists name the same jars
check_lib() {
  local want got
  want="$(grep -v '^#' "$LIB_SUMS" | sed '/^$/d' | LC_ALL=C sort -k2)"
  got="$(cd "$1" && sha256sum -- *.jar 2>/dev/null | LC_ALL=C sort -k2)"
  if [ "$want" != "$got" ]; then
    echo "fetch_jvm_deps: the translator jars in $1 are not the ones $(basename "$LIB_SUMS") pins; refusing them" >&2
    diff <(printf '%s\n' "$want") <(printf '%s\n' "$got") | grep '^[<>]' | head -20 >&2 || true
    echo "fetch_jvm_deps: a stale cache: delete $1 and run again; a pom change: UPDATE_LIB_SUMS=1" >&2
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
DEP_PLUGIN="3.7.0"  # maven-dependency-plugin (D-891)
if [ -z "$(ls -A "$OUT/cql-translator/lib")" ]; then
  # D-885: the build host's needs, said before Maven is called (lane G's VM had neither)
  JDK_MAJOR="$(cat "$ROOT/.java-version" 2>/dev/null || echo 21)"
  NEEDS="install Maven and a JDK $JDK_MAJOR (Ubuntu: apt-get install -y maven openjdk-$JDK_MAJOR-jdk-headless), or let deploy/poc.sh fetch in its builder container"
  command -v mvn >/dev/null 2>&1 || { echo "fetch_jvm_deps: no Maven (mvn) on PATH to fetch the CQL translator jars: $NEEDS" >&2; exit 1; }
  mvn -v >/dev/null 2>&1 || { echo "fetch_jvm_deps: mvn -v failed (no JDK, or JAVA_HOME wrong): $NEEDS" >&2; exit 1; }
  # D-891: the plugin named with its version, so Maven never asks Central which version is the newest (the box
  # rehearsal's CI stopped once on that lookup, "Error resolving version for plugin")
  mvn -q -B -C -f "$ROOT/services/criteria_compiler/compile_cql/translator/pom.xml" \
    "org.apache.maven.plugins:maven-dependency-plugin:$DEP_PLUGIN:copy-dependencies" \
    -DoutputDirectory="$OUT/cql-translator/lib"
  if [ "${UPDATE_LIB_SUMS:-0}" = 1 ]; then
    { grep '^#' "$LIB_SUMS"; (cd "$OUT/cql-translator/lib" && sha256sum -- *.jar | LC_ALL=C sort -k2); } > "$LIB_SUMS.tmp"
    mv "$LIB_SUMS.tmp" "$LIB_SUMS"
    echo "fetch_jvm_deps: wrote $LIB_SUMS"
  fi
fi
check_lib "$OUT/cql-translator/lib" || exit 1
"$PY" "$ROOT/tools/fetch_fhir_packages.py" --cache "$OUT/fhir-home/.fhir/packages"
# The TWPAS IG at the version the settings name (profiles.twpas_version, D-372) and the packages it needs; a version
# without a package set in tools/fetch_fhir_packages.py stops the fetch. TB_SETTINGS_FILE names a site's settings.
"$PY" "$ROOT/tools/fetch_fhir_packages.py" --cache "$OUT/fhir-home/.fhir/packages" \
  --twpas-settings "${TB_SETTINGS_FILE:-$ROOT/deploy/settings.example.yaml}"
echo "JVM dependencies ready in $OUT"
