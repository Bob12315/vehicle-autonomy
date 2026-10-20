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
        if command == 'reports' and payload == {}:
            from pathlib import Path
            from application.reports import release_audit
            return release_audit(Path(__file__).resolve().parents[1])
        if command == 'start_checked':
            if (set(payload) != {'mission','expected_session'} or type(payload['mission']) is not str
                    or type(payload['expected_session']) is not str):
                raise ValueError('registered mission and explicit expected session required')
            # Check and mutation occur in the same Application event-loop request.
            # No remote status/start race may cross a reconnect or process restart.
            state = self.coordinator.get_status(include_task=False)
            if state.get('session_id') != payload['expected_session']:
                raise ValueError('application session changed; new authorization required')
            return self.coordinator.start_mission(payload['mission'])
        if command == 'camera' and payload == {}:
            camera = getattr(self.coordinator, 'camera_frame', None)
            if camera is None:
                raise ValueError('this composition has no live camera use case')
            return camera()
        if command == 'map' and payload == {}:
            map_view = getattr(self.coordinator, 'map_view', None)
            if map_view is None:
                raise ValueError('this composition has no adopted map')
            return map_view()
        if command=='anchor':
            if set(payload)!={'path'} or type(payload['path']) is not str:
                raise ValueError('anchor requires only an explicit output path')
            return self.coordinator.export_map_anchor(payload['path'])
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
