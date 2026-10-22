"""Stable identity, version, and immutable JSON primitives."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from enum import Enum
import math
from typing import TypeAlias


class Identifier(str):
    """Runtime-validated, string-compatible identity value."""

    __slots__ = ()

    def __new__(cls, value: str) -> "Identifier":
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{cls.__name__} must be a non-empty string")
        return str.__new__(cls, value)


class VehicleId(Identifier):
    __slots__ = ()


class SensorId(Identifier):
    __slots__ = ()


class ProducerId(Identifier):
    __slots__ = ()


class ObservationId(Identifier):
    __slots__ = ()


class SnapshotId(Identifier):
    __slots__ = ()


class EffectId(Identifier):
    __slots__ = ()


class RunId(Identifier):
    __slots__ = ()


class ActionInstanceId(Identifier):
    __slots__ = ()


class LeaseId(Identifier):
    __slots__ = ()


class LinkSessionId(Identifier):
    __slots__ = ()


class CommandId(Identifier):
    __slots__ = ()


class IdempotencyKey(Identifier):
    __slots__ = ()


class ResourceId(Identifier):
    __slots__ = ()


class ResourceGenerationId(Identifier):
    __slots__ = ()


@dataclass(frozen=True, slots=True, order=True)
class SchemaVersion:
    major: int
    minor: int

    def __post_init__(self) -> None:
        for name, value in (("major", self.major), ("minor", self.minor)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")

    @classmethod
    def parse(cls, value: str) -> "SchemaVersion":
        if not isinstance(value, str):
            raise TypeError("schema version must be a string")
        parts = value.split(".")
        if len(parts) != 2 or any(not part.isdecimal() for part in parts):
            raise ValueError("schema version must use MAJOR.MINOR")
        return cls(int(parts[0]), int(parts[1]))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}"


@dataclass(frozen=True, slots=True, order=True)
class ResourceVersion:
    generation_id: ResourceGenerationId
    revision: int

    def __post_init__(self) -> None:
        if not isinstance(self.generation_id, ResourceGenerationId):
            object.__setattr__(self, "generation_id", ResourceGenerationId(self.generation_id))
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 0:
            raise ValueError("resource revision must be a non-negative integer")


FrozenScalar: TypeAlias = None | bool | int | float | str


@dataclass(frozen=True, slots=True)
class FrozenObject(Mapping[str, "FrozenJson"]):
    """Canonical immutable mapping used for JSON-shaped extension metadata."""

    items_tuple: tuple[tuple[str, "FrozenJson"], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.items_tuple, tuple):
            raise TypeError("frozen object items must be a tuple")
        if any(not isinstance(item, tuple) or len(item) != 2 for item in self.items_tuple):
            raise TypeError("frozen object items must be key/value pairs")
        keys = tuple(key for key, _ in self.items_tuple)
        if any(not isinstance(key, str) or not key for key in keys):
            raise ValueError("frozen object keys must be non-empty strings")
        if len(keys) != len(set(keys)):
            raise ValueError("frozen object keys must be unique")
        if keys != tuple(sorted(keys)):
            raise ValueError("frozen object keys must be in canonical order")
        for _, value in self.items_tuple:
            if freeze_json(value) != value:
                raise TypeError("frozen object values must be deeply immutable JSON")

    def __getitem__(self, key: str) -> "FrozenJson":
        for candidate, value in self.items_tuple:
            if candidate == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return (key for key, _ in self.items_tuple)

    def __len__(self) -> int:
        return len(self.items_tuple)


FrozenJson: TypeAlias = FrozenScalar | tuple["FrozenJson", ...] | FrozenObject


def freeze_json(value: object) -> FrozenJson:
    """Convert JSON-shaped input to sorted, recursively immutable values."""

    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("FrozenJson rejects NaN and infinity")
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("FrozenJson object keys must be strings")
        return FrozenObject(tuple(sorted((key, freeze_json(item)) for key, item in value.items())))
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item) for item in value)
    raise TypeError(f"unsupported FrozenJson value: {type(value).__name__}")


def thaw_json(value: FrozenJson) -> object:
    """Return a fresh mutable JSON-shaped value for an external serializer."""

    if isinstance(value, FrozenObject):
        return {key: thaw_json(item) for key, item in value.items_tuple}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


def is_deeply_immutable(value: object) -> bool:
    """Check the supported immutable shapes used inside published contracts."""

    if value is None or isinstance(value, (str, bytes, bool, int, Enum, datetime)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, FrozenObject):
        return all(is_deeply_immutable(item) for _, item in value.items_tuple)
    if isinstance(value, tuple | frozenset):
        return all(is_deeply_immutable(item) for item in value)
    if is_dataclass(value) and not isinstance(value, type):
        parameters = getattr(type(value), "__dataclass_params__", None)
        return bool(parameters and parameters.frozen) and all(
            is_deeply_immutable(getattr(value, item.name)) for item in fields(value)
        )
    return False
