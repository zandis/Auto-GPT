# Licence inventory of a release, and the list for the owner's lawyer

**Reader:** the owner and the owner's lawyer; the vendor who signs a release. It rides in every release bundle as
`LICENCE-INVENTORY.md` (`tools/make_bundle.sh`), beside the generated report `sbom/licences.md`.

- **Card:** INT-M10-min, item a (the integrator's 7184086631, item 2a). Base `int/system` 0894674f.
- **Date read:** 2026-11-26. Every licence below was read in its file on that day, or is marked **not verified**.
  Nothing is filled from memory.

## 1. What a release carries, and which part is generated

| File in the bundle | Written by | What it covers |
| --- | --- | --- |
| `sbom/licences.md` | `make release-gates` (the licence report of `tools/supply_chain/licences.py`) | Every Python package of `requirements.lock` and every package of every image, read from the CycloneDX SBOMs (the lock's SBOM and one SBOM per image, written by the scanner the images workflow already runs). Flags LGPL, GPL, AGPL, unknown and dual licences; the gate fails on a flag the allow-list does not accept |
| `sbom/*.cdx.json`, `sbom/index.json` | `make lock-sbom`, `make release-gates` | The SBOMs themselves |
| `NOTICE` | the repository | The notices and licence texts the shipped components require |
| `LICENCE-INVENTORY.md` | this page, by hand | The from-memory licence claims checked against their files (section 3) and the list for the lawyer (section 4) |

The generated report is the inventory of record for a release: it is made from that release's own lock and images.
This page does not repeat its rows.

## 2. The run on this base

- **Python dependencies** (`uv.lock`, through `make licences`): 73 components; 8 LGPL, 6 unknown, 1 dual, 58
  permissive; result PASS (every flag has an allow-list entry). The LGPL rows are psycopg, psycopg-binary, docxtpl,
  py7zr and py7zr's four LGPL dependencies (inflate64, multivolumefile, pybcj, pyppmd). The dual row is dulwich. The
  six unknown rows are permissive licences the SBOM does not name in SPDX form, each checked in its wheel.
- **Image dependencies:** **not run here.** The session that wrote this page has no container engine, so no image
  was built or scanned. The images workflow and `make release-gates` write one SBOM per image and add its packages to
  `sbom/licences.md` of each release.
- **An object-store image (MinIO or one like it):** none found. No compose file or image lock names one; the box
  keeps attachments and outputs on a filesystem volume (`objects-data`, D-121 removed the object store). The field
  name `minio_key` in some tools is a leftover name, not an image.

## 3. Licences the reviews took from memory, checked in their files

The lists: the component and ecosystem review of 2026-11-09 (`docs/reviews/2026-11-09-component-review-layer1.md`,
its list of licences and capabilities marked unverified or from memory) and the build-versus-reuse review of
2026-11-12 (`docs/reviews/2026-11-12-build-vs-reuse.md`, every licence marked `[M]`). For each: the LICENSE file read
in the project's repository (the default branch named, the first 12 hex digits of the file's sha256) and the release
page. A Python package's release page is its PyPI page (version and first upload date of the latest release). A
GitHub release page could not be read from this session (refused), so those are **not verified**.

| Component | Said from memory | LICENSE file read | Release page | Agrees |
| --- | --- | --- | --- | --- |
| OHDSI CommonDataModel | Apache-2.0 | **not verified**: no LICENSE, LICENSE.md, LICENSE.txt or COPYING on main or master | not verified | not verified |
| Criteria2Query | (unverified) | Apache-2.0 (master/LICENSE, b40930bbcf80) | not verified | read: Apache-2.0 |
| ohdsi-circepy | (unverified) | Apache-2.0 (main/LICENSE, 81f0ffa823ea) | PyPI 0.3.0, 2026-10-09, Apache-2.0 | read: Apache-2.0 |
| japanera | (not fetched) | MIT (master/LICENSE, 76cc6290cda6) | PyPI 2.1.3, 2025-06-23, MIT | read: MIT |
| jeraconv | (not fetched) | MIT (master/LICENSE, 9bd83b9c305a) | PyPI 0.2.1, 2019-06-19, MIT | read: MIT |
| jpdatetime | (not fetched) | Apache-2.0 (main/LICENSE, c71d239df917) | PyPI 1.5.0, 2024-11-23, Apache-2.0 | read: Apache-2.0 |
| twdate | (not fetched) | **not verified**: PyPI names no source repository | PyPI 1.1.0, 2026-03-20, metadata says MIT | not verified |
| synthea-international | (unverified) | Apache-2.0 (master/LICENSE, c71d239df917) | not verified | read: Apache-2.0 |
| Authelia (LDAP backend, locale list) | capabilities, from its docs | Apache-2.0 (master/LICENSE, 90afa7b9f90f) | not verified; the two capabilities not verified | licence yes; capabilities not verified |
| Keycloak (locales) | capability | Apache-2.0 (main/LICENSE.txt, cfc7749b96f6) | not verified; capability not verified | licence yes; capability not verified |
| Trivy (offline database mode) | capability | Apache-2.0 (main/LICENSE, c71d239df917) | not verified; capability not verified | licence yes; capability not verified |
| PGroonga (offline package) | capability | PostgreSQL-style permissive (main/COPYING, 62f6ecfbc5d3) | not verified; capability not verified | licence read; capability not verified |
| PaddleOCR (3.x wheels for CUDA on WSL2) | Apache-2.0, capability | Apache-2.0 (main/LICENSE, 3840c5c0c61c) | PyPI paddleocr 3.7.0, 2026-06-11; the CUDA wheel on WSL2 not verified | licence yes; capability not verified |
| Infinity (embedding server) | MIT | MIT (main/LICENSE, cd7e2c585736) | PyPI infinity-emb 0.0.80, 2026-11-09, MIT | yes |
| age | BSD-3-Clause | BSD-3-Clause (main/LICENSE, c5d65279d029) | not verified | yes |
| WhiteRabbit | Apache-2.0 | Apache-2.0 (master/LICENSE, d4e8e3f895c9) | not verified | yes |
| Usagi | Apache-2.0 | **not verified**: no LICENSE file found on main, master or develop | not verified | not verified |
| memray | Apache-2.0 | Apache-2.0 (main/LICENSE, c973dd08e490) | PyPI 1.20.0, 2026-08-07, Apache 2.0 | yes |
| DeepEval | Apache-2.0 | Apache-2.0 (main/LICENSE.md, d004e4b8bbfa) | PyPI 4.3.6, 2026-11-25, Apache-2.0 | yes |
| Trillian | Apache-2.0 | Apache-2.0 (master/LICENSE, cfc7749b96f6) | not verified | yes |
| Rekor | Apache-2.0 | Apache-2.0 (main/LICENSE, cfc7749b96f6) | not verified | yes |
| WAL-G | Apache-2.0 | Apache-2.0 (master/LICENSE.md, 0f352dc56c4f) | not verified | yes |
| pyotp | MIT | MIT (main/LICENSE, be5964e73ece) | PyPI 2.12.1, 2026-11-19, MIT | yes |
| Casbin | Apache-2.0 | Apache-2.0, and an MIT notice for an included part (master/LICENSE, 0fa497ee86d2) | not verified | yes, with the MIT part named |
| OPA | Apache-2.0 | Apache-2.0 (main/LICENSE, c6596eb7be85) | not verified | yes |
| OpenFGA | Apache-2.0 | Apache-2.0 (main/LICENSE, 1c46d7b2bed9) | not verified | yes |
| Fluent (the specification) | Apache-2.0 | Apache-2.0 (main/LICENSE, cfc7749b96f6) | not verified | yes |
| Babel | BSD | BSD-3-Clause (master/LICENSE, 86bad5758c78) | PyPI 2.19.0, 2026-11-24, BSD-3-Clause | yes |
| gICS and gPAS | AGPL-3.0 | **not verified**: no source repository read | not verified | not verified |
| Fides | Apache-2.0 | Apache-2.0 (main/LICENSE, c71d239df917) | PyPI ethyca-fides 2.86.2, 2026-06-01, Apache 2.0 (the PyPI name `fides` is another project) | yes |
| Tesseract | Apache-2.0 | Apache-2.0 (main/LICENSE, cfc7749b96f6) | not verified | yes |
| pytest-split | MIT | MIT (master/LICENSE, 98c9ba280046) | PyPI 0.11.0, 2026-02-03, MIT | yes |

Not checked: the `[M]` marks of the build-versus-reuse review that state no licence (what a tool does, a hosting
price, a maintenance state). None of the components above is in a TrialBox image today; the check is for whoever
adopts one.

## 4. For the owner's lawyer

Each item needs a lawyer's reading before a release goes to a site. The facts are from the files named; the
judgement is the lawyer's.

| Item | Licence | What the box does with it | The question |
| --- | --- | --- | --- |
| psycopg and psycopg-binary 3.3.8 | LGPL-3.0-only | Installed unmodified as a Python package in the box image; the binary wheel carries libpq and OpenSSL under their own permissive licences | Do the notices and the replaceable package meet LGPL-3.0's terms for an image the vendor ships? |
| docxtpl 0.20.2 | LGPL-2.1-only | Installed unmodified; fills the Word templates | The same question under LGPL-2.1 |
| py7zr 1.1.4, with inflate64, multivolumefile, pybcj and pyppmd | LGPL-2.1-or-later | Installed unmodified; reads 7z attachments only; R-12 may replace attachments with links and remove all five | The same question; or the date by which they leave |
| dulwich 1.2.21 | Apache-2.0 OR GPL-2.0-or-later | Installed unmodified; the release chooses **Apache-2.0** (allow-list entry, notice in `NOTICE`) | Confirm the choice of Apache-2.0 and that the notice suffices |
| An object-store image | none found (section 2) | none | none, unless one is added |
| The judge model | Apache-2.0 by its licence register row (verified there); the weights' source carries no licence file (`none-in-source` in the registry) | Weights loaded on the box; whether a bundle may carry them is marked OWNER in the profile records | May the vendor ship the weights in a bundle, and under which terms and use policy? |
| The verifier model | Apache-2.0 by its licence register row; the licence file is pinned by sha256 in the registry | As for the judge | The same question |
| The embedder | MIT by its licence register row | Weights loaded on the box and pinned at install | The same question |
| A model a site or profile adds later (a second judge, a hosted model) | several are `verified: false` in `models/registry.yaml` | Not shipped until its licence is verified (a build without a verified licence never moves past `candidate`) | Read each before it is qualified |

The model rows name roles only. Which build fills a role is in `models/registry.yaml` and `docs/licences/register.csv`.
