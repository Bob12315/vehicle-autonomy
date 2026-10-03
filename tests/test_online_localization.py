"""Same-source cuts, source-age rejection and epoch isolation."""
from dataclasses import replace
import unittest
from contracts.core.geometry import Transform3, Quaternion, Vector3
from core.transform import TransformTree
from localization.online import OnlineLocalization
from tests import test_simulation_runtime as helpers


class OnlineLocalizationTests(unittest.TestCase):
    setUp = helpers.SimulationRuntimeTests.setUp
    make_transport = helpers.SimulationRuntimeTests.make_transport
    heartbeat = helpers.SimulationRuntimeTests.heartbeat
    state_messages = helpers.SimulationRuntimeTests.state_messages
    cycle = helpers.SimulationRuntimeTests.cycle

    def test_online_cut_transform_and_reconnect(self):
        self.runtime.connect()
        self.cycle(self.heartbeat()+self.state_messages())
        world = self.runtime.world_snapshot()
        self.assertEqual(world.vehicle.reported_pose, world.localization.pose)
        self.assertEqual(world.vehicle.reported_twist, world.localization.twist)
        self.assertEqual(world.vehicle.version.revision, world.localization.version.revision)
        dependency = next(d for d in world.dependencies if d.resource_type == "Transform")
        self.assertEqual(dependency.version, world.vehicle.version)
        transform = self.runtime.localization.tree.resolve("base_link", "odom", world.localization.pose.captured_at)
        self.assertEqual(transform.translation, world.localization.pose.value.position)
        inverse_point = self.runtime.localization.tree.transform_point(transform.translation, from_frame="odom",
            to_frame="base_link", at_time=world.localization.pose.captured_at)
        self.assertEqual(inverse_point, Vector3(0, 0, 0))
        old_epoch = self.runtime.localization.epoch
        old_time = world.localization.pose.captured_at
        self.transports[-1].disconnected = True
        self.cycle()
        self.runtime.connect()
        self.assertNotEqual(old_epoch, self.runtime.localization.epoch)
        with self.assertRaises(LookupError):
            self.runtime.localization.tree.resolve("odom", "base_link", old_time)
        self.runtime.shutdown()

    def test_stale_future_and_domain_have_no_adopted_estimate(self):
        self.runtime.connect()
        self.cycle(self.heartbeat()+self.state_messages())
        state = self.runtime.world_snapshot().vehicle
        now = self.clock()
        chain = OnlineLocalization(3_000_000_000)
        for stamp in (replace(now, monotonic_ns=now.monotonic_ns+1),
                      replace(now, clock_domain_id="other")):
            candidate = replace(state, reported_pose=replace(state.reported_pose, captured_at=stamp))
            self.assertEqual(chain.update(candidate, now), (None, None))
        self.assertEqual(chain.update(state, replace(now, monotonic_ns=now.monotonic_ns+4_000_000_000)),
                         (None, None))
        chain.update(state, now)
        with self.assertRaises(LookupError):
            chain.tree.resolve("map", "odom", now)
        with self.assertRaises(LookupError):
            chain.tree.resolve("base_link", "odom", replace(now, monotonic_ns=now.monotonic_ns+1))
        self.runtime.shutdown()

    def test_transform_history_is_bounded(self):
        tree = TransformTree(max_interpolation_gap_ns=100, max_dynamic_samples=2)
        now = self.clock()
        for i in range(3):
            tree.add_dynamic("base_link", "odom", replace(now, monotonic_ns=now.monotonic_ns+i),
                             Transform3(Vector3(i, 0, 0), Quaternion(0, 0, 0, 1)))
        with self.assertRaises(LookupError):
            tree.resolve("base_link", "odom", now)
