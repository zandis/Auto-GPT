# Known image findings

Dated 2026-11-10. Source: the image gates of CI run 42735233384 (PR #61, head eb9f3b2), Trivy 0.75.0 with the DB of
2026-11-09. Counts are fixable CRITICAL/HIGH findings per image and platform.

Since T-110b (D-340, ENG-007) the image vulnerability gate **blocks for every image a bundle can carry**. Report
mode is left only for the two test-only mail servers of `deploy/docker-compose.test.yml`, which no bundle carries
(`tools/make_bundle.sh` takes the box's compose file only, OPS-017; and it refuses any image with a report-mode finding).
The open findings of the HAPI FHIR and vLLM images are no longer waved through as a class: each one is a dated entry of
`deploy/supply-chain-allowlist.yaml`, scoped to that image (`image:`), with `review_by: 2026-12-10`. A new finding in
either image fails the gate (one exception, D-622: one dated entry accepts every finding of the kernel headers package
`linux-libc-dev` in the pinned vLLM image); on 2026-12-10 the entries lapse and the gate fails until each image has moved or each entry
is reviewed again. The postgres row moved to our own `trialbox-postgres` image (T-104, built on `postgres:16-trixie`),
which the gates now scan and block on; its base's findings are dated entries the same way. The licence gate, `make lock-check`, `make allowlist-check` and `make pip-audit`
block as before. The list of images in report mode is `VULN_REPORT_ONLY` in `tools/supply_chain/release.py`; a test
checks that each one has a row here.

Owner of every row: security owner (to assign). Target date of every row: 2026-12-10.

| Image | Platforms | Findings | Main packages | Gate | Planned fix |
| --- | --- | --- | --- | --- | --- |
| axllent/mailpit | amd64, arm64 | 1 | golang.org/x/crypto v0.58.0 (GO-2026-5932) in the Mailpit binary; seen by the image gates of PR #150 on 2026-11-11 | report (test only, never in a bundle) | move to the next Mailpit release built with the fixed x/crypto (digest-pinned in `deploy/images.lock`) |
| greenmail/standalone | amd64, arm64 | 16 each | jackson-databind, jackson-core, openssl/libssl3, apt, gpgv | report (test only, never in a bundle) | move to a patched GreenMail tag (digest-pinned) |
| vllm/vllm-openai | amd64, arm64 | 29 each | pyasn1, openssl/libssl3t64, certifi, msgpack, urllib3, setuptools, gnupg, apt, brotli, uv | block; 29 dated per-image entries, and since D-622 one dated entry for every finding of its kernel headers package `linux-libc-dev` (build-time files; the owner's ruling of 2026-11-12) | move to a patched vLLM release tag (digest-pinned); our own image without the headers after go-live |
| trialbox-postgres (base postgres:16-trixie) | amd64, arm64 | 29 each | Go stdlib 1.24.6 and golang.org/x/sys in gosu, zlib1g | block; 29 dated per-image entries | move the base digest (deploy/images.lock and db.Dockerfile together) |
| hapiproject/hapi | amd64, arm64 | 23 each | libexpat1, zlib1g, jackson-core, jackson-databind, guava, spring-webmvc, ca-certificates | block; 23 dated per-image entries | move to a patched HAPI FHIR tag (digest-pinned) |
| caddy | amd64, arm64 | 3 each | golang.org/x/crypto (GO-2026-5932), golang.org/x/net (CVE-2026-78661), Go stdlib 1.27.3 (CVE-2026-97054) in the Caddy binary; first gated on 2026-11-12 (D-574) | block; 3 dated per-image entries (the owner's ruling of 2026-11-12) | move to the next Caddy image (digest-pinned); build it ourselves if upstream is silent on 2026-12-10 |
| authelia/authelia | amd64, arm64 | 8 each | Go stdlib 1.27.1, golang.org/x/net, golang.org/x/crypto in the Authelia binary; no package database in the image; first gated on 2026-11-12 (D-574) | block; 7 dated per-image entries, each with why it is not reachable on a box, and one `os_packages_unreadable` entry; **CVE-2026-111943 (crypto/x509) has no entry and fails the gate: with the owner** | move to the next Authelia image (digest-pinned); build it ourselves if upstream is silent on 2026-12-10 |

When a row is fixed, remove the image's entries from the allow-list (or the image from `VULN_REPORT_ONLY`) and its row
from this table in the same pull request.

## Fixed rows

| Image | Fixed by | What changed | Evidence |
| --- | --- | --- | --- |
| trialbox-jvm | T-672 (PR #78) | CQL translator jars (`services/criteria_compiler/compile_cql/translator/pom.xml`): HL7 FHIR core 6.9.12, jackson 2.21.8, guava 33.7.2, commons-beanutils 1.11.0, httpcore5 5.4.4, ucum 1.0.10, opentelemetry 1.68.0, commons-compress 1.28.0, junit excluded; JRE `eclipse-temurin:21.0.13_9-jre` by digest | OSV on the resolved classpath (102 jars): 0 findings on 2026-11-10; the Trivy gate blocks for this image |
| trialbox-demo | T-672 (PR #78) | the same translator jars | the Trivy gate blocks for this image |
| mailhog/mailhog | T-673 (D-348) | MailHog (amd64 only, abandoned since 2020) replaced in the test profile by `axllent/mailpit:v1.33.1` by digest (amd64 and arm64), pinned in `deploy/images.lock` | MailHog's 1,590 findings are gone; Mailpit has one (row above, report mode) |
