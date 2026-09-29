"""Vehicle-independent descriptions of an operating environment."""

from .model import (
    CoordinateReference,
    EnvironmentProfile,
    EnvironmentSnapshot,
    EnvironmentSnapshotPort,
    NamedLocation,
)

__all__ = [
    "CoordinateReference", "EnvironmentProfile", "EnvironmentSnapshot",
    "EnvironmentSnapshotPort", "NamedLocation",
]
