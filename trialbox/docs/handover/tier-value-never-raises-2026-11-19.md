# The tier record reader never raises (card H-51, 2026-11-19)

Lane J reported on PR #1157 (2026-11-19 07:51 UTC): `tier_value.measured` raised `RecursionError` on a tier record
nested about 200000 deep. The reader (`libs/tb_common/tier_value.py`, 10E-1c, D-1322) is called by the gateway at
start (`services/gateway/load.py`), the night budget (`services/orchestrator/scenarios/microbatch.py`) and console
pages, on a file an operator can replace; its docstring promised "never raises". Finding **H51-01**
([findings.json](tier-value-never-raises-2026-11-19/findings.json)).

## What a replaced record gives now

| Input | Before | After (`measured`) |
| --- | --- | --- |
| nested ~200000 deep | `RecursionError` | `malformed`, "nested too deep to read" |
| over 1000000 bytes | read whole into memory | `malformed`, "over 1000000 bytes", refused unread |
| not UTF-8 | `malformed` (`UnicodeDecodeError`) | `malformed`, "not UTF-8" |
| not JSON, integer over 4300 digits | `malformed` (exception name) | `malformed`, "not JSON (...)" |
| directory, link loop, no permission | `malformed` (exception name) | `malformed`, "not readable (...)" |
| top level not an object, wrong types | `malformed`, "no readable field" | unchanged |
| NaN, Infinity, bool, negative value | `measured`, `positive_int` None | unchanged |
| a deep or long declared value in the log line | unbounded `repr` | at most 80 characters |

The reasons are fixed words and the file's name, never its content. The cap is `TIER_RECORD_MAX_BYTES` in
`libs/tb_common/tier_value.py` (the shipped records are under 8 kB); `read_record` is the one bounded read.

## The checker stays strict

`tools/tier_record.py check` and `summary` read through `read_record` and refuse the same files with exit 3 and
`tier record: refused: <file>: not readable JSON (<file>: nested too deep to read)` (or the size, or the encoding);
a record parsed but too deep to walk is refused as "nested too deep to check". No traceback.

## Tests

`tests/unit/test_tier_value_never_raises.py` (each class above; the checker on deep and oversized records, in
process and as a command) and `tests/property/test_malformed_tier_record.py` (10G-43's "returns or refuses", with
the 200000-deep record as an explicit example; it fails on master with `RecursionError`).
