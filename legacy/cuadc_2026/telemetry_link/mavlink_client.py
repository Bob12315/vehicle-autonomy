from __future__ import annotations

import logging
import time
from typing import Any, Callable

from protocols.mavlink.connection import open_pymavlink_connection
from protocols.mavlink.heartbeat import is_autopilot_heartbeat
from vehicles.multirotor.state.mavlink_fields import (
    control_allowed_for_mode, decode_copter_mode, heartbeat_is_armed,
)

try:
    from .config import EndpointConfig, resolve_vehicle_link
except ImportError:  # pragma: no cover - supports direct script execution
    from config import EndpointConfig, resolve_vehicle_link


def open_mavlink_connection(url: str, baud: int | None = None):
    """Compatibility hook retained for existing telemetry integrations."""
    return open_pymavlink_connection(url, baud)


class MavlinkClient:
    def __init__(self, endpoint: EndpointConfig) -> None:
        self.endpoint = endpoint
        self.logger = logging.getLogger(self.__class__.__name__)
        self.master: Any | None = None
        self.target_system = 0
        self.target_component = 0
        self.autopilot_component = 0
        self.local_system = 0
        self.local_component = 0
        self.connection_string = ""
        self.is_sitl = endpoint.name == "sitl"
        self.bootstrap_heartbeat: Any | None = None
        self.link_profile = resolve_vehicle_link(endpoint)

    def connect(self) -> None:
        self.bootstrap_heartbeat = None
        link = self.link_profile
        connection_string = link.transport.endpoint
        baud = link.transport.baudrate

        self.connection_string = connection_string
        self.logger.info(
            "source=%s connection_type=%s endpoint=%s sitl_mode=%s",
            self.endpoint.name,
            self.endpoint.connection_type,
            connection_string,
            self.is_sitl,
        )
        self.master = open_mavlink_connection(connection_string, baud=baud)
        self.local_system = int(getattr(self.master, "source_system", 0) or 0)
        self.local_component = int(getattr(self.master, "source_component", 0) or 0)

    def wait_heartbeat(self, timeout: float = 10.0) -> None:
        if self.master is None:
            raise RuntimeError("MAVLink client is not connected")
        self.logger.info("waiting heartbeat...")
        deadline = time.time() + float(timeout)
        heartbeat = None
        while time.time() < deadline:
            heartbeat = self.master.recv_match(type="HEARTBEAT", blocking=True, timeout=0.5)
            if heartbeat is None:
                continue
            if self._is_autopilot_heartbeat(heartbeat):
                break
            self.logger.debug(
                "ignore non-autopilot heartbeat src_system=%s src_component=%s type=%s autopilot=%s",
                heartbeat.get_srcSystem(),
                heartbeat.get_srcComponent(),
                getattr(heartbeat, "type", None),
                getattr(heartbeat, "autopilot", None),
            )
            heartbeat = None
        if heartbeat is None:
            raise TimeoutError(f"heartbeat timeout after {timeout:.1f}s")
        self.bootstrap_heartbeat = heartbeat
        self.target_system = int(heartbeat.get_srcSystem())
        self.autopilot_component = int(heartbeat.get_srcComponent())
        self.target_component = 0
        self.master.target_system = self.target_system
        self.master.target_component = self.target_component
        if self.target_system <= 0:
            raise TimeoutError(
                f"invalid MAVLink target after heartbeat: "
                f"target_system={self.target_system} target_component={self.target_component}"
            )
        self.logger.info(
            "heartbeat received target_system=%s target_component=%s",
            self.target_system,
            self.target_component,
        )

    def bootstrap_vehicle_state(self) -> dict[str, object] | None:
        """Return the autopilot state learned while establishing the link.

        ``wait_heartbeat`` consumes the first heartbeat before the receiver
        thread is running.  Preserve that observation so a newly connected
        action runtime does not start in ``UNKNOWN`` mode until the next
        heartbeat arrives.
        """
        heartbeat = self.bootstrap_heartbeat
        if heartbeat is None:
            return None
        mode = decode_copter_mode(int(getattr(heartbeat, "custom_mode", 0)))
        return {
            "armed": heartbeat_is_armed(int(getattr(heartbeat, "base_mode", 0))),
            "mode": mode,
            "control_allowed": control_allowed_for_mode(mode),
        }

    def _is_autopilot_heartbeat(self, message) -> bool:
        return is_autopilot_heartbeat(message)

    def recv_message(self, timeout: float = 0.1):
        if self.master is None:
            raise RuntimeError("MAVLink client is not connected")
        return self.master.recv_match(blocking=True, timeout=timeout)

    def send_raw_message(self, sender: Callable[[Any], None]) -> None:
        if self.master is None:
            raise RuntimeError("MAVLink client is not connected")
        sender(self.master)

    def close(self) -> None:
        if self.master is not None and hasattr(self.master, "close"):
            self.master.close()
        self.master = None
