"""SERVING-ERRTEXT (D-636): the embed service, the gateway's start check, the model stub and the model guard say a
sentence of their own or an error's type, never the text of an error nobody wrote (D-700's list for the serving
path)."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from tests.unit.test_error_text_across_services import THEIRS, _found

pytestmark = pytest.mark.nodb

SERVING = ("embed_service/embedder.py", "gateway/app.py", "llm_stub/app.py", "model_guard/__init__.py")
WORDS = "WORDS-ONLY-THE-ERROR-KNEW-51c2"


def test_the_four_files_take_no_general_errors_text_and_left_the_list() -> None:
    found = {f for f, _ in _found()}
    assert not found & set(SERVING), sorted(found & set(SERVING))
    assert not set(SERVING) & set(THEIRS)


def test_the_embed_service_still_says_its_own_sentence_for_a_mode_it_does_not_serve() -> None:
    from embed_service.embedder import MODES, EmbedderRefused, service_embedder

    with pytest.raises(EmbedderRefused) as exc:
        service_embedder({"TB_ENV": "TEST", "TB_EMBED_MODE": "telepathy"})
    said = str(exc.value)
    assert "TB_EMBED_MODE" in said and "'telepathy'" in said and all(m in said for m in MODES)


def test_a_model_server_that_does_not_answer_is_named_by_the_errors_type(caplog: pytest.LogCaptureFixture) -> None:
    from gateway import app as gw_app

    class Http:
        def get(self, *_a: Any, **_kw: Any) -> Any:
            raise ConnectionError(f"refused {WORDS}")

    class Gw:
        http = Http()

    with caplog.at_level(logging.DEBUG):
        status, what = gw_app._get_models(Gw(), "http://llm:8000/v1", "")  # type: ignore[arg-type]
    assert status is None and what == "ConnectionError"
    assert WORDS in caplog.text  # the text is in the log, for the operator


def test_the_model_guards_refusals_are_its_own_class_and_its_own_sentences(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import model_guard as mg

    assert issubclass(mg.GuardConfigError, ValueError)
    for name in ("TB_GUARD_ROUTES", "TB_LLM_API_KEY", "TB_LLM_API_KEY_FILE"):
        monkeypatch.delenv(name, raising=False)
    assert mg.main([]) == 2
    assert "model_guard: no route (TB_GUARD_ROUTES)" in capsys.readouterr().err

    def other() -> Any:
        raise ValueError(f"something else {WORDS}")

    monkeypatch.setattr(mg, "build", other)
    with pytest.raises(ValueError, match="something else"):
        mg.main([])  # an error nobody wrote is not printed as the guard's sentence: it fails loudly, with its trace
