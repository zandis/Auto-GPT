# D-913 The CQL translator's errors are read from its own lines

- **Task:** red of lane G's frozen-commit run (#639, 2026-11-16: the CQL translator took a kotlin-logging line on stdout as its output, once); **Date:** 2026-11-16; **Status:** reserved
- **Decision:**
  - The translator's result was already read from a file (`--output`), never from stdout.
  - On CQL it cannot parse, it writes no file, exits 0, and prints its errors on stderr under `Translation failed due to errors:`, among the JVM's and the logger's lines. The compiler quoted the last 800 characters of stdout and stderr as the reason, so a logging line could stand where the error belonged.
  - Now only the translator's own error lines (`Error:` / `Warning:` with their position) are read, never bare stdout (`no_output`). With none, the message says the translator wrote no ELM and names no error, with the exit code.
- **Test:** `tests/unit/test_cql_translator_output.py` (one test runs the real cql-to-elm 5.4.0 where it is installed).
