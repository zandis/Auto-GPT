# RUNBOOK §12 part: the TLS check per release

**Reader:** the integrator, at each release, on the rehearsal or stub box; hospital IT for a site box's address.

*Plan 10 row 10G-48 (review 21, OT-12), D-1328; card H-48 (finding H10G48-02) for the one relaxation. The policy is `deploy/security/tls-policy.json`; the judge is
`tools/tls_policy.py`.*

What is checked: the TLS the box serves on 443 (Caddy, §12) and, on a two-device box, the link's port (§8), against
one policy: TLS 1.2 or 1.3 on 443 and TLS 1.3 only on the link; AEAD ciphers with forward secrecy only (no CBC, so no
CBC-SHA1, no RC4, 3DES, NULL or export suite); RSA keys of 2048 bits or more, EC keys of 256 or more, no SHA-1 or MD5
signature, no expired certificate; HSTS of at least one year on 443; a client certificate required on the link; no
finding testssl.sh rates HIGH or CRITICAL.

**Without a box (every pull request).** The shipped Caddyfile is held to the same policy by the unit test
`tests/unit/test_tls_policy_judge.py`, which also shows that a Caddyfile weakened one way (TLS 1.0 or 1.1 allowed, a
CBC suite, HSTS removed or shortened, a site without the TLS snippet, plain HTTP off the loopback) fails. The one
relaxation, `TB_TLS_OLD_CLIENTS` (below), is held by `tests/unit/test_tls_old_clients_setting.py`. By hand, from
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

   A box that serves an old client (`TB_TLS_OLD_CLIENTS=cbc` in its `deploy/.env`, below) is judged with that value
   given, `--old-clients cbc` after `--target box`. When it meets the policy so relaxed the judge prints one line,
   `EXCEPTION relaxed by setting TB_TLS_OLD_CLIENTS=cbc: ...`, and exits 3: that line, not `PASS`, is the release's TLS
   line for that box, so the record shows the exception. A CBC suite on a box judged without the value fails as
   before, and any other weakening fails with the value given too (exit 1). Another value is refused (exit 2); the
   link is never relaxed. The Caddyfile check takes the same option.

**A hospital's old client (the integrator's ruling of 2026-11-19).** The strict policy stands for what the box
serves, and the default stays strict; since the box takes a hospital as it is, this is what an old client meets. A
browser or other client that can do only TLS 1.0 or 1.1, or only CBC suites, or only static-RSA key exchange, gets a
handshake failure on the box's 443: the box offers TLS 1.2 and 1.3 with AEAD suites and an ephemeral key exchange
only, so client and box agree on nothing, the connection closes before any page is sent, and the browser shows its
own "cannot connect securely" error. The repository's documents state no list of supported browsers or operating
systems, so this page names none.

**The one setting that relaxes it (H-48, D-1328 amended 2026-11-19).** `TB_TLS_OLD_CLIENTS` in `deploy/.env`
(`deploy/identity/identity.env.example`) takes two values:

- `off`, the default (and what an unset or empty value means): the policy above; the only setting the TLS check
  passes.
- `cbc`: 443 also serves the four TLS 1.2 suites with ECDHE key exchange and AES-CBC-SHA
  (`TLS_ECDHE_ECDSA_WITH_AES_128_CBC_SHA`, `TLS_ECDHE_RSA_WITH_AES_128_CBC_SHA`, and the two AES-256 ones). An old
  client that has TLS 1.2 but no AEAD suite then connects; a modern browser still chooses an AEAD suite or TLS 1.3, so
  it sees no change. Nothing else is relaxed: a client that can do only TLS 1.0 or 1.1, or only static-RSA key
  exchange, or only 3DES, RC4, export or NULL suites, still gets the handshake failure above. If a hospital's client
  needs one of those, that is a new decision, not this setting.

To turn it on, hospital IT or the integrator sets `TB_TLS_OLD_CLIENTS=cbc` in `deploy/.env` and runs
`deploy/install.sh` again. The installer refuses any other value before Caddy reads it; Caddy then serves the
`suites_<mode>_cbc` snippet of `deploy/identity/Caddyfile`; the switch is written to the box's audit chain as
`update.tls_relaxed` (with the value and the one before), and `trialbox doctor` shows a `tls_old_clients` WARN line on
every run while it is on. If the audit event cannot be sent the install ends with a FAIL line and the event is sent
by the next install. To turn it off, set `TB_TLS_OLD_CLIENTS=off` (or remove the line) and run `deploy/install.sh`
again: the box is strict again and the switch is audited as `update.tls_strict`. Turn it off when the old client is
replaced.

The value is the one compose gives Caddy: a `TB_TLS_OLD_CLIENTS` exported in the shell wins over `deploy/.env`, and
quotes around it are dropped; the installer reads it the same way. `deploy/site/tls-old-clients.audited` holds the
value the installer last audited. A value that differs from it (switched by a plain `docker compose up -d`, by an
exported variable, or after a restore, which removes the file because the restored audit chain may lack the event)
makes `trialbox doctor` FAIL its `tls_old_clients` line, and `tools/apply_update.sh` refuses the update before
anything changes; running `deploy/install.sh` sends the event and clears both. Before H-48 the only way was a hand edit of the Caddyfile, which the policy check fails by design; that is
still true of any edit other than this setting.

**Not yet seen.** No scan has been run against a box. The first run must show, on 443: TLS1 and TLS1_1 "not
offered", TLS1_2 and TLS1_3 offered, only GCM or ChaCha20 suites with ECDHE, HSTS of 31536000 seconds; on the link:
TLS1_3 only and `clientAuth` "required". The judge reads the ids testssl.sh 3.2 writes as this page names them
(`TLS1_1`, `cipherlist_OBSOLETED`, `cert_keySize`, `HSTS_time`, `clientAuth` and the per-cipher `cipher-tls1_2_…`
lines); with `TB_TLS_OLD_CLIENTS=cbc` the first run must also show `cipherlist_OBSOLETED` offered with only the four
ECDHE AES-CBC-SHA suites among the TLS 1.2 ciphers, and the judge's `EXCEPTION` line. If the first real result names
an id differently, the judge reports it missing and the fixtures in
`tests/fixtures/tls/` are corrected from that result.
