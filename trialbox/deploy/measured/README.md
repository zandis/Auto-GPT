# Vendor serving records

`serving_config.<gpu>.json`: the serving-configuration record (`tools/serving_config.py`, schema
`tb-serving-config/1`) of a GPU profile, taken by the vendor on that card, uncapped, running that profile's flags.
`deploy/install.sh` accepts one as the measurement of the profile when the site has no record of its own
(`deploy/site/serving_config.<gpu>.json`); `python -m tools.serving_config measured <gpu> <file>` must pass (D-124).

| file | card | taken by |
| --- | --- | --- |
| `serving_config.rtxpro6000.json` | RTX PRO 6000 Blackwell (96 GB) | `deploy/gcp/gpu-pro6000-run.sh` on tb-gpu-sim |
