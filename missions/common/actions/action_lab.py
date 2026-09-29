"""Compatibility catalog import; CUADC 2026 owns the definitions."""

from applications.cuadc_2026.actions.definitions import (
    action_definition, action_definitions, action_lab_specs, create_action_lab_registry,
)

__all__ = ["action_definition", "action_definitions", "action_lab_specs", "create_action_lab_registry"]
