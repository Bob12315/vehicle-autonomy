"""Explicit read-only Nav2 planning entry; never opens a vehicle connection."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from application.planning import ReadOnlyPlanningService
from contracts.core.primitives import ResourceVersion
from contracts.core.time import TimePoint
from contracts.world.models import ResourceReference
from integrations.ros2.nav2_planner import Nav2Planner
from mapping.exchange import MappingConfig, MappingInput
from mapping.grid import MapStore, atomic_json
from planning.models import MapContext, PlanningError, Pose2D


class LiveMapProvider:
    """Query the existing public Application status; no mutation API is used."""
    def __init__(self, config, control_socket):
        self.config, self.control_socket = config, control_socket
        self.reader = MappingInput(config)

    def clock(self):
        return TimePoint(time.monotonic_ns(),datetime.now(timezone.utc),self.config.clock_domain_id)

    def __call__(self):
        from app.control import request
        response = request(self.control_socket,"status",timeout_s=.5)
        if not response["ok"]:
            raise PlanningError("STALE_MAP","Application status unavailable")
        state = response["result"]
        if state["vehicle_kind"] != "rover" or state["state"] != "READY" or not state["connected"] or state["system_send"] or state["action_send"]:
            raise PlanningError("STALE_MAP","live planning requires an idle read-only Rover Application")
        if state["clock_domain_id"] != self.config.clock_domain_id or not (state.get("mapping") or {}).get("adopted"):
            raise PlanningError("STALE_MAP","Application has no adopted map in the configured clock domain")
        epoch = state["world_version"]["generation"]
        value = self.reader.poll(self.clock(),epoch)
        if value is None:
            raise PlanningError("STALE_MAP",self.reader.health["error"])
        if (value.sha256,str(value.reference.version.generation_id)) != (state["mapping"]["sha256"],state["mapping"]["source_epoch"]):
            raise PlanningError("MAP_CHANGED","Application and map exchange do not describe the same map")
        return MapContext(value.reference,value.sha256,epoch,value.grid,"live_map",value.captured_at,self.config.max_age_ns)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--map-store",type=Path,help="recorded immutable map store; no live freshness claim")
    source.add_argument("--mapping-config",type=Path,help="live P18 map exchange configuration")
    parser.add_argument("--map-sha256")
    parser.add_argument("--control-socket")
    parser.add_argument("--clock-domain",default="host-monotonic-simulation")
    parser.add_argument("--frame",default="map",help="explicit frame of start and goal")
    parser.add_argument("--start",nargs=2,type=float,required=True,metavar=("X","Y"))
    parser.add_argument("--goal",nargs=2,type=float,required=True,metavar=("X","Y"))
    parser.add_argument("--start-yaw",type=float,default=0.)
    parser.add_argument("--goal-yaw",type=float,default=0.)
    parser.add_argument("--clearance",type=float,default=.55)
    parser.add_argument("--timeout",type=float,default=15.)
    parser.add_argument("--evidence-directory",type=Path,default=Path("artifacts/simulation/nav2-planning"))
    parser.add_argument("--output",type=Path)
    args = parser.parse_args()
    if args.map_store is not None:
        if not args.map_sha256 or args.control_socket:
            parser.error("recorded planning requires --map-sha256 and accepts no control socket")
    elif not args.control_socket or args.map_sha256:
        parser.error("live planning requires --control-socket and accepts no recorded map hash")
    try:
        if args.map_store is not None:
            grid = MapStore(args.map_store).load(args.map_sha256)
            context = MapContext(ResourceReference("recorded.map",ResourceVersion("recording:"+args.map_sha256,0)),
                args.map_sha256,"recording:"+args.map_sha256,grid,"recorded_map")
            provider = lambda: context
            clock = lambda: TimePoint(time.monotonic_ns(),datetime.now(timezone.utc),"host-monotonic-planning")
        else:
            provider = LiveMapProvider(MappingConfig.load(args.mapping_config,args.clock_domain),args.control_socket)
            clock = provider.clock
        original_provider = provider
        def checked_provider():
            context = original_provider()
            if context.grid.frame_id != args.frame:
                raise PlanningError("INVALID_INPUT","start/goal frame does not match the source map")
            return context
        backend = Nav2Planner(args.evidence_directory)
        result = ReadOnlyPlanningService(checked_provider,backend,clock).plan(
            Pose2D(*args.start,args.start_yaw),Pose2D(*args.goal,args.goal_yaw),timeout_s=args.timeout,clearance_m=args.clearance)
        response = {"ok":True,"result":result.document(),"evidence_directory":str(backend.last_directory)}
    except (OSError,ValueError,TypeError,RuntimeError,KeyError,RecursionError) as exc:
        response = {"ok":False,"result":None,"error":{"code":getattr(exc,"code","INVALID_INPUT"),"message":str(exc)}}
    if args.output is not None:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        atomic_json(args.output,response)
    print(json.dumps(response,allow_nan=False))
    return 0 if response["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
