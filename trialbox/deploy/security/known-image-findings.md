# Known image findings

Dated 2026-11-10. Source: the image gates of CI run 42735233384 (PR #61, head eb9f3b2), Trivy 0.75.0 with the DB of
2026-11-09. Counts are fixable CRITICAL/HIGH findings per image and platform.

Since T-110b (D-340, ENG-007) the image vulnerability gate **blocks for every image a bundle can carry**. Report
mode is left only for the two test-only mail servers of `deploy/docker-compose.test.yml`, which no bundle carries
(`tools/make_bundle.sh` takes the box's compose file only, OPS-017; and it refuses any image with a report-mode finding).
The open findings of the HAPI FHIR and vLLM images are no longer waved through as a class: each one is a dated entry of
`deploy/supply-chain-allowlist.yaml`, scoped to that image (`image:`), with `review_by: 2026-12-10`. A new finding in
either image fails the gate; on 2026-12-10 the entries lapse and the gate fails until each image has moved or each entry
is reviewed again. The postgres row moved to our own `trialbox-postgres` image (T-104, built on `postgres:16-trixie`),
which the gates now scan and block on. The licence gate, `make lock-check`, `make allowlist-check` and `make pip-audit`
block as before. The list of images in report mode is `VULN_REPORT_ONLY` in `tools/supply_chain/release.py`; a test
checks that each one has a row here.

Owner of every row: security owner (to assign). Target date of every row: 2026-12-10.

| Image | Platforms | Findings | Main packages | Gate | Planned fix |
| --- | --- | --- | --- | --- | --- |
| mailhog/mailhog | amd64 (no arm64 image) | 1,590 | Go stdlib 1.14.7, busybox, ssl_client, libcrypto1.1, libssl1.1, apk-tools | report (test only, never in a bundle) | replace MailHog with Mailpit in the test profile |
| greenmail/standalone | amd64, arm64 | 16 each | jackson-databind, jackson-core, openssl/libssl3, apt, gpgv | report (test only, never in a bundle) | move to a patched GreenMail tag (digest-pinned) |
| vllm/vllm-openai | amd64, arm64 | 29 each | pyasn1, openssl/libssl3t64, certifi, msgpack, urllib3, setuptools, gnupg, apt, brotli, uv | block; 29 dated per-image entries | move to a patched vLLM release tag (digest-pinned) |
| hapiproject/hapi | amd64, arm64 | 23 each | libexpat1, zlib1g, jackson-core, jackson-databind, guava, spring-webmvc, ca-certificates | block; 23 dated per-image entries | move to a patched HAPI FHIR tag (digest-pinned) |

When a row is fixed, remove the image's entries from the allow-list (or the image from `VULN_REPORT_ONLY`) and its row
from this table in the same pull request.

## Fixed rows

| Image | Fixed by | What changed | Evidence |
| --- | --- | --- | --- |
| trialbox-jvm | T-672 (PR #78) | CQL translator jars (`services/criteria_compiler/compile_cql/translator/pom.xml`): HL7 FHIR core 6.9.12, jackson 2.21.8, guava 33.7.2, commons-beanutils 1.11.0, httpcore5 5.4.4, ucum 1.0.10, opentelemetry 1.68.0, commons-compress 1.28.0, junit excluded; JRE `eclipse-temurin:21.0.13_9-jre` by digest | OSV on the resolved classpath (102 jars): 0 findings on 2026-11-10; the Trivy gate blocks for this image |
| trialbox-demo | T-672 (PR #78) | the same translator jars | the Trivy gate blocks for this image |
