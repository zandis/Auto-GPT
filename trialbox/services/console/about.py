"""``/about``: the third-party notices of the box (T-617a, STD-044, plan v6 §9.4).

The page shows ``NOTICE`` (the trialbox folder's root; ``/app/NOTICE`` in the demo image): every third-party code
system, library, font and data set the image ships, with its version, licence and the attribution its licence asks
for. ``/about/NOTICE.txt`` serves the same file as plain text. Both answer without a sign-in: a licence notice is for
anyone the box is shown to, and the page carries no study or patient content. The notice texts stay in English (the
licences' own wording); the page around them follows the reader's language.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

from console.home import Helpers
from console.i18n import CATALOGUES, LANGS

NOTICE = Path(__file__).resolve().parents[2] / "NOTICE"
_RULE = re.compile(r"={3,}")

EN = {
    "about.title": "About TrialBox: third-party notices",
    "about.intro": "TrialBox ships third-party code systems, libraries, fonts and data. Their versions, licences "
    "and the notices those licences ask for are below.",
    "about.text": "Plain text (NOTICE)",
    "about.missing": "The notice file is missing from this installation. Tell the administrator.",
    "about.back": "Back to TrialBox",
}
JA = {
    "about.title": "TrialBox について：第三者の権利表示",
    "about.intro": "TrialBox には第三者のコード体系、ライブラリ、フォント、データが含まれています。各版、ライセンス、"
    "ライセンスが求める表示を以下に示します（原文：英語）。",
    "about.text": "テキスト版（NOTICE）",
    "about.missing": "この環境には NOTICE ファイルがありません。管理者に連絡してください。",
    "about.back": "TrialBox に戻る",
}
ZH = {
    "about.title": "關於 TrialBox：第三方聲明",
    "about.intro": "TrialBox 內含第三方代碼系統、程式庫、字型與資料。"
    "各項版本、授權及授權要求的聲明如下（原文為英文）。",
    "about.text": "純文字版（NOTICE）",
    "about.missing": "此環境缺少 NOTICE 檔案，請通知管理者。",
    "about.back": "返回 TrialBox",
}
for _lang, _cat in (("en", EN), ("ja", JA), ("zh-TW", ZH)):
    CATALOGUES[_lang].update(_cat)


def sections(text: str) -> list[dict[str, Any]]:
    """NOTICE as sections: a heading is a line underlined with ``===``; a block is a run of non-blank lines."""
    lines = text.splitlines()
    out: list[dict[str, Any]] = []
    block: list[str] = []

    def flush() -> None:
        if block:
            if not out:
                out.append({"title": "", "blocks": []})
            out[-1]["blocks"].append([ln.strip() for ln in block])
            block.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        if _RULE.fullmatch(line.strip()):
            flush()
        elif line.strip() and i + 1 < len(lines) and _RULE.fullmatch(lines[i + 1].strip()):
            flush()
            out.append({"title": line.strip(), "blocks": []})
            i += 1
        elif line.strip():
            block.append(line)
        else:
            flush()
        i += 1
    flush()
    return out


def _read() -> str | None:
    try:
        return NOTICE.read_text(encoding="utf-8")
    except OSError:
        return None


def register(app: FastAPI, h: Helpers) -> None:
    @app.get("/about", response_class=HTMLResponse)
    def about(request: Request, lang: str = "") -> Response:
        from console.app import COOKIE  # console.app imports this module (through step4)

        # the reader's language: ?lang=, else a signed-in reader's own (read only, the session is not touched), else
        # the sign-in page's choice or the browser's. The page itself is drawn without the session: no nav, no scope.
        sess = h.users.session(request.cookies.get(COOKIE), touch=False)
        chosen = lang if lang in LANGS else (sess.lang if sess is not None else "")
        if chosen in LANGS:
            request.state.lang = chosen
        text = _read()
        parts = sections(text) if text else []
        return h.page(request, "about.html", None, status=200 if text else 503, sections=parts, missing=not text)

    @app.get("/about/NOTICE.txt")
    def about_text() -> Response:
        text = _read()
        if text is None:
            return PlainTextResponse("NOTICE missing\n", status_code=503)
        return PlainTextResponse(text)
