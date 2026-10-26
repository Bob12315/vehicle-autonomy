"""DDS native positive/negative controls; private keys destroyed on every exit."""
import argparse
import json
import os
from pathlib import Path
import time

from tests.simulation.launch import ROOT,OwnedSimulation,install_signal_cleanup


def run(path):
    path.mkdir(parents=True,exist_ok=False);owned=OwnedSimulation(path,'rover');report={'passed':False,'motion_requested':False};before=dict(os.environ)
    try:
        os.environ['ROS_DOMAIN_ID']=str(120+os.getpid()%80);os.environ['PYTHONPATH']=str(ROOT/'src')+os.pathsep+str(ROOT)
        parent=owned.credentials.create_state('_dds_auth');owned._save();keyroot=parent/'keystore'
        profile=path/'dds-profiles.json';profile.write_text(json.dumps({
          'probe_server':{'topics':{'publish':['/phase5/probe/final'],'subscribe':['/phase5/probe/final']},'actions':{'execute':['/phase5/probe/navigate']}},
          'probe_allowed':{'topics':{'subscribe':['/phase5/probe/final']},'actions':{'call':['/phase5/probe/navigate']}},
          'probe_viewer':{'topics':{'subscribe':['/phase5/probe/final']}}}))
        wrapper=str(ROOT/'scripts/with_ros2.sh')
        p=owned.start_process('provision',[wrapper,'/usr/bin/python3','-m','vehicle_autonomy.app.bootstrap.ros2_security','--root',str(keyroot),'--profiles',str(profile),'--result',str(path/'dds-public-proof.json')],transient=True)
        assert p.wait(timeout=30)==0;owned.stop_process(p)
        os.environ.update(ROS_SECURITY_ENABLE='true',ROS_SECURITY_STRATEGY='Enforce',ROS_SECURITY_KEYSTORE=str(keyroot))
        def process(role):return owned.start_process(role,[wrapper,'/usr/bin/python3','-m','tests.simulation.ros_security_probe','--role',role,'--result',str(path/(role+'.json')),'--ros-args','--enclave','/vaf/probe_'+role],transient=True)
        server=process('server');time.sleep(1);allowed=process('allowed');assert allowed.wait(timeout=12)==0;owned.stop_process(allowed)
        viewer=process('viewer');assert viewer.wait(timeout=12)==0;owned.stop_process(viewer)
        os.environ['ROS_SECURITY_ENABLE']='false';assert server.poll() is None
        unsigned=process('unsigned');assert unsigned.wait(timeout=8)==0;owned.stop_process(unsigned);assert server.poll() is None
        report['authenticated_producer_alive_during_unsigned_probe']=True
        assert server.wait(timeout=25)==0;owned.stop_process(server)
        values={role:json.loads((path/(role+'.json')).read_text()) for role in ('server','allowed','viewer','unsigned')};report['actual']=values
        assert values['server']['goals_executed']==1,values
        assert values['allowed']['received']>=5 and values['allowed']['goal_completed'],values
        assert values['viewer']['received']>=5 and values['viewer']['publisher_denied'] and not values['viewer']['goal_completed'] and values['viewer']['goal_denied'],values
        assert values['unsigned']['received']==0,values
        report.update(passed=True,vehicle_writer_calls=0)
    except BaseException as exc:report['error']=type(exc).__name__+': '+str(exc);raise
    finally:
        try:owned.close()
        finally:
            os.environ.clear();os.environ.update(before);(path/'summary.json').write_text(json.dumps(report,indent=2))
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=Path,required=True);a=p.parse_args();install_signal_cleanup();print(run(a.run_dir.resolve())['passed'],flush=True)
