"""D-827: the test-only mail servers are report-only in every vuln mode; every image a bundle can carry blocks.

`make release-gates` in its default (block) mode failed on lane G's GPU box on fixable findings in
axllent/mailpit v1.33.1 and greenmail/standalone 2.1.15: the newest releases, no patched tag exists, and no bundle
carries either image (tools/make_bundle.sh leaves docker-compose.test.yml out; bundle_problems refuses an image
with a report-mode finding)."""

from __future__ import annotations

import pytest

from tools.supply_chain import release, vulns


def _finding(fid: str, severity: str = "HIGH", fixed: str = "2.0") -> vulns.Finding:
    return vulns.Finding("trivy", "img", "pkg", "1.0", fid, (), severity, fixed)


FAILING = [_finding("CVE-1"), _finding("CVE-2", "CRITICAL"), _finding("CVE-3", fixed=""), _finding("CVE-4", "MEDIUM")]


@pytest.mark.parametrize("mode", release.VULN_MODES)
@pytest.mark.parametrize("ref", ["axllent/mailpit:v1.33.1", "docker.io/greenmail/standalone@sha256:ab"])
def test_the_test_mail_servers_defer_fixable_high_findings_in_every_mode(mode: str, ref: str) -> None:
    blocking, deferred = release.split_report_mode(FAILING, ref, mode)
    assert [f.id for f in deferred] == ["CVE-1", "CVE-2"]
    assert [f.id for f in blocking] == ["CVE-3", "CVE-4"]


@pytest.mark.parametrize("mode", release.VULN_MODES)
@pytest.mark.parametrize(
    "ref", ["vllm/vllm-openai@sha256:ab", "hapiproject/hapi:v8.12.0-2", "trialbox-py:1.0.0", "trialbox-demo:step5"]
)
def test_every_image_a_bundle_can_carry_still_blocks_in_every_mode(mode: str, ref: str) -> None:
    assert release.split_report_mode(FAILING, ref, mode) == (FAILING, [])
