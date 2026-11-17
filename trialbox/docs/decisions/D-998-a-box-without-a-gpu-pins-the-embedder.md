# D-998 a box without a GPU pins the embedder, and every site bundle carries it

- **Task:** H-22 card 2 (lane D): lane H's finding 5 (#993), under the owner's ruling D-1066 of 2026-11-17 ("Option
  a": a no-GPU PRODUCTION box is a product form), given by the integrator on #639
- **PR:** this branch (`agent/H22-STUB-a-no-gpu-production-box-embeds`), stacked on H-22 card 1 (D-996)
- **Date:** 2026-11-17
- **Status:** accepted
- **Builds on:** D-1066 (the ruling), D-563 (ENG-003: the embedder every box runs), D-429 (the embed service loads its
  pinned weights only), D-142 (the installer pins), D-726 (rehearsal bundles)

## Context

On a PRODUCTION box installed with `--mode stub`, lane H saw every service become healthy except `embed-service`. It
refused to start: "EmbedderRefused: no pin for e-embed-1". Three things combined:

- the installer pinned models only in GPU mode, where `pin_model --install <gpu>` pins the pair and the embedder;
- the embed service refuses an unpinned embedder in PRODUCTION only. DEV, TEST and VALIDATION run its hash stub, and
  so do the rehearsal's stand-ins. That is why no test saw it;
- no bundle check required the embedder's weights.

The box form's no-GPU board (`tools/box/plan.py`) installs the same way. The owner ruled that such a box is a product
form: a feasibility-only site, which may add a GPU later.

## Decision

1. **`pin_model --install-embedder`** pins `e-embed-1` alone, strictly. `install_pins` tolerates a missing embedder
   beside the pair; this does not. Each of these fails, and nothing is written:
   - no weights;
   - other weights (not the registry's expected manifest);
   - an earlier pin that is not the expected manifest.

   An existing good pin is kept. `--registry` names the registry; the default is the release's.
2. **`install.sh` in stub mode** runs it with the box's `TB_ENV`, then runs `--verify-all`. Before this change,
   `--verify-all` ran in GPU mode only; it now runs in both modes, between `# ---- PINS` and `# ---- end of PINS`.
   - A failure stops a PRODUCTION install.
   - On DEV, TEST or VALIDATION a failure is a warning, because the embed service runs its hash stub there.
3. **Every site bundle carries the embedder.** `tools/release.py` `embedder_problems`, run by `release check` and so
   by `make_bundle.sh`, refuses a bundle whose `embedder/` files, as the signed manifest lists them, do not hash to
   the registry's expected manifest for `e-embed-1`.
   - The bundle is checked from the manifest's per-file sha256, in the pin's own format, so 2.3 GB is not read again.
   - A rehearsal bundle (D-726) is exempt: a site box refuses it, and its placeholders are no model.
   - The unit tests' synthetic bundles carry a synthetic embedder under a synthetic registry (`TB_RELEASE_REGISTRY`,
     tests only).
4. **The box plan and the installer agree.** The plan's no-GPU board installs with `--mode stub` on PRODUCTION
   (D-822). That is the branch that now pins the embedder.
5. **RUNBOOK §1 says what such a box does and does not do.**
   - It does: feasibility and screening on the structured criteria.
   - It does not: criteria that need a note's free text wait for a GPU or a pinned cloud model.
   - The embedder is pinned on the CPU from the bundle.

## What it costs

- **Bundle size:** every site bundle grows by the embedder's folder: BGE-M3 at revision 7b44caba, 18 files,
  **2,295,165,682 bytes** (`models/registry.yaml`, hashed by lane G on 2026-11-12). A GPU bundle already carried it
  for its own pin.
- **Build time:** `make_bundle.sh` copies and hashes those files once more. That is not timed here, because the
  weights were not downloaded (no model download, the hard rules).
- **CPU speed:** how fast the CPU embeds at a hospital's size is **not measured**. The repository holds estimates
  only:
  - 5–15 chunks/s on a CPU (`docs/reviews/2026-11-09-dataflow-lifecycle-review.md:705`);
  - a benchmark of 754 docs/s with no device stated (`docs/reviews/2026-11-09-assessment-and-tasks.md:20`).

  The clean cloud VM run below gives the figure (also planned as G-8 and G-11).

## What is proven, and what is not

Proven by unit tests:
- the strict pin, its refusals and its command line;
- the installer's wiring;
- the bundle rule, in three cases: refused without the embedder, accepted with it, rehearsal exempt;
- the existing release tests, with an embedder now in their bundles;
- the plan and the installer agreeing.

Not proven: "a PRODUCTION stub box with every service healthy, embed-service included". In PRODUCTION the embed
service loads the real 2.3 GB weights and checks them against the registry's digest, which needs a model download.
No CI run fetches them (the integrator, 2026-11-17): the proof, and the CPU speed, are the clean cloud VM run below.

## The proof on a clean cloud VM (the integrator's run, after this card is on master)

No model is downloaded in CI (the integrator, 2026-11-17). The proof is a by-hand run on a clean Ubuntu 24.04 VM with
no GPU, as the GPU launches fetch their pinned weights. On the build machine (a checkout of the commit on master):

```sh
# 1. the embedder at the pinned revision, without the three pickle files (D-429); ~2.3 GB from huggingface.co
python3 -m pip install --user huggingface_hub
python3 -c "from huggingface_hub import snapshot_download; snapshot_download('BAAI/bge-m3', \
  revision='7b44caba5c06fd6f1ef1d2786261e636c38e4295', local_dir='vendor-models/embedder', \
  ignore_patterns=['pytorch_model.bin', 'colbert_linear.pt', 'sparse_linear.pt'])"
rm -rf vendor-models/embedder/.cache   # hidden, and outside the manifest either way
# 2. it is the registry's: must print e131f3203849cd7ba89144fdefce52c950bd748c285c2235c1f5628ddcc6e895 18 2295165682
PYTHONPATH=libs:. python3 -c "from pathlib import Path; from tools.pin_model import weight_manifest as w; \
  m = w(Path('vendor-models/embedder')); print(m.sha256, m.files, m.bytes)"
# 3. a site bundle with it (release check refuses one without it), a throwaway key
make images && make trivy-db
PYTHONPATH=libs:. python3 tools/sign_bundle.py keygen --out vm-keys
make release-bundle BUNDLE_ARGS="--key vm-keys/vendor_ed25519.key --id vm-stub-1 --release-seq 1 \
  --out dist/trialbox-vm-stub-1.tar --models vendor-models"
```

On the VM, as root, with the four files of `dist/` on the stick and `vm-keys/vendor_ed25519.pub` beside it, RUNBOOK
§1's first command with a box without a GPU and a PRODUCTION environment:

```sh
cd /media/usb && openssl pkeyutl -verify -pubin -inkey /root/vendor_ed25519.pub -rawin -in trialbox-bootstrap.sh \
  -sigfile trialbox-bootstrap.sh.sig && bash trialbox-bootstrap.sh trialbox-vm-stub-1.tar \
  --pub /root/vendor_ed25519.pub -- --mode stub --environment PRODUCTION --answers /root/site/site.yaml --yes
# every service healthy, embed-service included; its pin is the registry's
docker compose --project-directory /opt/trialbox/deploy ps --format '{{.Service}} {{.Health}}'
grep -A3 'e-embed-1' /opt/trialbox/deploy/site/registry.site.yaml
# CPU embedding speed: N chunks of about 200 words each, in the running service's own embedder
docker compose --project-directory /opt/trialbox/deploy exec -T embed-service python -c "
import time; from embed_service.embedder import service_embedder
e = service_embedder(); n = 2000; chunk = ' '.join(['synthetic clinical note text'] * 50)
t = time.perf_counter(); e.embed([chunk] * n); s = time.perf_counter() - t
print(f'{n} chunks in {s:.1f} s: {n / s:.1f} chunks/s on the CPU')"
```

What to send back: the `ps` lines, the pin and the chunks/s line. §1 and this record say "not measured" until then.

## Remains

- These build bundles for a site box without the embedder; with this rule, `release check` refuses them until they
  pass it under `--models`:
  - `deploy/gcp/demo-vm-update.sh` and `deploy/gcp/box-install-run.sh` (paid VMs, run by hand, not lane D's);
  - lane H's `tools.runbook_install bundle`.
- The by-hand or CI measurement of CPU embedding speed.
