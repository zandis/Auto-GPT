# Three guard cards: the tripwire in doctor, the REDCap host on egress, refused licences (2026-11-20)

**Reader:** the people who build TrialBox: lane H and the integrator. For builders, so in one language.

Card H-65: plan 9 cards 9g-11, 9g-14 and 9g-15 (`docs/plan/45-plan-9-2026-11-17.md`), decision D-1348. None of the
three was on master when the card started (checked by searching the tree for each subject). New findings in the
register's `--add-from` form: `three-guard-cards-2026-11-20/findings.json`.

## 9g-11: doctor and the PHI tripwire (review 01 B1-P2)

`trialbox doctor` has a check `phi_tripwire` (`tools/trialbox/doctor.py`). It reads `TB_GATEWAY_PHI_TRIPWIRE` by the
gateway's own rule (`gateway.core.GatewayConfig.from_env`), so doctor and the gateway cannot disagree, in the
gateway's environment (`TB_ENV`, PRODUCTION when unset).

| Setting | PRODUCTION | DEV, TEST, VALIDATION |
| --- | --- | --- |
| off (`off`, `0`, `false`, `no`) | FAIL | WARN |
| unset, on, or any other value | PASS | PASS |

The FAIL line says what is off and how to turn it on: set `TB_GATEWAY_PHI_TRIPWIRE=on` in deploy/.env (or remove
the line) and restart the gateway. VALIDATION is a WARN because the P2b launch ran there with it off on public data,
which the review marked Low. The doctor's pin list (`test_default_install_passes`) gains `phi_tripwire`.

Not in this card: the second half of B1-P2, the launch record printing the setting on its first line.

## 9g-14: the REDCap host on the egress allow-list (review 01 section 7.2)

`deploy/egress.py` reads `TB_REDCAP_API_URL` (`REDCAP_API_URL` when that is empty, the connector's own rule in
`services/edc_backend/config.py`) and gives the orchestrator one row: exactly that host and port, 443 when the URL
names none. Nothing wider: one host, one TCP port, the orchestrator's addresses only.

| `TB_REDCAP_API_URL` | Row |
| --- | --- |
| unset or empty | none |
| `inproc://...` (the demo's in-process simulator) | none |
| `https://host[:port]/...` | orchestrator -> host:port |
| not https, no host, a user or password, a port that is not a number | refused: a line naming the setting and what is wrong, exit 1; the URL is not echoed (it may carry a password) |
| a model host | refused, as `EGRESS_EXTRA` refuses one |

`EGRESS_EXTRA` works as before; a site that already added its REDCap host there gets the same pair twice, which
renders the same rule. The network sheet (three languages, generated) gains the row.

## 9g-15: refused licences in the allow-list check (review 03 B3-11)

`tools/supply_chain/allowlist.py` has `REFUSED`: FSL, SSPL, a non-profit-only licence, cloud features on by default.
A licence entry of the allow-list whose `licence`, `chosen` or `reason` names one is an error of
`make allowlist-check`, so no entry can accept such a component and the licence gate stays failed for it. The words
are matched without case and not inside a longer word (`FSLX` is not FSL). Only the identifiers the review names are
used; no licence fact was added beyond them.

One planted entry per kind in `tests/fixtures/supply_chain/planted/` (made-up package names). Each is refused by
`allowlist-check`; the same entry with a plain MIT licence passes, so the refusal is the licence's. The project's
allow-list passes unchanged (`allowlist-check: PASS (96 valid entries)`); no entry of it names a refused licence.

GPL and AGPL stay what they were: flags of the licence report that only an entry of their class accepts. The
licence report still classes an FSL or SSPL component as `unknown`; the refusal holds because no `unknown` entry
may record either.

## Findings

- **H65-01** (Low): the egress row covers only `TB_REDCAP_API_URL`. With `TB_EDC_BACKEND` unset, the study link
  calls the URL saved on the S36 page (`services/orchestrator/study_api.py` `StudyService.client`), which may be
  another host; that host still needs an `EGRESS_EXTRA` line, and a private address needs it for the in-process
  guard too (that client does not declare its host).
- **H65-02** (Low): `declared_egress` in `libs/tb_common/http.py` (the in-process mirror of the egress table, held
  to it by `test_the_declared_table_matches_the_box_egress_table`) does not carry the REDCap row. The connector's
  own client declares its host per call, so nothing is refused today; the test's settings have no REDCap URL, so the
  two tables are not compared on it. A libs file, not lane H's.
- **H65-03** (Low): the second half of B1-P2 is not built: the launch record does not print the tripwire setting on
  its first line.
- **H65-04** (Low): the licence refusal reads what an allow-list entry records. An `unknown` entry that records a
  wrong licence for an FSL or SSPL component would still accept it; the licence report has no `refused` class of its
  own.

## What was and was not run

Run here: the three new test files, the doctor, egress, network-sheet and supply-chain tests, `make allowlist-check`
on the project's allow-list. Not run: doctor on a box, `deploy/network.sh apply` (no root, no Docker), the release
licence gate on real SBOMs.
