"""Local use cases; neither a vehicle command port nor a transport is exposed."""
from typing import Protocol


class RuntimeCoordinator(Protocol):
    def get_status(self, *, include_task=True) -> dict: ...
    def start_mission(self, name: str) -> dict: ...
    def cancel_mission(self) -> dict: ...
    def request_shutdown(self) -> dict: ...


class RuntimeService:
    def __init__(self, coordinator: RuntimeCoordinator):
        self.coordinator = coordinator

    def handle(self, command: str, payload: dict) -> dict:
        if command == "status" and payload == {"view":"state"}:
            return self.coordinator.get_status(include_task=False)
        if command == "start":
            if set(payload) != {"mission"} or type(payload["mission"]) is not str:
                raise ValueError("start requires only a registered mission name")
            return self.coordinator.start_mission(payload["mission"])
        if payload:
            raise ValueError("command takes no payload")
        operations = {"status": self.coordinator.get_status,
                      "cancel": self.coordinator.cancel_mission,
                      "shutdown": self.coordinator.request_shutdown}
        if command not in operations:
            raise ValueError("unknown control command")
        return operations[command]()
