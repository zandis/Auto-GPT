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
  - **An old client** (TLS 1.0/1.1 only, CBC only or static RSA only) gets a handshake failure on 443; the policy stays
    strict (the integrator's ruling, 2026-11-19); no setting relaxes it today (finding H10G48-02, RUNBOOK §12 part).
  - **Amended 2026-11-19 (card H-48, finding H10G48-02; the integrator's ruling of 05:52 UTC: "one documented key,
    off by default, audited when switched on, shown on the administrator's first page while it is on").** One
    setting relaxes the box's 443, `TB_TLS_OLD_CLIENTS`: `off` (the default, also when unset or empty) is the policy
    above and the only pass; `cbc` also serves the four TLS 1.2 ECDHE AES-CBC-SHA suites, for an old client with TLS
    1.2 but no AEAD suite, the smallest relaxation that admits one (forward secrecy kept). It never re-enables TLS
    1.0/1.1, SSLv3, static RSA, 3DES, RC4, export or NULL, and the two-device link is never relaxed. The policy file
    names it (`relaxation`); `tools/tls_policy.py` given `--old-clients cbc` reports a result or Caddyfile that meets
    the policy so relaxed as the named exception (`EXCEPTION relaxed by setting TB_TLS_OLD_CLIENTS=cbc`, exit 3),
    never as a pass, and still fails any other weakening (exit 1); another value is refused (exit 2).
    `deploy/install.sh` refuses another value, and audits a switch as `update.tls_relaxed` or `update.tls_strict`
    from the orchestrator's container (as `update.applied`); `trialbox doctor` shows a `tls_old_clients` WARN line
    while it is on; the console receives the value (`deploy/docker-compose.identity.yml`) for the administrator's
    first page.
- **Held by:** `tests/unit/test_tls_policy_judge.py`; the relaxation by `tests/unit/test_tls_old_clients_setting.py`.
