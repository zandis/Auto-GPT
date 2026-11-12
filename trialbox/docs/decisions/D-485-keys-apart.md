# D-485 Keys apart, first part: the key that signs people is its own secret, not a function of the console's service token

- **Card:** T-717 (`docs/plan/31-master-plan-v6.1-addendum.md` §3.2, TB-PLAN-06.1; wave T, safety core)
- **PR:** this branch (`agent/T-717-keys-apart`); built on T-716's branch (PR #326), which is built on #317 and
  #312: it shows their commits until they merge
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI)
- **Builds on:** D-138 (one token per service), D-143 (the signed actor), D-437 (the secret layout), D-483 (actor
  assertion v3)
- **Closes:** proposal TR-5 of `docs/reviews/2026-11-12-architecture/trust.md`, its first clause (see "Not done")

## The problem

The console signs the person of a call with `HMAC(console token, "tb-actor-assertion/1")`. The console sends its
token on every call it makes, to the orchestrator and also to the mail gateway and the adapter. Whoever holds the
token can compute the key: a service that only *receives* the console's calls can name any person, with any role
and any grant, to the orchestrator.

## The decision

1. **The signing key is a secret of its own.** `trialbox secrets init` makes
   `deploy/secrets/services/actor-sign.key` (32 random bytes, hex, 0600) when the box has none, and writes the
   orchestrator's keys file (`secrets/services/actor/keys`) from it. The key is no function of any token.
2. **Who signs** (`tb_common.service_auth.signing_key`, used by the v2 `sign_actor` and by `actor_v3`):
   - `TB_ACTOR_SIGN_KEY_FILE` set: that key; a file that cannot be read or is not a key gives no key, and nothing
     is signed (fail closed, never a fall-back);
   - a box with a token registry (per-service tokens) and no such file: no key. Every service but the console is
     in this position: it signs nobody, with either format;
   - one shared token and no registry (tests, `make demo`, a box before per-service tokens): the key derived from
     that token, as before; every service holds that token there anyway;
   - no token at all (DEV, TEST): nothing is signed or verified.
3. **Who holds it.** The secrets overlay gives the file to the console alone, as a compose secret
   (`actor_sign_key`, `TB_ACTOR_SIGN_KEY_FILE=/run/secrets/tb_actor_sign_key`); the orchestrator alone mounts the
   keys file, as before. The Kubernetes form has the same split: Secret `trialbox-actor-sign` for the console,
   `trialbox-actor` for the orchestrator.
4. **Rotation.** The console's token and its signing key are two secrets: `secrets rotate --service console`
   leaves the key. `secrets rotate --service actor` (and a rotation of everything) makes a new key; the
   orchestrator's keys file lists the old and the new one while the console and the orchestrator restart, then
   the new one only.
5. **An updated box.** `trialbox update` makes the key for a box with per-service tokens that has none
   (`ensure_actor_sign_key`, beside the model key's step), because the overlay's compose secret needs its file;
   the orchestrator's keys file then holds the new key only, so an assertion under the token-derived key stops
   verifying when the containers are made again.
6. **The tests take the attacker's seat.** `tests/unit/test_actor_key_apart.py` holds the console's token and
   nothing else (what the mail gateway and the adapter receive on every console call), derives the old key and
   signs a person in both formats: neither verifies. `tests/service_tokens.per_service_tokens` (every PRODUCTION
   test of an orchestrator route) and the demo box (`tools/role_demo.orch_client`) run in the new configuration.

## Not done

- **The secrets volume is not split; the adapter can still open `edc_sign.key` and `audit_sign.key`** (review
  F8; the row's acceptance). The keys of the secrets folder are one set for the KEK (`tb_common.kek.PROTECTED`,
  one `kek.json`, one unseal), for `trialbox keys` (re-key, custody), for the backup and for `doctor`. Moving the
  orchestrator's keys to a volume of their own means moving files on every installed box at an update, with the
  EDC signatures and the audit heads depending on the result, and none of it can be run here (no box, no Docker
  daemon). It is recorded as a strict expected failure
  (`test_the_adapter_cannot_open_the_edc_or_audit_signing_keys`), which turns into an error when the volume is
  split. What it takes: a second folder (`TB_ORCH_SECRETS_DIR`) for `edc_sign.key`, `audit_sign.key`,
  `objects.key` and the REDCap tokens, read by `edc.store`, `tb_common.audit`, `objstore` and the study store; a
  one-time move at the orchestrator's start, with the KEK's wrapped files; `kek.py`, `tools/keys.py`, the backup
  list and `doctor` taught the two folders; a rehearsal on a box.
- **The EDC re-authentication key.** A signature still counts as re-authenticated by the session prefix
  `reauth-` under the same key. A second HMAC key would sit in the same two processes as the first (the console
  signs with both, the orchestrator verifies with both) and separate nothing. What separates it is the signed,
  timed `reauth_at` of the v3 claim (D-483) when the EDC routes move to v3, or an asymmetric key so that the
  orchestrator holds no signing key at all; neither is built here.
- **Asymmetric signing** (Ed25519: the orchestrator would hold a public key only) is not built; the keys file is
  still a signing key in the orchestrator's hands.

## Consequences

- A service that receives the console's calls can no longer name a person to the orchestrator.
- A box needs `actor-sign.key` before the console starts: `install.sh` (through `secrets init`) and
  `trialbox update` make it. A box started with the overlay and without the file does not start the console
  (compose refuses a missing secret file), which is the safe side.
- `secrets rotate` with no service named now also rotates the signing key.

## Dropped (D-311)

No security sign-off or owner review step.
