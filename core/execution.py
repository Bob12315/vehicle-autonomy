"""Only boundary permitted to submit a vehicle effect."""

from __future__ import annotations

from dataclasses import dataclass

from contracts.core.models import Effect
from contracts.core.ports import SafetyPolicy
from contracts.vehicle.ports import VehicleCommandPort
from contracts.world.models import WorldSnapshot


@dataclass(frozen=True)
class SendGate:
    system_enabled: bool = False
    action_enabled: bool = False


class ExecutionGateway:
    def __init__(self, commands: VehicleCommandPort, safety: SafetyPolicy) -> None:
        self._commands = commands
        self._safety = safety

    def submit(self, effect: Effect, snapshot: WorldSnapshot, gate: SendGate = SendGate()) -> bool:
        if not gate.system_enabled or not gate.action_enabled:
            return False
        if not self._safety.evaluate(effect, snapshot):
            return False
        self._commands.submit(effect)
        return True
