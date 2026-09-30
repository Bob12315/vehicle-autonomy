"""Explicit P5 cycle composition; the caller owns scheduling and policy."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from contracts.core.time import TimePoint
from contracts.vehicle.command import CommandStatus
from core.vehicle_execution import StopResult, VehicleExecution
from vehicles.multirotor.session import ArduPilotSession


@dataclass(frozen=True, slots=True)
class CopterCycleResult:
    received_count: int
    stops: tuple[StopResult, ...]
    written: CommandStatus | None
    disconnected: bool


class CopterCycleDriver:
    """Invoke at a configured period shorter than the Safety deadman."""

    def __init__(self, *, session: ArduPilotSession, execution: VehicleExecution,
                 clock: Callable[[], TimePoint]) -> None:
        if not callable(clock):
            raise TypeError("clock is required")
        self._session = session
        self._execution = execution
        self._clock = clock

    def cycle(self) -> CopterCycleResult:
        disconnected = False
        messages: tuple[object, ...] = ()
        try:
            messages = self._session.poll(self._clock())
        except (OSError, ConnectionError):
            disconnected = True
        disconnected = disconnected or self._session.session_id is None
        stops = self._execution.tick(self._clock())
        written = None if disconnected else self._session.write_next(self._clock())
        return CopterCycleResult(len(messages), stops, written, disconnected)
