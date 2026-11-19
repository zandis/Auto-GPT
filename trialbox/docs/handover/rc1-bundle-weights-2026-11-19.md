# H-43: the rc1 site bundle's weights and the embedder

- **Card:** H-43 (lane H; lane D's files since 2026-11-19 01:50 UTC)
- **Date:** 2026-11-19
- **Reader:** the lead, the integrator and the owner (section 4 holds their two questions)
- **Findings:** [`rc1-bundle-weights-2026-11-19/findings.json`](rc1-bundle-weights-2026-11-19/findings.json)
  (H43-01 to H43-04)
- **Launch sheet:** [install-rehearsal-sheet-2026-11-18.md](../plan/measurements/install-rehearsal-sheet-2026-11-18.md)
  (H-38), blockers D1 and D2 of its section 6. That sheet is not edited here.

Nothing on this card was run for real. There was no cloud call, no gcloud command, no weight download and no
signing key. `deploy/gcp/box-install-run.sh` was checked statically and through its local rehearsal, which uses
stand-ins.

## 1. What lane D left open, as found on master `a44a39da`

| | As found | Where |
| --- | --- | --- |
| D1 | Both key branches of b05 call `tools/make_bundle.sh` without `--models`. These are the release key (`d_sign`) and the throwaway key (`d_sign_throwaway`). `release check` runs at the end of `make_bundle.sh` and refuses a site bundle without `embedder/` (D-998). So neither branch can build a site bundle today: `make_bundle.sh` removes the signed bundle. The build route never placed weights at all: only the start and dev routes run `d_models_place`. | `deploy/gcp/box-install-run.sh:1262`, `:1276` (unchanged lines) |
| D1, also | `make_bundle.sh --models` read its folder with `find "$MODELS" -type f`, and `tools/bundle_space.py` read it with `rglob`. Neither follows links. A model cache's snapshot files are links to its blobs, and the start route's flat folders are links into that cache. So such a folder would have given an empty or partial bundle. | `tools/make_bundle.sh:181`, `tools/bundle_space.py:49` |
| D2 | `tools/fetch_weights.py` plans `PROFILE_PAIRS` only: the pair and the judge's template. It does not plan `embedder/`. | `tools/fetch_weights.py:314` (`plan`) |
| D2, the gap | The `e-embed-1` row of `models/registry.yaml` names its repository, its revision and the expected manifest digest `e131f320…`. It has **no `expected.source`**: no committed record that lists the 18 files with their sizes and sha256s. The per-file list exists only in the bucket (`r2/models/e-embed-1.sha256`, sha256 and path, no sizes). `box_vm.py models-place` reads it from there. | `models/registry.yaml:587-618`; `deploy/gcp/box-run.sh:671` |

## 2. What changed

**D1: the build route passes the weights, with either key.**

- `box-install-run.sh` b05 (`step_b_sign`) first runs `d_bundle_models`, before either key is touched:
  - It places the weights as the start route does. This is `d_models_put`, the placement half of `d_models_place`,
    split out unchanged: `box_vm.py models-place` links the VM's model cache, fetches the judge's template and
    `embedder/` from their pinned public sources, and checks each file against its sha256.
  - It then lays out `$BUILD/bundle-models` as links, in the layout the profile's compose file reads: the
    `tb-model-links` folder names, the template's path and `embedder/`.
  - A VM without them stops at b05 with `TB-NO-WEIGHTS` or `TB-NO-EMBEDDER`.
- Both `make_bundle.sh` calls now end with `--models "$BMODELS"`.
- A run without weights changes only in where it stops. It used to stop in `make_bundle.sh`, at `release check`. It
  now stops at b05, before the key is read.
- `box-run.sh`: a `--steps build` launch now sets `tb-embed-list` (default `$BUCKET/r2/models/e-embed-1.sha256`) in
  both modes. Before, it was set for validation `start` launches only.
- `make_bundle.sh` reads `--models` with `find -L`. `bundle_space.py` uses `os.walk(followlinks=True)`. A folder
  without links reads as before.

**D2: `fetch_weights --embedder`, opt-in.**

- `--embedder` adds `embedder/` (`tools.pin_model.EMBED_PIN`, the folder that compose mounts and that
  `release check` reads). It is taken from the `e-embed-1` row by the same verified route as the pair:
  `expected.source` must name a record whose file list hashes to `expected.manifest_sha256`. `--dry-run` lists it,
  and `--verify-only` checks it.
- **With today's registry, `--embedder` stops with exit 2.** The message says what is missing (H43-01). No address,
  list or hash was invented.
- Without `--embedder`, the run, its CLI and its output are as before.
- The flag is opt-in, not the default, because a default embedder would make every run of the pair exit 2 until
  H43-01 is closed.
- So the rule "fetch_weights fetches every weight the release check requires" is **not** in force yet, and no
  decision record was written (D-1324 is not taken).
- Once H43-01 lands, `--embedder` could become the default. That change would be the decision record.

**Docs.**

- RUNBOOK §1, the vendor's build paragraph: what `--models` holds, that it is read through links, that `embedder/`
  is required, and how the folder is filled.
- RUNBOOK §11, Build (R2): b05 places the weights and passes them with either key.
- RUNBOOK §27 (the workstation install) is unchanged. It fetches the pair for a workstation, not a bundle, and the
  workstation card (PR #1144) is editing around it.

## 3. Tests

- **New**, `tests/unit/test_h43_bundle_weights.py` (12 tests; synthetic files, a loopback stand-in hub):
  - `--embedder`: a dry run lists it and asks for nothing. A fetch verifies it, and `release check`'s
    `embedder_problems` accepts the fetched files.
  - A row without its file record is refused with exit 2, and the pair alone is unaffected.
  - The repository's registry either gives the embedder or says what is missing.
  - `make_bundle.sh`'s own models loop and `bundle_space` read through links.
  - Both key branches pass `--models` after `d_bundle_models`.
  - `d_bundle_models`, run as written with stand-ins, lays out the folder; without `embedder/` it stops.
  - The driver names the embedder list for a build.
- **Rehearsal** (`tests/rehearsal/box-run/`):
  - The stand-in `make_bundle.sh` takes `--models` and refuses one without `embedder/`.
  - The build cases put the "VM's" pair folders and an `embedder/` stand-in in place.
  - `check.py` asserts that the bundle was given the weights in `build`, `build-preempt` and `build-validation`.
  - No assertion was removed or weakened.

## 4. D3: the rc1 bundle's two open questions (not decided here)

Lane D's phrase was "the key, and `--release-seq`". Neither is in the repository as a question. Below is what the code
supports today.

### Question 1: which key signs the rc1 site bundle?

| Option | How the code does it | What it needs | What the bundle is |
| --- | --- | --- | --- |
| a. The release key, on the cloud build VM | `box-run.sh --steps build --release-id <ID> --release-seq <N> --commit <sha> --key-version <V>`; b05 `d_sign` reads the secret `TB_VENDOR_KEY_SM_NAME` (default `tb-vendor-signing-key`) version V as `tb-bundle-signer` into tmpfs (runbook §11) | the owner's key in Secret Manager at a known version, the account's grant, `r2/keys/vendor_ed25519.pub` in the bucket (b06 verifies with it), the same public key given to each site out of band (RUNBOOK §1), the release gates green in enforcing mode, `r2/models/e-embed-1.sha256` in the bucket, a GPU VM whose model cache holds the pair, and about 110 GB free on the build disk (H-38 §3) | a release |
| b. A throwaway key, on the cloud build VM | `--mode validation`; b05 `d_sign_throwaway` makes a key in tmpfs, and only its public half leaves the VM | nothing from the owner | **not a release**: `records/bundle.json` says so, the gates ran in report mode (`release check` prints "not a green release"), and a box that trusts the release key refuses it. The rehearsal follower takes any key (H-38 §3), and the owner's workstation does not |
| c. The release key, on a vendor machine | `make release-bundle BUNDLE_ARGS="--key <file> --id <ID> --release-seq <N> --out ... --models <folder>"` | the key file on that machine, the images built and gated there, a models folder laid out as above (today only by hand or by models-place: `fetch_weights --embedder` waits on H43-01), and the disk | a release |

### Question 2: what `--release-seq` does rc1 take?

What the code does:

- `make_bundle.sh` requires `--release-seq`; it has no default. The value is signed into the manifest and into
  `release.json`, and the two must agree.
- A new site has no `installed.json`, which reads as `release_seq` 0, so it takes any value of 1 or more.
- Every later update must be strictly above the installed value. Anything else is refused unless an audited
  `--allow-downgrade REASON` is given (`tools/verify_update.py:268-283`).
- The tree's floor, `MIN_INSTALLED_SEQ` in `tools/trialbox/prestart.py`, is 0.
- No ledger in the repository records which value each signed bundle took.

| Option | What it needs |
| --- | --- |
| a. `1` (the first release) | A rule that rc2 and GA take 2 and up. Validation builds also used 1 (runbook §11), but they are signed by throwaway keys, so they never meet a release-key box. |
| b. A higher value, as in the examples (`3` in runbook §11, `box-run.sh`, `make_bundle.sh --help`) | Nothing in the code. Only a stated reason, since nothing below it was ever issued. |
| c. A value derived from the id or the date | A code change: today the value is a plain integer, and nothing derives it. |

Under every option, rc1's value is what every rc1 site's next update must exceed. Someone has to keep a record of
the values issued. The repository has none (H43-03).

## 5. Not run, not verified

- **No real bundle was built.** On the build VM, a real build must show:
  - b05's notes name `bundle_models` with the two pair folders, `chat-templates` and `embedder`;
  - `make_bundle.sh` prints `==> models from .../bundle-models` and lists about 48 files: the judge's 12, the
    verifier's 17, the template, and the embedder's 18;
  - `bundle_space` asks for about 110 GB, then the bundle comes out at about 60 GB;
  - `release check` passes with no `embedder/` line;
  - `release check` and b06 show the gates in block mode for a release.
- **The start route was not checked with a bundle that carries weights.** It still binds the VM's `/models` over
  `deploy/models` (H43-04).
- `box_vm.py models-place` was not re-run. It is unchanged and covered by its own tests.

## 6. Checks

The results are in the card's report to the lead.
