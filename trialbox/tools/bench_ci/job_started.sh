#!/usr/bin/env bash
# The runner's job-started hook (card H-105), before the job's first step: the host's gate (gate.py: only a push or
# the owner's run of master's bench workflow, in this repository; the review's F1), then the CI cards' check (a GPU
# job starts only while its cards are within their cap). Either refusal ends the job here.
set -euo pipefail
python3 -I /opt/tb-bench/gate.py --job /scratch/.tb-bench/job.json
exec python3 -I /opt/tb-bench/gpu_check.py --in-job /scratch/.tb-bench/job.json
