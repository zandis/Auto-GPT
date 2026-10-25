"""Hermes Agent integration (spec v4 §9; S1-11): pin, hardened profiles, the relay adapter and policy plugin.

Status in this build: **blocked**. The release could not be fetched, verified by tag + commit SHA + image digest and
mirrored offline, so ``hermes.lock`` carries no SHA or digest, ``channels.engine`` stays ``native`` (OPS-02) and
``trialbox doctor`` fails closed if ``engine: hermes`` is configured against this lock.
"""
