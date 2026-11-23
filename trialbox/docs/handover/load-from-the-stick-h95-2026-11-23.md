# Load from the stick, in two packs (2026-11-23)

**Reader:** the people who build TrialBox: lane H, the integrator and the independent reviewer.

Card H-95 (high-risk: it changes what the installer verifies and loads). The rulings: the integrator's 7092830629
(load straight from the stick; peak free-disk use at most the installed size plus 10 %, measured by a test; the sizes
on the install page) and 7092940586 (a software pack and a model pack, each signed on its own; the box refuses a
software pack whose model pack it does not hold); 7092087958 and 7095256773 (the five stops of a PoC box);
7092045961 (a guard on the install path rides with a test on the real install path in the rehearsal job);
7097604232 (`make_bundle.sh` refuses a pinned image given without a digest). Decision: D-1094.

## Pull request body (draft)

**Why.** The walk's install on the bench host stopped at step 1 for disk: on a 60.7 GB bundle the free disk fell
from 79 GB to 14 GB. Where it went: `tools/verify_update.py` staged every payload into `TMPDIR` (a full copy of the
bundle), `deploy/install.sh` ran it twice (its `--dry-run`, then the load), and `copy_models` copied the weights again
into the models folder while the stage still held them.

**(a) Load from the stick.** `tools/apply_update.sh` runs the verifier with `--stream image --stream model`: those
payloads are hashed on the stick like every other payload and staged nowhere. The small ones (host tree, rule sets,
reference data, other files) are staged as before. The update path (`tools/trialbox/update.py`) gets the bundle
(`--bundle`; refused unless its `manifest.json` is the one verified) and reads each image archive and weight file
from where it lies in the bundle:

- a weight file is written to `<models>/<path>.part`, hashed as it is written, renamed to its name only when its
  sha256 is the signed one; a mismatch removes the `.part` and fails the load (`stream_models`);
- an image archive goes into `docker load` on its standard input, hashed as it goes, with its last MiB held back
  until the whole sha256 is known: on a match the tail follows and the load completes; on a mismatch the load is
  killed with its archive cut short, and every tag, image id and index digest the archive names is removed
  (`stream_image`).

**When each hash is checked.** (1) In the verify pass, before any payload is acted on: the signature, then every
payload's size and sha256, read from the stick (stop (1), as before; `install.sh` runs it for both packs before
either is loaded). (2) Again on every image and weight file while it streams in, which catches a stick that changes
between the two reads: a payload whose second read fails its hash is never loaded. Each pack's whole-file sidecar
(`.sha256`) is checked by `install.sh` too, as before.

**Disk.** The first load's own space check (stop (2)) counts what it writes (images into Docker's data root, weights
into the models folder, the host tree unpacked, other files), no copy of the bundle. `install.sh` prints, from the
signed manifests, before it loads: `disk: installed size …; peak during the load …, at most … (installed + 10 %); the
stick holds …` (`tools/packs.py sizes`).

**(b) Two packs.** Manifest 1.4.0 adds an optional `pack`: `{"kind": "model"}` (payload kinds image and model only)
or `{"kind": "software", "requires_model": {"bundle_id", "manifest_sha256"}}` (no weights). The model pack's identity
is its bundle id and the sha256 of its signed `manifest.json`, the bytes its signature covers; never a file or folder
name. The box records the model pack it holds in `deploy/updates/model-pack.json` (`installed.json` stays the
software's release). The verifier refuses a software pack whose model pack is not that record (stop (1)), naming the
model pack's bundle id and manifest sha256; a model pack's `release_seq` is compared with that record. A pack
carries no key rotation. `tools/make_bundle.sh --model-pack-out DIR/trialbox-models-<id>.pack` builds both (the
engine image: every image whose repository `deploy/images.lock` pins with a `gpu` entry; the weights: `--models`);
`--model-pack FILE` builds a software pack alone for an existing model pack. `install.sh` takes `--model-pack FILE`,
else finds the model pack beside the bundle by identity (`tools/packs.py find`), verifies both (the software pack's
dry run with `--with-model-pack`, dry run only), then loads the model pack, then the software pack.
`tools/apply_update.sh` takes a software pack alone. The launcher takes only `trialbox-*.tar` as a release, so the
`.pack` beside it changes nothing there.

**The old single bundle** keeps installing (D-1094): a manifest without `pack` is verified and loaded as before, and
also streamed. It counts as holding both packs: installed now with weights, it is recorded in `model-pack.json` with
`whole` set; on a box installed before H-95 (no `model-pack.json`), its `installed.json` record stands for it (a box
that took a software pack always has the file, its model pack loaded first). A later software pack names that whole
bundle as its model pack (`make_bundle.sh --model-pack <the whole bundle>`). A whole bundle's record does not order
model packs: the first model pack after it is compared with none.

**The record is trusted state.** `deploy/updates/model-pack.json` is written only by the update path (apply_update.sh,
as root), atomically, 0600. The verifier and the update path refuse a link, a file another user owns (running as
root) or one others may write; its path is set by apply_update.sh from its own folder, never from a caller's
variable.

**One reader.** What is loaded is exactly what is hashed: each streamed payload is read once, front to back, through
one open of the bundle, and every chunk is hashed and handed on (the image's tail only after the whole hash). Reading
a docker archive's own manifest.json to name its tags (before loading, for the pins check) is a separate read; a
stick that changes between that read and the load fails the load's hash.

**TMPDIR** is a caller's variable: the verifier stages the small payloads in a folder mktemp makes there, 0700 and the
installer's own (apply_update.sh also sets the mode), removed on exit; no image or weight is written there.

**The sizes first, and stop (2).** Before the stick is read whole, `install.sh` prints the three sizes and runs
`tools/packs.py space`: per file system, what the load writes there at its peak (images in Docker's data root,
weights in the models folder, the small payloads staged, the host tree and other files beside deploy/), against its
free space. Short: the install stops with the numbers, nothing loaded (H-94 (2)). A pack the box already holds is
not counted, so a run again is not refused for the space it used. A manifest that cannot be read is left to the
verifier (stop (1)).

**(c) Digest pins.** `make_bundle.sh` refuses, before anything is exported, an image whose repository
`deploy/images.lock` pins by digest (third_party) given by `--image` without `@sha256:`: such a bundle carried no
`image-pins.json`. Not covered: the default list, which compose renders from the compose files, takes an image
variable the caller exported (a plain tag there passes); checking it there changes what the existing make_bundle
tests' stand-in compose answers, so it is a question to the lead.

**Harm each guard stops (7092045961).** The software pack without its model pack: a box whose software expects
weights or an engine it does not hold starts and fails at its first screen. The second hash on the way in: a stick
that changes between the verify pass and the load would load bytes nobody verified. The digest refusal: a bundle the
box cannot start offline. The first load's space check replaces the verifier's old stage check (stop (2)).

**PRODUCTION's refusals.** Every refusal that existed keeps its words and exit code. Changed assertions: none.

**Measured.** `tests/unit/test_load_from_the_stick_h95.py` builds a model pack and a software pack of the walk's
parts scaled down (weights 40 MiB in four files, an engine image of 9 MiB, seven images of 1 to 3 MiB, 80 KiB of
small files) and runs the real `tools/apply_update.sh` four times as `install.sh`'s bundle step does (both dry runs,
then each load), with a stand-in docker that keeps the layers it loads in a folder of its own. A sampler sums the
allocated blocks of the box folder, `TMPDIR` and the stand-in's data root for the whole step. Measured: installed
65,224,704 bytes, peak 65,323,008 bytes (1.0015 of the installed size; the bound 1.10). With the verifier staging
every payload again (mutant M1 below) the test fails.

**Real install path (the rehearsal job).** `tools/rehearse_box/rehearse.sh` builds the media as two packs
(`--model-pack-out`); the install step runs the real `install.sh` on them (model pack found beside the bundle,
verify, load from the stick, the signed re-run); `media-negative` runs `install.sh` on the software pack alone and
expects the refusal by the model pack's identity, nothing written.

**Mutants planted and caught** (each restored after): M1 the verifier stages streamed payloads; M2 an image's tail
sent whatever its hash; M3 a weight file renamed before its hash is compared; M4 no clean-up after a cut image
stream; M5 the software pack check off; M6 the model pack named by bundle id only; M7 the digest check passes; M8 a
model pack ordered by `installed.json`. All eight caught.

**Not run or not verified here.** No Docker daemon in this session: the rehearsal job (its two-pack media, the
install from them, the new `media-negative` case) and a real `make_bundle.sh` build of two packs were not run; CI's
rehearsal runs them. What a real `docker load` writes inside its data root while it loads is not measured (H95-02; measured on the
bench host after H-95 merges). After a cut image stream, a real engine may keep what it wrote in flight (the classic
store's temporary folder, removed when the request aborts; the containerd store's ingest, until its next clean-up):
the stand-in's in-flight folder stands for that, and the test holds that no tag and no image id of the archive stays.
`install.sh`'s space stop is held by `tests/unit/test_load_from_the_stick_h95.py` on `tools/packs.py`; a refusing run
of the real `install.sh` is not in the rehearsal (its host has the space).
The bench's size breakdown was not found on #639 (H95-05); the per-pack sizes on the install page wait for it.

**Found by this card's own tests, fixed before review.** A model pack's first load wrote `trust.json`, which
`box_in_service` reads as a box in service: the software pack's load after it was refused. Now the model pack's
first load leaves `trust.json` to the software pack (a pack carries no rotation).

## Findings

`load-from-the-stick-h95-2026-11-23/findings.json` (H95-01 to H95-05), in the register's `--add-from` form.
