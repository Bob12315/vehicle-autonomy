"""Framework-only remote fakes; none bind a socket or a vehicle writer."""

import ast
from collections import deque
from pathlib import Path

import pytest

from contracts.platform.vehicle_commands import CommandSubmissionReceipt, SubmissionState
from contracts.sensors.health import SensorHealth
from deployment import DeploymentCatalog, DeploymentMode, DeploymentProfile
from gateway import GatewayHealth, GatewayWatchdogStatus


class FakeRemoteVehicleLink:
    def __init__(self) -> None:
        self.telemetry = None
        self.ingress = None

    def snapshot(self, source=None):
        if self.telemetry is None:
            raise RuntimeError("remote telemetry unavailable")
        return self.telemetry

    def wait_next(self, *, after_session_id, after_sequence, timeout_s, source=None):
        return None

    def health(self):
        return GatewayHealth(False, False, None, "not_connected")

    def submit(self, command):
        if self.ingress is None:
            return CommandSubmissionReceipt(command.command_id, SubmissionState.REJECTED,
                                            "local_safety_admission_unavailable")
        return self.ingress.submit(command)

    def cancel(self, request):
        if self.ingress is None:
            raise RuntimeError("local safety admission unavailable")
        return self.ingress.cancel(request)

    def status(self, command_id):
        if self.ingress is None:
            raise RuntimeError("local safety admission unavailable")
        return self.ingress.status(command_id)


class FakeRemoteCameraSource:
    def __init__(self) -> None:
        self.frames = deque()

    def read(self):
        return self.frames.popleft() if self.frames else None

    def close(self):
        self.frames.clear()

    def health(self):
        return SensorHealth("remote", False, "not_connected")


class FakeGatewayWatchdog:
    def __init__(self, deadline_ns: int) -> None:
        self.deadline_ns = deadline_ns
        self._status = GatewayWatchdogStatus(False, False, False, False)

    def check(self, now_monotonic_ns: int):
        expired = now_monotonic_ns >= self.deadline_ns
        self._status = GatewayWatchdogStatus(expired, expired, expired, False)
        return self._status

    def status(self):
        return self._status


def test_profile_catalog_marks_only_onboard_available() -> None:
    catalog = DeploymentCatalog()
    assert {profile.mode for profile in catalog.profiles()} == set(DeploymentMode)
    assert catalog.require_available("onboard_rk3588").node_for("safety") == "onboard"
    for profile_id in ("server", "hybrid"):
        with pytest.raises(ValueError, match="not available"):
            catalog.require_available(profile_id)
    with pytest.raises(ValueError, match="unknown deployment"):
        catalog.get("missing")


def test_remote_profiles_cannot_move_local_safety_or_link() -> None:
    with pytest.raises(ValueError, match="vehicle link"):
        DeploymentProfile("bad", DeploymentMode.SERVER, (
            ("safety", "onboard"), ("vehicle_link", "server"), ("gateway", "onboard"),
        ))
    with pytest.raises(ValueError, match="gateway"):
        DeploymentProfile("bad", DeploymentMode.HYBRID, (
            ("safety", "onboard"), ("vehicle_link", "onboard"),
        ))
    with pytest.raises(ValueError, match="not available"):
        DeploymentProfile("bad", DeploymentMode.SERVER, (
            ("safety", "onboard"), ("vehicle_link", "onboard"), ("gateway", "onboard"),
        ), available=True)


def test_remote_fakes_have_no_command_or_camera_source_by_default() -> None:
    link = FakeRemoteVehicleLink()
    receipt = link.submit(type("Command", (), {"command_id": "test"})())
    assert receipt.submission_state is SubmissionState.REJECTED
    assert link.health().local_safety_ready is False
    assert FakeRemoteCameraSource().read() is None
    watchdog = FakeGatewayWatchdog(10)
    assert watchdog.check(9).command_admission_closed is False
    expired = watchdog.check(10)
    assert expired.command_admission_closed and expired.stop_requested
    assert expired.stop_confirmed is False
    with pytest.raises(ValueError, match="before it is requested"):
        GatewayWatchdogStatus(False, True, False, True)
    with pytest.raises(ValueError, match="close admission"):
        GatewayWatchdogStatus(True, False, True, False)


def test_gateway_and_deployment_do_not_import_mission_or_hardware() -> None:
    root = Path(__file__).resolve().parents[2]
    for relative in ("deployment/profiles.py", "gateway/contracts.py", "gateway/remote.py"):
        tree = ast.parse((root / relative).read_text(encoding="utf-8"))
        modules = [node.module for node in ast.walk(tree)
                   if isinstance(node, ast.ImportFrom) and node.module]
        assert all(not module.startswith(("missions", "pymavlink", "telemetry_link", "yolo_app"))
                   for module in modules)
