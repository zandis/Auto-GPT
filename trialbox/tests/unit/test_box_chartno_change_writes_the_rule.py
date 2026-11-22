import pathlib

import pytest

# Import the function and constant under test
from tools.box.__main__ import CHARTNO_RULE, chartno_change


@pytest.mark.xfail(
    strict=True,
    reason="open finding: box-chartno-rule-written-test; the fix belongs with the record-identity gate (#1294)",
)
def test_chartno_change_writes_new_rule_when_pid_map_is_empty(tmp_path: pathlib.Path) -> None:
    """
    The docstring of ``chartno_change`` says it changes the chart-number rule.
    If the implementation correctly writes the new rule to the ``.env`` file,
    the file should contain the updated value after the call.

    The current implementation does **not** write any changes, so this test
    will fail, proving the reviewer’s claim.
    """
    # Create a temporary .env file with an initial rule
    env_file = tmp_path / ".env"
    initial_rule = "asis"
    env_file.write_text(f"{CHARTNO_RULE}={initial_rule}\n", encoding="utf-8")

    # Define a new rule that differs from the initial one
    new_rule = "newrule"

    # rows() returns 0 to simulate an empty pid map (no loaded patients)
    def rows_callable() -> int:
        return 0

    # Call the function – it should update the env file
    chartno_change(env_file, new_rule, rows_callable)

    # After the call, the env file must contain the new rule
    content = env_file.read_text(encoding="utf-8")
    assert f"{CHARTNO_RULE}={new_rule}" in content, (
        "chartno_change did not write the new chart-number rule to the env file "
        "(implementation missing the write step)."
    )
