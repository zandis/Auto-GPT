# RUNBOOK §12 part: the TLS check per release

**Reader:** the integrator, at each release, on the rehearsal or stub box; hospital IT for a site box's address.

*Plan 10 row 10G-48 (review 21, OT-12), D-1328. The policy is `deploy/security/tls-policy.json`; the judge is
`tools/tls_policy.py`.*

What is checked: the TLS the box serves on 443 (Caddy, §12) and, on a two-device box, the link's port (§8), against
one policy: TLS 1.2 or 1.3 on 443 and TLS 1.3 only on the link; AEAD ciphers with forward secrecy only (no CBC, so no
CBC-SHA1, no RC4, 3DES, NULL or export suite); RSA keys of 2048 bits or more, EC keys of 256 or more, no SHA-1 or MD5
signature, no expired certificate; HSTS of at least one year on 443; a client certificate required on the link; no
finding testssl.sh rates HIGH or CRITICAL.

**Without a box (every pull request).** The shipped Caddyfile is held to the same policy by the unit test
`tests/unit/test_tls_policy_judge.py`, which also shows that a Caddyfile weakened one way (TLS 1.0 or 1.1 allowed, a
CBC suite, HSTS removed or shortened, a site without the TLS snippet, plain HTTP off the loopback) fails. By hand, from
`trialbox/`: `python -m tools.tls_policy caddyfile`.

**With the box (each release).** testssl.sh (GPL-2.0) runs on the test laptop. It is never shipped with the box,
never copied into this repository and never fetched by a tool here (review 21, OT-D1). Use version 3.2; the options
below are as that version names them. Results go to `build/security/<release>/` (git ignores `build/`), where the
per-release security record of card 10G-50 collects them.

1. The box's 443, with the root that signed its certificate (Caddy's internal root, or the hospital's CA chain) given
   to testssl.sh so the chain is judged against it:

   ```
   testssl.sh --quiet --color 0 --protocols --std --fs --server-defaults --headers --vulnerable --cipher-per-proto \
     --add-ca <root.pem> --jsonfile build/security/<release>/tls.json https://<TB_TLS_HOSTNAME>/
   ```

2. The two-device link, from the workstation, which holds its own certificate and key from the install ceremony
   (`deploy/secrets/link`): put the certificate and key in one temporary file readable by root only, run, then delete
   the file. Without the client certificate the link refuses the handshake; that refusal is expected.

   ```
   testssl.sh --quiet --color 0 --protocols --std --fs --server-defaults --vulnerable --cipher-per-proto \
     --mtls <workstation pem and key> --add-ca deploy/secrets/link/ca.pem \
     --jsonfile build/security/<release>/tls-link.json <spark link address>:8443
   ```

3. Judge each result on the laptop, from `trialbox/`:

   ```
   python -m tools.tls_policy judge --target box build/security/<release>/tls.json
   python -m tools.tls_policy judge --target link build/security/<release>/tls-link.json
   ```

   `PASS` (exit 0) is the release's TLS line. Otherwise each failing check is one `FAIL <id>: <why>` line (exit 1);
   an id the policy needs that the result does not hold fails as missing, so a scan run without the options above
   cannot pass. The release stops until the box is fixed or the policy is changed by a new decision.

**Not yet seen.** No scan has been run against a box. The first run must show, on 443: TLS1 and TLS1_1 "not
offered", TLS1_2 and TLS1_3 offered, only GCM or ChaCha20 suites with ECDHE, HSTS of 31536000 seconds; on the link:
TLS1_3 only and `clientAuth` "required". The judge reads the ids testssl.sh 3.2 writes as this page names them
(`TLS1_1`, `cipherlist_OBSOLETED`, `cert_keySize`, `HSTS_time`, `clientAuth` and the per-cipher `cipher-tls1_2_…`
lines); if the first real result names one differently, the judge reports it missing and the fixtures in
`tests/fixtures/tls/` are corrected from that result.
