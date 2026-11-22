from pathlib import Path

# Import the internal helper directly from the module under test.
# The repository's PYTHONPATH is set to include the project root, so this works.
from tools.asvs_checklist import _line_ok


def test_absolute_path_ignores_root(tmp_path: Path) -> None:
    """
    Verify that _line_ok does NOT enforce the provided ``root`` when the
    ``path`` component of the reference is absolute.

    The function builds the file path with ``root / path``.  In pathlib,
    if ``path`` is absolute the left‑hand operand is ignored, so the file
    is resolved outside ``root``.  The test expects an error (e.g. “no such
    file”) but the current implementation returns an empty string,
    causing this test to fail – proving the claim.
    """
    # Create a temporary file *outside* the fake root directory.
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("first line\nsecond line\n")

    # Construct a reference using an absolute path to the temporary file.
    # Use line number 1, which is valid.
    ref = f"{outside_file}:{1}"

    # Define a fake root that does NOT contain the file.
    fake_root = tmp_path / "fake_root"
    fake_root.mkdir()

    # Call the function with the fake root and the absolute reference.
    result = _line_ok(fake_root, ref)

    # If the root were correctly enforced, we would get an error message.
    # The current implementation returns an empty string, so this assertion
    # fails, demonstrating the vulnerability.
    assert result, "Expected an error because the absolute path should be rejected, but got an empty result."
