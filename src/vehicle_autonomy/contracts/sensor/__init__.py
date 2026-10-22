"""Sensor-facing data contracts."""

from vehicle_autonomy.contracts.sensor.observation import Observation
from vehicle_autonomy.contracts.sensor.data import DetectedObject, ObjectId

__all__ = ["Observation", "DetectedObject", "ObjectId"]
