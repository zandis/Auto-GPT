# Recorded `image inspect` answers of the two image stores (H-149)

Synthetic, written by hand from the container engine's documented formats; no real host or image content.

- `hapi-config.json`: the image config a `save` archive carries for a stand-in of the pinned FHIR image (three
  synthetic layer diff ids). Its sha256 is the image id the bundle pins.
- `hapi-manifest.json`: the OCI manifest that names that config and those layers. Its sha256 is the id the
  newer image store gives the loaded image.
- `inspect-classic-store.json`: `image inspect` of the loaded image on the classic store (major version 28 and
  before): `Id` is the config digest, `RepoDigests` is empty, `Config` carries the container fields.
- `inspect-newer-store.json`: the same image on the newer image store (the default from major version 29): `Id`
  and `RepoDigests` name the manifest digest, never the config digest; `Config` carries the image config's fields
  only; `Descriptor` names the manifest.

Both answers agree on `RootFS.Layers`, `Architecture`, `Os` and the run fields of `Config`: what
`tools/image_pins.py` proves the image by.
