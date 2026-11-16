# D-831 install.sh checks the host python3 first and says it is alive while it loads

- **Task:** INSTALL-HOST, the integrator's red of 2026-11-15 from lane G's GPU box (#639)
- **PR:** this branch (`agent/INSTALL-HOST-python-checked-first`)
- **Date:** 2026-11-15
- **Status:** accepted

## Decision

1. In its host step, before anything loads, install.sh checks that the host python3 imports the modules its host
   steps import at the top (`HOST_PY_MODULES`, today `yaml` = python3-yaml). A missing one stops it with the Debian
   package to install and "nothing was changed". On lane G's box PyYAML was missing and install.sh died about 20
   minutes in, after the load. `cryptography` stays out: the host python3 may lack it (kek.py). No python3 at all
   keeps today's notes.
2. The verify and the load each print a line first and, through `alive`, a line a minute on stderr. The load's
   output is prefixed by the shell as it comes (`sed` block-buffered into a pipe or log) with `PYTHONUNBUFFERED=1`.

## Test

`tests/unit/test_install_host_python.py`: before, 5 failed; after, 5 passed. It also pins that every top-level
third-party import of the host modules is in `HOST_PY_MODULES`.

## Correction (2026-11-15, I-8)

Point 1 says more than was seen. On lane G's VM PyYAML was present: the fault was predicted from the code (install.sh's
host steps import `yaml` after the load), not observed on that box. The check stands as a guard for a host without
python3-yaml; the 20-minute figure is the expected cost of that case, not a measurement.
