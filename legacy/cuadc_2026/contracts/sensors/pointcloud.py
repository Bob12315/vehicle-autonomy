"""LiDAR extension boundary; P5 does not implement a point-cloud driver."""

from __future__ import annotations

from dataclasses import dataclass

from contracts.platform.common import ClockStamp


@dataclass(frozen=True, slots=True)
class PointCloudFrame:
    source_id: str
    frame_id: int
    captured_at: ClockStamp
    coordinate_frame: str
    point_count: int
    points_xyz_m: tuple[tuple[float, float, float], ...]

    def __post_init__(self) -> None:
        if not self.source_id or self.frame_id < 0 or not self.coordinate_frame:
            raise ValueError("invalid point-cloud identity")
        if self.point_count != len(self.points_xyz_m):
            raise ValueError("point count mismatch")
