"""doc-parser service: ``POST /parse {minio_key}`` -> ``ParsedDoc`` (SPEC §4.2)."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from tb_common.http import make_app
from tb_common.objstore import ObjectStore, from_config
from tb_contracts import ParsedDoc, ParseRequest

from doc_parser.parser import parse

app = make_app("doc-parser")
_store: ObjectStore | None = None


def store() -> ObjectStore:
    global _store
    if _store is None:
        _store = from_config()
    return _store


def _ie_locator(job_id: str | None) -> Any:
    def locate(sections: list[dict[str, Any]]) -> dict[str, list[str]]:
        from tb_common.llm import chat_json

        return chat_json("ie_locate", {"sections": sections}, job_id=job_id).data

    return locate


@app.post("/parse")
def parse_doc(req: ParseRequest) -> ParsedDoc:
    try:
        data = store().get(req.minio_key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"object not found: {req.minio_key}") from exc
    return parse(data, req.minio_key.rsplit("/", 1)[-1], _ie_locator(req.job_id))
