# Known image findings (report mode)

Dated 2026-11-10. Source: the image gates of CI run 42735233384 (PR #61, head eb9f3b2), Trivy 0.75.0 with the DB of
2026-11-09. Counts are fixable CRITICAL/HIGH findings per image and platform.

The image vulnerability gate is in **report mode** for the images below until the follow-up lands (owner decision
of 2026-11-10, D-186). Their fixable CRITICAL/HIGH findings are listed in the CI job summary and do not fail a pull
request. trialbox-py's vulnerability gate, the licence gate, `make lock-check`, `make allowlist-check` and
`make pip-audit` still block. A bundle never carries an image that passed only in report mode
(`tools/make_bundle.sh --gates`). The list of images in report mode is `VULN_REPORT_ONLY` in
`tools/supply_chain/release.py`; a test checks that each one has a row here.

Owner of every row: security owner (to assign). Target date of every row: 2026-12-10.

| Image | Platforms | Findings | Main packages | Planned fix |
| --- | --- | --- | --- | --- |
| trialbox-jvm | amd64, arm64 | 32 each | jackson-databind, jackson-core, HL7 FHIR core 6.9.4.1 (r5, r4, r4b, dstu3, dstu2, convertors, utilities), commons-beanutils, guava, httpcore5, ucum | bump the HL7 validator and cql-to-elm jars (`tools/fetch_jvm_deps.sh`), rerun the CQL and validator tests |
| trialbox-demo | amd64, arm64 | 32 each | the same cql-to-elm and HL7 jars as trialbox-jvm | the same jar bump |
| mailhog/mailhog | amd64 (no arm64 image) | 1,590 | Go stdlib 1.14.7, busybox, ssl_client, libcrypto1.1, libssl1.1, apk-tools | replace MailHog with Mailpit in the test profile |
| vllm/vllm-openai | amd64, arm64 | 29 each | pyasn1, openssl/libssl3t64, certifi, msgpack, urllib3, setuptools, gnupg, apt, brotli, uv | move to a patched vLLM release tag (digest-pinned), or a dated exception |
| postgres | amd64, arm64 | 30 each | Go stdlib 1.24.6 (gosu), musl, zlib, golang.org/x/sys | move to the patched postgres:16-alpine digest |
| hapiproject/hapi | amd64, arm64 | 24 each | libexpat1, zlib1g, jackson-core, jackson-databind, guava, spring-webmvc, ca-certificates | move to a patched HAPI FHIR tag (digest-pinned), or a dated exception |
| greenmail/standalone | amd64, arm64 | 16 each | jackson-databind, jackson-core, openssl/libssl3, apt, gpgv | move to a patched GreenMail tag (digest-pinned), or a dated exception |

When a row is fixed, remove the image from `VULN_REPORT_ONLY` and from this table in the same pull request. When the
table is empty, report mode ends and the CI step drops `--vuln-mode report`.
