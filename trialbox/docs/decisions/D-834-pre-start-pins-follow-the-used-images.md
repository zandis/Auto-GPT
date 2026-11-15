# D-834 the start-up step resolves pins for the images the stack runs

- **Task:** I-3 of the independent examination of the bundle and installer path (2026-11-15, #639)
- **PR:** this branch (`agent/I-3-pre-start-pins-follow-the-used-images`)
- **Date:** 2026-11-15
- **Status:** accepted
- **Builds on:** D-574 (OPS-004b, `used`)

## Decision

1. `ComposeBox.resolve_pins` (the release's pre-start step and an update's restart) asks `docker compose config
   --images` and passes it to `image_pins.resolve` as `used`, as install.sh does. A pinned image no service runs is
   "not needed on this box"; a used one the box lacks still stops it. Before, it asked for every pinned image and
   stopped four lines after the installer said Authelia and vLLM were not needed.
2. `test_image_pins.py`'s "stops before the restart" now allows that one read-only `config --images` call and still
   no other compose call.

## Test

`tests/unit/test_prestart_pins_used.py`: before, the unused pin stopped the step and `used` was not passed; after,
all pass, and a used missing pin still stops it.
