"""Interactive, isolated localhost Rover simulation; no automatic mission start."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import signal
import sys
import time
from uuid import uuid4

from app.control import request
from intelligence.proposals import LlmAdapter
from tests.simulation.launch import OwnedSimulation, ROOT


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-send',action='store_true',help='Authorize only the owned localhost simulation')
    parser.add_argument('--llm-config',type=Path)
    parser.add_argument('--scenario',choices=('training','yard'),default='training')
    parser.add_argument('--gui',action='store_true',help='Open the Gazebo 3D client for this owned world')
    parser.add_argument('--run-dir',type=Path)
    parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--lifetime-s',type=int,default=900,help='Bounded interactive session, 1..3600 seconds')
    args=parser.parse_args()
    if not 1<=args.lifetime_s<=3600 or not 1024<=args.port<=65535:
        parser.error('invalid bounded lifetime/port')
    if args.llm_config:LlmAdapter.load(args.llm_config)  # Validate before starting any child.
    directory=(args.run_dir or ROOT/'artifacts/simulation'/('console-'+uuid4().hex[:8])).resolve()
    if len(str(directory/'app.sock').encode())>=108:parser.error('use a shorter evidence directory')
    directory.mkdir(parents=True,exist_ok=False,mode=0o700)
    owned=OwnedSimulation(directory,'rover',rover_actuation='low_rate' if args.scenario=='yard' else 'baseline')
    if args.scenario=='yard':
        from tests.simulation.yard_scene import add_yard
        add_yard(owned)
    endpoint=directory/'app.sock'
    outcome={'started_at':datetime.now(timezone.utc).isoformat(),'scope':'localhost simulation only',
             'allow_send':args.allow_send,'missions_started_automatically':False,'clean_shutdown':False}
    app=None
    def interrupted(*_):raise KeyboardInterrupt
    signal.signal(signal.SIGINT,interrupted);signal.signal(signal.SIGTERM,interrupted)
    try:
        owned.start()
        profile=directory/'profile.toml'
        profile.write_text((ROOT/('simulation/profiles/rover_yard.toml' if args.scenario=='yard' else 'simulation/profiles/rover.toml')).read_text().replace('port = 5760',f'port = {owned.port}'))
        app=owned.start_process('application',[sys.executable,'-m','app.main','run','--profile','rover_sim',
            '--config',str(profile),'--control-socket',str(endpoint),*(['--allow-send'] if args.allow_send else []),
            *(['--environment-config',str(ROOT/'simulation/environments/yard.toml'),'--scenario-scene',str(ROOT/'simulation/scenes/yard.json')] if args.scenario=='yard' else [])])
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            owned.assert_alive()
            if endpoint.exists():
                state=request(endpoint,'status')['result']
                if (state['state']=='READY' and state['environment']['origin_verified']
                        and state['motion_warmup_remaining_ns']==0):break
            time.sleep(.2)
        else:raise TimeoutError('stable simulation preflight not ready')
        if args.gui:owned.start_process('gazebo-gui',['gz','sim','-g','-v3'])
        token=directory/'token'
        web=owned.start_process('web',[sys.executable,'-m','app.web','--control-socket',str(endpoint),
            '--port',str(args.port),'--data-dir',str(directory/'console'),'--token-file',str(token),
            '--missions',('disarmed_mode,motion:drive,motion:turn,motion:circle,motion:wait,motion:visit' if args.scenario=='yard' else 'disarmed_mode,basic_route'),
            *(['--llm-config',str(args.llm_config.resolve())] if args.llm_config else [])])
        until=time.monotonic()+10
        while not token.exists() and time.monotonic()<until:owned.assert_alive();time.sleep(.05)
        if not token.exists():raise TimeoutError('Web authentication token not ready')
        owned.assert_alive()
        print(json.dumps({'ready':True,'url':f'http://127.0.0.1:{args.port}',
            'token_file':str(token),'evidence':str(directory),'allow_send':args.allow_send,
            'expires_in_s':args.lifetime_s,'scenario':args.scenario,'stop':'Ctrl+C; owned processes only'},ensure_ascii=False),flush=True)
        deadline=time.monotonic()+args.lifetime_s
        while time.monotonic()<deadline:owned.assert_alive();time.sleep(.5)
        outcome['reason']='bounded session expired'
    except KeyboardInterrupt:outcome['reason']='operator shutdown'
    except Exception as exc:outcome['error']=f'{type(exc).__name__}: {exc}'
    finally:
        if app is not None and app.poll() is None and endpoint.exists():
            try:
                response=request(endpoint,'shutdown')
                if not response['ok']:raise RuntimeError(response)
                if app.wait(timeout=12):raise RuntimeError('Application shutdown failed')
                owned.stop_process(app)
                outcome['clean_shutdown']=True
            except Exception as exc:outcome['shutdown_error']=str(exc)
        try:owned.close()
        except Exception as exc:outcome['cleanup_error']=str(exc)
        (directory/'console-session.json').write_text(json.dumps(outcome,indent=2)+'\n')
    print(json.dumps(outcome,ensure_ascii=False),flush=True)
    return 0 if outcome['clean_shutdown'] and not any(k in outcome for k in ('error','shutdown_error','cleanup_error')) else 1


if __name__=='__main__':raise SystemExit(main())
