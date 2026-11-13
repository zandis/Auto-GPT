"""Build ``services/guard/data/zh_common_words.csv``: the common Chinese words the PHI tripwire's name rule reads
(NEW-LLM-3, D-647).

A build-time tool, run by hand in a scratch environment; nothing here runs on a box and neither package is in the
lock:

    python -m tools.zh_common_words --dict <jieba>/dict.txt --out services/guard/data/zh_common_words.csv

* ``--dict``: the word list of the jieba project (``jieba/dict.txt``, MIT licence), read as data: one line per word,
  "word frequency part-of-speech". No tagger runs.
* ``opencc`` (opencc-python-reimplemented, Apache-2.0) gives each word's Traditional form; both forms are kept.

Kept: words that are not person names (the tag does not start with ``nr``) with a dictionary frequency of at least
:data:`MIN_FREQ`. The file has two columns, ``kind`` and ``word``:

* ``word``: a common word of 2 to 4 characters;
* ``one``: a very common one-character verb, preposition or adverb (frequency :data:`ONE_FREQ` and up);
* ``plain``: a one-character word of the function classes (frequency :data:`PLAIN_FREQ` and up); the guard keeps the
  ones that are also surnames (曾 "once", 高 "high", 於 "at").

The frequencies are the ones the measurement of D-647 was made with; a change is a re-measurement.
"""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path

MIN_FREQ = 5
ONE_FREQ = 3000
PLAIN_FREQ = 1000
PLAIN_TAGS = ("d", "a", "p", "c", "v", "f", "m", "r", "u")


def build(dict_text: str) -> list[tuple[str, str]]:
    s2t = importlib.import_module("opencc").OpenCC("s2t")
    rows: set[tuple[str, str]] = set()
    for line in dict_text.splitlines():
        word, freq, tag = ([*line.split(" "), "", ""])[:3]
        n = int(freq or 0)
        if tag.startswith("nr") or n < MIN_FREQ:
            continue
        for form in {word, s2t.convert(word)}:
            if 2 <= len(form) <= 4:
                rows.add(("word", form))
            elif len(form) == 1:
                if tag[:1] in ("v", "p", "d") and n >= ONE_FREQ:
                    rows.add(("one", form))
                if tag[:1] in PLAIN_TAGS and n >= PLAIN_FREQ:
                    rows.add(("plain", form))
    return sorted(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--dict", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args(argv)
    rows = build(a.dict.read_text(encoding="utf-8"))
    a.out.write_text("kind,word\n" + "".join(f"{k},{w}\n" for k, w in rows), encoding="utf-8")
    print(f"{a.out}: {len(rows)} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
