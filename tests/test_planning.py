"""Read-only planning provenance and independent continuous collision boundaries."""
from dataclasses import replace
from datetime import datetime, timezone
import ast
import hashlib
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.plan import LiveMapProvider
from application.planning import ReadOnlyPlanningService
from contracts.core.geometry import Pose3,Quaternion,Vector3
from contracts.core.primitives import ResourceVersion
from contracts.core.time import TimePoint
from contracts.world.models import ResourceReference
from mapping.exchange import MappingConfig
from mapping.grid import MapStore,OccupancyGrid,atomic_json,pose_to_json
from planning.collision import CollisionGrid
from planning.models import MapContext,PathCandidate,PlanningError,Pose2D

IDENTITY = Pose3(Vector3(0,0,0),Quaternion(0,0,0,1))


def context(grid=None, **changes):
    grid = grid or OccupancyGrid("map",.1,80,80,IDENTITY,(0,)*6400)
    return MapContext(ResourceReference("test.map",ResourceVersion("map-source",1)),
        hashlib.sha256(grid.encoded()).hexdigest(),"world-A",grid,"recorded_map",**changes)


class Backend:
    name = "test-only"
    def __init__(self,callback=None):self.callback,self.calls = callback,0
    def compute(self,request,grid):
        self.calls += 1
        result = PathCandidate(request.request_id,request.context.sha256,request.context.frame_epoch,
                               request.context.grid.frame_id,(request.start,request.goal))
        return self.callback(request,result) if self.callback else result


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.now = TimePoint(5_000_000_000,datetime(2026,10,19,tzinfo=timezone.utc),"test-clock")
        self.context = context()
        self.start,self.goal = Pose2D(2,4),Pose2D(6,4)

    def service(self,backend=None,provider=None):
        return ReadOnlyPlanningService(provider or (lambda:self.context),backend or Backend(),lambda:self.now)

    def test_valid_path_has_immutable_source_and_no_execution_authority(self):
        path = self.service().plan(self.start,self.goal)
        self.assertEqual(path.length_m,4)
        self.assertEqual(path.request.context.reference,self.context.reference)
        self.assertEqual(path.document()["map"]["source_kind"],"recorded_map")
        self.assertFalse(path.document()["executable"])
        with self.assertRaises(AttributeError):path.length_m = 0

    def test_sparse_segments_cannot_tunnel_through_thin_wall_or_unknown(self):
        for occupancy in (100,20,-1):
            cells = list(self.context.grid.cells)
            cells[40*80+40] = occupancy
            self.context = context(replace(self.context.grid,cells=tuple(cells)))
            with self.assertRaisesRegex(PlanningError,"intersects"):
                self.service().plan(self.start,self.goal)

    def test_footprint_clearance_blocks_clear_centerline(self):
        cells = list(self.context.grid.cells);cells[45*80+40] = 100
        self.context = context(replace(self.context.grid,cells=tuple(cells)))
        with self.assertRaisesRegex(PlanningError,"footprint intersects"):
            self.service().plan(self.start,self.goal)

    def test_grazing_the_lower_search_boundary_is_a_collision(self):
        cells = list(self.context.grid.cells);cells[39*80+40] = 100
        self.context = context(replace(self.context.grid,cells=tuple(cells)))
        with self.assertRaisesRegex(PlanningError,"intersects"):
            self.service().plan(Pose2D(2,4.5),Pose2D(6,4.5),clearance_m=.5)

    def test_map_edge_and_blocked_goal_rejected_before_backend(self):
        backend = Backend()
        with self.assertRaises(PlanningError):self.service(backend).plan(Pose2D(.1,4),self.goal)
        cells = list(self.context.grid.cells);cells[40*80+60] = 100
        self.context = context(replace(self.context.grid,cells=tuple(cells)))
        with self.assertRaises(PlanningError):self.service(backend).plan(self.start,self.goal)
        self.assertEqual(backend.calls,0)

    def test_request_identity_map_epoch_and_frame_cannot_be_replayed(self):
        for change in ({"request_id":"old"},{"map_sha256":"0"*64},{"frame_epoch":"world-B"},{"frame_id":"odom"}):
            with self.assertRaisesRegex(PlanningError,"does not match"):
                self.service(Backend(lambda r,c:replace(c,**change))).plan(self.start,self.goal)

    def test_clipped_endpoint_and_untyped_backend_rejected(self):
        backend = Backend(lambda r,c:replace(c,poses=(r.start,Pose2D(5.5,4))))
        with self.assertRaisesRegex(PlanningError,"endpoint"):
            self.service(backend).plan(self.start,self.goal)
        with self.assertRaisesRegex(PlanningError,"untyped"):
            self.service(Backend(lambda r,c:None)).plan(self.start,self.goal)

    def test_map_content_or_epoch_change_invalidates_result(self):
        cells = list(self.context.grid.cells);cells[0] = 100
        changed = context(replace(self.context.grid,cells=tuple(cells)))
        for other in (changed,replace(self.context,frame_epoch="world-B"),replace(self.context,reference=ResourceReference("test.map",ResourceVersion("another-source",1)))):
            values = iter((self.context,other))
            with self.assertRaisesRegex(PlanningError,"changed during"):
                self.service(provider=lambda:next(values)).plan(self.start,self.goal)

    def test_identical_content_revision_retains_original_dependency(self):
        newer = replace(self.context,reference=ResourceReference("test.map",ResourceVersion("map-source",2)))
        values = iter((self.context,newer))
        result = self.service(provider=lambda:next(values)).plan(self.start,self.goal)
        self.assertEqual(result.request.context.reference.version.revision,1)

    def test_live_stale_future_and_cross_clock_maps_rejected(self):
        for stamp in (replace(self.now,monotonic_ns=self.now.monotonic_ns-11_000_000) ,replace(self.now,monotonic_ns=self.now.monotonic_ns+1),replace(self.now,clock_domain_id="other")):
            self.context = replace(context(),source_kind="live_map",captured_at=stamp,max_age_ns=10_000_000)
            with self.assertRaises(PlanningError):self.service().plan(self.start,self.goal)

    def test_late_result_and_expired_live_map_are_not_accepted(self):
        def late(r,c):
            self.now = replace(self.now,monotonic_ns=self.now.monotonic_ns+2_000_000_000)
            return c
        with self.assertRaisesRegex(PlanningError,"deadline"):
            self.service(Backend(late)).plan(self.start,self.goal,timeout_s=1)
        self.context = replace(context(),source_kind="live_map",captured_at=self.now,max_age_ns=1_000_000_000)
        with self.assertRaisesRegex(PlanningError,"expired"):
            self.service(Backend(late)).plan(self.start,self.goal)

    def test_rotated_translated_map_origin_is_explicit(self):
        origin = Pose3(Vector3(-2,3,0),Quaternion(0,0,math.sin(.4),math.cos(.4)))
        self.context = context(replace(self.context.grid,origin=origin))
        start,goal = self.context.to_world(self.start),self.context.to_world(self.goal)
        path = self.service().plan(start,goal)
        self.assertAlmostEqual(path.length_m,4)
        recovered = self.context.to_local(start)
        self.assertAlmostEqual(recovered.x,self.start.x)
        self.assertAlmostEqual(recovered.y,self.start.y)

    def test_configuration_grid_blocks_unknown_and_keeps_a_margin(self):
        cells = list(self.context.grid.cells);cells[40*80+40] = -1
        self.context = context(replace(self.context.grid,cells=tuple(cells)))
        derived = CollisionGrid(self.context,.55).configuration_grid()
        self.assertEqual(derived.cells[40*80+34],100)
        self.assertEqual(derived.cells[40*80+32],0)
        self.assertEqual(derived.cells[0],100)
        self.assertEqual(self.context.grid.cells[40*80+40],-1)

    def test_invalid_geometry_and_unbounded_path_are_rejected(self):
        for values in ((float("nan"),0),(0,False),(0,0,4)):
            with self.assertRaises(ValueError):Pose2D(*values)
        with self.assertRaises(ValueError):replace(self.context,sha256="0"*64)
        with self.assertRaises(ValueError):PathCandidate("r",self.context.sha256,"e","map",())
        with self.assertRaises(ValueError):PathCandidate("r",self.context.sha256,"e","map",(self.start,)*8193)

    def test_domain_and_application_have_no_ros_or_command_dependencies(self):
        root = Path(__file__).resolve().parents[1]
        paths = list((root/"planning").rglob("*.py"))+[root/"application/planning.py"]
        forbidden = {"rclpy","nav2_msgs","vehicles","protocols","infrastructure","legacy","integrations"}
        for path in paths:
            for node in ast.walk(ast.parse(path.read_text())):
                modules = [n.name for n in node.names] if isinstance(node,ast.Import) else [node.module or ""] if isinstance(node,ast.ImportFrom) else []
                self.assertFalse(any(name.split('.')[0] in forbidden for name in modules),str(path))


class LivePlanningTests(unittest.TestCase):
    def test_public_status_only_and_unavailable_mapping_fails_closed(self):
        with TemporaryDirectory() as name:
            directory = Path(name)
            c = context();digest = MapStore(directory/"maps").save(c.grid)
            now = TimePoint(5_000_000_000,datetime(2026,10,19,tzinfo=timezone.utc),"test-clock")
            document = {"schema":1,"source":"ros2.slam_toolbox","source_epoch":"source-A","frame_epoch":"world-A",
                "clock_domain_id":"test-clock","published_ns":now.monotonic_ns,"status":"VALID",
                "map":{"revision":1,"sha256":digest,"captured_ns":now.monotonic_ns-1},
                "base_link_in_map":pose_to_json(IDENTITY),"odom_in_map":pose_to_json(IDENTITY)}
            atomic_json(directory/"bridge.json",document)
            state = {"vehicle_kind":"rover","state":"READY","connected":True,"system_send":False,"action_send":False,
                "clock_domain_id":"test-clock","world_version":{"generation":"world-A"},
                "mapping":{"adopted":True,"sha256":digest,"source_epoch":"source-A"}}
            provider = LiveMapProvider(MappingConfig(directory,"test-clock",10_000_000_000),"/unused-test.sock")
            provider.clock = lambda:now
            with patch("app.control.request",return_value={"ok":True,"result":state}) as status:
                self.assertEqual(provider().source_kind,"live_map")
                self.assertEqual(status.call_args.args[1],"status")
                for key,value in (("mapping",None),("system_send",True),("connected",False)):
                    original = state[key];state[key] = value
                    with self.assertRaises(PlanningError):provider()
                    state[key] = original
