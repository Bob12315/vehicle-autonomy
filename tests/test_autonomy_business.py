"""Business composition, immutable observations, deadlines and observed cleanup."""
from dataclasses import replace
from datetime import datetime,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import unittest
from application.autonomy_recipes import RecipeCatalog
from contracts.core.geometry import Twist3,Vector3
from contracts.core.primitives import ResourceVersion
from contracts.core.quality import QualityState
from contracts.core.stamped import Stamped
from contracts.core.time import TimePoint
from deployment.autonomy_business import AutonomyBusiness
from planning.models import Pose2D


class Navigation:
    def __init__(self,n):self.task_id='navigation:'+str(n);self.status='RUNNING';self.error=None;self.attempt=1;self.cancel_requested=False
    @property
    def active(self):return self.status not in ('SUCCEEDED','FAILED','CANCELLED')
    def cancel(self,app,error=None):self.cancel_requested=True
    def view(self,app):return {'task_id':self.task_id,'status':self.status,'error':self.error,'effects':{},'requests':{},'steps':[],'stops':{}}


class BusinessTests(unittest.TestCase):
    def setUp(self):
        self.directory=TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.now=TimePoint(1_000_000_000,datetime.now(timezone.utc),'test')
        self.position=NS(value=Vector3(2,1,0),frame_id='odom',captured_at=self.now)
        self.obj=NS(object_id='target',producer_id='sim.objects:test',label='bucket_1',confidence=.9,
                    quality=QualityState.VALID,position=self.position,source_observation_id='capture:1')
        self.world=NS(objects=(self.obj,),version=ResourceVersion('epoch',1),
            localization=NS(twist=NS(value=Twist3(Vector3(0,0,0),Vector3(0,0,0)))),vehicle=NS(operation=NS(armed=False)))
        goal=NS(frame='odom',resolve=lambda env:Pose2D(.8,2))
        goals=NS(goals={'A':goal,'B':goal,'HOME':goal})
        self.path=Path(self.directory.name)/'recipes.toml'
        self.path.write_text('schema=1\n[[recipes]]\nname="PATROL"\ngoals=["A","B","HOME"]\ntotal_timeout_s=300\n[[recipes]]\nname="INSPECT"\ngoals=["A","HOME"]\ntotal_timeout_s=240\ninspection_label="bucket_1"\ninspection_at="A"\n')
        self.launched=[];self.cleanup=None;self.events=[]
        self.app=NS(autonomy_recipes=RecipeCatalog(self.path,goals),navigation_goals=goals,
            vehicle=NS(clock=lambda:self.now,world_epoch='epoch',world_snapshot=lambda:self.world),
            environment=NS(reference='environment:1'),_launch_goal=self.launch,_mission_status=lambda:self.cleanup,
            start_mission=self.recover,_cancel_child=lambda:self.cleanup.update(status='EXITING'),
            _emit=lambda event,**data:self.events.append((event,data)))

    def launch(self,name):
        self.launched.append(name);return Navigation(len(self.launched))
    def recover(self,name,**kwargs):
        self.assertEqual(name,'safe_recovery');self.cleanup={'task_id':'cleanup','status':'RUNNING','error':None}
        return self.cleanup

    def test_named_patrol_runs_each_goal_with_separate_navigation_identity(self):
        task=AutonomyBusiness(self.app,'PATROL')
        for i in range(3):task.navigation.status='SUCCEEDED';task.tick(self.app)
        self.assertEqual(task.status,'SUCCEEDED');self.assertEqual(self.launched,['A','B','HOME'])
        self.assertEqual(len({c['navigation_task_id'] for c in task.checkpoints}),3)
        self.assertEqual(task.inspections,[])

    def test_inspection_records_source_observation_after_disarmed_stop_then_returns_home(self):
        task=AutonomyBusiness(self.app,'INSPECT');task.navigation.status='SUCCEEDED';task.tick(self.app)
        self.assertEqual(task.inspections[0]['observation_id'],'capture:1');self.assertEqual(self.launched,['A','HOME'])
        self.world.objects=();task.navigation.status='SUCCEEDED';task.tick(self.app)
        self.assertEqual(task.status,'SUCCEEDED')

    def test_lost_expired_or_moved_target_cancels_navigation_and_waits_for_cleanup(self):
        for fault in ('lost','expired','moved'):
            self.world.objects=(self.obj,);self.position.value=Vector3(2,1,0);self.now=self.position.captured_at
            task=AutonomyBusiness(self.app,'INSPECT')
            if fault=='lost':self.world.objects=()
            if fault=='expired':self.now=replace(self.now,monotonic_ns=self.now.monotonic_ns+600_000_000)
            if fault=='moved':self.world.objects=(NS(**{**vars(self.obj),'position':NS(**{**vars(self.position),'value':Vector3(2.3,1,0)})}),)
            task.tick(self.app)
            self.assertEqual(task.status,'CANCELLING');self.assertTrue(task.navigation.cancel_requested)
            self.assertIsNone(task.cleanup_id)
            task.navigation.status='CANCELLED';task.tick(self.app)
            self.assertEqual(task.status,'CLEANUP');self.assertEqual(task.inspections,[])
            self.cleanup['status']='SUCCEEDED';task.tick(self.app)
            self.assertEqual(task.status,'FAILED')

    def test_cancel_during_planning_does_not_submit_next_checkpoint(self):
        task=AutonomyBusiness(self.app,'PATROL');task.navigation.status='PLANNING'
        task.cancel(self.app);task.tick(self.app);self.assertEqual(len(self.launched),1)
        task.navigation.status='CANCELLED';task.tick(self.app)
        self.cleanup['status']='SUCCEEDED';task.tick(self.app)
        self.assertEqual(task.status,'CANCELLED');self.assertEqual(task.checkpoints,[])

    def test_recipe_and_epoch_mutation_deadline_and_cleanup_failure_are_explicit(self):
        task=AutonomyBusiness(self.app,'PATROL');self.app.vehicle.world_epoch='new'
        task.tick(self.app);self.assertIn('epoch',task.error)
        task.navigation.status='CANCELLED';task.tick(self.app)
        self.cleanup.update(status='FAILED',error='stop unconfirmed');task.tick(self.app)
        self.assertEqual(task.status,'FAILED');self.assertIn('cleanup_unconfirmed',task.error)
        self.app.vehicle.world_epoch='epoch';task=AutonomyBusiness(self.app,'PATROL')
        task.deadline_ns=self.now.monotonic_ns-1;task.tick(self.app)
        self.assertIn('deadline',task.error)
        self.path.write_text(self.path.read_text()+'\n# changed')
        with self.assertRaises(ValueError):AutonomyBusiness(self.app,'PATROL')

    def test_inspection_rejects_bad_quality_unknown_approach_and_unregistered_goals(self):
        self.obj.confidence=.1
        with self.assertRaises(ValueError):AutonomyBusiness(self.app,'INSPECT')
        self.assertEqual(self.launched,[])
        self.path.write_text(self.path.read_text().replace('"HOME"]','"UNKNOWN"]'))
        with self.assertRaises(ValueError):RecipeCatalog(self.path,self.app.navigation_goals)
