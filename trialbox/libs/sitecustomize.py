"""Run at interpreter start for every TrialBox service (``/app/libs`` is on PYTHONPATH): trust a mounted hospital
TLS-inspection CA in addition to the public CAs (``tb_common.extra_ca``). Never fails the interpreter."""

try:
    from tb_common.extra_ca import install

    install()
except Exception:  # noqa: S110 (a broken CA file must not stop a service from starting)
    pass
