# H149: a pinned image from the signed bundle is proved on either image store

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders.

- **Card:** H-149, High, blocks S0 (the integrator's 7168582084 on #1504).
- **Date:** 2026-11-25
- **Findings:** [`h149-image-pins-both-stores-2026-11-25/findings.json`](h149-image-pins-both-stores-2026-11-25/findings.json)
  (H149-01 to H149-04)
- **Files:** `tools/image_pins.py` (the pin record, `resolve`'s third case, `bundle-pins`, write-then-rename with
  fsync for `merge` and `write_env`), `tools/make_bundle.sh` (the pins written by the pin tool), runbook page 01
  (a paragraph at its end), the new test `tests/unit/test_image_pins_both_stores.py` and its fixtures
  `tests/fixtures/image_pins/`.
- **Files outside the card:** none. `deploy/install.sh` is not touched: it calls `tools.image_pins resolve` as before.

## 1. What failed

On a host with the container engine at major version 29, whose default image store is the newer image store, the
install of a signed bundle stopped at "starting the stack": `image pins: MISSING ...: neither on this box by digest
nor loaded from the bundle`. The pin check knew two cases: the digest reference resolves, or the bundle's image id
(the config digest) does. On the newer image store neither does: the loaded image's `Id` is the digest of the manifest
the archive carried, and `RepoDigests` names that manifest, not the registry's.

## 2. What changed

`make_bundle.sh` now writes `image-pins.json` with `python3 -m tools.image_pins bundle-pins`. Each pin is read out of
the saved archive and carries the config digest (`image`), the tag the image was saved under, the layer diff ids
(`rootfs.diff_ids`) and the config fields a container runs by (architecture, OS, variant, entrypoint, command, environment, user, working directory,
volumes, ports, stop signal, labels, health check, shell, on-build). The layers and config are pinned only when the
config blob is the content its digest names and carries diff ids; otherwise the pin is today's (the id only) and
`make_bundle` prints a WARNING that the bundle installs on the classic store only. Refusing there instead is a
question for the integrator: the shared fake engine of `tests/unit/test_release_bundle.py` writes `{}` as every
config, under a name that is not its hash, and a faithful fake changes the image ids those tests assert (H149-04).
The file stays a signed member of the bundle.

`resolve` tries, in order: the digest reference (nothing to set); the config digest (the classic store, as before);
then the image under the pin's tag, whose `RootFS.Layers` must equal the signed diff ids in order and whose config
fields must equal the signed ones, absent and empty being one value. Only then is the compose variable set to the
store's own `Id`: an id the store keeps, so compose neither pulls nor names a digest the store does not keep. Any
difference leaves the variable alone, notes what differs, and keeps the line `MISSING <VAR>: <ref>` (its words are
unchanged). A pin without layers (a bundle from before this card) is not enough on the newer image store.

## 3. Every place that compares an image id or digest

| Place | What it compares | Fate |
| --- | --- | --- |
| `tools/image_pins.py` `resolve` (install.sh before the start, update's restart, pre-start's first step) | digest reference, config digest | fixed here: the third case |
| `tools/trialbox/update.py` `check_loaded` | `.Id` after the load against the archive's config digest and its index.json manifest digests | already both stores; a test on the recorded answer added |
| `tools/trialbox/update.py` `snapshot_images`, the demo box's `snapshot` | `.Id` read to tag a rollback copy | no compare; an id either store gives back |
| `deploy/install.sh` (the loop after `resolve`) | `image inspect` of every image compose names | existence only; the names are the ids `resolve` set |
| `tools/images_lock.py` `host_check` | an image variable that is a `sha256:` id counts as the bundle's copy | holds for the store's own id too |
| `tools/trialbox/platform.py` `image_digests` | a pod's `imageID` against the release digest | a cluster's registry digests, not a loaded bundle: not affected |
| `tools/rehearse_box/box.sh`, `tools/rehearse_box/rehearse.sh`, `tools/runbook_install.py` | `.Id` of running containers against the bundle's image ids | the rehearsal on one engine; not changed, named for the walk |
| `tools/supply_chain/release.py`, `tools/serving_profile.py`, `tools/serving_config.py`, `tools/b200_qualify.py`, `tools/measure48-host.sh` | `Id` and `RepoDigests` on the build or bench host | not on a site box; not changed |
| doctor, the support bundle, restore, the web-front check | no image id or digest compare found (`.Id`, `RepoDigests`, `@sha256`, `image inspect` searched) | nothing to change |

## 4. The invariant and its mutants

`test_the_loaded_image_is_proved_by_its_layers_and_config_or_refused`: on the recorded newer image store answer the
variable is set to the store's own id and nothing else; on thirteen changed answers (a layer differs, missing, one
more, reordered; another entrypoint, command, environment, user, working directory, platform, an added label; no root
file system; no id) nothing is set and the image is `MISSING`. Mutants run against the final code, each killed:

| Mutant | Killed by |
| --- | --- |
| M1 the tag accepted without the compare | the invariant (and the CLI test) |
| M2 only the number of layers compared | the invariant |
| M3 the layers compared as a set | the invariant |
| M4 the config not compared | the invariant |
| M5 a field only the box has ignored | the invariant |
| M6 the config digest written on the newer image store | the invariant (and two more) |
| M7 the tag written | the invariant (and two more) |
| M8 a pin without layers accepted by its tag | `test_a_pin_from_before_h149_is_not_enough_on_the_newer_store` |

Failing first: on master's `tools/image_pins.py` the new file had 9 of 12 failing; the three that pass are the
recorded bench failure, update's load check (already both stores) and the make_bundle text check.

## 5. Not shown

- No container engine runs in the card's container: that compose starts from the store's own id with no pull, and
  that a real engine's answers match the recorded ones, are for the walk on hosts with major versions 28 and 29.
- A bundle made by `make_bundle.sh` was not built here (it needs the engine); `bundle-pins` is tested on a
  synthetic archive.
