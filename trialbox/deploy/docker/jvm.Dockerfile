# syntax=docker/dockerfile:1.7
# trialbox-jvm: trialbox-py + JRE 21 + HL7 validator + cql-to-elm 5.4.0 + offline FHIR package cache.
# Used by criteria-compiler (CQL translation), adapter (validator sample) and orchestrator (TWPAS validation).
# Prerequisite: tools/fetch_jvm_deps.sh (fills .cache/jvm in the build context). Multi-arch (amd64/arm64).
ARG BASE_IMAGE=trialbox-py:1.0.0
# Temurin 21.0.13+9 JRE (the October 2026 CPU), the Java line CI tests with (T-672, DEP-015). Tag 21.0.13_9-jre = 21-jre
# on 2026-11-10; multi-arch index digest (amd64, arm64), image created 2026-10-29. Only /opt/java/openjdk is copied.
ARG JRE_IMAGE=eclipse-temurin:21.0.13_9-jre@sha256:0b99b3376fbb50dbf9c0af8535fdd5b8eb0d3fdfc8b1e4967f383b6919f6901a
# both bases are pinned through their ARG (a digest, or the locally built trialbox-py tag): DL3006 cannot see it
# hadolint ignore=DL3006
FROM ${JRE_IMAGE} AS jre
# hadolint ignore=DL3006
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
