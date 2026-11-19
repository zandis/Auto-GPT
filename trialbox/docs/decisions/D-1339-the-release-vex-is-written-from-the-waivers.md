# D-1339 The release VEX is written from the waivers, and every waiver has a role owner and a date (10G-8)

- **Task:** lane H, plan 10 row 10G-8 (review 16, item 16-9, rows J12 and I9): VEX per release from the waivers;
  every waiver with an owner and a date. · **Date:** 2026-11-19
- **Decision:**
  - A waiver is an entry of `deploy/supply-chain-allowlist.yaml` that lets a vulnerability gate pass: every entry of
    `vulnerabilities` (62 on 2026-11-19) and of `os_packages_unreadable` (1). The licence entries and budgets are no
    vulnerability waiver; the reviewed findings of `tools/security_scan_ignores.yaml` (secrets and SAST in our own
    code) are no component vulnerability either. Neither is in the VEX (findings H10G8-07).
  - Every waiver has, in the allow-list's own form: `owner`, a role or a lane and never a person's name
    (`security owner`, `release owner` or `lane X`, optionally with the decision that says who holds the role:
    `security owner (D-1067)`); `date`, the day the ruling that accepted it was given; `reason`; `review_by`. The 63
    waivers' owner moves from a person's name to `security owner (D-1067)`: D-1067 names who holds the role, so
    nothing is lost. Their dates come from the decisions that accepted them: D-340 (2026-11-10) for the 49 per-id
    entries of the HAPI FHIR and vLLM images, D-574 (2026-11-12) for Caddy, seven Authelia entries and the
    `os_packages_unreadable` entry, D-622 (2026-11-12) for the package-wide kernel headers entry, D-790 (2026-11-15)
    for dnspython, D-820 (2026-11-15) for Authelia's crypto/x509. No waiver is added or removed, no reason or
    `review_by` changes, and the gates match on nothing new: `tools/supply_chain/allowlist.py` only accepts the key
    `date`.
  - `python -m tools.vex check` fails on a waiver with no owner, an owner that is not a role or a lane, no date, no
    reason, a date after its `review_by`, or a `review_by` before the release date (`--release-date`, default today).
    One file read, no network. It runs in `make lint`, `make ci` and CI's `docs` job, beside the findings register.
  - `python -m tools.vex write --release-date D --out F` writes one **CycloneDX 1.6 VEX** per release. CycloneDX, not
    OpenVEX or CSAF: the SBOMs the bundle already carries are CycloneDX JSON from Syft (`tools/supply_chain/sbom.py`),
    so one format, one set of tools, and a VEX that is a CycloneDX document a reader opens beside the SBOMs. One
    `vulnerabilities` record per vulnerability waiver, its image (with the digest `deploy/images.lock` pins) and
    package as the affected component, the reason as `analysis.detail`, the waiver date as `analysis.firstIssued`,
    and owner, date and review-by as properties. Deterministic: the timestamp is the release date and the serial
    number a UUID made from the content, so the same inputs give the same bytes.
  - The status is read from the reason, never guessed: a reason that starts "Not reachable:" (the owner's condition
    for the Authelia entries, D-574, D-820) is `not_affected` with `code_not_reachable`; every other waiver is
    `exploitable` ("may be exploitable" in CycloneDX) with the response `update`, because the ledger accepts it until
    a patched upstream image is pinned and records no analysis that would say more. The VEX never says less than the
    ledger. On 2026-11-19: 8 `not_affected`, 54 `exploitable`.
- **Not decided here:** the bundle does not carry the VEX yet (H10G8-03): `tools/release.py` copies a fixed list of
  SBOM extras and `release.json` names every payload file, so adding a file there changes what the rc1 bundle build
  requires. Whether the security owner records `not_affected` analyses for more waivers (H10G8-05). Owners and dates
  for the licence entries, budgets and the security-scan ignores (H10G8-07).
- **Held by:** `tests/unit/test_vex.py` (planted waivers without an owner, with a person as owner, without a date or
  reason, dated after review, past review on the release date; the CLI exits 1; the fixture's VEX is the expected
  bytes on two runs; status from the reason; the shipped list has 63 waivers each with the role owner).
