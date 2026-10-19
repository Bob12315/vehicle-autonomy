"""Explicit, versioned navigation-reference goals; no device access."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import re
import tomllib

from planning.models import Pose2D


@dataclass(frozen=True, slots=True)
class NavigationGoal:
    name: str
    position: Pose2D | None
    environment_point: str | None
    frame: str = "odom"
    reference_point: str = "navigation_reference"

    def resolve(self, environment):
        if self.environment_point is not None:
            point = environment.resolve(self.environment_point)
            if point.frame != self.frame:
                raise ValueError("navigation goal/environment frame mismatch")
            return Pose2D(point.position.x, point.position.y)
        return self.position


@dataclass(frozen=True, slots=True)
class NavigationPolicy:
    planning_timeout_s: float = 15.
    total_timeout_s: float = 240.
    max_replans: int = 0
    retry_delay_s: float = .5
    planning_reserve_m: float = 0.

    def __post_init__(self):
        for name, low, high in (("planning_timeout_s",.1,20), ("total_timeout_s",1,600), ("retry_delay_s",.1,5), ("planning_reserve_m",0,.25)):
            value = getattr(self,name)
            if type(value) not in (int,float) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError("invalid bounded navigation policy: "+name)
        if type(self.max_replans) is not int or not 0 <= self.max_replans <= 2:
            raise ValueError("navigation permits at most two explicit replans")


class GoalCatalog:
    def __init__(self, path):
        self.path = Path(path)
        raw = self.path.read_bytes()
        if len(raw) > 65536:
            raise ValueError("navigation goals exceed size bound")
        self.sha256 = hashlib.sha256(raw).hexdigest()
        data = tomllib.loads(raw.decode())
        if set(data)-{"schema","environment_id","goals","policy","anchor_path"} or not {"schema","environment_id","goals"} <= set(data) or type(data["schema"]) is not int or data["schema"] != 1:
            raise ValueError("invalid navigation goal catalog")
        self.environment_id = data["environment_id"]
        if type(self.environment_id) is not str or not self.environment_id:
            raise ValueError("explicit navigation environment identity required")
        anchor=data.get('anchor_path')
        if anchor is not None and (type(anchor) is not str or not Path(anchor).is_absolute()):
            raise ValueError('map anchor path must be absolute')
        self.anchor_path=None if anchor is None else Path(anchor)
        if type(data["goals"]) is not list or not 1 <= len(data["goals"]) <= 64:
            raise ValueError("navigation catalog needs 1..64 goals")
        self.goals = {}
        for item in data["goals"]:
            if type(item) is not dict or set(item)-{"name","frame","reference_point","position","environment_point"} or not {"name","frame","reference_point"} <= set(item):
                raise ValueError("invalid navigation goal fields")
            if type(item["name"]) is not str or re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,47}",item["name"]) is None or item["name"] in self.goals:
                raise ValueError("invalid/duplicate navigation goal name")
            if item["frame"] not in ("odom","map") or item["reference_point"] != "navigation_reference":
                raise ValueError("explicit planar/navigation_reference goal required")
            if item['frame']=='map' and (self.anchor_path is None or 'environment_point' in item):
                raise ValueError('map goals require an explicit session anchor and map position')
            if ("position" in item) == ("environment_point" in item):
                raise ValueError("choose exactly one position or environment point")
            position, point = None, item.get("environment_point")
            if "position" in item:
                if type(item["position"]) is not list or len(item["position"]) != 2:
                    raise ValueError("navigation goal needs an SI planar pair")
                position = Pose2D(*item["position"])
            elif type(point) is not str or not point:
                raise ValueError("explicit environment point required")
            self.goals[item["name"]] = NavigationGoal(item["name"],position,point,item['frame'])
        policy = data.get("policy",{})
        if type(policy) is not dict or set(policy)-{"planning_timeout_s","total_timeout_s","max_replans","retry_delay_s","planning_reserve_m"}:
            raise ValueError("unknown navigation policy")
        self.policy = NavigationPolicy(**policy)

    def check(self, environment):
        if hashlib.sha256(self.path.read_bytes()).hexdigest() != self.sha256:
            raise ValueError("navigation_goal_catalog_changed")
        if environment is None or str(environment.resource_id) != self.environment_id:
            raise ValueError("navigation goal environment mismatch")
