"""Hermes Agent integration (spec v4 §9; S1-11): pin, hardened profiles, the relay adapter and policy plugin.

Status: pinned to v0.22.2 by tag, commit SHA and multi-arch image digest (``hermes.lock``); the internal mirror is
pending, so only DEV/TEST may run it (upstream digest) and VALIDATION/PRODUCTION refuse it (``lock.py``). The
profiles are real v0.22.2 configurations checked against the vendored source (``contract.py``). ``channels.engine``
stays ``native`` by default (OPS-02) until the relay -> ``tb_relay_adapter`` listener exists.
"""
