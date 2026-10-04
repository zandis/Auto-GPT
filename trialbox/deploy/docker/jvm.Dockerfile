# syntax=docker/dockerfile:1.7
# trialbox-jvm: trialbox-py + JRE 17 + HL7 validator + cql-to-elm 5.4.0 + offline FHIR package cache.
# Used by criteria-compiler (CQL translation), adapter (validator sample) and orchestrator (TWPAS validation).
# Prerequisite: tools/fetch_jvm_deps.sh (fills .cache/jvm in the build context). Multi-arch (amd64/arm64).
ARG BASE_IMAGE=trialbox-py:1.0.0
ARG JRE_IMAGE=eclipse-temurin:17-jre@sha256:207ecae0b2b104dfc6dfa763d1e9cd2041cb344800a180e24cb1a28ed533ff90
FROM ${JRE_IMAGE} AS jre
FROM ${BASE_IMAGE}
USER root
COPY --from=jre /opt/java/openjdk /opt/java/openjdk
ENV JAVA_HOME=/opt/java/openjdk PATH=/opt/java/openjdk/bin:$PATH \
    TB_HL7_VALIDATOR_JAR=/opt/hl7/validator_cli.jar TB_FHIR_PACKAGE_HOME=/opt/hl7/home \
    TB_CQL_TRANSLATOR_LIB=/opt/cql-translator/lib
COPY .cache/jvm/validator_cli.jar /opt/hl7/validator_cli.jar
COPY --chown=tb:tb .cache/jvm/fhir-home /opt/hl7/home
COPY .cache/jvm/cql-translator/lib /opt/cql-translator/lib
USER tb
