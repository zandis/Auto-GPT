"""TrialBox LLM client library (spec v4 §8.2, ENG-04): the only way code reaches a model, through tb-gateway."""

from tb_llm.client import (
    CallLabels,
    ChatResult,
    GatewayClient,
    GatewayError,
    GatewayRefused,
    json_schema_format,
)

__all__ = ["CallLabels", "ChatResult", "GatewayClient", "GatewayError", "GatewayRefused", "json_schema_format"]
