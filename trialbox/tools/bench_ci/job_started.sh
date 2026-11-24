#!/usr/bin/env bash
# The runner's job-started hook (card H-105): a GPU job does not start unless its CI cards are free now (a
# registered runner can wait a while for its job). The card file is the launcher's; a missing one stops the job.
set -euo pipefail
exec python3 /opt/tb-bench/gpu_check.py --in-job /scratch/.tb-bench/job.json
