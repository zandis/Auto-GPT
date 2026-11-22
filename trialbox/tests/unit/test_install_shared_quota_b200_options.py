import pathlib
import re


def test_shared_quota_and_b200_no_mig_not_fatal() -> None:
    """
    Ensure that the installer script no longer aborts for B200 related GPU profiles.
    The script should not contain `die` calls for `shared-quota` or `b200-no-mig`.
    """
    script_path = pathlib.Path("deploy/install.sh")
    content: str = script_path.read_text(encoding="utf-8")
    # The `die` calls for these profiles must have been removed.
    assert not re.search(r"shared-quota\)\s*die", content), "shared-quota should not trigger die"
    assert not re.search(r"b200-no-mig\)\s*die", content), "b200-no-mig should not trigger die"
