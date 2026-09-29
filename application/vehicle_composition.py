"""Compatibility exports for the current CUADC application composition."""

from applications.cuadc_2026.composition import (
    capability_validator,
    compose_actions,
    create_registry,
    unsupported_action_reason,
)

__all__ = [
    "capability_validator", "compose_actions", "create_registry",
    "unsupported_action_reason",
]
