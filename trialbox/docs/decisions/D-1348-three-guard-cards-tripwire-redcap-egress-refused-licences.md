# D-1348 Three guards: doctor and the tripwire, the REDCap host on egress, refused licences (H-65)

- **Task:** lane H, card H-65: plan 9 cards 9g-11 (review 01 B1-P2), 9g-14 (review 01 section 7.2) and 9g-15
  (review 03 B3-11). · **Date:** 2026-11-20
- **Decision:**
  - **9g-11.** `trialbox doctor` has a check `phi_tripwire`. It reads `TB_GATEWAY_PHI_TRIPWIRE` by the gateway's own
    rule (`GatewayConfig.from_env`: `off`, `0`, `false` or `no` is off; unset or any other value is on) in the
    gateway's environment (`TB_ENV`, PRODUCTION when unset). Off is a FAIL in PRODUCTION and a WARN in DEV, TEST
    and VALIDATION; the line says what is off and how to turn it on. On is a PASS.
  - **9g-14.** `deploy/egress.py` opens the orchestrator to the REDCap server named by `TB_REDCAP_API_URL`
    (`REDCAP_API_URL` when that is empty, the connector's own rule): exactly that host and port (443 when none is
    written), nothing wider. No URL: no row. `inproc://` (the demo's in-process simulator): no row. A URL that is not
    `https`, has no host, carries a user or password, or has a port that is not a number is refused with a line
    naming the setting (the URL is not echoed); a REDCap host that is a model host is refused, as `EGRESS_EXTRA`
    refuses one. `EGRESS_EXTRA` works as before. The network sheet gains the row.
  - **9g-15.** The supply-chain allow-list refuses a licence entry whose `licence`, `chosen` or `reason` names FSL,
    SSPL, a non-profit-only licence, or cloud features on by default (`allowlist.REFUSED`, matched on those words and
    not inside a longer word). The entry is an error of `make allowlist-check`, so no entry can accept such a
    component and the licence gate stays failed. One planted fixture per kind in
    `tests/fixtures/supply_chain/planted/`. The project's allow-list passes unchanged.
- **Not done here:** the launch record printing the tripwire on its first line (the second half of B1-P2; not in
  this card). GPL and AGPL stay what they were: flags of the licence report that an entry of their class accepts
  (the real allow-list accepts eight LGPL packages that way). No package metadata is read for "cloud features on by
  default": that is a product behaviour, refused only when an entry records it.
- **Held by:** `tests/unit/test_doctor_phi_tripwire.py`, `tests/unit/test_egress_redcap.py`,
  `tests/unit/test_allowlist_refused_licences.py`; the doctor's pin list in
  `tests/unit/test_trialbox_doctor.py::test_default_install_passes` gains `phi_tripwire`.
