# ruff: noqa: E501
"""Generate fictional clinical notes with planted PHI spans and look-alike decoys (eval/phi_synth/notes.jsonl).

    OPENROUTER_API_KEY=... python tools/phi_synth_gen.py eval/phi_synth/notes.jsonl 40   # 40 notes per language

Every note is fictional and written by a model; spans and decoys are checked to occur verbatim in the text.
"""

import concurrent.futures as cf
import json
import os
import sys

import httpx

K = os.environ["OPENROUTER_API_KEY"]
LANG = {
    "ja": "Japanese (as written in a Japanese hospital EMR: mix of kanji, katakana, 和暦 and Western dates, abbreviations like DM(-), Ope歴)",
    "zh-TW": "Traditional Chinese as written in a Taiwanese hospital EMR (mix of Chinese and English medical terms, 民國 and Western dates)",
    "en": "English (US/UK clinical note style)",
}
P = """Write ONE realistic, fully fictional outpatient or discharge clinical note in {lang}, 80-180 words, for batch {i}.
Plant 4-8 protected health identifiers of varied kinds: patient/relative/staff PERSON names, DATE (birth date, admission/visit dates), ADDRESS, PHONE, ID (chart number, national ID, insurance number), FACILITY (named hospital/clinic), EMAIL, AGE over 89.
Also include 2-4 NON-identifiers that look like names: disease eponyms (e.g. Parkinson, Hashimoto, 橋本病, Crohn), drug or brand names, department names, or generic role words (主治医, 家族, attending).
Return ONLY JSON: {{"text": "...", "phi": [{{"span": "exact substring", "type": "PERSON|DATE|ADDRESS|PHONE|ID|FACILITY|EMAIL|AGE"}}], "decoys": ["exact substring", ...]}}. Every span and decoy must occur verbatim in text."""


def one(a):
    lang, i = a
    for _ in range(3):
        r = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": "Bearer " + K},
            timeout=120,
            json={
                "model": "anthropic/claude-sonnet-5.5",
                "temperature": 1,
                "max_tokens": 1500,
                "messages": [{"role": "user", "content": P.format(lang=LANG[lang], i=i)}],
                "response_format": {"type": "json_object"},
            },
        )
        try:
            c = r.json()["choices"][0]["message"]["content"]
            c = c[c.index("{") : c.rindex("}") + 1]
            d = json.loads(c)
            d["phi"] = [p for p in d["phi"] if p["span"] in d["text"]]
            d["decoys"] = [x for x in d.get("decoys", []) if x in d["text"]]
            d["lang"] = lang
            d["i"] = i
            return d
        except Exception as e:
            err = e
    print("fail", lang, i, err, file=sys.stderr)


jobs = [(lang, i) for lang in LANG for i in range(int(sys.argv[2]))]
with cf.ThreadPoolExecutor(12) as ex, open(sys.argv[1], "w") as fh:
    for d in ex.map(one, jobs):
        if d:
            fh.write(json.dumps(d, ensure_ascii=False) + "\n")
