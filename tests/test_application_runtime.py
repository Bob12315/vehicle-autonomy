"""Mission identity, authorization and reconnection through the actual writer."""
from dataclasses import replace
import unittest
from contracts.core.primitives import SchemaVersion
from contracts.effects.vehicle import EffectEnvelope, ModeEffect
from deployment.application_runtime import ApplicationRuntime
from tests.test_simulation_runtime import SimulationRuntimeTests


class ApplicationRuntimeTests(SimulationRuntimeTests):
    def test_autonomy_request_requires_authorized_ready_application_before_recipe_reads(self):
        self.ready(False)
        self.app.autonomy_recipes=object()
        with self.assertRaisesRegex(ValueError,'authorized'):
            self.app.start_mission('autonomy:PATROL')
        self.app.allow_send=True;self.app.state='CONNECTING'
        with self.assertRaisesRegex(ValueError,'authorized'):
            self.app.start_mission('autonomy:PATROL')
        self.assertFalse(self.runtime.authority.system_send)
        self.assertEqual(self.transports[-1].writes,[])

    def ready(self, allow_send=True):
        self.app = ApplicationRuntime(self.runtime.profile, profile_name="copter_sim",
                                      allow_send=allow_send, runtime=self.runtime)
        self.runtime.connect()
        self.cycle(self.heartbeat() + self.state_messages())
        self.app.state = "READY"

    def app_cycle(self, data=b""):
        self.clock.advance()
        self.transports[-1].incoming.append(data)
        self.app.cycle()

    def test_sensor_shutdown_failure_cannot_prevent_vehicle_fencing(self):
        self.ready()
        self.app.start_mission('disarmed_mode')
        self.app_cycle()
        class BrokenSensor:
            def close(self):raise RuntimeError('worker would not stop')
        self.app.sensor=BrokenSensor()
        status=self.app.shutdown()
        self.assertFalse(self.runtime.connected)
        self.assertFalse(self.runtime.authority.system_send)
        self.assertIsNone(self.runtime.authority.lease)
        self.assertEqual(self.transports[-1].writes,[])
        self.assertEqual(status['shutdown_error'],'sensor_shutdown_unconfirmed:RuntimeError')

    def test_mission_preserves_ids_requires_ack_and_new_state(self):
        self.ready()
        task = self.app.start_mission("disarmed_mode")
        self.assertFalse(hasattr(self.app.task._world, "dispatch_envelope"))
        self.assertFalse(hasattr(self.app.task._world, "authority"))
        self.app_cycle()
        envelope = next(iter(self.app.envelopes.values()))
        self.assertEqual(str(envelope.run_id), task["task_id"])
        self.assertEqual(str(envelope.action_instance_id), f'{task["task_id"]}:mode:1')
        self.assertEqual(self.runtime.dispatch_envelope(envelope), self.runtime._dispatch_results[str(envelope.effect_id)])
        with self.assertRaises(ValueError):
            self.runtime.dispatch_envelope(replace(envelope, deadline=replace(envelope.deadline,
                monotonic_ns=envelope.deadline.monotonic_ns + 1)))
        self.app_cycle()
        self.assertEqual(len(self.transports[-1].writes), 1)
        self.app_cycle(self.sender.command_ack_encode(176, 0).pack(self.sender))
        self.assertEqual(self.app.task_status()["status"], "RUNNING")
        self.app_cycle(self.heartbeat(mode=4))
        self.app_cycle()
        self.assertEqual(self.app.task_status()["status"], "SUCCEEDED")
        self.assertFalse(self.runtime.authority.system_send)
        self.assertIsNone(self.runtime.authority.lease)

    def test_readonly_disconnect_and_old_envelope_isolation(self):
        self.ready(False)
        with self.assertRaises(ValueError):
            self.app.start_mission("disarmed_mode")
        self.app.allow_send = True
        self.app.start_mission("disarmed_mode")
        self.app_cycle()
        old = next(iter(self.app.envelopes.values()))
        self.transports[-1].disconnected = True
        self.app_cycle()
        self.assertEqual(self.app.task_status()["status"], "FAILED")
        self.app_cycle()
        self.app_cycle(self.heartbeat() + self.state_messages())
        self.assertEqual(self.app.state, "READY")
        self.assertFalse(self.runtime.authority.system_send)
        self.assertEqual(self.runtime.dispatch_envelope(old).reason, "inactive_mission_scope")
        self.assertEqual(self.transports[-1].writes, [])

    def test_wrong_action_and_expired_envelopes_write_nothing(self):
        self.ready()
        self.app.start_mission("disarmed_mode")
        run = self.app.task.view().run_id
        now = self.clock()
        wrong = EffectEnvelope(SchemaVersion(1, 0), "wrong", run, f"{run}:wrong:1", now,
                               replace(now, monotonic_ns=now.monotonic_ns+100), ModeEffect("GUIDED"))
        self.assertEqual(self.runtime.dispatch_envelope(wrong).reason, "inactive_mission_scope")
        expired = replace(wrong, effect_id="expired", action_instance_id=f"{run}:mode:1",
                          created_at=replace(now, monotonic_ns=now.monotonic_ns-100), deadline=now)
        self.assertEqual(self.runtime.dispatch_envelope(expired).reason, "invalid_effect_time")
        self.app_cycle()
        self.assertEqual(self.transports[-1].writes, [])
        self.app.cancel_mission()
        self.app_cycle()
        self.app_cycle()
        self.assertEqual(self.app.task_status()["status"], "CANCELLED")
        self.assertFalse(self.runtime.authority.action_send)


if __name__ == "__main__":
    unittest.main()
