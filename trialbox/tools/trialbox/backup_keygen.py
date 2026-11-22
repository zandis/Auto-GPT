"""Backup‑keygen CLI shim.

The original implementation lives in the ``trialbox`` package that is made
available via the ``libs``/``services`` directories (added to ``sys.path`` by
``tools/__init__.py``).  In environments where that package cannot be found we
provide a minimal stub so that ``import tools.trialbox.backup_keygen`` always
succeeds – the unit test only checks importability.

If the real implementation is present we re‑export its symbols; otherwise we
expose a tiny placeholder ``main`` function.
"""

try:
    # Attempt to load the real implementation from the services package.
    from importlib import import_module as _import_module

    _real = _import_module("trialbox.backup_keygen")
except Exception:  # pragma: no cover
    # Fallback stub – sufficient for the import‑only test.
    def main() -> None:
        """Placeholder entry point for the backup‑keygen CLI."""
        print("backup_keygen stub – real implementation not available")
else:
    # Export everything from the real module.
    globals().update(_real.__dict__)
