# Licence inventory of a release, and the list for the owner's lawyer

**Reader:** the owner and the owner's lawyer; the vendor who signs a release. It rides in every release bundle as
`sbom/licence-inventory.md` (`tools/make_bundle.sh`), beside the generated report `sbom/licences.md`.

- **Card:** INT-M10-min, item a (the integrator's 7184086631, item 2a). Base `int/system` 0894674f.
- **Date read:** 2026-11-26. Every licence below was read in its file on that day, or is marked **not verified**.
  Nothing is filled from memory. Only the licence identifier and where it was read are recorded.

## 1. What a release carries, and which part is generated

| File in the bundle | Written by | What it covers |
| --- | --- | --- |
| `sbom/licences.md` | `make release-gates` (the licence report of `tools/supply_chain/licences.py`) | Every Python package of `requirements.lock` and every package of every image, read from the CycloneDX SBOMs (the lock's SBOM and one SBOM per image, written by the scanner the images workflow already runs). Flags LGPL, GPL, AGPL, unknown and dual licences; the gate fails on a flag the allow-list does not accept |
| `sbom/*.cdx.json`, `sbom/index.json` | `make lock-sbom`, `make release-gates` | The SBOMs themselves |
| `NOTICE` | the repository | The notices and licence texts the shipped components require |
| `sbom/licence-inventory.md` | this page, by hand | The from-memory licence claims checked against their files (section 3) and the list for the lawyer (section 4) |

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
  keeps attachments and outputs on a filesystem volume (`objects-data`; D-121 removed the object store). A field
  name in some tools still says so; it is not an image.

### The vector store and the FHIR server

Two images the box runs hold its data. Each licence was read in the project's own LICENSE file on 2026-11-26.

| Image (`deploy/images.lock`) | What runs in it | Licence read | Where |
| --- | --- | --- | --- |
| `db` (`trialbox-postgres`, built by `deploy/docker/db.Dockerfile`) | PostgreSQL 16 | PostgreSQL | the project's `COPYRIGHT`, master |
| the same | pgvector 0.8.x, the vector store | PostgreSQL | the project's `LICENSE`, master |
| the same | PGroonga, full-text search | PostgreSQL | the project's `COPYING`, main |
| `hapi` (`hapiproject/hapi`) | the HAPI FHIR JPA server, the FHIR server | Apache-2.0 | the starter project's `LICENSE`, master; the library's `LICENSE.txt`, master |

Their packages also come into `sbom/licences.md` through each image's SBOM at release.

## 3. Licences the reviews took from memory, checked in their files

The three lists: the component and ecosystem review of 2026-11-09
(`docs/reviews/2026-11-09-component-review-layer1.md`, line 324: thirteen items marked unverified or from memory,
counted here in their order), the build-versus-reuse review of 2026-11-12 (`docs/reviews/2026-11-12-build-vs-reuse.md`,
every licence marked `[M]`, by its line) and the open ecosystem survey (`docs/plan/design/05-open-source-reuse.md`,
TB-DS-05, every row whose checked column says unverified, by its line). Each row
names the claim by where it stands, not by the outside project's name: the review names it. For each, the licence
identifier of the LICENSE file read in the project's own repository (which file, on which branch) and of its release
page. A Python package's release page is its PyPI page. A GitHub release page could not be read from this session
(refused), so those are **not verified**.

| Claim | Said | LICENSE file read | Release page | Agrees |
| --- | --- | --- | --- | --- |
| layer 1, line 324, item 1 | Apache-2.0 | **not verified**: no LICENSE, LICENSE.md, LICENSE.txt or COPYING on main or master | not verified | not verified |
| layer 1, line 324, item 2 | unverified | Apache-2.0 (master/LICENSE) | not verified | read |
| layer 1, line 324, item 3 | unverified | Apache-2.0 (main/LICENSE) | PyPI: Apache-2.0 | read |
| layer 1, line 324, item 4 | not fetched | MIT (master/LICENSE) | PyPI: MIT | read |
| layer 1, line 324, item 5 | not fetched | MIT (master/LICENSE) | PyPI: MIT | read |
| layer 1, line 324, item 6 | not fetched | Apache-2.0 (main/LICENSE) | PyPI: Apache-2.0 | read |
| layer 1, line 324, item 7 | not fetched | **not verified**: the PyPI page names no source repository | PyPI metadata: MIT | not verified |
| layer 1, line 324, item 8 | unverified | Apache-2.0 (master/LICENSE) | not verified | read |
| layer 1, line 324, item 9 (two capabilities) | from its docs | Apache-2.0 (master/LICENSE) | not verified | licence read; capabilities not verified |
| layer 1, line 324, item 10 (a capability) | from memory | Apache-2.0 (main/LICENSE.txt) | not verified | licence read; capability not verified |
| layer 1, line 324, item 11 (a capability) | from memory | Apache-2.0 (main/LICENSE) | not verified | licence read; capability not verified |
| layer 1, line 324, item 12 (a capability) | from memory | PostgreSQL (main/COPYING) | not verified | licence read; capability not verified |
| layer 1, line 324, item 13 (a capability) | from memory | Apache-2.0 (main/LICENSE) | PyPI: Apache-2.0; the capability not verified | licence read; capability not verified |
| build-vs-reuse, line 192 | MIT | MIT (main/LICENSE) | PyPI: MIT | yes |
| build-vs-reuse, line 220 | BSD-3-Clause | BSD-3-Clause (main/LICENSE) | not verified | yes |
| build-vs-reuse, line 245, first tool | Apache-2.0 | Apache-2.0 (master/LICENSE) | not verified | yes |
| build-vs-reuse, line 245, second tool | Apache-2.0 | **not verified**: no LICENSE file on main, master or develop | not verified | not verified |
| build-vs-reuse, line 293 | Apache-2.0 | Apache-2.0 (main/LICENSE) | PyPI: Apache-2.0 | yes |
| build-vs-reuse, line 335 | Apache-2.0 | Apache-2.0 (main/LICENSE.md) | PyPI: Apache-2.0 | yes |
| build-vs-reuse, line 354, both | Apache-2.0 | Apache-2.0 (master/LICENSE; main/LICENSE) | not verified | yes |
| build-vs-reuse, line 364 | Apache-2.0 | Apache-2.0 (master/LICENSE.md) | not verified | yes |
| build-vs-reuse, line 399 | MIT | MIT (main/LICENSE) | PyPI: MIT | yes |
| build-vs-reuse, line 405, first | Apache-2.0 | Apache-2.0, with an MIT notice for an included part (master/LICENSE) | not verified | yes, the MIT part named |
| build-vs-reuse, line 405, second and third | Apache-2.0 | Apache-2.0 (main/LICENSE, both) | not verified | yes |
| build-vs-reuse, line 411, first | BSD | BSD-3-Clause (master/LICENSE) | PyPI: BSD-3-Clause | yes |
| build-vs-reuse, line 411, second | Apache-2.0 | Apache-2.0 (main/LICENSE) | not verified | yes |
| build-vs-reuse, line 447 (two services) | AGPL-3.0 | **not verified**: no source repository read | not verified | not verified |
| build-vs-reuse, line 451 | Apache-2.0 | Apache-2.0 (main/LICENSE) | PyPI: Apache-2.0 (its own package name; the bare name on PyPI is another project) | yes |
| build-vs-reuse, line 463, both | Apache-2.0 | Apache-2.0 (main/LICENSE, both) | one on PyPI: Apache-2.0; the other not verified | yes |
| build-vs-reuse, line 488 | MIT | MIT (master/LICENSE) | PyPI: MIT | yes |
| TB-DS-05, line 42 | Apache-2.0 | Apache-2.0 (master/LICENSE.txt) | not verified | yes |
| TB-DS-05, line 43 | Apache-2.0 | Apache-2.0 (main/LICENSE.txt) | not verified | yes |
| TB-DS-05, line 45 | Apache-2.0 | Apache-2.0 (main/LICENSE) | not verified | yes |
| TB-DS-05, line 47 | proprietary (unverified) | **not verified**: no public repository | not verified | not verified |
| TB-DS-05, line 48 | proprietary freeware | **not verified**: no public repository | not verified | not verified |
| TB-DS-05, line 67 | Apache-2.0 | Apache-2.0 (main/LICENSE) | not verified | yes |
| TB-DS-05, line 71 | (no licence stated) | nothing to read | not verified | not applicable |
| TB-DS-05, line 124 | MIT core, a separate licence for one folder | MIT, with that folder under its own licence (main/LICENSE) | not verified | yes |
| TB-DS-05, line 125, both | Apache-2.0 | Apache-2.0 (master/LICENSE, both) | not verified | yes |
| TB-DS-05, line 126 | AGPL-3.0 | AGPL-3.0 (main/LICENSE) | not verified | yes |
| TB-DS-05, line 137 | model terms unverified | **not verified**: the model card was not read | not verified | not verified |
| TB-DS-05, line 141 | an open licence (unverified) | **not verified**: the licence page was not read | not verified | not verified |
| TB-DS-05, line 143 | Apache-2.0 for the code | Apache-2.0 (master/LICENSE); each pretrained model's terms not read | not verified | yes, for the code |
| TB-DS-05, line 261 | AGPL-3.0 | **not verified**: its repository is not on a host this session could read | not verified | not verified |
| TB-DS-05, line 262 | LGPL (unverified) | LGPL-2.1 or LGPL-3 for the core, with BSD-3-Clause, CC-BY-SA-3.0 and GPL-3 parts (main/COPYING) | not verified | yes, with the other parts named |

Not checked: the `[M]` marks of the build-versus-reuse review that state no licence (what a tool does, a hosting
price, a maintenance state), and the versions and activity TB-DS-05 marks unverified. Three of the projects above run
in a TrialBox image (layer 1, items 9 and 12; TB-DS-05, line 42), and their packages are also in `sbom/licences.md`.
For the rest, the check is for whoever adopts one.

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
| The judge model | Apache-2.0 by its licence register row (verified there) and by its model card (read 2026-11-26). Source: the publisher's repository at the revision `models/registry.yaml` pins; the weights' source carries no licence file (`none-in-source`); the base model's own card was not read: **unverified** | Weights loaded on the box; whether a bundle may carry them is marked OWNER in the profile records | May the vendor ship the weights in a bundle, and under which terms and use policy? |
| The verifier model | Apache-2.0 by its licence register row and by its model card (read 2026-11-26). Source: the publisher's repository at the pinned revision; the licence file is pinned by sha256 in the registry; the base model's own card was not read: **unverified** | As for the judge | The same question |
| The embedder | MIT by its licence register row and by its model card (read 2026-11-26). Source: the publisher's repository at the pinned revision; the base model's own card was not read: **unverified** | Weights loaded on the box and pinned at install | The same question |
| A model a site or profile adds later (a second judge, a hosted model) | several are `verified: false` in `models/registry.yaml` | Not shipped until its licence is verified (a build without a verified licence never moves past `candidate`) | Read each before it is qualified |

The model rows name roles only. Which build fills a role is in `models/registry.yaml` and `docs/licences/register.csv`.
