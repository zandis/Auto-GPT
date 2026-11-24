#!/bin/sh
# H-121 (OCR 1469-5): the pre-push test set, by rule, from trialbox/; prints one file per line. Run:
#   sh docs/handover/update-size-check-roles-h121-2026-11-24/test-set.sh > /tmp/set.txt
#   .venv/bin/python -m pytest $(cat /tmp/set.txt) -q -p no:cacheprovider -n auto --dist worksteal
# The policy tests (every unit test that reads box.sh, update.py, a workflow, a Dockerfile, the Makefile or a shell
# script), the update path's tests (FakeRun, space_needs, db_bytes, ComposeBox) and the tests of every other module
# the card touches (backup_schedule, fetch_weights, packs).
set -eu
{
  grep -rl --include='test_*.py' -e 'rehearse_box/box.sh' -e '"box.sh"' tests/unit
  grep -rl --include='test_*.py' -e 'trialbox/update.py' -e '"update.py"' tests/unit
  grep -rlE --include='test_*.py' '\.github/workflows|"workflows"|Makefile|Dockerfile|\.sh"\)|rglob\("\*\.sh"\)|glob\("\*\.sh"\)' tests/unit
  grep -rl --include='test_*.py' -e 'FakeRun' -e 'space_needs' -e 'db_bytes' -e 'ComposeBox' tests/unit tests/integration
  grep -rl --include='test_*.py' -e 'backup_schedule' -e 'fetch_weights' -e 'tools import packs' -e 'tools.packs' tests/unit
} | sort -u
