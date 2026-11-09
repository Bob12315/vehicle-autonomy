"""New-session matching against an ended session's persisted map, judge only truth."""
import argparse,json,math,os,shutil,time,traceback
from pathlib import Path
from threading import Event,Thread
import numpy as np
from tests.simulation.control_binding_native import Native
from tests.simulation.oracle import GazeboTruthOracle
from tests.simulation.lio_accuracy import quaternion,rotate,inverse,angle
from vehicle_autonomy.world.transform.tree import multiply_quaternions
from vehicle_autonomy.app.simulation.mid360_slam import Mid360Slam
from vehicle_autonomy.world.mapping.cloud_maps import MapCatalog


def run(path,kind,reference,*,gui=False):
    n=Native(path);result=dict(status='FAIL',kind=kind,seed=[.8,.1,-.1,.25]);oracle=None
    stop=Event();collector=None;stream=[]
    try:
        old=json.loads((reference/'slam-result.json').read_text());identity=old['map']['id']
        # Read only admitted nominal clearance, not a measured pose, for spawn.
        spec=n.app.simulation_manager._specifications('L01',[dict(kind=kind,spawn={'id':'center'})],{'obstacle_count':0},0)[0]
        spawn=dict(x=1.,y=0.,z=spec['spawn']['z'],heading_deg=20.)
        r=n.api('/api/simulation/create',dict(scene_id='L01',vehicles=[dict(kind=kind,spawn=spawn,
            sensors={'mid360':True,'mid360_lio':True})],parameters={'obstacle_count':0}))
        n.api('/api/simulation/start',{'id':r['id']});n.app.simulation_manager.wait_ready(r['id'],180)
        owner=n.app.simulation_manager.owners[r['id']];child=next(iter(owner.vehicles.values()));sensor=child.mid360
        os.environ.update(GZ_PARTITION=owner.partition,GZ_IP='127.0.0.1');oracle=GazeboTruthOracle(owner.world,child.model.name)
        n.oracles[child.target]=oracle;n.wait(sensor.online,60)
        service=Mid360Slam(sensor);sensor.slam=service;service.start();n.wait(lambda:service.snapshot()['online'],60)
        result['new_world']=owner.partition;result['spawn']=spawn;result['map_id']=identity
        # Corrupt an isolated copy of a real produced map, never the user's
        # persistent catalog. Exercise the same service load entry as the UI.
        real_catalog=service.catalog;bad=MapCatalog(n.path/'corrupt-map-catalog')
        shutil.copytree(real_catalog.root/identity,bad.root/identity)
        damaged=bad.root/identity/'map.pcd';damaged.write_bytes(damaged.read_bytes()[:-17])
        service.catalog=bad
        try:
            try:service.load(identity)
            except ValueError as exc:result['corrupt_map_rejected']=str(exc)
            else:raise AssertionError('corrupt map was accepted')
            assert not sensor._active('map-view') and service.loaded is None
        finally:service.catalog=real_catalog
        start=time.monotonic();service.relocalize(identity,result['seed']);states=[]
        def collect():
            previous=None
            while not stop.wait(.05):
                try:
                    state=json.loads((service.relocation['directory']/'state.json').read_text())
                    cut=(str(service.relocation['directory']),state.get('revision'),state.get('capture_ros_ns'),state.get('online'),state.get('error'))
                    if cut!=previous:stream.append(dict(observed_host_ns=time.monotonic_ns(),state=state));previous=cut
                except (OSError,ValueError,TypeError):pass
        collector=Thread(target=collect,daemon=True);collector.start()
        while time.monotonic()-start<30:
            state=service.snapshot().get('relocalization');states.append(state)
            if state and state['online']:break
            time.sleep(.1)
        (n.path/'registration-states.json').write_text(json.dumps(states,indent=2)+'\n')
        assert state and state['online'],state
        result['time_to_match_host_s']=time.monotonic()-start;result['match']=state
        # The prior run's independent alignment is used only HERE, after the
        # match, to score it. It is never copied into a runtime config/seed.
        alignment=quaternion(old['metrics']['alignment_quaternion']);translation=np.array(old['metrics']['alignment_translation'])
        truth=oracle.latest();q=quaternion(truth.quaternion_xyzw)
        expected=rotate(inverse(alignment),np.array([truth.x_m,truth.y_m,truth.z_m])+rotate(q,sensor.config['model_to_body'])-translation)
        expected_q=multiply_quaternions(inverse(alignment),q);pose=state['state']['localization']
        error=float(np.linalg.norm(np.array(pose['position'])-expected))
        orientation_error=angle(multiply_quaternions(quaternion(pose['quaternion']),inverse(expected_q)))
        result.update(position_error_m=error,attitude_error_deg=orientation_error,
            expected_map_position=expected.tolist(),estimated_map_position=pose['position'],
            recovered_saved_frame=service.relocation_world.reader().snapshot().localization.pose.frame_id)
        assert error<=.35 and orientation_error<=5.,(error,orientation_error)
        assert state['state']['fitness']>=.8,state
        n.wait(lambda:service.snapshot()['state'].get('relocation_tf',{}).get('online'),10)
        result['tf']=service.snapshot()['state']['relocation_tf']
        if gui:
            from tests.visualization.desktop import goal
            service.rviz(relocated=True)
            def view_ready():
                view=sensor.snapshot()['tools'].get('slam-rviz',{})
                if view.get('stopping') or view.get('pid') and not view.get('process_running'):
                    raise AssertionError(dict(viewer=view,source=service.snapshot()))
                return view.get('ready')
            n.wait(view_ready,100)
            # Inspect an established stream after several genuine new map
            # matches, not just the first window or retained saved-map image.
            revision=service.snapshot()['relocalization']['state']['revision']
            n.wait(lambda:service.snapshot()['relocalization'].get('state',{}).get('revision',0)>=revision+5,15)
            assert view_ready(),service.snapshot()
            goal(sensor.tools.instances['slam-rviz']['pid'],select=False)
            time.sleep(2)
            result['gui']=goal(sensor.tools.instances['slam-rviz']['pid'],capture=n.path/'rviz-relocalized.png',select=False)
            result['view_probe']=json.loads(next(service.directory.glob('view-health-*.json')).read_text())
            assert result['view_probe']['status']=='READY' and result['view_probe']['tf_at_capture'],result['view_probe']
            assert result['view_probe']['registered_channel']=='relocated_registered',result['view_probe']
        # A deliberately wrong operator seed must not reuse the prior valid
        # pose with a fresh stamp. The upstream real ICP gate decides failure.
        result['wrong_seed_trials']=[]
        for label,seed in (('far',[60.,60.,0.,0.]),('near',[8.,8.,0.,0.])):
            service.relocalize(identity,seed);negative=[];start_negative=time.monotonic();accurate_recoveries=0
            while time.monotonic()-start_negative<8:
                rejected=service.snapshot()['relocalization'];negative.append(rejected)
                assert sensor._active('relocalization'),'wrong-seed rejection must come from a running matcher'
                if rejected['online']:
                    # A difficult seed can legitimately converge. It may be
                    # called valid only if the independent judge confirms the
                    # recovered old-map pose, not merely a high fitness score.
                    estimate=rejected['state']['localization'];actual=oracle.latest();actual_q=quaternion(actual.quaternion_xyzw)
                    expected_position=rotate(inverse(alignment),np.array([actual.x_m,actual.y_m,actual.z_m])+
                        rotate(actual_q,sensor.config['model_to_body'])-translation)
                    error_position=float(np.linalg.norm(np.array(estimate['position'])-expected_position))
                    error_rotation=angle(multiply_quaternions(quaternion(estimate['quaternion']),inverse(multiply_quaternions(inverse(alignment),actual_q))))
                    assert error_position<=.35 and error_rotation<=5.,dict(seed=seed,position_error=error_position,attitude_error=error_rotation,state=rejected)
                    accurate_recoveries+=1
                else:assert service.relocation_world.reader().snapshot().localization is None,rejected
                time.sleep(.1)
            (n.path/('wrong-seed-'+label+'-states.json')).write_text(json.dumps(negative,indent=2)+'\n')
            fitness=[s['state']['fitness'] for s in negative if s.get('state') and 'fitness' in s['state']]
            assert len(fitness)>=3,fitness
            cuts={s['state']['capture_ros_ns'] for s in negative if s.get('state') and 'fitness' in s['state']}
            assert len(cuts)>=3,'multiple genuine capture-time registration attempts required'
            if label=='far':assert accurate_recoveries==0 and max(fitness)<=.8,fitness
            result['wrong_seed_trials'].append(dict(status='PASS',seed=seed,fitness_max=max(fitness),observations=len(fitness),distinct_registration_captures=len(cuts),
                accurate_recoveries=accurate_recoveries))
        sensor._stop('relocalization');snapshot=service.snapshot()
        assert not snapshot['relocalization']['online']
        assert service.relocation_world.reader().snapshot().localization is None
        result['withdrawal_after_stop']='PASS';result['status']='PASS';n.report['status']='PASS'
    except Exception:result['error']=traceback.format_exc();print(result['error'],flush=True)
    finally:
        stop.set()
        if collector:collector.join(3)
        (n.path/'registration-stream.json').write_text(json.dumps(stream,indent=2)+'\n')
        if 'service' in locals():result['last_status']=service.snapshot()
        n.close();result['cleanup']=n.report['cleanup']
        if n.report.get('cleanup_error'):result.update(status='FAIL',cleanup_error=n.report['cleanup_error'])
        (n.path/'relocalization-result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(result['status'],flush=True);return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run-dir',required=True,type=Path);p.add_argument('--reference-run',required=True,type=Path)
    p.add_argument('--kind',choices=['rover','copter'],required=True);p.add_argument('--gui',action='store_true');a=p.parse_args()
    raise SystemExit(0 if run(a.run_dir,a.kind,a.reference_run,gui=a.gui)['status']=='PASS' else 1)
