# The release VEX from the waivers (2026-11-19)

**Reader:** the people who build TrialBox: lane H, the security owner, the integrator and whoever builds a
release bundle. For builders, so in one language.

Plan 10 row 10G-8 (review 16, item 16-9), decision D-1339. Done when a waiver without an owner fails CI: it does
(`python -m tools.vex check`, CI job `docs`, `make lint`).

## Where the waivers live

| File | Entries | What they wave through | In this card |
| --- | --- | --- | --- |
| `deploy/supply-chain-allowlist.yaml` `vulnerabilities` | 62 | a pip-audit or Trivy finding, per id, package and image | yes: owner, date, VEX |
| `deploy/supply-chain-allowlist.yaml` `os_packages_unreadable` | 1 | an image whose OS packages the scanner cannot read | yes: owner, date (a property in the VEX) |
| `deploy/supply-chain-allowlist.yaml` `licences`, `budgets` | 23, 10 | a licence flag | no: no vulnerability (H10G8-07) |
| `tools/security_scan_ignores.yaml` | 57 | a secrets or SAST finding in our own code (`make security-scan`) | no: no component vulnerability (H10G8-07) |

There is no `.trivyignore`, OSV or pip-audit ignore file: the gates read the allow-list only.

## What changed

- Every one of the 63 waivers names its owner as a role, `security owner (D-1067)`, in place of a person's name
  (D-1067 says who holds the role), and gains `date`, the day the ruling that accepted it was given. No waiver is
  added or removed; no reason, `review_by`, id, package or image changes. All 63 had a reason; none needed "reason not
  recorded".
- `tools/supply_chain/allowlist.py` accepts the key `date` (it stays optional there, so the gates match on nothing new).
- `tools/vex.py` (new): `check` and `write`. `check` fails on a waiver without an owner (a role or a lane), a date or a
  reason, dated after its review, or past its `review_by` on the release date. `write` gives one CycloneDX 1.6 VEX per
  release; same inputs, same bytes.
- `make lint`, `make ci` and CI's `docs` job run `python -m tools.vex check`.
- Two tests that pinned the owner's old value pin the role and the date now (`test_vllm_dnspython_entry.py`,
  `test_authelia_x509_entry.py`).

## The dates

| Waivers | Date | Source |
| --- | --- | --- |
| HAPI FHIR (21) and vLLM per id (28) | 2026-11-10 | D-340 item 5 ("the open findings of HAPI FHIR and vLLM of 2026-11-10"); see H10G8-04 |
| vLLM `linux-libc-dev`, every id | 2026-11-12 | D-622 |
| vLLM dnspython CVE-2026-128089 | 2026-11-15 | D-790 |
| Caddy (3), Authelia (7), Authelia `os_packages_unreadable` | 2026-11-12 | D-574, the owner's ruling of 2026-11-12 |
| Authelia CVE-2026-111943 | 2026-11-15 | D-820 (the "not reachable" form) |

## The VEX of 2026-11-19

`python -m tools.vex write --release-date 2026-11-19 --out <file>` on this branch: 62 records, 8 `not_affected`
(`code_not_reachable`: the Authelia entries whose reason starts "Not reachable:") and 54 `exploitable` with response
`update` (every other waiver: the ledger accepts it until a patched image is pinned and records no analysis that says
more). Two runs give the same bytes. CycloneDX was chosen because the SBOMs in the bundle are CycloneDX (D-1339).

## Limits

- Not validated against the CycloneDX 1.6 JSON schema: the schema is not in the tree and the card makes no network
  call (H10G8-09). The test checks the fields it writes and that every `affects` reference is a component.
- The bundle does not carry the VEX (H10G8-03).

## Findings

`findings.json` beside this page.

| Id | Severity | Finding | State |
| --- | --- | --- | --- |
| H10G8-01 | Medium | all 63 waivers named a person as owner, and none recorded the date it was accepted | fixed 7a69081e |
| H10G8-02 | Medium | a waiver without an owner or a date passed every check (`owner` optional, no `date`) | fixed 7a69081e |
| H10G8-03 | Medium | the signed bundle carries no VEX: adding it to `tools/release.py`'s SBOM extras changes what the rc1 build requires, so it is left for after rc1 | open |
| H10G8-04 | Low | the 49 per-id HAPI and vLLM waivers carry D-340's date 2026-11-10; the ledger's comment says some findings were published 2026-11-11 under the same rule, and which ones is not recorded per entry | open |
| H10G8-05 | Low | 54 of 62 VEX records say `exploitable` because only the 8 Authelia reasons record a "not reachable" analysis; the security owner may record more (e.g. kernel headers, dnspython zone-file parsing) | open |
| H10G8-06 | Low | the package-wide `linux-libc-dev` waiver (D-622) names no ids, so its VEX record has id `*`, which no scanner matches; the ids could come from the release's gate record | open |
| H10G8-07 | Low | the 23 licence entries, 10 budgets and 57 security-scan ignores have no owner or date (the scan ignores no review date) and are outside this card's check | open |
| H10G8-08 | Low | `deploy/security/known-image-findings.md` and D-1004 still name a person as owner of every row; a test pins that page's text | open |
| H10G8-09 | Low | the VEX is not validated against the CycloneDX 1.6 schema (no schema in the tree, no network) | open |
