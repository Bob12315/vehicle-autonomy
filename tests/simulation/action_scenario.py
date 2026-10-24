"""Real HTTP -> standalone Action -> existing Execution -> owned AP/Gazebo."""
import argparse
from dataclasses import replace
import json
import math
import os
from pathlib import Path
import secrets
from threading import Thread
import time
from urllib.request import Request,urlopen
from uuid import uuid4

from vehicle_autonomy.app.bootstrap.action_ownership import OwnedActionSimulation
from vehicle_autonomy.app.bootstrap.action_driver import VehicleActionDriver
from vehicle_autonomy.app.web.action_lab import ActionLab,ActionLabServer
from vehicle_autonomy.vehicles.ardupilot.commands import ArduPilotCommandTranslator
from vehicle_autonomy.vehicles.plane.ardupilot_commands import ArduPlaneCommandTranslator
from vehicle_autonomy.vehicles.rover.ardupilot_commands import ArduRoverCommandTranslator
from vehicle_autonomy.vehicles.ardupilot.transports.bytes import TcpByteTransport
from tests.simulation.launch import OwnedSimulation,install_signal_cleanup
from tests.simulation.oracle import GazeboTruthOracle
from tests.simulation.faults import TcpFaultProxy


def run(path,kind,*,faults=False,browser=False):
    path.mkdir(parents=True,exist_ok=False)
    owned=OwnedSimulation(path,kind,confirmation_signing=True,rover_native_rtl=kind=='rover')
    lab=server=proxy=driver=None;writer=[];trajectory=[];actions=[]
    result={'passed':False,'kind':kind,'faults':faults,'actions':actions}
    events=(path/'runtime.jsonl').open('w');trace=(path/'trajectory.jsonl').open('w')
    received=[];rxlog=(path/'application-rx.jsonl').open('w')
    def event(value):events.write(json.dumps(value)+'\n');events.flush()
    try:
        owned.start();ownership=OwnedActionSimulation(path/'manifest.json')
        oracle=GazeboTruthOracle(owned.world,owned.model)
        proxy=TcpFaultProxy(owned.port,path/'proxy.jsonl',capture_payload=True)
        class Observed:
            def __init__(self,t):
                from pymavlink.dialects.v20 import ardupilotmega as mav
                self.t=t;self.parser=mav.MAVLink(None);self.parser.robust_parsing=True
            def read(self,*a,**kw):
                raw=self.t.read(*a,**kw)
                if raw:
                    for m in self.parser.parse_buffer(raw) or []:
                        if m.get_type()=='BAD_DATA':continue
                        value={'host_ns':time.monotonic_ns(),'type':m.get_type(),'payload':m.to_dict(),'raw_hex':bytes(m.get_msgbuf()).hex()}
                        received.append(value);rxlog.write(json.dumps(value)+'\n');rxlog.flush()
                return raw
            def write(self,data):
                writer.append({'host_ns':time.monotonic_ns(),'raw_hex':data.hex()});self.t.write(data)
            def close(self):self.t.close()
        def connect(host,port,**kw):
            if (host,port)!=('127.0.0.1',owned.port):raise ValueError('wrong owned connection')
            return Observed(TcpByteTransport.connect('127.0.0.1',proxy.port,**kw))
        translator=({'plane':ArduPlaneCommandTranslator,'rover':ArduRoverCommandTranslator,'copter':ArduPilotCommandTranslator}[kind])(mode_ids=owned.profile.mode_ids)
        driver=VehicleActionDriver(kind,owned.profile,translator,ownership,allow_send=True,event_sink=event,transport_factory=connect)
        lab=ActionLab({kind:driver},event_sink=event)
        token=secrets.token_urlsafe(32)
        server=ActionLabServer(('127.0.0.1',0),lab,token,path/'http-audit.jsonl')
        thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_address[1]}'
        def api(route,payload=None,identifier=None):
            headers={'Authorization':'Bearer '+token}
            if payload is not None:headers.update({'Content-Type':'application/json','X-VAF-CSRF':token,'X-VAF-Request-ID':identifier or uuid4().hex})
            request=Request(base+route,data=None if payload is None else json.dumps(payload).encode(),headers=headers)
            with urlopen(request,timeout=4) as response:body=json.load(response)
            if not body['ok']:raise RuntimeError('Action API operation failed')
            return body['result']
        def sample():
            owned.assert_alive();truth=oracle.latest()
            if truth:
                if time.monotonic_ns()-truth.host_received_ns>500_000_000:raise AssertionError('Gazebo truth stale')
                item={'host_ns':time.monotonic_ns(),'sim_ns':truth.simulation_ns,'position':[truth.x_m,truth.y_m,truth.z_m],
                    'yaw':truth.yaw_rad,'speed':oracle.recent_speed_mps()}
                world=driver.snapshot()
                if world and world.vehicle and world.vehicle.reported_pose:
                    p=world.vehicle.reported_pose.value.position
                    item['reported_position']=[p.x,p.y,p.z]
                trajectory.append(item);trace.write(json.dumps(item)+'\n');trace.flush()
            return truth
        def pause(seconds):
            until=time.monotonic()+seconds
            while time.monotonic()<until:sample();time.sleep(.1)
        pause(owned.profile.warmup_ns/1e9)
        initial=sample();baseline=initial.z_m;result['initial_truth']=[initial.x_m,initial.y_m,baseline]
        def submit(name,parameters=None,**kw):
            a=api('/api/run',{'name':name,'target':kind,'parameters':parameters or {},'allow_send':True,**kw})
            actions.append({'name':name,'id':a['id'],'request':parameters or {},'submitted':a})
            return a
        def state(identifier):return next(a for a in api('/api/instances') if a['id']==identifier)
        def wait(a,timeout=50,expected='SUCCEEDED'):
            until=time.monotonic()+timeout
            while time.monotonic()<until:
                sample();value=state(a['id'])
                if value['state'] in ('SUCCEEDED','FAILED','REJECTED','CANCELLED','TIMED_OUT','UNKNOWN'):
                    actions[next(i for i,r in enumerate(actions) if r['id']==a['id'])]['final']=value
                    if value['state']!=expected:raise AssertionError(f'{value["name"]}: {value["state"]}: {value["error"]}')
                    return value
                time.sleep(.1)
            raise TimeoutError('Action '+a['name'])
        result['catalog']=api('/api/actions?target='+kind)
        wait(submit('GetVehicleState'))
        readonly=api('/api/run',{'name':'Arm','target':kind,'parameters':{}})
        pause(.5)
        if state(readonly['id'])['state']!='REJECTED' or writer:raise AssertionError('default SEND wrote a vehicle command')
        result['default_send']={'passed':True,'writer_calls':0}
        if browser:
            if kind!='rover' or faults:raise ValueError('browser fixture requires normal Rover scene')
            from tests.simulation.action_browser import exercise
            result['web_browser']=exercise(base,token,lab,oracle,path,sample,actions)
        else:
            wait(submit('SetMode',{'mode':'MANUAL' if kind=='plane' else 'GUIDED'}))
            wait(submit('Arm'))
        if faults:
            if kind=='plane':
                cutoff=time.monotonic_ns();before=len(writer)
                proxy.inject(drop_ack_command=176)
                a=submit('Takeoff',{'height_m':50})
                until=time.monotonic()+4
                while time.monotonic()<until:
                    pause(.1)
                    dropped=[m for m in proxy.records if m.get('host_ns',0)>=cutoff and m.get('direction')=='rx_discard' and m.get('cause')=='filter'
                        and m.get('type')=='COMMAND_ACK' and m.get('payload',{}).get('command')==176]
                    if dropped:break
                if not dropped:raise AssertionError('target ACK was not actually intercepted')
                app_ack=[m for m in received if m['host_ns']>=cutoff and m['type']=='COMMAND_ACK' and m['payload'].get('command')==176]
                forwarded=[m for m in proxy.records if m.get('host_ns',0)>=cutoff and m.get('direction')=='rx_forward'
                    and m.get('type')=='COMMAND_ACK' and m.get('payload',{}).get('command')==176]
                if app_ack or forwarded:raise AssertionError('dropped ACK reached the application')
                api('/api/cancel',{'id':a['id']});value=wait(a,expected='UNKNOWN')
                frames=[proxy.frame_metadata(bytes.fromhex(w['raw_hex'])) for w in writer[before:]]
                takeoff_frames=[m for m in frames if m.get('payload',{}).get('command')==176 and m['payload'].get('param2')==13]
                if len(takeoff_frames)!=1:raise AssertionError('cancel window did not contain exactly one real TAKEOFF writer call')
                if any(r['phase']=='COMPLETED' for r in value['command_results']):raise AssertionError('missing ACK falsely completed TAKEOFF')
                result['ack_interception']={'passed':True,'dropped':len(dropped),'forwarded':len(forwarded),'application_received':len(app_ack),'takeoff_writer_calls':len(takeoff_frames)}
            else:
                if kind=='copter':wait(submit('Takeoff',{'height_m':1.5}),timeout=55)
                name,p=('Drive',{'speed_mps':.3}) if kind=='rover' else ('SetVelocity',{'vx_mps':.2})
                a=submit(name,p);pause(2)
                before=len(writer)
                pending=submit('Goto',{'x_m':1.,'y_m':0.},wait_timeout_s=4)
                if pending['state']!='WAITING_RESOURCE':raise AssertionError('resource conflict did not wait')
                api('/api/cancel',{'id':pending['id']});wait(pending,expected='CANCELLED')
                if state(pending['id'])['effects']:raise AssertionError('cancelled wait emitted an Effect')
                api('/api/cancel',{'id':a['id']});wait(a,expected='CANCELLED')
                if kind=='rover':wait(submit('SetMode',{'mode':'GUIDED'}))
                timed=submit(name,p,timeout_s=1.2);wait(timed,expected='TIMED_OUT')
                if not state(timed['id'])['safety']['release_safe']:raise AssertionError('normal timeout did not confirm stop')
                if kind=='rover':wait(submit('SetMode',{'mode':'GUIDED'}))
                a=submit(name,p);pause(1)
                old=[bytes.fromhex(m['raw_hex']) for m in received if m['type']=='HEARTBEAT'][:1]
                proxy.inject(drop_rx={'HEARTBEAT','LOCAL_POSITION_NED','GLOBAL_POSITION_INT','ATTITUDE'})
                for raw in old:proxy.replay_rx(raw)
                value=wait(a,timeout=30,expected='UNKNOWN')
                if value['safety']['release_safe']:raise AssertionError('lost telemetry incorrectly released motion')
                result['cancel_wait_timeout_link_loss']={'passed':True,'wait_effects':0,'replayed_old_heartbeat':len(old),
                    'physical_stop':'UNCONFIRMED','timed_action':state(timed['id'])}
            before=len(writer)
            denied=submit('SetMode',{'mode':'LOITER' if kind!='rover' else 'GUIDED'})
            wait(denied,expected='REJECTED');wait(submit('GetVehicleState'));pause(.5)
            if len(writer)!=before:raise AssertionError('rejected handoff wrote a frame')
            if not api('/api/resources'):raise AssertionError('UNKNOWN lost its safety reservation')
            result['unsafe_handoff']={'passed':True,'writer_calls':0}
        elif kind=='rover':
            result['motion_truth']=[]
            for name,p in [('Drive',{'speed_mps':.5}),('Drive',{'speed_mps':-.5}),('Turn',{'yaw_rate_rad_s':.35}),('Turn',{'yaw_rate_rad_s':-.35})]:
                wait(submit('SetMode',{'mode':'GUIDED'}))
                begin=sample();a=submit(name,p);end=time.monotonic()+(10 if name=='Drive' else 9)
                while time.monotonic()<end:
                    pause(.1);truth=sample()
                    measured=(math.hypot(truth.x_m-begin.x_m,truth.y_m-begin.y_m) if name=='Drive' else
                        abs(math.atan2(math.sin(truth.yaw_rad-begin.yaw_rad),math.cos(truth.yaw_rad-begin.yaw_rad))))
                    if measured>=(1.0 if name=='Drive' else math.pi/4):break
                else:raise AssertionError('Rover Action did not meet unchanged physical '+name+' threshold')
                result['motion_truth'].append({'action':a['id'],'parameters':p,'measured':measured,'passed':True})
                if state(a['id'])['state']!='RUNNING':raise AssertionError('continuous Action not running')
                if name=='Drive':
                    conflict=submit('Goto',{'x_m':1.,'y_m':0.});wait(conflict,expected='REJECTED')
                    wait(submit('GetVehicleState'))
                api('/api/cancel',{'id':a['id']});wait(a,expected='CANCELLED')
            wait(submit('SetMode',{'mode':'GUIDED'}))
            wait(submit('Goto',{'x_m':2.,'y_m':0.}),timeout=55)
            wait(submit('Stop'))
            wait(submit('ReturnHome'),timeout=65)
            wait(submit('Disarm'))
            final=sample()
            if max(math.hypot(t['position'][0]-initial.x_m,t['position'][1]-initial.y_m) for t in trajectory)<1.2:
                raise AssertionError('Gazebo did not observe Rover movement')
            if math.hypot(final.x_m-initial.x_m,final.y_m-initial.y_m)>.75:raise AssertionError('Rover home error')
        elif kind=='copter':
            wait(submit('Takeoff',{'height_m':1.5}),timeout=55)
            truth=sample()
            if abs(truth.z_m-baseline-1.5)>.35:raise AssertionError('Copter takeoff Gazebo height')
            wait(submit('Goto',{'x_m':2.,'y_m':1.,'z_m':1.5}),timeout=55)
            truth=sample()
            if math.hypot(truth.x_m-initial.x_m-2,truth.y_m-initial.y_m-1)>.75:raise AssertionError('Copter Goto Gazebo error')
            wait(submit('SetYaw',{'yaw_rad':1.0}),timeout=40)
            if abs(math.atan2(math.sin(sample().yaw_rad-1.0),math.cos(sample().yaw_rad-1.0)))>.1:raise AssertionError('Copter yaw independent truth error')
            for name,p in [('SetVelocity',{'vx_mps':.5}),('Hold',{})]:
                begin=sample();a=submit(name,p);pause(3)
                if name=='SetVelocity':
                    truth=sample();distance=math.hypot(truth.x_m-begin.x_m,truth.y_m-begin.y_m);speed=oracle.recent_speed_mps()
                    if distance<.6 or speed is None or not .25<=speed<=.75:raise AssertionError('Copter velocity unchanged physical thresholds')
                    result['velocity_truth']={'passed':True,'distance_m':distance,'speed_mps':speed}
                wait(submit('GetVehicleState'))
                api('/api/cancel',{'id':a['id']});wait(a,expected='CANCELLED')
            wait(submit('Land'),timeout=60)
            truth=sample()
            if truth.z_m-baseline>.2 or (oracle.recent_speed_mps() or 0)>.15:raise AssertionError('Copter landing Gazebo ground')
            home_truth=sample()
            wait(submit('SetMode',{'mode':'GUIDED'}));wait(submit('Arm'));wait(submit('Takeoff',{'height_m':1.5}),timeout=55)
            wait(submit('Goto',{'x_m':1.,'y_m':1.,'z_m':1.5}),timeout=55)
            wait(submit('ReturnHome'),timeout=100)
            truth=sample()
            if truth.z_m-baseline>.2 or math.hypot(truth.x_m-home_truth.x_m,truth.y_m-home_truth.y_m)>.75:
                raise AssertionError('Copter RTL did not physically return and land')
        else:
            previous=wait(submit('Takeoff',{'height_m':50}),timeout=140)
            flight=[t for t in trajectory if t['position'][2]-baseline<1 and (t['speed'] or 0)>8]
            if not flight or max(math.hypot(t['position'][0]-initial.x_m,t['position'][1]-initial.y_m) for t in flight)<10:
                raise AssertionError('Plane real wheel ground rollout missing')
            if not previous['safety']['continuation_allowed']:raise AssertionError('Plane flight reservation lost')
            world=driver.snapshot();geo=world.vehicle.global_position.value
            target={'latitude_deg':geo.latitude_deg+math.degrees(150/6378137.),'longitude_deg':geo.longitude_deg,'altitude_amsl_m':584+50.}
            previous=wait(submit('SetGuidedTarget',target,continuation_of=previous['id']),timeout=30)
            if previous['result']['physical_arrival_claim']:raise AssertionError('target configuration claimed arrival')
            center=(sample().x_m,sample().y_m+150);start_yaw=sample().yaw_rad;last_yaw=start_yaw;rotation=0.;stable=None
            end=time.monotonic()+90
            while time.monotonic()<end:
                truth=sample();rotation+=abs(math.atan2(math.sin(truth.yaw_rad-last_yaw),math.cos(truth.yaw_rad-last_yaw)));last_yaw=truth.yaw_rad
                error=math.hypot(truth.x_m-center[0],truth.y_m-center[1]);speed=oracle.recent_speed_mps()
                good=error<=120 and abs(truth.z_m-baseline-50)<=7 and speed is not None and 8<=speed<=28
                stable=(stable or time.monotonic()) if good else None
                if stable and time.monotonic()-stable>=3 and rotation>=math.pi/2:break
                time.sleep(.1)
            else:raise TimeoutError('Plane native target independent flight truth')
            result['native_target_truth']={'passed':True,'center_error_m':error,'rotation_rad':rotation,'speed_mps':speed}
            previous=wait(submit('Loiter',continuation_of=previous['id']),timeout=30)
            pause(5)
            previous=wait(submit('RTL',continuation_of=previous['id']),timeout=30)
            pause(5)
            previous=wait(submit('AutoLand',continuation_of=previous['id']),timeout=420)
            truth=sample()
            if truth.z_m-baseline>.25 or oracle.recent_speed_mps()>=1:raise AssertionError('Plane touchdown/rollout Gazebo evidence missing')
            if math.hypot(truth.x_m-initial.x_m,truth.y_m-initial.y_m)>80 or abs(truth.y_m-initial.y_m)>15:
                raise AssertionError('Plane landing outside audited runway tolerance')
        result['passed']=True
    except BaseException as exc:result['error']=f'{type(exc).__name__}: {exc}'
    finally:
        if server:server.shutdown();server.server_close()
        for name,close in [('lab',lambda:lab.close() if lab else driver.close() if driver else None),('proxy',lambda:proxy.close() if proxy else None),('owned',owned.close)]:
            try:close()
            except BaseException as exc:result[name+'_cleanup_error']=type(exc).__name__;result['passed']=False
        result['writer_attempts']=writer
        result['trajectory_samples']=len(trajectory)
        events.close();trace.close();rxlog.close();(path/'summary.json').write_text(json.dumps(result,indent=2))
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--allow-send',action='store_true');p.add_argument('--faults',action='store_true');p.add_argument('--browser',action='store_true');p.add_argument('--kind',choices=['rover','copter','plane'],required=True);p.add_argument('--run-dir',type=Path,required=True)
    args=p.parse_args()
    if not args.allow_send:p.error('explicit own simulation SEND required')
    install_signal_cleanup();r=run(args.run_dir.resolve(),args.kind,faults=args.faults,browser=args.browser);print(json.dumps({'passed':r['passed'],'error':r.get('error')}),flush=True)
    return 0 if r['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
