"""TrialBox contracts: pydantic v2 models generated from ``schemas/`` plus JSON-Schema helpers.

Services exchange only these models. Regenerate with ``make contracts`` after changing a schema (and bump the
schema's version in its description).
"""

from __future__ import annotations

from tb_contracts.generated.models import *  # noqa: F403
from tb_contracts.schema import SCHEMAS_DIR, dump, dump_json, inline_schema, load_schema, schema_errors, validate

__all__ = ["SCHEMAS_DIR", "dump", "dump_json", "inline_schema", "load_schema", "schema_errors", "validate"]
