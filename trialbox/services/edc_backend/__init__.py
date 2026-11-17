"""Selectable EDC backend (D-1041). Off until ``TB_EDC_BACKEND`` is set, so the demo and the study link are unchanged.

``redcap`` talks to the site's REDCap. ``internal`` talks to a service on this box that exposes the same ``/api/``
(token + ``content=``). Both go through :class:`EdcConnection`.
"""

from edc_backend.connection import EdcConnection, connect, copy_records
from edc_backend.mapping import map_project

__all__ = ["EdcConnection", "connect", "copy_records", "map_project"]
