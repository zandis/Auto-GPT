"""A reader's evidence is read as sentence ids whether it gives the number or the quoted sentence that starts with
its id ("[3] ..."), in English and in Japanese; an id outside the note is still dropped."""

import json
from pathlib import Path
from typing import Any

import httpx

from tools import mlbench

NOTE_EN = ["A 58-year-old woman with chest pain.", "No diabetes.", "Consent is expected."]
NOTE_JA = ["58歳女性。胸痛を主訴に受診。", "糖尿病なし。", "本人よりインフォームド・コンセントが得られる見込み。"]


def _judge(tmp_path: Path, note: list[str], evidence: list[Any]) -> mlbench.Result:
    pair = mlbench.Pair("1", "p", "t", "inclusion", "Adults who can consent", "included", (2,), "included", True)
    reply = {"label": "included", "evidence": evidence}
    client = mlbench.Client("http://fake/v1", "k", tmp_path / "cache")
    client.http = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(reply)}}]})
        )
    )
    return mlbench.judge(client, "m", "en", pair, note)


def test_numbers_and_quoted_sentences_give_the_same_ids(tmp_path: Path) -> None:
    for note in (NOTE_EN, NOTE_JA):
        as_numbers = _judge(tmp_path / "n", note, [0, "2"])
        as_quotes = _judge(tmp_path / "q", note, [f"[0] {note[0]}", f"[2] {note[2]}"])
        assert as_numbers.evidence == as_quotes.evidence == [0, 2]


def test_an_id_outside_the_note_or_a_sentence_without_its_id_is_dropped(tmp_path: Path) -> None:
    res = _judge(tmp_path, NOTE_JA, [7, "[9] 該当なし", NOTE_JA[1], "x", True, -1])
    assert res.evidence == []
