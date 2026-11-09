"""Real source interruptions, process loss, replay and instance isolation."""
import argparse,json,os,signal,sys,time,traceback
from pathlib import Path
from tests.simulation.control_binding_native import Native
from vehicle_autonomy.app.simulation.mid360_slam import Mid360Slam


def run(path):
    n=Native(path);result=dict(status='FAIL',checks={})
    def wait_withdraw(predicate,timeout):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if predicate():return
            time.sleep(.01)  # Measure a 1 s bound without 100 ms quantization.
        raise TimeoutError('actual localization withdrawal')
    def check(name,value,detail=None):
        result['checks'][name]=dict(status='PASS' if value else 'FAIL',detail=detail)
        assert value,(name,detail)
    try:
        r=n.api('/api/simulation/create',dict(scene_id='L01',vehicles=[dict(kind=kind,spawn={'id':spawn},
            sensors={'mid360':True,'mid360_lio':True}) for kind,spawn in (('rover','center'),('copter','north'))],parameters={'obstacle_count':0}))
        sid=r['id'];n.api('/api/simulation/start',{'id':sid});n.app.simulation_manager.wait_ready(sid,180)
        owner=n.app.simulation_manager.owners[sid];children=list(owner.vehicles.values());services=[]
        for child in children:
            n.wait(child.mid360.online,50);service=Mid360Slam(child.mid360);child.mid360.slam=service
            service.start();n.wait(lambda:service.snapshot()['online'],60);services.append(service)
        rover=next(s for s in services if s.parent.config['kind']=='rover');copter=next(s for s in services if s.parent.config['kind']=='copter')
        check('simultaneous_sources_isolated',rover.parent._ctx('live')['ros_domain_id']!=copter.parent._ctx('live')['ros_domain_id'] and
            rover.config['frames']['map']!=copter.config['frames']['map'] and rover.snapshot()['online'] and copter.snapshot()['online'])
        rover.parent.handle('record_start');time.sleep(15);rover.parent.handle('record_stop')
        bag=next(b for b in reversed(list(rover.parent.bags.values())) if b['complete']);result['bag']=bag
        check('actual_timed_recording',len(bag['message_counts'])>=10 and
            bag['message_counts'].get(rover.parent.config['namespace']+'/custom',0)>50 and
            bag['message_counts'].get(rover.parent.config['capture_topic'],0)>50,bag['message_counts'])
        for sensor in ('cloud','imu'):
            if not rover.snapshot()['online']:
                rover.start();n.wait(lambda:rover.snapshot()['online'],50)
            generation=rover.config['generation'];began=time.monotonic()
            rover.parent.handle(sensor+'_fault_on')
            wait_withdraw(lambda:not rover.snapshot()['online'] and rover.world.reader().snapshot().localization is None,2)
            delay=time.monotonic()-began
            check(sensor+'_loss_withdraws_world',rover.world.reader().snapshot().localization is None and delay<=1.,dict(seconds=delay,limit_s=1.))
            time.sleep(5.5)
            check(sensor+'_dependent_process_cleanup',not rover.parent._active('fast-lio') and not rover.parent._active('lio-adapter'))
            check(sensor+'_other_instance_survives',copter.snapshot()['online'])
            rover.parent.handle(sensor+'_fault_off');n.wait(rover.parent.online,10)
            rover.start();n.wait(lambda:rover.snapshot()['online'],50)
            check(sensor+'_explicit_restart_new_epoch',rover.config['generation']!=generation)
        generation=rover.config['generation'];began=time.monotonic()
        (rover.parent.directory/'fault-point-stamp').touch(mode=0o600)
        wait_withdraw(lambda:not rover.snapshot()['online'],3)
        elapsed=time.monotonic()-began
        check('bad_point_stamp_withdraws_world',elapsed<=1. and rover.world.reader().snapshot().localization is None,elapsed)
        n.wait(lambda:not rover.parent._active('fast-lio') and not rover.parent._active('lio-adapter'),15)
        invalid=json.loads((rover.parent.directory/'health.json').read_text())
        check('bad_point_stamp_rejected_before_lio',not invalid['online'] and 'timebase mismatch' in invalid.get('error',''),invalid)
        check('bad_point_stamp_other_instance_survives',copter.snapshot()['online'])
        rover.parent.handle('sensor_start');n.wait(rover.parent.online,15)
        rover.start();n.wait(lambda:rover.snapshot()['online'],50)
        check('bad_point_stamp_restart_new_epoch',rover.config['generation']!=generation)
        for fault,on,off in (
            ('clock_pause','clock_pause_on','clock_pause_off'),
            ('clock_back','clock_back_once',None),('clock_reset','clock_reset_once',None),
            ('tf_missing','tf_fault_on','tf_fault_off'),('tf_conflict',None,None)):
            generation=rover.config['generation'];began=time.monotonic()
            if fault=='tf_conflict':
                rover._register('fault-publisher','Simulation TF authority fault')
                rover.parent._launch('fault-publisher',[sys.executable,str(owner.root/'tests/simulation/lio_graph_native.py'),
                    '--domain',str(rover.parent._ctx('live')['ros_domain_id']),
                    '--topics',json.dumps([rover.parent.config['namespace']+'/slam/tf']),
                    '--output',str(n.path/'tf-conflict-graph.json'),'--conflict'])
            elif fault=='tf_missing':rover.handle({'action':on})
            else:rover.parent.handle(on)
            wait_withdraw(lambda:not rover.snapshot()['online'],8)
            snapshot=rover.snapshot();delay=time.monotonic()-began
            check(fault+'_withdraws_world',rover.world.reader().snapshot().localization is None,
                dict(seconds=delay,error=snapshot['error'],source_error=snapshot['state'].get('error')))
            if fault=='clock_pause':check('clock_pause_withdrawal_bound',delay<=1.,delay)
            if fault.startswith('clock_'):
                check(fault+'_clock_diagnostic',('paused' if fault=='clock_pause' else 'epoch') in str(snapshot['error']),snapshot['error'])
            n.wait(lambda:not rover.parent._active('fast-lio') and not rover.parent._active('lio-adapter'),12)
            check(fault+'_dependent_cleanup',not rover.parent._active('lio-adapter') and copter.snapshot()['online'])
            if fault=='tf_conflict':rover.parent._stop('fault-publisher')
            elif off:
                if fault=='tf_missing':rover.handle({'action':off}) if rover.parent._active('lio-adapter') else None
                else:rover.parent.handle(off)
            n.wait(rover.parent.online,15);rover.start();n.wait(lambda:rover.snapshot()['online'],50)
            check(fault+'_restart_new_epoch',rover.config['generation']!=generation)
        n.wait(lambda:rover.snapshot()['state'].get('map_worker') and rover.snapshot()['state'].get('map_reference'),15)
        state=rover.snapshot();mapper=state['state']['map_worker']['pid']
        stat=Path('/proc',str(mapper),'stat').read_text().split(') ',1)[1].split()
        adapter_pid=rover.parent.tools.instances['lio-adapter']['pid']
        check('map_fault_target_is_owned_child',int(stat[1])==adapter_pid and b'spawn_main' in Path('/proc',str(mapper),'cmdline').read_bytes())
        os.kill(mapper,signal.SIGKILL)
        n.wait(lambda:rover.snapshot()['state'].get('map',{}).get('error'),5)
        check('map_crash_withdraws_resource_only',rover.world.reader().snapshot().map is None and rover.snapshot()['online'] and copter.snapshot()['online'])
        rover.stop();n.wait(lambda:not Path('/proc',str(mapper)).exists(),10)
        rover.start();n.wait(lambda:rover.snapshot()['online'] and rover.snapshot()['state'].get('map_reference'),50)
        record=rover.parent.tools.instances['lio-adapter'];pid=record['pid']
        mapper=rover.snapshot()['state']['map_worker']['pid']
        check('fault_target_is_owned_lio_process',b'vehicle_autonomy.world.mapping.lio_worker' in Path('/proc',str(pid),'cmdline').read_bytes())
        os.kill(pid,signal.SIGKILL);n.wait(lambda:not rover.snapshot()['running'],10)
        check('worker_crash_withdraws_world',not rover.snapshot()['online'] and rover.world.reader().snapshot().localization is None)
        n.wait(lambda:not rover.parent._active('fast-lio') and not rover.parent._active('lio-adapter'),15)
        check('worker_crash_dependency_cleanup',not rover.parent._active('fast-lio') and copter.snapshot()['online'])
        n.wait(lambda:not Path('/proc',str(mapper)).exists(),10)
        check('worker_crash_reaps_map_child',not Path('/proc',str(mapper)).exists())
        rover.parent.handle('replay_once',bag_id=bag['id']);rover.start('replay');n.wait(lambda:rover.snapshot()['online'],40)
        check('real_replay_runs_lio_in_separate_domain',rover.source=='replay' and rover.parent._ctx('replay')['ros_domain_id']!=rover.parent._ctx('live')['ros_domain_id'] and copter.snapshot()['online'])
        replay=rover.snapshot();result['replay']=replay
        check('replay_has_real_paired_output',replay['state']['revision']>=1 and replay['state']['scan_coverage']['imu_bracket_max_gap_ns']<=20_000_000)
        rover.parent.handle('replay_stop');check('replay_stop_withdraws_world',not rover.snapshot()['online'] and rover.world.reader().snapshot().localization is None)
        rover_id=rover.parent.child.id
        raw_topics=[rover.parent.config[key] for key in ('raw_custom','raw_imu','raw_capture')]
        retired_domain=rover.parent._ctx('live')['ros_domain_id']
        n.api('/api/simulation/remove_vehicle',dict(id=sid,vehicle_id=rover_id));n.operation(sid)
        check('single_instance_removal_preserves_other',copter.snapshot()['online'])
        copter._register('retired-graph','Retired instance DDS audit')
        copter.parent._launch('retired-graph',[sys.executable,str(owner.root/'tests/simulation/lio_graph_native.py'),
            '--domain',str(retired_domain),'--topics',json.dumps(raw_topics),'--output',str(n.path/'retired-graph.json')])
        n.wait(lambda:not copter.parent._active('retired-graph'),15)
        retired=json.loads((n.path/'retired-graph.json').read_text())
        check('removed_sensor_dds_publishers_exit',all(not entries for entries in retired.values()),retired)
        # Keep the original live-clock safety fence: never reset a vehicle's
        # active SITL clock. Reset the actual empty Gazebo World, then add a
        # new admitted instance with fresh sensor and SLAM generations.
        n.api('/api/simulation/reset',dict(id=sid),reject=True)
        check('live_sitl_reset_remains_rejected',copter.snapshot()['online'])
        old_capture=copter.snapshot()['state']['localization']['capture_ros_ns']
        old_generation=copter.config['generation']
        n.api('/api/simulation/remove_vehicle',dict(id=sid,vehicle_id=copter.parent.child.id));operation=n.operation(sid)
        check('last_vehicle_removed_before_real_reset',operation['operation']['state']=='SUCCEEDED' and not owner.vehicles)
        n.api('/api/simulation/reset',dict(id=sid))
        n.api('/api/simulation/add_vehicle',dict(id=sid,vehicle=dict(kind='rover',spawn={'id':'center'},
            sensors=dict(mid360=True,mid360_lio=True))))
        operation=n.operation(sid);check('new_timed_instance_after_reset',operation['operation']['state']=='SUCCEEDED',operation.get('operation'))
        reborn=next(iter(owner.vehicles.values()));n.wait(reborn.mid360.online,40)
        resumed=Mid360Slam(reborn.mid360);reborn.mid360.slam=resumed;resumed.start();n.wait(lambda:resumed.snapshot()['online'],60)
        state=resumed.snapshot()
        check('actual_world_reset_requires_new_frame_epoch',state['generation']!=old_generation and
            state['state']['localization']['capture_ros_ns']<old_capture and copter.world.reader().snapshot().localization is None)
        result['status']='PASS';n.report['status']='PASS'
    except Exception:result['error']=traceback.format_exc();print(result['error'],flush=True)
    finally:
        n.close();result['cleanup']=n.report['cleanup']
        if n.report.get('cleanup_error'):result.update(status='FAIL',cleanup_error=n.report['cleanup_error'])
        (n.path/'fault-result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(result['status'],flush=True);return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run-dir',type=Path,required=True);a=p.parse_args()
    raise SystemExit(0 if run(a.run_dir)['status']=='PASS' else 1)
