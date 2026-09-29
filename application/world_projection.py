"""Compatibility projection from current Field reference to generic World data."""

from __future__ import annotations

from environments.cuadc_2026 import environment_reference_from_field
from world_model.projection import environment_reference_from_snapshot


__all__ = ["environment_reference_from_field", "environment_reference_from_snapshot"]
