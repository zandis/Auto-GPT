# Vendor serving records

`serving_config.<gpu>.json`: the serving-configuration record (`tools/serving_config.py`, schema
`tb-serving-config/1`) of a GPU profile, taken by the vendor on that card, uncapped, running that profile's flags.
`deploy/install.sh` accepts one as the measurement of the profile when the site has no record of its own
(`deploy/site/serving_config.<gpu>.json`); `python -m tools.serving_config measured <gpu> <file>` must pass (D-124).

| file | card | taken by |
| --- | --- | --- |
| `serving_config.rtxpro6000.json` | RTX PRO 6000 Blackwell (96 GB) | `deploy/gcp/gpu-pro6000-run.sh` on tb-gpu-sim |

`serving_config.rtxpro6000.json` was taken with `--enforce-eager` on both servers (its `enforce_eager: true`). Since
D-1359 no profile runs with the flag: the record stays the measurement it was (card, context, sequences, fractions),
and `tools/serving_config.py measured` notes on stderr that start time, memory and rate of the new setting are to
be re-measured on it by the bench. Replace the file with the record of that run.
