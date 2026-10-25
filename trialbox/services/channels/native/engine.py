"""converse-native (spec v4 §3.4.1, §3.4.2; S1-10, FR-CONV-2, FR-CONV-7, FR-CONV-8, HER-4).

The native engine does what Hermes does, in one turn: free text → ``classify_intent`` through ``tb-gateway`` (caller
``converse-native``) → a typed intent → the front-door tools. It never renders or executes a command line: the
proposal lines come back from ``tb.submit_request``, rendered by the orchestrator (FR-CONV-2), and nothing runs until
the sender's ``OK`` passes deterministic intake.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import ValidationError
from tb_common.llm import load_prompt, render
from tb_llm import CallLabels, GatewayClient, GatewayError, json_schema_format

from channels.base import Attachment, ClassifiedIntent
from channels.grammar import HELP_LINES

FrontDoorCall = Callable[[dict[str, Any], str, str], dict[str, Any]]  # (JSON-RPC message, assertion, conv)
_KANA = re.compile(r"[぀-ヿ]")
_CJK = re.compile(r"[一-鿿]")
_LATIN_WORD = re.compile(r"[A-Za-z]{2,}")

_TEXT: dict[str, dict[str, str]] = {
    "zh-TW": {
        "help": "我可以處理以下指令（直接輸入即可，不經模型）：",
        "unavailable": "目前無法理解這則訊息，請改用下列指令：",
        "refused": "無法處理此請求（{reason}）。",
        "need_study": "請問是哪一個研究？(1) 研究代碼，例如 GZQO。",
        "status": "您的請求：",
        "not_stated": "計畫書中沒有寫明。",
    },
    "en": {
        "help": "I accept these lines (typed exactly, no model involved):",
        "unavailable": "I could not understand the message; please use one of these lines:",
        "refused": "The request was refused ({reason}).",
        "need_study": "Which study do you mean? (1) the study code, for example GZQO.",
        "status": "Your requests:",
        "not_stated": "The protocol does not state this.",
    },
    "ja": {
        "help": "次の行をそのまま入力できます（モデルは使いません）：",
        "unavailable": "メッセージを理解できませんでした。次の行を使ってください：",
        "refused": "リクエストは拒否されました（{reason}）。",
        "need_study": "どの試験ですか？ (1) 試験コード（例：GZQO）。",
        "status": "あなたのリクエスト：",
        "not_stated": "プロトコルには記載がありません。",
    },
}
_TEXT["mixed"] = _TEXT["zh-TW"]


def detect_language(text: str) -> str:
    if _KANA.search(text):
        return "ja"
    cjk = len(_CJK.findall(text))
    latin = len(_LATIN_WORD.findall(text))
    if cjk and latin >= 3:
        return "mixed"
    return "zh-TW" if cjk else "en"


@dataclass(frozen=True)
class EngineTurn:
    text: str
    ticket_id: str | None = None
    tool: str | None = None
    proposal: bool = False
    refused: str | None = None


class EngineUnavailable(RuntimeError):
    pass


class NativeEngine:
    name = "native"
    actor_type = "agent"
    client_id = "converse-native"

    def __init__(self, gateway: GatewayClient, frontdoor: FrontDoorCall, *, today: Callable[[], date]) -> None:
        self.gateway = gateway
        self.frontdoor = frontdoor
        self.today = today
        self.prompt = load_prompt("classify_intent")
        self._ids = 0

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
        )
        schema = ClassifiedIntent.model_json_schema()
        try:
            res = self.gateway.chat(msgs, labels, response_format=json_schema_format("classify_intent", schema))
        except GatewayError as e:
            raise EngineUnavailable(str(e)) from e
        try:
            return ClassifiedIntent.model_validate(res.data)
        except ValidationError as e:
            raise EngineUnavailable("classify_intent returned an invalid intent") from e

    def _tool(self, name: str, args: dict[str, Any], assertion: str, conv: str) -> dict[str, Any]:
        self._ids += 1
        msg = {"jsonrpc": "2.0", "id": self._ids, "method": "tools/call", "params": {"name": name, "arguments": args}}
        out = self.frontdoor(msg, assertion, conv)
        if "error" in out:
            return {"refused": str(out["error"].get("message"))}
        res = out["result"]
        sc: dict[str, Any] = res.get("structuredContent") or json.loads(res["content"][0]["text"])
        return sc

    def converse(
        self,
        *,
        text: str,
        attachments: tuple[Attachment, ...],
        conv: str,
        assertion: str,
        data_class: str,
    ) -> EngineTurn:
        lang = detect_language(text)
        t = _TEXT[lang]
        try:
            intent = self.classify(text, attachments, lang, data_class)
        except EngineUnavailable:
            return EngineTurn("\n".join([t["unavailable"], *HELP_LINES]), refused="engine_unavailable")
        lang = intent.language if intent.language in _TEXT else lang
        t = _TEXT[lang]
        if intent.type in ("FEAS", "QFILL", "SCREEN"):
            params: dict[str, Any] = {}
            if intent.scope:
                params["scope"] = intent.scope
            if intent.lookback_months:
                params["lookback"] = f"{intent.lookback_months}m"
            if intent.deadline:
                params["deadline"] = intent.deadline
            study = intent.study or ("NEW" if intent.type == "FEAS" else None)
            if study is None:
                return EngineTurn(t["need_study"])
            sc = self._tool(
                "tb.submit_request",
                {"type": intent.type, "study": study, "params": params, "language": lang},
                assertion,
                conv,
            )
            if "refused" in sc:
                return EngineTurn(
                    t["refused"].format(reason=sc["refused"]), tool="tb.submit_request", refused=sc["refused"]
                )
            body = "\n".join([sc["restatement"], *sc["commands"], sc["confirm_instruction"]])
            return EngineTurn(body, ticket_id=sc["ticket_id"], tool="tb.submit_request", proposal=True)
        if intent.type == "ASK":
            if not intent.study:
                return EngineTurn(t["need_study"])
            sc = self._tool(
                "tb.ask_protocol", {"study": intent.study, "question": intent.question or text[:500]}, assertion, conv
            )
            if "refused" in sc:
                return EngineTurn(
                    t["refused"].format(reason=sc["refused"]), tool="tb.ask_protocol", refused=sc["refused"]
                )
            if sc["not_stated"]:
                return EngineTurn(t["not_stated"], tool="tb.ask_protocol")
            return EngineTurn(f"{sc['answer']} [{', '.join(sc['citations'])}]", tool="tb.ask_protocol")
        if intent.type == "STATUS":
            sc = self._tool("tb.status", {"study": intent.study} if intent.study else {}, assertion, conv)
            if "refused" in sc:
                return EngineTurn(t["refused"].format(reason=sc["refused"]), tool="tb.status", refused=sc["refused"])
            lines = [t["status"]] + [f"{i['ticket_id']} {i['type']} {i['state']}" for i in sc["items"]]
            return EngineTurn("\n".join(lines), tool="tb.status")
        return EngineTurn("\n".join([t["help"], *HELP_LINES]))
