"""Compatibility import; implementation belongs to the multirotor plugin."""

import time  # Legacy tests and integrations patch this module's monotonic clock.

from vehicles.multirotor.actions.takeoff import TakeoffAction

__all__ = ["TakeoffAction"]
