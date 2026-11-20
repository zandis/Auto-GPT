"""An added bypass fails CI. Removing a bypass requires removing its inventory entry too."""

from __future__ import annotations

import json
from collections import Counter

import pytest
from model_guard import CHAT_COMPLETIONS

from tools.output_sinks import TABLE, Site, inspect_source, inventory

pytestmark = [pytest.mark.guard, pytest.mark.nodb]


def test_remaining_output_sinks_match_the_inventory() -> None:
    entries = json.loads(TABLE.read_text())
    assert all(row["why"].strip() for row in entries)
    want = Counter(Site(**{k: v for k, v in row.items() if k != "why"}) for row in entries)
    got = inventory()
    assert got == want, {"new": list((got - want).elements()), "stale": list((want - got).elements())}


@pytest.mark.parametrize(
    ("source", "area"),
    [
        ("model.chat_json('judge', row)", "model"),
        ("client.chat.completions.create(messages=row)", "model"),
        (f"http.post(base + {CHAT_COMPLETIONS!r}, json=row)", "model"),
        ("log.info('note %s', row['text'])", "log"),
        ("logging.getLogger('x').warning('failure', extra={'nested': row})", "log"),
        ("smtp.send_message(row)", "mail"),
        ("return FileResponse(row)", "download"),
        ("z.writestr('bundle', row)", "package"),
        ("tar.addfile(info, row)", "support"),
    ],
)
def test_new_sink_shapes_are_found(source: str, area: str) -> None:
    file = "tools/support_bundle.py" if area == "support" else "services/new_area.py"
    result = inspect_source(file, f"def new(row):\n    {source}\n")
    assert [(s.area, s.function) for s in result] == [(area, "new")]


def test_one_gated_call_does_not_excuse_a_second_raw_call_in_the_same_function() -> None:
    hits = inspect_source(
        "libs/new.py",
        """
from tb_common.output_gate import prepare_output as release
def send(client, raw):
    approved = release('chat', 'model', raw)
    client.complete(approved, labels)
    client.complete(raw, labels)
    client.complete(raw, labels)
""",
    )
    assert len(hits) == 2 and hits[0] == hits[1]


@pytest.mark.parametrize(
    "sink",
    [
        "client.complete(out, labels)",
        "log.info('entry %s', out)",
        "mail.send(out)",
        "return Response(out, headers={'content-disposition': 'attachment'})",
        "archive.writestr('file', out)",
        "ctx.publish('report', out)",
    ],
)
def test_changing_the_released_operand_removes_the_bypass(sink: str) -> None:
    source = "from tb_common.output_gate import prepare_output\ndef release(row):\n    out = {}\n    " + sink
    assert len(inspect_source("services/test.py", source.replace("out = {}", "out = row"))) == 1
    assert not inspect_source("services/test.py", source.replace("out = {}", "out = prepare_output('p', 'dest', row)"))


def test_conditional_gate_does_not_approve_other_branch() -> None:
    hits = inspect_source(
        "libs/test.py",
        """
from tb_common.output_gate import prepare_output
def release(row, enabled):
    if enabled:
        row = prepare_output("chat", "model", row)
    client.complete(row, labels)
""",
    )
    assert len(hits) == 1


def test_gating_a_name_after_an_earlier_copy_does_not_clean_the_copy() -> None:
    hits = inspect_source(
        "libs/test.py",
        """
from tb_common.output_gate import prepare_output
def release(row):
    earlier = row
    row = prepare_output("chat", "model", row)
    client.complete(earlier, labels)
    client.complete(row, labels)
""",
    )
    assert len(hits) == 1


@pytest.mark.parametrize(
    "branch",
    [
        "try:\n        row = prepare_output('chat', 'model', row)\n    except Exception:\n        pass",
        "for candidate in candidates:\n        row = prepare_output('chat', 'model', candidate)",
    ],
)
def test_failure_or_an_empty_loop_does_not_approve_the_original_row(branch: str) -> None:
    source = (
        f"from tb_common.output_gate import prepare_output\ndef f(row):\n    {branch}\n    client.complete(row, labels)"
    )
    assert len(inspect_source("libs/test.py", source)) == 1


def test_a_raw_question_is_a_bypass_even_with_gated_excerpts() -> None:
    sites = inspect_source(
        "services/test.py",
        """
from tb_common.output_gate import prepare_output
def check(question, row):
    shown = prepare_output("judge", "model", row)
    model.judge(criterion_text=question, excerpts=shown["excerpts"])
""",
    )
    assert len(sites) == 1


def test_an_archive_filename_cannot_disclose_a_record_even_with_approved_content() -> None:
    result = inspect_source(
        "services/new.py",
        """
from tb_common.output_gate import prepare_output
def bundle(archive, row):
    content = prepare_output("study", "package", row)
    archive.writestr(row["name"], content)
""",
    )
    assert len(result) == 1 and result[0].area == "package"


def test_a_writer_with_a_new_archive_handle_name_is_found() -> None:
    result = inspect_source(
        "services/new.py",
        """
from zipfile import ZipFile as Writer
def bundle(path, row):
    with Writer(path, "w") as arbitrary:
        arbitrary.write(row)
""",
    )
    assert len(result) == 1 and result[0].area == "package"
