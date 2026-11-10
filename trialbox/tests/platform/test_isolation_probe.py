"""Shared-host isolation, tested (WS-13.9, TST-SEC-09; D-211): from a second namespace, every TrialBox port is
refused and no TrialBox volume can be mounted.

Runs against a cluster where the platform manifests are applied (the acceptance cluster, a kind cluster, CGMH at IQ
and after every platform patch): ``TB_INTEGRATION=1 TB_PLATFORM_NAMESPACE=<ns> pytest -m integration
tests/platform``, with ``kubectl`` on PATH pointed at the cluster (``KUBECONFIG``). The probe pod runs
``TB_PROBE_IMAGE`` (default ``busybox:1.36``; on an offline platform an image the platform already holds) in a
throw-away namespace, which it deletes afterwards. The cluster's CNI must enforce NetworkPolicy (kind's default
kindnet does since kind v0.24 / Kubernetes 1.31 with its network-policy controller; otherwise install Calico).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from typing import Any

import pytest

pytestmark = pytest.mark.integration

NS = os.environ.get("TB_PLATFORM_NAMESPACE", "")
PROBE_IMAGE = os.environ.get("TB_PROBE_IMAGE", "busybox:1.36")


def kubectl(*args: str, input: str | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["kubectl", *args], input=input, capture_output=True, text=True, check=check, timeout=300)


@pytest.fixture(scope="module")
def probe_ns() -> Any:
    if not NS or shutil.which("kubectl") is None:
        pytest.skip("needs kubectl and TB_PLATFORM_NAMESPACE (a cluster with the platform manifests applied)")
    if kubectl("get", "namespace", NS, check=False).returncode != 0:
        pytest.skip(f"namespace {NS} not found")
    name = f"tb-probe-{uuid.uuid4().hex[:6]}"
    kubectl("create", "namespace", name)
    try:
        yield name
    finally:
        kubectl("delete", "namespace", name, "--wait=false", check=False)


def _targets() -> list[tuple[str, int]]:
    svcs = json.loads(kubectl("-n", NS, "get", "services", "-o", "json").stdout)["items"]
    out = [(s["metadata"]["name"], int(p["port"])) for s in svcs for p in s["spec"].get("ports") or []]
    assert out, f"no Service in {NS}"
    return out


def _run_pod(
    ns: str, name: str, spec: dict[str, Any], labels: dict[str, str] | None = None, timeout: int = 240
) -> tuple[str, str]:
    pod = {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": name, "labels": labels or {}}, "spec": spec}
    kubectl("-n", ns, "apply", "-f", "-", input=json.dumps(pod))
    phase = ""
    deadline = time.time() + timeout
    while time.time() < deadline:
        phase = kubectl("-n", ns, "get", "pod", name, "-o", "jsonpath={.status.phase}", check=False).stdout
        if phase in ("Succeeded", "Failed"):
            break
        time.sleep(3)
    logs = kubectl("-n", ns, "logs", name, check=False).stdout
    return phase, logs


def test_every_trialbox_port_is_refused_from_a_second_namespace(probe_ns: str) -> None:
    targets = _targets()
    script = "; ".join(
        f'if nc -z -w 3 {svc}.{NS}.svc.cluster.local {port}; then echo "OPEN {svc}:{port}"; '
        f'else echo "CLOSED {svc}:{port}"; fi'
        for svc, port in targets
    )
    phase, logs = _run_pod(
        probe_ns,
        "port-probe",
        {
            "restartPolicy": "Never",
            "containers": [{"name": "probe", "image": PROBE_IMAGE, "command": ["sh", "-c", script]}],
        },
    )
    assert phase == "Succeeded", (phase, logs)
    lines = [ln for ln in logs.splitlines() if ln.startswith(("OPEN", "CLOSED"))]
    assert len(lines) == len(targets), logs
    opened = [ln for ln in lines if ln.startswith("OPEN")]
    assert not opened, f"reachable from namespace {probe_ns}: {opened}"


def test_the_probe_sees_an_open_port_when_one_is_allowed(probe_ns: str) -> None:
    """Control: the same probe from a pod labelled as a TrialBox service inside the namespace reaches the database,
    so the CLOSED answers above are the policy, not a probe that cannot connect at all."""
    pod = f"tb-probe-ctl-{uuid.uuid4().hex[:6]}"
    try:
        phase, logs = _run_pod(
            NS,
            pod,
            {
                "restartPolicy": "Never",
                "automountServiceAccountToken": False,
                "containers": [
                    {
                        "name": "probe",
                        "image": PROBE_IMAGE,
                        "command": ["sh", "-c", "nc -z -w 3 db 5432 && echo OPEN || echo CLOSED"],
                    }
                ],
            },
            labels={"trialbox.io/tier": "app", "app.kubernetes.io/component": "isolation-probe"},
        )
    finally:
        kubectl("-n", NS, "delete", "pod", pod, "--wait=false", check=False)
    assert phase == "Succeeded" and "OPEN" in logs, (phase, logs)


def test_no_trialbox_volume_can_be_mounted_from_a_second_namespace(probe_ns: str) -> None:
    claims = json.loads(kubectl("-n", NS, "get", "pvc", "-o", "json").stdout)["items"]
    assert claims, f"no PersistentVolumeClaim in {NS}"
    for c in claims:
        name = c["metadata"]["name"]
        vol = c["spec"].get("volumeName")
        spec = {
            "restartPolicy": "Never",
            "containers": [
                {
                    "name": "probe",
                    "image": PROBE_IMAGE,
                    "command": ["ls", "/v"],
                    "volumeMounts": [{"name": "v", "mountPath": "/v"}],
                }
            ],
            "volumes": [{"name": "v", "persistentVolumeClaim": {"claimName": name}}],
        }
        pod_name = f"vol-{name}"[:63]
        pod = {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": pod_name}, "spec": spec}
        kubectl("-n", probe_ns, "apply", "-f", "-", input=json.dumps(pod))
        time.sleep(5)
        got = json.loads(kubectl("-n", probe_ns, "get", "pod", pod_name, "-o", "json").stdout)
        assert got["status"].get("phase") == "Pending", (name, got["status"])  # the claim is not in this namespace
        if vol:  # binding the TrialBox volume by a new claim in the second namespace fails: it is already bound
            steal = f"steal-{name}"[:63]
            pvc = {
                "apiVersion": "v1",
                "kind": "PersistentVolumeClaim",
                "metadata": {"name": steal},
                "spec": {
                    "accessModes": c["spec"]["accessModes"],
                    "volumeName": vol,
                    "storageClassName": c["spec"].get("storageClassName") or "",
                    "resources": {"requests": {"storage": c["spec"]["resources"]["requests"]["storage"]}},
                },
            }
            kubectl("-n", probe_ns, "apply", "-f", "-", input=json.dumps(pvc))
            time.sleep(3)
            ph = kubectl("-n", probe_ns, "get", "pvc", steal, "-o", "jsonpath={.status.phase}").stdout
            assert ph != "Bound", f"volume {vol} of {name} bound from {probe_ns}"
