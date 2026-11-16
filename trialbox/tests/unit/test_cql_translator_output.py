"""Red of lane G's frozen-commit run (#639, 2026-11-16): the CQL translator's answer was a kotlin-logging line from
stdout, once (D-913).

The translator writes its ELM to a file (``--output``). On CQL it cannot parse it writes no file, exits 0, and prints
its errors on stderr under ``Translation failed due to errors:``, among the JVM's and the logger's lines; the compiler
quoted the last 800 characters of stdout and stderr, so a logging line could stand where the error belonged. Now only
the translator's own error lines are read, never bare stdout; with none, the message says so with the exit code.
"""

from __future__ import annotations

import pytest
from criteria_compiler.compile_cql.translator import TranslationError, Translator, available, no_output

STDERR = """Picked up JAVA_TOOL_OPTIONS: -Dhttps.proxyHost=127.0.0.1
[main] INFO io.github.oshai.kotlinlogging.KotlinLogging - starting cql-to-elm
================================================================================
TRANSLATE /tmp/tbcql-x/cql/T-1.0.0.cql
Translation failed due to errors:
Error:[4:0, 4:0] no viable alternative at input '((('
Warning:[2:1, 2:9] could not resolve the code system
"""


def test_only_the_translators_own_error_lines_are_read() -> None:
    got = no_output("T", 0, STDERR)
    assert got == [
        "T:[4:0, 4:0] [error] no viable alternative at input '((('",
        "T:[2:1, 2:9] [warning] could not resolve the code system",
    ]
    assert not any("KotlinLogging" in m or "JAVA_TOOL_OPTIONS" in m for m in got)


def test_no_error_line_says_so_with_the_exit_code() -> None:
    assert no_output("T", 3, "[main] INFO KotlinLogging - done\n") == [
        "T: the translator wrote no ELM and no error it names (exit 3)"
    ]


@pytest.mark.skipif(not available(), reason="the cql-to-elm jars and java are not installed here")
def test_the_real_translator_on_cql_it_cannot_parse() -> None:
    bad = "library Bad version '1.0.0'\nusing FHIR version '4.0.1'\ndefine X: (((\n"
    with pytest.raises(TranslationError) as got:
        Translator().translate({"Bad": bad}, check=set())
    msgs = got.value.messages
    assert msgs and all(m.startswith("Bad:") for m in msgs) and any("no viable alternative" in m for m in msgs)
    assert not any("JAVA_TOOL_OPTIONS" in m or "TRANSLATE" in m for m in msgs)
