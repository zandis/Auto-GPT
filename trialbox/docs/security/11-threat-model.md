# 11. Threat model

**Reader:** the security owner, the hospital's security officer and the outside tester. **Reviewed for release:**
1.0.0 (2026-11-19, lane H, card 10G-4). Decision: D-1327.

This is the box's threat model (ASVS 1.1.2; review 16, item 16-16, whose section 2 was its first draft). It names
what is worth protecting, who may want it, the boundaries data crosses, and for each threat at each boundary the
control the box has and the file or test that proves it, or the finding that says it is still open. It names threats
and controls only; it is not a test plan.

**Reviewed per release.** The line above names the release this file was last reviewed for.
`tests/unit/test_threat_model_per_release.py` fails when `[project] version` in `pyproject.toml` (the one place the
version is written, `python -m tools.release version`) is not that release, so the pull request that sets a new
version must review this file and move the line. The same test fails when a file, test or finding this page cites no
longer exists. A reviewer reads the design changes since the last review (`git log` of `deploy/`, `services/`,
`tools/` and `docs/decisions/`), adds a boundary or threat a change brings, and moves a threat from open to proved
only with the test that proves it.

## Assets

| Asset | Where it lives |
| --- | --- |
| Patient data (pseudonymised lake, FHIR store, candidate lists, screening verdicts) | `lake`, `fhir-store` and `db` services in `deploy/docker-compose.yml`; their volumes |
| The pseudonym keys and the KEK that wraps them | the secrets folder; section 4 of this document set (`docs/security/04-secrets.md`) |
| The audit chain and its signed heads | the audit volume (written by `audit-writer` only), the anchor folder |
| The box's software and its update channel | the signed bundle; `tools/apply_update.sh`, `tools/verify_update.py` |
| The model servers and the model key | `llm-service`, `model-guard` and the gateway in `deploy/docker-compose.yml` |
| Staff accounts and sessions | the console (`services/console/`); Authelia when the site uses it |
| Mail (lists to coordinators, intake replies) | `mail-gateway` |
| Backups | encrypted to a key the box does not hold (`docs/security/04-secrets.md`) |

## Actors

- **Staff with an account** (coordinator, investigator, steward, privacy office, admin): may read more than their
  role allows, or more patients than the work needs.
- **A person on the hospital network without an account**: reaches only what the box publishes.
- **Someone with root on the host, or the disks**: an insider, a thief of a desk-side box, a lost backup medium.
- **A supplier**: a poisoned package, image or model; the vendor's own update channel.
- **Content as an actor**: a hostile document, chart text that tries to steer the model, a mail that pretends to be
  a coordinator's.
- **The remote-support person** in a supervised session (RUNBOOK §21).

## Trust boundaries

The services, networks and published ports are those of `deploy/docker-compose.yml` with the identity overlay
`deploy/docker-compose.identity.yml` (the form a site box runs; the network sheet,
`docs/handover/network-sheet.en.md`, lists every port). The host itself is section 1
([01-the-host.md](01-the-host.md)) and the network section 2 ([02-network.md](02-network.md)).

| # | Boundary | What crosses it |
| --- | --- | --- |
| B1 | Hospital network to the box's 443 (Caddy on `trialbox-edge`) and on to the console | staff browsers; the only published port |
| B2 | Between the box's services on `trialbox-net` (internal: no route out) | service calls with a per-service token; the database |
| B3 | The gateway to the model servers: `trialbox-model-net` to `model-guard` to `trialbox-model-backend` (both internal) | prompts with chart text; model answers |
| B4 | The box to the outside: `trialbox-egress` (gateway, orchestrator, criteria-compiler, mail-gateway; Authelia with the overlay) under the host's egress table (`deploy/egress.py`, `deploy/network.sh`) | the declared destinations only |
| B5 | `mail-gateway` to the hospital's mail server (SMTP out, IMAP in) | lists, notices, replies |
| B6 | The two-device link: the Spark and the workstation, one TLS port on the link address (`tools/two_device.py`, `deploy/two-device/`) | the routes each device exports to the other |
| B7 | The update bundle: the vendor's build to the box, on media or a copy | the whole box's software and rule sets |
| B8 | The audit chain: services to `audit.journal` to `audit-writer` to the chain, the nightly signed head to the anchor folder | every event the box records |

## Threats per boundary

"Proved" names a test (or, where marked, a file whose check runs in CI). "Open" names a finding of the findings
register (`docs/handover/findings-register.md`) or of this page (H10G4-nn, below), or the plan 10 card that holds it.

### B1: the hospital network to the console

| Threat | Control | Proved by | Open |
| --- | --- | --- | --- |
| Reading or changing traffic between a browser and the box | TLS 1.2/1.3 at Caddy, HSTS one year (`deploy/identity/Caddyfile`); policy `deploy/security/tls-policy.json` (D-1328) | `tests/unit/test_tls_policy_judge.py`: `test_the_shipped_caddyfile_meets_the_policy` | TLS as served never scanned: H10G48-01 |
| Reaching the console without Caddy | behind the overlay the console publishes no port; only 443 | `tests/unit/test_network_sheet.py`: `test_the_identity_overlay_shows_443_ldaps_and_no_console_port` | – |
| A browser sending an identity header to sign in as someone | Caddy strips every identity header; the console refuses header sign-in with TOTP or OIDC | `tests/console/test_identity.py`: `test_caddy_strips_identity_headers_and_query_strings_from_logs`, `test_trusted_header_never_skips_the_password_or_the_second_factor` | – |
| A session cookie taken from a plain connection or script | Secure, HttpOnly, SameSite=Strict in PRODUCTION; CSP | `tests/console/test_identity.py`: `test_production_cookies_are_secure_httponly_and_strict`; `tests/console/test_console_app.py`: `test_security_headers_and_cookie_flags` | sign-out cookie flags V3-12; other sessions not visible V3-03 |
| Guessing or reusing passwords | password policy; breached-password list (D-447) | `tests/console/test_console_app.py`: `test_password_hash_roundtrip_and_policy` | V3-05, V3-09, V3-10, V3-11 |
| A role reading or doing what the matrix forbids | one role matrix for every route | `tests/console/test_role_route_matrix.py`: `test_the_generated_matrix_equals_the_design_table` | refusals not audited V2-02; V2-04; break-glass twice V11-08 |
| Staff bulk-reading patients | identifier views and reveals rate-limited and audited | `tests/console/test_console_app.py`: `test_identifier_views_are_rate_limited`; `tests/console/test_reveal_paths.py`: `test_every_surface_reveals_for_the_pi_with_one_audit_shape` | no unusual-activity alert: card 10G-12 |
| A typed note left for the next person on a shared PC | – | – | V3-19 |

### B2: between the box's services

| Threat | Control | Proved by | Open |
| --- | --- | --- | --- |
| A container calling a service it should not | per-service token; callee accepts its listed callers (D-128, D-138) | `tests/unit/test_service_token_everywhere.py`: `test_changing_calls_need_the_token`, `test_no_token_configured_refuses_in_production_and_opens_in_dev` | an unlisted callee accepts any token: V3-15 |
| A service reaching the internet directly | `trialbox-net` is `internal: true`; only four services join `trialbox-egress` | `tests/unit/test_threat_model_per_release.py`: `test_the_base_networks_are_internal_and_four_services_reach_out` | – |
| A secret read from a container's environment | secret files for the model key | `tests/unit/test_model_key.py`: `test_only_the_gateway_and_the_guard_hold_the_key_and_from_a_file` | database, mail and KEK passwords in the environment: V3-13 |
| A container with more privilege than it needs | `model-guard` alone drops capabilities, read-only, fixed user | – | card 10G-1 (the other services) |

### B3: the gateway to the model servers

| Threat | Control | Proved by | Open |
| --- | --- | --- | --- |
| A container other than the gateway calling the model | model networks internal; `model-guard` in front of vLLM needs the model key | `tests/unit/test_model_guard.py`: `test_the_allowed_calls_pass_with_the_key_only`, `test_vllm_routes_that_skip_the_key_never_reach_it`, `test_admin_paths_only_with_admin_and_the_key` | – |
| The model server sending data out | `trialbox-model-net` and `trialbox-model-backend` are internal; no egress rule for a model host but the gateway's | `tests/unit/test_threat_model_per_release.py`: `test_the_base_networks_are_internal_and_four_services_reach_out`; `tests/unit/test_egress_rules.py`: `test_only_the_gateway_gets_model_host_rules`, `test_egress_extra_cannot_give_another_container_a_model_host` | – |
| Chart text steering the model to a wrong verdict | fenced data blocks; two models must agree on a verified quote to exclude (section 5) | `docs/security/05-data-protection.md` (design); suite not run on the real pair | card 10G-53 |
| A model answer carrying patient data into a trace | – | – | V1-05 |

### B4: the box to the outside

| Threat | Control | Proved by | Open |
| --- | --- | --- | --- |
| Data sent to a destination no one declared | default-deny egress table per container, from one allowlist (D-211) | `tests/unit/test_egress_rules.py`: `test_render_default_deny_and_rules`, `test_allowlist_from_env` | the table's effect is tested by `tests/integration/test_egress.py` only (root, not in CI): card 10G-49 |
| A call steered to a metadata or internal address | `tb_common.http.guarded_client` checks every hop | `tests/unit/test_egress_guard.py`: `test_internal_and_odd_addresses_are_refused`, `test_a_declared_lan_host_passes_but_never_to_metadata_or_link_local` | – |
| Data leaving in name lookups | – | – | H10G4-01 |

### B5: the mail gateway

| Threat | Control | Proved by | Open |
| --- | --- | --- | --- |
| A mail pretending to be a coordinator's | intake trusts only the named authserv-id's results; a failed check sends nothing | `tests/unit/test_mail_boundary.py`: `test_no_authserv_id_trusts_no_header`, `test_a_failed_mail_auth_sends_nothing` | – |
| A patient file mailed out | link mode by default: no patient file, no password in mail | `tests/unit/test_mail_boundary.py`: `test_the_default_is_not_zip`, `test_a_patient_file_is_never_mailed_as_a_password_zip_on_a_real_box`; `tests/unit/test_mail_unit.py`: `test_link_mode_sends_no_patient_file_and_no_password` | a queued mail keeps a patient's name after opt-out: V1-14 |
| Header injection through a subject | encoded subjects | `tests/unit/test_mail_unit.py`: `test_reply_to_subject_with_encoded_crlf` | – |
| The mail gateway reaching anything but the mail server | egress rows for SMTP and IMAP only (`deploy/egress.py`) | `tests/unit/test_egress_rules.py`: `test_render_default_deny_and_rules` | – |

### B6: the two-device link

| Threat | Control | Proved by | Open |
| --- | --- | --- | --- |
| Reading or changing traffic on the cable | mutual TLS 1.3 only, both certificates from the install ceremony's CA | `tests/unit/test_two_device_link.py`: `test_the_contexts_require_tls13_and_a_peer_certificate`, `test_selftest_round_trip_and_every_refusal` | link never scanned as served: H10G48-01 |
| A third machine joining the link | the peer's certificate must name the other device; the CA key is not kept | `tests/unit/test_two_device_link.py`: `test_certs_name_each_device_and_keep_no_ca_key` | – |
| More than the named routes crossing | only the exported routes; the link is the Spark's only listener | `tests/unit/test_two_device_config.py`: `test_the_two_devices_share_only_the_link` | – |

### B7: the update bundle

| Threat | Control | Proved by | Open |
| --- | --- | --- | --- |
| A changed or forged bundle | Ed25519 signature over the manifest checked before parsing; key id; each member's sha256 | `tests/unit/test_update_bundle.py`: `test_tampered_bundles_are_rejected` | – |
| An old, vulnerable release put back | `release_seq` above the installed one; downgrade only with an audited reason | `tests/unit/test_update_safety.py`: `test_an_older_release_seq_is_refused_and_allow_downgrade_needs_a_reason`, `test_allow_downgrade_is_audited_before_anything_else` | – |
| An update with no way back | backup before apply; `--no-backup` needs a reason in PRODUCTION (D-1321) | `tests/unit/test_no_backup_needs_a_reason.py`: `test_the_shell_entry_refuses_no_backup_without_a_reason_on_a_production_box` | – |
| The vendor's signing key stolen or used by one person | – | – | H10G4-02 |
| A poisoned dependency or image in the build | hashed locks, offline Trivy, pip-audit, SBOM; waivers dated (`deploy/supply-chain-allowlist.yaml`) | `tests/unit/test_release_bundle.py`: `test_an_image_outside_the_gate_record_is_refused` | owners "to assign": card 10G-8; no image signatures: card 10G-7 |

### B8: the audit chain and its anchor

| Threat | Control | Proved by | Open |
| --- | --- | --- | --- |
| A service writing or changing audit lines | services append to `audit.journal` only; `audit-writer` alone writes the chain | `tests/unit/test_audit_one_writer.py`: `test_nothing_but_the_writer_writes_the_journal_table` | a change stored before its audit event: V3-18, V8-04 |
| Lines dropped, a day deleted, the chain rewritten | the anchor follows every write; a rewritten chain is never signed again | `tests/unit/test_audit_anchor.py`: `test_dropping_the_last_events_fails`, `test_rewriting_and_rehashing_everything_fails`; `tests/unit/test_audit_heads_nightly.py`: `test_a_rewritten_chain_is_never_signed_again` | V8-02, V8-05, V8-06 |
| Root rewriting the day before the nightly head | – | – | H10G4-03; card 10G-2 |
| Identifiers typed into free text kept in the audit for ever | – | – | V3-14, V8-03, V8-07 |

## Not in this version

The host, its disks and the backups are section 1 and RUNBOOK §22 (review 16, section 2.1, rows "Insider with host
root", "Stolen GPU workstation", "Stolen backup medium"); hostile documents and rule-set zips (D-1102) and the remote
support session (RUNBOOK §21) get their own rows at the next review. Each threat review 16 lists there stays open
until a row here names its control.

## Findings of this page

Also in `docs/handover/threat-model-2026-11-19/findings.json`, in the register's `--add-from` form.

| Id | Severity | Claim | Lane | Basis |
| --- | --- | --- | --- | --- |
| H10G4-01 | Medium | The egress table leaves Docker's embedded DNS alone (`deploy/egress.py`), so a container's name lookups still reach the hospital's resolver (review 16's J-M7); the decision waits on card 10G-49 | H | hypothesis |
| H10G4-02 | Medium | The vendor's update key is one file passed as `--key` to `tools/make_bundle.sh`: one person can sign a release (card 10G-7) | H | hypothesis |
| H10G4-03 | High | The audit signing key sits in the box's own secrets folder (`tools/trialbox/audit_heads.py`): root can change the events written since the last signed head before the next night signs them, and holds the key that signs (review 16, section 2.2; card 10G-2) | H | hypothesis |
