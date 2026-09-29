"""Shared legacy ActionDefinition builder during catalog migration."""
from __future__ import annotations

from contracts.core.action import ExitBarrier
from missions.definitions import ActionDefinition


def _definition(
    name: str,
    factory,
    description: str,
    defaults: dict | None = None,
    *,
    properties: dict | None = None,
    required_inputs: tuple[str, ...] = (),
    output_properties: dict | None = None,
    parameter_aliases: dict[str, tuple[str, ...]] | None = None,
    parameter_schema_extra: dict | None = None,
    effects: tuple[str, ...] = (),
    exit_barrier: ExitBarrier = ExitBarrier.NONE,
) -> ActionDefinition:
    return ActionDefinition(
        name=name,
        revision="v1",
        factory=factory,
        label=name.replace("_", " ").title(),
        description=description,
        default_params=dict(defaults or {}),
        parameter_schema={"type": "object", "properties": dict(properties or {}), "additionalProperties": False, **dict(parameter_schema_extra or {})},
        required_inputs=required_inputs,
        output_schema={"type": "object", "properties": dict(output_properties or {}), "additionalProperties": False},
        parameter_aliases=dict(parameter_aliases or {}),
        allowed_effect_types=effects,
        exit_barrier=exit_barrier,
    )
