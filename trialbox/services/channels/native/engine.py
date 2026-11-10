"""converse-native (spec v4 §3.4.1; FR-CONV-7, FR-CONV-8; D-121).

The one conversation engine: free text → ``classify_intent`` through ``tb-gateway`` (caller ``converse-native``) → a
typed intent. The console's header command box turns the intent into a proposal line (``console.proposals``); nothing
runs until the person confirms it. The Hermes agent, the front-door MCP server and the channel relay were removed in
D-121, so the engine no longer calls tools.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date

from pydantic import ValidationError
from tb_common.llm import load_prompt, render
from tb_llm import CallLabels, GatewayClient, GatewayError, json_schema_format

from channels.base import Attachment, ClassifiedIntent

_KANA = re.compile(r"[぀-ヿ]")
_CJK = re.compile(r"[一-鿿]")
_LATIN_WORD = re.compile(r"[A-Za-z]{2,}")


def detect_language(text: str) -> str:
    if _KANA.search(text):
        return "ja"
    cjk = len(_CJK.findall(text))
    latin = len(_LATIN_WORD.findall(text))
    if cjk and latin >= 3:
        return "mixed"
    return "zh-TW" if cjk else "en"


class EngineUnavailable(RuntimeError):
    pass


class EngineBusy(EngineUnavailable):
    """The gateway answered ``model_busy``: the model is swapped out or slower than the chat limit."""


class NativeEngine:
    name = "native"
    actor_type = "agent"
    client_id = "converse-native"

    def __init__(self, gateway: GatewayClient, *, today: Callable[[], date]) -> None:
        self.gateway = gateway
        self.today = today
        self.prompt = load_prompt("classify_intent")

    def classify(
        self, text: str, attachments: tuple[Attachment, ...], language: str, data_class: str
    ) -> ClassifiedIntent:
        msgs = render(
            self.prompt,
            {
                "text": text,
                "attachments": [{"filename": a.filename, "content_type": a.content_type} for a in attachments],
                "today": self.today().isoformat(),
                "language": language,
            },
        )
        labels = CallLabels(
            data_class=data_class,
            purpose="intake",
            study_id="none",
            context_of_use="intake_classify",
            role="classify_intent",
            prompt=f"{self.prompt.meta.id}@{self.prompt.meta.version}",
            prompt_sha=self.prompt.sha256,
        )
        schema = ClassifiedIntent.model_json_schema()
        try:
            res = self.gateway.chat(msgs, labels, response_format=json_schema_format("classify_intent", schema))
        except GatewayError as e:
            if getattr(e, "reason", "") == "model_busy":
                raise EngineBusy(str(e)) from e
            raise EngineUnavailable(str(e)) from e
        try:
            return ClassifiedIntent.model_validate(res.data)
        except ValidationError as e:
            raise EngineUnavailable("classify_intent returned an invalid intent") from e
