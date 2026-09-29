from __future__ import annotations

import threading
from types import SimpleNamespace

from app.bootstrap import ServiceManager
from contracts.platform.perception import PerceptionHealthSnapshot


def test_service_manager_exposes_perception_port_without_udp_payload_dependency() -> None:
    config = SimpleNamespace(runtime=SimpleNamespace(require_gimbal_feedback=False),
                             telemetry=object())
    manager = ServiceManager(config, threading.Event())
    assert manager.get_perception_platform_snapshot() is None
    assert manager.get_perception_health().reason_code == "source_disabled"

    marker = object()
    health = PerceptionHealthSnapshot(True, "session", 0.0, "ok", 1)
    manager.perception_port = SimpleNamespace(snapshot=lambda: marker,
                                              health=lambda: health)
    assert manager.get_perception_platform_snapshot() is marker
    assert manager.get_perception_health() is health
