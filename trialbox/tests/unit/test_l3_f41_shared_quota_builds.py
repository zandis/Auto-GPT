import os
import tempfile

from tools.qualify import profile_builds

# Ensure the test environment does not trigger the global PostgreSQL test fixtures
# by providing an empty TB_TEST_ROOT directory.
os.environ["TB_TEST_ROOT"] = tempfile.mkdtemp()


def test_shared_quota_builds():
    builds = profile_builds("shared-quota")
    assert builds["judge"].build_id == "gemma-4-26b-a4b-it-sharedquota"
    assert builds["verifier"].build_id == "qwen3.5-9b-sharedquota"
