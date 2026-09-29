from __future__ import annotations

import logging
import threading

from app.config import AppConfig
from fusion.fusion_manager import FusionManager
from fusion.models import FusionConfig, PerceptionTarget, SceneDetections
from telemetry_link.link_manager import LinkManager
from telemetry_link.models import DroneState, GimbalState, LinkStatus
from telemetry_link.config import TelemetryConfig
from telemetry_link.ports import LinkControlAdapter, VehicleCommandAdapter, VehicleStateAdapter
from contracts.platform.vehicle_state import VehicleStateSnapshot
from contracts.platform.perception import PerceptionHealthSnapshot, PerceptionPort
from application.adapters.yolo_udp import YoloUdpReceiver


class ServiceManager:
    def __init__(self, config: AppConfig, stop_event: threading.Event) -> None:
        self.config = config
        self.stop_event = stop_event
        self.logger = logging.getLogger(self.__class__.__name__)
        self.yolo_receiver: YoloUdpReceiver | None = None
        self.perception_port: PerceptionPort | None = None
        self.link_manager: LinkManager | None = None
        self.state_port = VehicleStateAdapter(lambda: self.link_manager)
        self.link_control = LinkControlAdapter(lambda: self.link_manager)
        self.command_port = VehicleCommandAdapter(lambda: self.link_manager)
        self.fusion_manager = FusionManager(
            FusionConfig(
                require_gimbal_feedback=bool(config.runtime.require_gimbal_feedback)
            )
        )
        self._field_version_port: object | None = None
        self._execution_fence_query: object | None = None

    def set_field_reference_version_port(self, port: object) -> None:
        self._field_version_port = port
        if self.link_manager is not None:
            self.link_manager.set_field_reference_version_port(port)

    def set_execution_fence_query(self, port: object) -> None:
        self._execution_fence_query = port
        if self.link_manager is not None:
            self.link_manager.set_execution_fence_query(port)

    def start(self) -> None:
        if self.config.runtime.start_yolo_udp:
            self.yolo_receiver = YoloUdpReceiver(
                self.config.runtime.yolo_udp_ip,
                self.config.runtime.yolo_udp_port,
                self.stop_event,
                max_datagram_bytes=self.config.runtime.yolo_max_datagram_bytes,
                max_detections=self.config.runtime.yolo_max_detections,
                tombstone_capacity=self.config.runtime.yolo_tombstone_capacity,
            )
            self.yolo_receiver.start()
            self.perception_port = self.yolo_receiver
            self.logger.info(
                "YOLO UDP receiver started at %s:%s",
                self.config.runtime.yolo_udp_ip,
                self.config.runtime.yolo_udp_port,
            )
        else:
            self.logger.info("YOLO UDP receiver disabled")

        if self.config.runtime.connect_telemetry:
            self.link_manager = LinkManager(self.config.telemetry)
            if self._execution_fence_query is not None:
                self.link_manager.set_execution_fence_query(self._execution_fence_query)
            if self._field_version_port is not None:
                self.link_manager.set_field_reference_version_port(self._field_version_port)
            self.link_manager.start_background()
            self.logger.info("telemetry link manager starting in background")
        else:
            self.logger.info("telemetry link manager disabled; running without a MAVLink link")

    def stop(self) -> None:
        if self.yolo_receiver is not None:
            receiver = self.yolo_receiver
            receiver.close()
            if receiver.is_alive():
                receiver.join(timeout=1.0)
            self.yolo_receiver = None
        self.perception_port = None
        if self.link_manager is not None:
            self.link_manager.stop()
            self.link_manager = None

    def reconnect_telemetry(self, config: TelemetryConfig) -> None:
        if self.link_manager is not None:
            self.link_manager.stop()
        self.config.telemetry = config
        self.link_manager = LinkManager(config)
        if self._execution_fence_query is not None:
            self.link_manager.set_execution_fence_query(self._execution_fence_query)
        if self._field_version_port is not None:
            self.link_manager.set_field_reference_version_port(self._field_version_port)
        self.link_manager.start_background()
        self.logger.info("telemetry link manager restarted from saved configuration")

    def get_perception(self, now: float) -> PerceptionTarget:
        if self.yolo_receiver is None:
            return PerceptionTarget(timestamp=now)
        return self.yolo_receiver.get_latest_target(
            now,
            self.config.runtime.perception_timeout_sec,
        )

    def get_perception_frame(self, now: float) -> tuple[PerceptionTarget, SceneDetections]:
        if self.yolo_receiver is None:
            return PerceptionTarget(timestamp=now), SceneDetections(timestamp=now)
        return self.yolo_receiver.get_latest_frame(now, self.config.runtime.perception_timeout_sec)

    def get_perception_platform_snapshot(self):
        return None if self.perception_port is None else self.perception_port.snapshot()

    def get_perception_health(self) -> PerceptionHealthSnapshot:
        if self.perception_port is None:
            return PerceptionHealthSnapshot(False, None, None, "source_disabled", 0)
        return self.perception_port.health()

    def get_yolo_process_session_id(self) -> str | None:
        return None if self.yolo_receiver is None else self.yolo_receiver.active_process_session_id()

    def perception_status(self, now: float) -> dict[str, object]:
        """Expose whether the optional UDP perception input is usable.

        The app deliberately runs without the board-local YOLO environment.
        Visual Actions receive an invalid target in that mode and therefore
        fail closed; nonvisual Actions remain available.
        """
        if self.yolo_receiver is None:
            return {"perception_source": "disabled", "stale": True, "age_sec": None}
        age = self.yolo_receiver.packet_age(now)
        return {
            "perception_source": "udp",
            "stale": age is None or age > self.config.runtime.perception_timeout_sec,
            "age_sec": age,
        }

    def get_scene_detections(self, now: float) -> SceneDetections:
        if self.yolo_receiver is None:
            return SceneDetections(timestamp=now)
        return self.yolo_receiver.get_latest_scene(
            now,
            self.config.runtime.perception_timeout_sec,
        )

    def get_drone_state(self) -> DroneState:
        if self.link_manager is None:
            return DroneState()
        return self.link_manager.get_latest_drone_state()

    def get_vehicle_snapshot(self) -> VehicleStateSnapshot:
        return self.state_port.snapshot()

    def get_gimbal_state(self) -> GimbalState:
        if self.link_manager is None:
            return GimbalState()
        return self.link_manager.get_latest_gimbal_state()

    def get_link_status(self) -> LinkStatus | None:
        if self.link_manager is None:
            return None
        return self.link_manager.get_link_status()
