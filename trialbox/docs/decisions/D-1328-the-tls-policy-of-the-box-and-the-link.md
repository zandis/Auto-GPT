# D-1328 The TLS policy of the box's 443 and the two-device link (10G-48)

- **Task:** lane H, plan 10 row 10G-48 (review 21, item OT-12): testssl.sh against the box's 443 and the two-device
  link per release, with a policy file. · **Date:** 2026-11-19
- **Decision:**
  - The policy is one file, `deploy/security/tls-policy.json`; `tools/tls_policy.py` judges a testssl.sh JSON result
    against it (`judge --target box|link`, exit 1 with one line per failing id) and holds the shipped Caddyfile to it
    (`caddyfile`).
  - **Protocols.** The box's 443: TLS 1.2 and 1.3 only, as the Caddyfile sets and section 2 of the security document
    states (`docs/security/02-network.md`, "TLS 1.2 or 1.3"; review 21 OT-12). The link: TLS 1.3 only, as
    `tools/two_device.py` sets (`minimum_version`). SSLv2, SSLv3, TLS 1.0 and 1.1 are never offered.
  - **Ciphers.** AEAD suites (AES-GCM, ChaCha20-Poly1305, AES-CCM) with an ephemeral key exchange only. This is
    stricter than review 21's "no CBC-SHA1": every CBC suite, static RSA key exchange, RC4, 3DES, NULL, anonymous and
    export suites fail, and testssl.sh's categories `cipherlist_NULL`, `cipherlist_aNULL`, `cipherlist_EXPORT`,
    `cipherlist_LOW`, `cipherlist_3DES_IDEA` and `cipherlist_OBSOLETED` must read "not offered". A `ciphers` line in
    the Caddyfile is held to the same rule.
  - **Certificate.** RSA keys of at least 2048 bits, EC keys of at least 256; no MD5 or SHA-1 signature; an expired
    certificate fails. The 30-day warning stays with `console.cli check-tls` (`services/console/identity.py`), which
    also checks the name and the key; Caddy's internal certificates are short-lived and renewed by Caddy, so the scan
    does not fail on a near end date.
  - **HSTS.** On 443 a `Strict-Transport-Security` max-age of at least 31536000 seconds (the Caddyfile's one year,
    D-193). `includeSubDomains` is not asked: it stays open under D-447 (ASVS 14.4.5 "partly").
  - **Client certificate.** Required on the link (mutual TLS, `ssl.CERT_REQUIRED`); not asked on 443.
  - **Severity.** Any testssl.sh finding rated HIGH, CRITICAL or FATAL fails, whatever its id.
  - **Missing is failing.** An id the policy needs that a result does not hold fails as missing.
  - **The run.** testssl.sh 3.2 from the test laptop per release (RUNBOOK §12 part, the TLS check per release);
    never shipped, kept or fetched by the repository (review 21, OT-D1). Results under `build/security/<release>/`.
  - A plain-HTTP site in the Caddyfile is allowed only bound to the loopback (the health site, D-360).
- **Held by:** `tests/unit/test_tls_policy_judge.py`.
