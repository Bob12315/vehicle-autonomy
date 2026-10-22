"""Application use cases over a runtime interface; no command port is exposed."""

from __future__ import annotations

from typing import Protocol


class MissionCoordinator(Protocol):
    def start_mission(self) -> dict: ...
    def cancel_mission(self) -> dict: ...
    def get_status(self) -> dict: ...
    def shutdown(self) -> dict: ...


class MissionService:
    def __init__(self, coordinator: MissionCoordinator) -> None:
        self._coordinator = coordinator

    def start_mission(self) -> dict:
        return self._coordinator.start_mission()

    def cancel_mission(self) -> dict:
        return self._coordinator.cancel_mission()

    def get_status(self) -> dict:
        return self._coordinator.get_status()

    def shutdown(self) -> dict:
        return self._coordinator.shutdown()
