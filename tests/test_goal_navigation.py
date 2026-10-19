"""Goal binding, nonblocking planning, cancellation and immutable admission."""
from dataclasses import replace
from datetime import datetime,timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import time
from types import SimpleNamespace
import unittest

from application.navigation_goals import GoalCatalog,NavigationPolicy
from application.planning import ReadOnlyPlanningService
from contracts.core.time import TimePoint
from deployment.goal_navigation import GoalNavigation
from deployment.navigation_job import PlanningJob
from planning.models import PathCandidate,PlanningError,Pose2D
from tests import test_path_following as nav_helpers


class Backend:
    name = "nav2.SmacPlanner2D.jazzy"
    last_directory = None
    def compute(self,request,grid):
        return PathCandidate(request.request_id,request.context.sha256,request.context.frame_epoch,
                             request.context.grid.frame_id,(request.start,request.goal))


class Job:
    done = False
    closed = False
    cancelled = False
    def __init__(self,context,start,goal,policy,clearance,directory):
        self.backend=Backend()
        self.value=ReadOnlyPlanningService(lambda:context,self.backend,lambda:context.captured_at).plan(
            start,goal,clearance_m=clearance)
    def result(self):return self.value
    def cancel(self):self.cancelled=True
    def close(self):self.closed=True


class GoalTests(unittest.TestCase):
    def setUp(self):
        self.helper=nav_helpers.NavigationTests();self.helper.setUp()
        self.helper.world=replace(self.helper.world,vehicle=replace(self.helper.world.vehicle,
            operation=replace(self.helper.world.vehicle.operation,armed=False)))
        self.addCleanup(self.helper.doCleanups)
        self.directory=Path(self.helper.directory.name)
        self.path=self.directory/"goals.toml"
        self.path.write_text('schema=1\nenvironment_id="test.environment"\n[[goals]]\nname="A"\nframe="odom"\nreference_point="navigation_reference"\nposition=[0.7,0.0]\n')
        self.events=[]
        self.child=None
        self.app=SimpleNamespace(navigation_goals=GoalCatalog(self.path),navigation=self.helper.supervisor,
            environment=SimpleNamespace(resource_id="test.environment",reference=self.helper.world.environment),
            environment_fault=False,vehicle=SimpleNamespace(world_epoch=self.helper.world.version.generation_id,
                world_snapshot=lambda:self.helper.world,clock=lambda:self.helper.now,
                authority=SimpleNamespace(system_send=False,action_send=False)),
            _emit=lambda event,**fields:self.events.append((event,fields)),_mission_status=lambda:self.child,
            start_mission=self.launch,_cancel_child=self.cancel_child)

    def launch(self,name,**kwargs):
        self.assertIn(name,("follow_path","safe_recovery"))
        if name == "follow_path":self.app.navigation.admit(self.helper.world,self.helper.now)
        self.child={"task_id":"child-run" if self.child is None else self.child['task_id']+'-next',"status":"RUNNING","error":None,"step":name,"steps":[],
                    "effects":{},"requests":{},"stops":{}}
        return self.child

    def cancel_child(self):
        self.child["status"]="EXITING"

    def task(self):return GoalNavigation(self.app,"A",job_factory=Job)

    def test_catalog_is_explicit_versioned_and_strict(self):
        catalog=self.app.navigation_goals
        self.assertEqual(catalog.goals['A'].resolve(self.app.environment),Pose2D(.7,0))
        for old,new in (('reference_point="navigation_reference"','reference_point="base_link"'),
                        ('frame="odom"','frame="map"'),('position=[0.7,0.0]','position=[true,0.0]')):
            original=self.path.read_text();self.path.write_text(original.replace(old,new))
            with self.assertRaises(ValueError):GoalCatalog(self.path)
            self.path.write_text(original)
        self.path.write_text(self.path.read_text()+'\nunknown=2\n')
        with self.assertRaises(ValueError):catalog.check(self.app.environment)

    def test_bounded_policy_and_unknown_goal_rejected(self):
        for changes in ({"max_replans":3},{"total_timeout_s":float('nan')},{"planning_timeout_s":21},{"max_replans":True}):
            with self.assertRaises(ValueError):NavigationPolicy(**changes)
        with self.assertRaises(ValueError):GoalNavigation(self.app,'missing',job_factory=Job)

    def test_pending_job_never_starts_vehicle_and_result_reenters_admission(self):
        task=self.task()
        for _ in range(50):task.tick(self.app)
        self.assertEqual(task.status,'PLANNING');self.assertIsNone(self.child)
        task.job.done=True;task.tick(self.app)
        self.assertEqual(task.status,'RUNNING')
        self.assertEqual(task.child_id,'child-run')
        self.assertIsNotNone(self.app.navigation.parameters)
        self.child['status']='SUCCEEDED';task.tick(self.app)
        self.assertEqual(task.status,'SUCCEEDED')

    def test_cancel_discards_a_late_success_and_waits_for_worker_cleanup(self):
        task=self.task();job=task.job
        task.cancel(self.app);task.tick(self.app)
        self.assertTrue(job.cancelled);self.assertTrue(task.active)
        job.done=True;task.tick(self.app)
        self.assertEqual(task.status,'CANCELLED');self.assertIsNone(self.child)
        self.assertTrue(job.closed)

    def test_catalog_epoch_and_source_changes_fail_without_dispatch(self):
        for change in ('catalog','epoch','source'):
            task=self.task();job=task.job
            old=self.app.vehicle.world_epoch
            context=self.app.navigation.context
            source=self.path.read_text()
            if change=='catalog':self.path.write_text(source+'\n# changed\n')
            if change=='epoch':self.app.vehicle.world_epoch='new'
            if change=='source':self.app.navigation.context=replace(context,reference=replace(context.reference,
                version=replace(context.reference.version,generation_id='new-source')))
            job.done=True;task.tick(self.app)
            self.assertEqual(task.status,'FAILED');self.assertIsNone(self.child)
            self.path.write_text(source);self.app.vehicle.world_epoch=old;self.app.navigation.context=context

    def test_cancel_during_motion_waits_for_child_stop(self):
        task=self.task();task.job.done=True;task.tick(self.app)
        task.cancel(self.app);task.tick(self.app)
        self.assertEqual(task.status,'CANCELLING');self.assertEqual(self.child['status'],'EXITING')
        self.child['status']='CANCELLED';task.tick(self.app)
        self.assertEqual(task.status,'CANCELLED')

    def test_replan_waits_for_stop_disarm_and_obeys_attempt_budget(self):
        self.app.navigation_goals.policy=NavigationPolicy(max_replans=1,retry_delay_s=.1)
        task=self.task();task.job.done=True;task.tick(self.app)
        old_id=task.child_id
        self.child.update(status='FAILED',error='navigation_path_blocked: obstacle')
        self.app.navigation.finish();task.tick(self.app)
        self.assertEqual(task.status,'RECOVERING');self.assertNotEqual(task.child_id,old_id)
        for _ in range(10):task.tick(self.app)
        self.assertEqual(task.attempt,1);self.assertIsNone(task.job)
        self.child.update(status='SUCCEEDED',error=None);task.tick(self.app)
        self.assertEqual(task.status,'RETRY_WAIT')
        self.helper.now=replace(self.helper.now,monotonic_ns=self.helper.now.monotonic_ns+110_000_000)
        task.tick(self.app);self.assertEqual(task.attempt,2)
        task.job.done=True;task.tick(self.app)
        self.child.update(status='FAILED',error='navigation_path_blocked: second obstacle')
        self.app.navigation.finish();task.tick(self.app)
        self.assertEqual(task.status,'FAILED');self.assertEqual(task.attempt,2)

    def test_nonrecoverable_faults_and_default_policy_never_retry(self):
        for error in ('navigation_map_unavailable','navigation_alignment_changed','Safety rejected','navigation_path_blocked: obstacle'):
            self.child=None
            self.app.navigation_goals.policy=NavigationPolicy(max_replans=0 if 'path_blocked' in error else 2)
            task=self.task();task.job.done=True;task.tick(self.app)
            self.child.update(status='FAILED',error=error)
            self.app.navigation.finish();task.tick(self.app)
            self.assertEqual(task.status,'FAILED');self.assertEqual(task.attempt,1)

    def test_cancel_recovery_and_total_deadline_do_not_start_another_job(self):
        self.app.navigation_goals.policy=NavigationPolicy(max_replans=2)
        task=self.task();task.job.done=True;task.tick(self.app)
        self.child.update(status='FAILED',error='navigation_path_blocked: obstacle')
        self.app.navigation.finish();task.tick(self.app)
        task.cancel(self.app);task.tick(self.app)
        self.assertEqual(task.status,'CANCELLING');self.assertEqual(task.attempt,1)
        self.child['status']='CANCELLED';task.tick(self.app)
        self.assertEqual(task.status,'CANCELLED')
        self.child=None
        task=self.task();task.deadline_ns=self.helper.now.monotonic_ns-1
        task.tick(self.app);task.job.done=True;task.tick(self.app)
        self.assertEqual(task.status,'FAILED');self.assertIn('total_deadline',task.error)

    def test_background_work_does_not_run_in_vehicle_tick(self):
        entered,release=Event(),Event()
        class Blocking(Backend):
            def compute(self,request,grid):
                entered.set();release.wait(2)
                return super().compute(request,grid)
        now=TimePoint(time.monotonic_ns(),datetime.now(timezone.utc),'host-monotonic-simulation')
        context=replace(self.helper.supervisor.context,captured_at=now)
        job=PlanningJob(context,Pose2D(.25,0),Pose2D(.7,0),NavigationPolicy(),.95,
            self.directory/'job',backend_factory=Blocking)
        self.assertTrue(entered.wait(1));self.assertFalse(job.done)
        release.set();job.future.result(timeout=2);job.close()
        self.assertTrue(job.closed)

    def test_completed_backend_timeout_still_joins_its_worker(self):
        class TimedOut(Backend):
            def compute(self,request,grid):raise TimeoutError('backend deadline')
        now=TimePoint(time.monotonic_ns(),datetime.now(timezone.utc),'host-monotonic-simulation')
        context=replace(self.helper.supervisor.context,captured_at=now)
        job=PlanningJob(context,Pose2D(.25,0),Pose2D(.7,0),NavigationPolicy(),.95,
            self.directory/'timeout-job',backend_factory=TimedOut)
        with self.assertRaises(TimeoutError):job.future.result(timeout=2)
        job.close()
        self.assertTrue(job.closed)
