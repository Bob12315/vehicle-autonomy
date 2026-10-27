"""Real managed native cohort lifecycle. No vehicle movement bridge assembled."""
import argparse,json,os,time,hashlib
from pathlib import Path
from uuid import uuid4
from tests.simulation.launch import ROOT,install_signal_cleanup
from tests.simulation.phase5_sensors import SensorFixture
from tests.simulation.phase5_slam import start_slam
from tests.simulation.phase5_nav2_chain import _is_control
from vehicle_autonomy.actions.common.standard import ContextFactory,Empty
from vehicle_autonomy.actions.external.job import ExternalInstance
from vehicle_autonomy.actions.navigation.native_job import NativeNavigationJob
from vehicle_autonomy.app.bootstrap.native_navigation_processes import NativeNavigationProcesses
from vehicle_autonomy.app.bootstrap.navigation_ownership import OwnedNavigationIdentity,RESOURCES
from vehicle_autonomy.contracts.decision import ActionSpec


def run(path):
    f=SensorFixture(path,source_time_sync=True,secure=True);jobs=[];report={'passed':False,'motion_bridge_assembled':False}
    os.environ['VAF_SLAM_BOUNDARY_LIBRARY']=str((ROOT/'artifacts/phase5-world-navigation/slam-boundary/libvaf_slam_boundary.so').resolve())
    binary=ROOT/'artifacts/phase5-world-navigation/source-receiver-qualified/vaf_native_source_receiver'
    os.environ['VAF_NATIVE_SOURCE_RECEIVER']=str(binary);os.environ['VAF_NATIVE_SOURCE_RECEIVER_SHA256']=hashlib.sha256(binary.read_bytes()).hexdigest()
    try:
        f.start();start_slam(f,'slam',ROOT/'simulation/phase5/slam_mapping.yaml')
        identity=OwnedNavigationIdentity(f.driver.ownership);store=identity.provision()
        class Factory(ContextFactory):
            resource_store=store
            x=1.5
            def start_with_context(self,p,w,ctx):
                goal=dict(goal_id=uuid4().hex,action_id=ctx.action_id,target_id=ctx.target_id,vehicle_session=ctx.vehicle_session,world_generation=ctx.world_generation,map_epoch='native-probe-map',x_m=self.x,y_m=0.,yaw_rad=0.,provider_id=identity.provider_id,provider_epoch=identity.provider_epoch)
                job=ctx.external_jobs.start(lambda:NativeNavigationJob(identity,goal,security_environment=f.security_environment,world_name=f.owned.world,clock_domain=w.published_at.clock_domain_id,cohort_factory=NativeNavigationProcesses))
                jobs.append(job);return ExternalInstance(job)
        factory=Factory()
        f.lab.registry.register_typed(ActionSpec('NativeNavDataProbe',Empty,frozenset(),vehicle_types=frozenset({'rover'}),resources=RESOURCES,external_lifecycle='managed',default_timeout_ns=85_000_000_000),factory)
        first=f.lab.runtime.submit('NativeNavDataProbe','rover',{},timeout_s=85)
        deadline=time.monotonic()+65;sample=None
        while time.monotonic()<deadline:
            f.truth();view=f.lab.runtime.view(first['id'])
            if jobs:
                value=jobs[0].poll();sample=value.get('feedback',{}).get('command')
                if sample and abs(sample['speed_mps'])+abs(sample['yaw_rate_rad_s'])>0:break
            if view['state'] in ('UNKNOWN','FAILED','REJECTED','TIMED_OUT'):raise AssertionError('native data macro failed: '+view['state']+': '+str(view['error']))
            time.sleep(.04)
        else:raise AssertionError('real registered native macro produced no qualified command')
        report['qualified_command']=sample
        contender=f.lab.runtime.submit('NativeNavDataProbe','rover',{},timeout_s=85)
        until=time.monotonic()+2
        while time.monotonic()<until and f.lab.runtime.view(contender['id'])['state'] not in ('REJECTED','FAILED'):time.sleep(.02)
        assert f.lab.runtime.view(contender['id'])['state']=='REJECTED' and len(jobs)==1,'exclusive cohort admitted a conflict'
        f.lab.runtime.cancel(first['id']);until=time.monotonic()+12
        while time.monotonic()<until:
            view=f.lab.runtime.view(first['id'])
            if view['state'] in ('CANCELLED','UNKNOWN','FAILED','TIMED_OUT'):break
            time.sleep(.04)
        assert view['state']=='CANCELLED' and view['safety']['release_safe'],str((view['state'],view['error']))
        assert not store.records(),'stopped native cohort left an unsafe or leaked reservation'
        report['cancelled']=view;report['first_job']=jobs[0].poll()
        factory.x=0.
        second=f.lab.runtime.submit('NativeNavDataProbe','rover',{},timeout_s=85);until=time.monotonic()+65
        while time.monotonic()<until:
            f.truth();view=f.lab.runtime.view(second['id'])
            if view['state'] in ('SUCCEEDED','FAILED','UNKNOWN','TIMED_OUT','REJECTED'):break
            time.sleep(.04)
        assert view['state']=='SUCCEEDED' and view['safety']['release_safe'],str((view['state'],view['error']))
        assert not store.records();report['stationary_native_success']=view
        assert not any(_is_control(row) for row in f.writer),'data-only native job wrote vehicle frames'
        report.update(passed=True,writer_calls=len(f.writer),control_writer_calls=0,job_count=len(jobs))
    except BaseException as exc:report['error']=type(exc).__name__+': '+str(exc);raise
    finally:
        for job in jobs:job.cancel()
        for job in jobs:job._thread.join(10)
        report['jobs_final']=[job.poll() for job in jobs]
        try:f.close()
        finally:(path/'summary.json').write_text(json.dumps(report,indent=2))
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=Path,required=True);a=p.parse_args();install_signal_cleanup();print(run(a.run_dir.resolve())['passed'],flush=True)
