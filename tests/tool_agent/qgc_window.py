"""Actual QGC window via Agent against an owned receive-only SITL relay.

Uses fresh XDG settings, disables USB/radio/ZeroConf autoconnect, and chooses a
dedicated UDP port. Never edits the user's existing QGC settings or opens USB.
"""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

from vehicle_autonomy.app.tools.builtins import registry
from .helpers import CTX,wait
from .test_service import Harness


def windows():
    result=subprocess.run(['xwininfo','-root','-tree'],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=3,check=True)
    return {match.group(1):line.strip() for line in result.stdout.splitlines() if 'QGroundControl' in line and (match:=re.match(r'\s*(0x[0-9a-f]+)',line))}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--qgc',type=Path,required=True);p.add_argument('--run-dir',type=Path,required=True)
    a=p.parse_args();root=a.run_dir.resolve();root.mkdir(parents=True,exist_ok=False,mode=0o700)
    report=dict(passed=False,source='actual QGC AppImage window + actual owned read-only Rover SITL relay; no hardware',vehicle_commands=0)
    launcher=h=None;before=windows();log=(root/'launcher.log').open('w')
    try:
        command=[sys.executable,'-m','vehicle_autonomy.app.bootstrap.qgc_simulation','--kind','rover','--headless','--read-only','--qgc-port','14650','--web-port','18890','--run-dir',str(root/'simulation')]
        launcher=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        def ready():
            if launcher.poll() is not None:raise RuntimeError('owned simulation exited; see launcher.log')
            try:
                value=json.loads((root/'simulation/session.json').read_text());return value if value.get('ready') else None
            except (FileNotFoundError,json.JSONDecodeError):return None
        session=wait(ready,100);assert session['qgc_role']=='telemetry_only'
        relay=root/'relay.json';relay.write_text(json.dumps(dict(telemetry_only=True,description='Actual framework TelemetryMirror loopback UDP 14650; inbound requests are dropped')))
        tools=registry(qgc=a.qgc,qgc_relay=relay)['tools'];qgc=next(t for t in tools if t['id']=='qgroundcontrol')
        config=root/'qgc-config';data=root/'qgc-data';cache=root/'qgc-cache'
        for path in (config,data,cache):path.mkdir(mode=0o700)
        settings='autoConnectUDP=true\nautoConnectPixhawk=false\nautoConnectSiKRadio=false\nautoConnectLibrePilot=false\nautoConnectZeroConf=false\nautoConnectRTK=false\nautoConnectNmeaPort=false\nudpListenPort=14650\nudpTargetHostIP=127.0.0.1\nudpTargetHostPort=14650\n'
        for organization in ('QGroundControl.org','QGroundControl'):
            directory=config/organization;directory.mkdir(mode=0o700)
            for name in ('QGroundControl.ini','QGroundControl Daily.ini'):
                (directory/name).write_text('[AutoConnect]\n'+settings+'\n[LinkManager]\n'+settings)
        qgc['profiles']['monitor']['env'].update(XDG_CONFIG_HOME=str(config),XDG_DATA_HOME=str(data),XDG_CACHE_HOME=str(cache))
        h=Harness(root/'control',[qgc])
        payload=dict(agent_id='desktop',tool_id='qgroundcontrol',profile_id='monitor',operation='launch',context=CTX)
        code,body=h.api('/api/tools/operation',payload);assert code==200,body
        def actual_window():
            instance=h.local.instances.get('qgroundcontrol')
            if instance and instance['state'] in ('FAILED','UNKNOWN'):raise RuntimeError(instance['error'])
            for window,line in windows().items():
                if window in before:continue
                size=re.search(r'\s(\d+)x(\d+)[+-]',line)
                if not size or int(size.group(1))<300 or int(size.group(2))<200:continue
                geometry=subprocess.run(['xwininfo','-id',window],text=True,stdout=subprocess.PIPE,timeout=2,check=True).stdout
                if 'Map State: IsViewable' not in geometry:continue
                info=subprocess.run(['xprop','-id',window,'_NET_WM_PID'],text=True,stdout=subprocess.PIPE,timeout=2,check=True).stdout
                match=re.search(r'=\s*(\d+)',info)
                if match and instance and os.getpgid(int(match.group(1)))==instance['pid']:return dict(id=window,title=line,pid=int(match.group(1)),width=int(size.group(1)),height=int(size.group(2)),mapped=True)
            return None
        window=wait(actual_window,70);report['window']=window
        instance=h.local._view(h.local.instances['qgroundcontrol']);assert instance['process_running'] and not instance['ready']
        report.update(tool=instance,connection='GUI launched; internal telemetry UI not asserted as functionally ready')
        assert h.api('/api/tools/operation',payload|{'operation':'stop'})[0]==200
        wait(lambda:h.local.instances['qgroundcontrol']['state']=='STOPPED',20)
        report.update(passed=True,qgc_cleanup=h.local.instances['qgroundcontrol']['cleanup_confirmed'])
    finally:
        if h:h.close()
        if launcher and launcher.poll() is None:
            launcher.terminate()
            try:launcher.wait(30)
            except subprocess.TimeoutExpired:launcher.kill();launcher.wait()
        log.close();(root/'summary.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:report[k] for k in ('passed','qgc_cleanup','window','connection','vehicle_commands')}))


if __name__=='__main__':main()
