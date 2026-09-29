"""Compatibility import for the CUADC 2026 Action owner."""

import time  # Shared clock module for existing test and integration patches.

from applications.cuadc_2026.actions.goto_waypoint import GotoWaypointAction

__all__ = ['GotoWaypointAction']
