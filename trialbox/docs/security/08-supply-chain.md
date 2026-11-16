# 8. Supply chain

What goes into the images is fixed by hashes, scanned before a release, and listed in an SBOM (D-185, D-186).
The build side needs the network; the box never runs these tools. Code: `tools/supply_chain/`; tests
`tests/unit/test_supply_chain.py` (offline, on fixtures trimmed from real Trivy and Syft output).

- **One hashed lock.** `uv.lock` records a sha256 for every file of every package. `deploy/requirements.lock` is its
  export (`make lock`); every entry carries `--hash=sha256:`, so `pip install -r` in the images runs in pip's
  hash-checking mode and refuses a file whose bytes differ. `make lock-check` fails when `uv.lock` no longer matches
  `pyproject.toml`, when `deploy/requirements.lock` is not the export of `uv.lock`, or when an entry (or the
  pip-audit lock) has no hash; CI runs it on every pull request. Never edit `deploy/requirements.lock` by hand.
- **Pinned tools.** Every GitHub action is pinned to a commit. Syft and Trivy are release archives with a pinned
  sha256 (`make scanners`); pip-audit is installed from its own hashed lock (`tools/supply_chain/pip-audit.lock`).
  The base images are pinned by digest (`deploy/docker/python.Dockerfile`, `demo/Dockerfile`).
- **pip-audit** checks the lock against PyPI and OSV advisories (`make pip-audit`, on Python 3.12 so the lock's
  markers are judged as on the box). Every advisory fails unless allow-listed; the audited set must equal the lock
  (a package left out, an extra one or another version fails); a package it could not audit fails.
- **Trivy** scans every image that ships with its database loaded first (`make trivy-db`; on the media, `oras pull`
  of `trivy-db:2` and `trivy-java-db:1`) and the scan offline, with no ignore file, no config file and no `TRIVY_*`
  environment, so only the allow-list can accept a finding. A CRITICAL or HIGH finding with a fixed version fails
  unless allow-listed (Trivy's UNKNOWN, a CVE not scored yet, counts as HIGH); a finding with a missing or odd
  severity fails; findings with no fix yet and MEDIUM/LOW are
  listed. A report must show what it scanned (OS packages, the Python packages of the TrialBox images, the jars of the
  JVM image). The database may be at most 7 days old (its `UpdatedAt`).
- **Release gates.** `make release-gates` pins each image first (a local image by its image id, a third-party image
  by its registry digest for the platform), then runs Trivy and Syft on it and checks that both name that image. It
  covers trialbox-py, trialbox-jvm, trialbox-demo and every third-party image compose pulls. The record
  (`build/supply-chain/gates.json`) and `dist/sbom/index.json` list per image the reference, platform, image id,
  digests, and the report and SBOM with their sha256. CI runs it on amd64 and arm64 for pull requests that change
  what goes into an image, weekly and for a release tag; a release tag also gates both platforms of
  `make images-multiarch`, by digest. `make release-bundle` makes a bundle only from images in a passing record
  (`tools/make_bundle.sh --gates`, which refuses any other image id or a record older than 7 days).
- **The vulnerability gate blocks for every image a bundle carries** (T-110b, D-340). Report mode
  (`--vuln-mode report`) is left for the test-only mail servers (Mailpit, GreenMail), which no bundle carries; since
  D-827 they are report-only in the default mode too. The
  open findings of HAPI FHIR, vLLM and the `trialbox-postgres` base are dated allow-list entries scoped to that image (`image:`), each with
  `review_by: 2026-12-10`; a new finding blocks. One exception, D-622: one dated entry accepts every finding of the kernel headers package `linux-libc-dev` in the pinned vLLM image, so a new finding of that package there does not block. The list, with planned fixes, is in
  `deploy/security/known-image-findings.md`. MailHog has no arm64 image; it is left out of the arm64 gates by name
  (`SC_AMD64_ONLY`).
- **SBOM per release.** Syft writes CycloneDX JSON for each image and platform, and for the Python lock: Syft over an
  environment installed from the lock with hashes (`make lock-sbom`), so each package carries the licence of its
  installed metadata. The lock's SBOM must name every locked package that installs on the box, at its version.
- **Licences.** `make licences` reads the SBOMs (nested components, licence ids, names, expressions, URLs and full
  texts) and flags GPL, LGPL, AGPL, unknown licences, and dual licences. Only a licence on the known permissive list
  counts as an `OR` choice: `LicenseRef-*`, `NOASSERTION`, `Proprietary` never do. Who must answer for a flag:
  - *The Python lock and our images* (trialbox-py, trialbox-jvm, trialbox-demo): every copyleft or dual flag, and
    every unknown licence of a Python or npm package, needs its own allow-list entry (a dual entry names the branch
    taken, an unknown entry the licence a person verified), so a stricter licence fails again. Jars, Go and Rust
    binaries and other binaries carry no licence data Syft can read: their unknowns are counted per image and
    ecosystem against a reviewed budget, which fails as soon as one more appears.
  - *Third-party images* (postgres, HAPI, GreenMail, MailHog, vLLM), redistributed unmodified under their
    publishers' terms: all their open flags are counted per image against a reviewed budget; the image's terms are
    reviewed as a whole (counsel: vLLM's CUDA libraries).
  - Distro packages of a base image are listed, not gated.
  Today: eight LGPL packages (psycopg, psycopg-binary, docxtpl, py7zr and its four helpers), dulwich under
  Apache-2.0, six Python packages whose licence the SBOM cannot read (verified in the wheels), the base image's
  interpreter and pip launchers, the JRE, one HL7 FHIR package; budgets of 68 jars (trialbox-jvm), 64 jars
  (trialbox-demo) and the third-party images' counts from the first CI run.
- **The allow-list** (`deploy/supply-chain-allowlist.yaml`) is the only way to ship with a finding. Each entry needs
  its package (or, for a budget, its image and ecosystem), a reason of at least 20 characters and a `review_by` date
  at most 180 days ahead; `make allowlist-check` rejects an entry without them, a key given twice and a list given
  as anything else. After
  `review_by` every gate fails until the entry is reviewed or removed. Changes need the security owner's approval.
- **Done in T-110b** (D-340): `--gates` mandatory in `tools/make_bundle.sh`; the SBOMs, the gate record, `NOTICE`
  (the third-party notices) and `release.json` inside the signed bundle. **Not done yet** (WS-14.6): the venv
  installed from the same lock (`make venv` still resolves from `pyproject.toml`).
