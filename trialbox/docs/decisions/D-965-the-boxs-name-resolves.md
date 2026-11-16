# D-965 the box's name resolves

- **Task:** OPS-005, lane D backlog (#639, 2026-11-16; the owner's ruling to complete everything as soon as possible)
- **PR:** this branch (`agent/OPS-005-the-boxs-name-resolves`)
- **Date:** 2026-11-16
- **Status:** accepted

## Decision

The box is named `<name>.local`, but the plan's input firewall dropped UDP 5353, nothing set the host name and
nothing started an mDNS responder (deep review OPS-005).

1. `deploy/hardening/apply.sh`: `MDNS=on|off` (default off); on, UDP 5353 is accepted from the clinic sets only.
2. `tools/box/plan.py`: `MDNS=on` for a `.local` box name, off for a DNS name; the IT form's default stays off.
3. `deploy/box-install.sh`: after the apply step the host takes the owner's name and `avahi-daemon` starts, or the
   script says it is missing (root, not WSL2, `.local` names only); the first-run screen also prints the box's address,
   with the certificate warning it brings.
4. RUNBOOK §16 says the same. The root-certificate download page (T-735, the console) is not here; the name on a real
   network is proven by T-213b.

## Test

`tests/unit/test_box_name_resolves.py`: the firewall render with mDNS on, off and invalid; the plan's setting for a
`.local` and a DNS name; the apply step's host name, responder and warning; the screen's address line.
